#!/usr/bin/env python3
"""Reusable media preparation/rendering; editorial review and publishing are agent steps."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT = os.environ.get('DAILY_VIDEO_FONT', '/System/Library/Fonts/STHeiti Medium.ttc')
CARD_FONT = os.environ.get('DAILY_VIDEO_CARD_FONT', '/System/Library/Fonts/Hiragino Sans GB.ttc')
# Reserve the lower quarter of portrait frames for platform UI.
CAPTION_Y = 0.69
ANNOTATION_Y = 0.54
SAFE_BOTTOM = 0.75
HDR_TRANSFERS = {'arib-std-b67', 'smpte2084'}

def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)

def read(path):
    return json.loads(Path(path).read_text())

def write(path, value):
    # Atomic replace, so an interrupted run never leaves a truncated JSON that later steps trust.
    path = Path(path)
    tmp = path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    tmp.replace(path)

def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def probe(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]))

def credentials():
    path = Path(os.environ.get('VOLC_CONFIG_FILE', str(Path.home() / '.config/volc.env'))).expanduser()
    if not path.is_file():
        raise RuntimeError(f'ASR credentials file missing: {path}')
    env = dict(os.environ)
    for line in path.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('\"\'')
    missing = [k for k in ('VOLC_ACCESS_KEY', 'VOLC_APP_ID') if not env.get(k)]
    if missing:
        raise RuntimeError(f'ASR credentials file lacks {missing}')
    return env

def transcribe(audio, dest):
    if dest.exists():
        return read(dest)
    env = credentials()
    body = {'user': {'uid': 'daily-article-video'},
            'audio': {'data': base64.b64encode(audio.read_bytes()).decode(), 'format': 'mp3'},
            'request': {'model_name': 'bigmodel', 'enable_itn': True, 'enable_punc': True,
                        'show_utterances': True, 'enable_speaker_info': True}}
    headers = {'Content-Type': 'application/json', 'X-Api-Resource-Id': env.get('VOLC_RESOURCE_ID', 'volc.seedasr.auc'),
               'X-Api-Request-Id': str(uuid.uuid4()), 'X-Api-Sequence': '-1',
               'X-Api-Key': env['VOLC_ACCESS_KEY'], 'X-Api-App-Key': env['VOLC_APP_ID']}
    req = urllib.request.Request('https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash',
                                 data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=600) as response:
            code = response.headers.get('X-Api-Status-Code', '20000000')
            message = response.headers.get('X-Api-Message', '')
            result = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'ASR HTTP {error.code}; status={error.headers.get("X-Api-Status-Code")}; '
                           f'message={error.headers.get("X-Api-Message", "")}. No render or publish.')
    except urllib.error.URLError as error:
        raise RuntimeError(f'ASR request failed: {error.reason}. No render or publish.')
    if code != '20000000' or not result.get('result', {}).get('utterances'):
        raise RuntimeError(f'ASR status={code}; message={message}; response keys={list(result)}; '
                           f'service message={result.get("message", "")}. No render or publish.')
    write(dest, result)
    return result

def speech_spans(utterances):
    """Word-level spans when ASR provides them (pauses inside an utterance count); utterance spans otherwise."""
    spans = []
    for u in utterances:
        words = [(w['start_time']/1000, w['end_time']/1000) for w in u.get('words', [])
                 if w.get('start_time', -1) >= 0 and w.get('end_time', -1) > w['start_time']]
        spans.extend(words or [(u['start'], u['end'])])
    return sorted(spans)

def pause_candidates(utterances, silences, duration, minimum=0.9, pad=0.2):
    """All speech-free gaps >= minimum for review; cuts only where acoustic silence confirms them, padded on both sides."""
    gaps, cursor = [], 0.0
    for a, b in speech_spans(utterances):
        if a-cursor >= minimum:
            gaps.append((cursor, a))
        cursor = max(cursor, b)
    if duration-cursor >= minimum:
        gaps.append((cursor, duration))
    candidates, cuts = [], []
    for c, d in gaps:
        overlap = [(max(a, c), min(b, d)) for a, b in silences if min(b, d) > max(a, c)]
        candidates.append({'start': round(c, 3), 'end': round(d, 3), 'gap': round(d-c, 3),
                           'acoustic_silence': round(sum(b-a for a, b in overlap), 3)})
        for a, b in overlap:
            lo, hi = a+pad, b-pad
            if hi-lo >= 0.5:
                cuts.append([round(lo, 4), round(hi, 4)])
    return candidates, cuts

def prepare(source, job):
    source = source.resolve(strict=True)
    work = job / 'work'
    work.mkdir(parents=True, exist_ok=True)
    fingerprint = sha256_file(source)
    if (job / 'source.json').exists() and read(job / 'source.json')['sha256'] != fingerprint:
        raise ValueError('Job directory belongs to another input. Choose a fresh directory.')
    info = probe(source)
    duration = float(info['format']['duration'])
    if duration > 930:
        raise ValueError('Video exceeds this 2–15 minute workflow; inspect before proceeding.')
    video = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
    if video is None:
        raise ValueError('Source has no video stream.')
    if not any(s['codec_type'] == 'audio' for s in info['streams']):
        write(job/'input-check.json', {'status':'blocked', 'reason':'Source has no audio stream', 'duration':duration})
        raise ValueError('Source has no audio stream. Need audible original or matching separate recording.')
    transfer = video.get('color_transfer')
    write(job / 'source.json', {'path': str(source), 'sha256': fingerprint, 'duration': duration,
                                'hdr_transfer': transfer if transfer in HDR_TRANSFERS else None, 'probe': info})
    audio = work / 'audio.mp3'
    if not audio.exists():
        partial = work / 'audio.partial.mp3'
        run(['ffmpeg', '-v', 'error', '-i', source, '-vn', '-ac', '1', '-ar', '16000', '-b:a', '64k', '-y', partial])
        partial.replace(audio)
    levels = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(source), '-vn', '-af', 'astats=metadata=0:reset=0',
                             '-f', 'null', '-'], capture_output=True, text=True, check=True).stderr
    peaks = re.findall(r'Peak level dB: ([^\n]+)', levels)
    if peaks and all(p.strip() == '-inf' for p in peaks):
        write(job/'input-check.json', {'status':'blocked', 'reason':'Source audio samples are all zero', 'duration':duration})
        raise ValueError('Source audio is completely silent. Need audible original or matching separate recording.')
    raw = transcribe(audio, work / 'asr.json')
    utterances = [{'id': i, 'start': u['start_time']/1000, 'end': u['end_time']/1000,
                   'text': u['text'], 'words': u.get('words', [])}
                  for i, u in enumerate(raw['result']['utterances'])]
    write(work / 'transcript.json', utterances)
    (work / 'transcript.txt').write_text('\n'.join(f"{u['id']} [{u['start']:.2f}–{u['end']:.2f}] {u['text']}" for u in utterances))
    detected = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(audio), '-af', 'silencedetect=noise=-35dB:d=0.9',
                               '-f', 'null', '-'], capture_output=True, text=True, check=True).stderr
    silences = []
    start = None
    for line in detected.splitlines():
        if 'silence_start:' in line:
            start = max(0.0, float(re.search(r'silence_start: (-?[0-9.]+)', line)[1]))
        if 'silence_end:' in line and start is not None:
            end = float(re.search(r'silence_end: (-?[0-9.]+)', line)[1])
            silences.append([start, end])
            start = None
    if start is not None:
        silences.append([start, duration])
    candidates, cuts = pause_candidates(utterances, silences, duration)
    write(work / 'silences.json', silences)
    write(work / 'pause-candidates.json', candidates)
    write(work / 'suggested-cuts.json', cuts)
    for t in (1, duration/3, duration*2/3):
        run(['ffmpeg', '-v', 'error', '-ss', str(t), '-i', source, '-frames:v', '1', '-vf', 'scale=540:-2', '-y', work / f'frame-{int(t)}.jpg'])
    unconfirmed = sum(1 for c in candidates if c['acoustic_silence'] < 0.5)
    print(f'Prepared {len(utterances)} utterances, {len(cuts)} acoustic-confirmed cuts, '
          f'{unconfirmed} ASR-only pauses in pause-candidates.json to audition. Agent must review before render.')
    if transfer in HDR_TRANSFERS:
        print(f'Note: HDR source ({transfer}); output stays HDR-tagged 8-bit because this pipeline does not perform HDR-to-SDR tone mapping. Check cover and preview colors.')

def keep_ranges(duration, cuts):
    cursor, kept = 0.0, []
    for a, b in sorted(cuts):
        if not (cursor <= a < b <= duration):
            raise ValueError('Cuts overlap or are out of bounds')
        if a > cursor:
            kept.append((cursor, a))
        cursor = b
    if cursor < duration:
        kept.append((cursor, duration))
    if not kept:
        raise ValueError('No footage retained')
    return kept

def mapped(t, kept):
    offset = 0.0
    for a, b in kept:
        if a <= t <= b:
            return offset+t-a
        offset += b-a
    raise ValueError(f'Subtitle timestamp falls within cut: {t}')

def clock(t):
    ms = round(t*1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'

def wrap(text, font, maxwidth):
    lines, current = [], ''
    for token in re.findall(r'[A-Za-z0-9]+(?:[-.][A-Za-z0-9]+)*|\s+|.', text):
        if '\n' in token:
            if current:
                lines.append(current.rstrip())
                current = ''
            continue
        if font.getlength(token) > maxwidth:
            raise ValueError('Single word exceeds available text width')
        if current and font.getlength(current+token) > maxwidth:
            carry = ''
            if token[0] in '，。、；：？！）】》’”' and len(current) > 1:
                current, carry = current[:-1], current[-1]
            lines.append(current.rstrip())
            current = carry
        if current or token.strip():
            current += token
    if current:
        lines.append(current)
    return lines

def tag_line(tags):
    return ' '.join('#'+t.lstrip('#') for t in tags)

def frame_size(source, work):
    """Displayed size after FFmpeg autorotation, rounded down to even pixels like the render filter."""
    sample = work / 'size-frame.png'
    run(['ffmpeg', '-v', 'error', '-i', source, '-frames:v', '1', '-y', sample])
    with Image.open(sample) as frame:
        w, h = frame.size
    return w//2*2, h//2*2

def overlay_fonts(w, plan):
    scale = plan.get('annotation_scale', 1.0)
    try:
        title_font = ImageFont.truetype(CARD_FONT, round(w*0.055*scale), index=1)
    except OSError:
        title_font = ImageFont.truetype(CARD_FONT, round(w*0.055*scale))
    return {'caption': ImageFont.truetype(FONT, max(26, round(w*0.049))),
            'note': ImageFont.truetype(CARD_FONT, round(w*0.042*scale)),
            'title': title_font,
            'english': ImageFont.truetype(CARD_FONT, round(w*0.033*scale))}

def draw_overlay(w, h, plan, fonts, texts, notes, label):
    """One transparent frame; raises on layout that would overflow, hit platform UI, or cover captions."""
    image = Image.new('RGBA', (w,h), (0,0,0,0))
    draw = ImageDraw.Draw(image)
    font = fonts['caption']
    caption_top = None
    for text in texts:
        lines = wrap(text, font, w*0.83)
        if len(lines) > 2:
            raise ValueError(f'Caption exceeds two lines; split editorial caption: {text}')
        step = round(font.size*1.35)
        y = h*plan.get('caption_y_fraction', CAPTION_Y)-(len(lines)-1)*step
        caption_top = y
        if h > w and y+(len(lines)-1)*step+font.size > h*SAFE_BOTTOM:
            raise ValueError(f'Caption enters the bottom {1-SAFE_BOTTOM:.0%} covered by platform UI; lower caption_y_fraction')
        for line in lines:
            draw.text((w/2,y), line, font=font, fill='white', anchor='mt', stroke_width=max(2,w//270), stroke_fill=(0,0,0,235))
            y += step
    scale = plan.get('annotation_scale', 1.0)
    for note in notes:
        x, y, pad = w*0.04, h*plan.get('annotation_y_fraction', ANNOTATION_Y), w*0.035*scale
        title = note['title']
        english = note.get('english', '')
        inner = w*0.92-2*pad-w*0.008
        lines = wrap(note['text'], fonts['note'], inner)
        if len(lines) > 4:
            raise ValueError(f'Term explanation exceeds four lines: {title}')
        title_width = fonts['title'].getlength(title)
        english_below = title_width+w*0.02+fonts['english'].getlength(english) > inner
        english_lines = wrap(english,fonts['english'],inner) if english_below else []
        header_height = fonts['title'].size+8+len(english_lines)*fonts['english'].size*1.35
        body_y = y+pad+header_height+12
        bottom = body_y+len(lines)*fonts['note'].size*1.45+pad
        if bottom > h:
            raise ValueError(f'Term explanation "{title}" extends below the frame')
        if caption_top is not None and bottom > caption_top-pad/2:
            raise ValueError(f'Term explanation "{title}" covers captions at {label}; lower annotation_y_fraction/annotation_scale or shorten text')
        draw.rounded_rectangle((x,y,w*0.96,bottom), radius=w*0.018, fill=(18,18,20,210))
        draw.rounded_rectangle((x,y,x+w*0.006,bottom), radius=w*0.003, fill=(125,211,252,255))
        text_x = x+pad+w*0.008
        draw.text((text_x,y+pad),title,font=fonts['title'],fill=(125,211,252),anchor='lt')
        if english_below:
            for j,line in enumerate(english_lines):
                draw.text((text_x,y+pad+fonts['title'].size+8+j*fonts['english'].size*1.35),line,font=fonts['english'],fill=(150,150,150),anchor='lt')
        else:
            draw.text((text_x+title_width+w*0.02,y+pad+fonts['title'].size-fonts['english'].size),english,font=fonts['english'],fill=(150,150,150),anchor='lt')
        for j,line in enumerate(lines):
            draw.text((text_x,body_y+j*fonts['note'].size*1.45),line,font=fonts['note'],fill=(255,255,255),anchor='lt')
    return image

def make_cover(src, plan, work, dest):
    run(['ffmpeg', '-v', 'error', '-ss', str(plan.get('cover_time',1)), '-i', src['path'], '-frames:v', '1', '-y', work / 'cover-frame.jpg'])
    cover = Image.open(work / 'cover-frame.jpg').convert('RGBA')
    # One clean-frame 3:4 cover; center the title and reserve both corners for platform icons.
    cover = ImageOps.fit(cover, (1080,1440), centering=(0.5,0))
    panel = Image.new('RGBA', cover.size, (0,0,0,0))
    pen = ImageDraw.Draw(panel)
    font = ImageFont.truetype(FONT, round(1080*plan.get('cover_font_fraction',88/1080)))
    lines = wrap(plan['cover_title'], font, 700)
    if len(lines)>3:
        raise ValueError('Cover title too long for shared centered layout')
    spacing = round(font.size*1.375)
    top = round(1440*plan.get('cover_y_fraction',66/1440))
    panel_width = max(pen.textlength(line,font=font) for line in lines) + 80
    left = (1080-panel_width)/2
    pen.rounded_rectangle((left,top-18,left+panel_width,top+len(lines)*spacing+19),radius=28,fill=(20,25,30,205))
    for i,line in enumerate(lines):
        x = (1080-pen.textlength(line,font=font))/2
        pen.text((x,top+i*spacing),line,font=font,fill=(255,244,220),stroke_width=1,stroke_fill=(0,0,0))
    Image.alpha_composite(cover,panel).convert('RGB').save(dest,quality=95)

def render(job):
    src = read(job / 'source.json')
    plan = read(job / 'editorial.json')
    if plan.get('reviewed') is not True or not plan.get('source_evidence') or not plan.get('captions'):
        raise ValueError('Editorial review, source evidence, and timed captions are required')
    if 'platforms' not in plan or not plan.get('cover_title'):
        raise ValueError('editorial.json needs platforms and cover_title')
    for path in (FONT, CARD_FONT):
        if not Path(path).is_file():
            raise RuntimeError(f'Font missing: {path}')
    cuts = plan.get('cuts', [])
    kept = keep_ranges(src['duration'], cuts)
    for cap in plan['captions']:
        if any(cap['start'] < b and cap['end'] > a for a,b in cuts):
            raise ValueError('A cut overlaps a spoken caption; review the edit timeline')
    work = job / 'work'
    work.mkdir(exist_ok=True)
    captions = []
    last = 0.0
    for cap in plan['captions']:
        a, b = mapped(cap['start'], kept), mapped(cap['end'], kept)
        if not (a >= last-0.001 and b > a and cap['text'].strip()):
            raise ValueError('Captions must be non-overlapping, nonempty, and increasing')
        last = b
        captions.append((a, b, cap['text']))
    annotations = sorted(((mapped(note['start'], kept), mapped(note['end'], kept), note)
                          for note in plan.get('annotations', [])), key=lambda item: item[0])
    for (a, b, note), (c, _, nxt) in zip(annotations, annotations[1:]+[(float('inf'), 0, None)]):
        if b <= a:
            raise ValueError(f'Term explanation "{note["title"]}" must end after it starts')
        if nxt is not None and c < b:
            raise ValueError(f'Term explanations overlap: "{note["title"]}" and "{nxt["title"]}"')
    w, h = frame_size(src['path'], work)
    fonts = overlay_fonts(w, plan)
    duration = sum(b-a for a,b in kept)
    # Build and validate every overlay and the cover before the long encode, so layout errors fail fast.
    images = work / 'captions'
    images.mkdir(exist_ok=True)
    for stale in images.glob('*.png'):
        stale.unlink()
    Image.new('RGBA', (w,h), (0,0,0,0)).save(images / 'blank.png')
    timeline = ['ffconcat version 1.0']
    boundaries = sorted({0.0, duration, *[t for a,b,_ in captions for t in (a,b)],
                         *[t for a,b,_ in annotations for t in (a,b)]})
    for i, (a,b) in enumerate(zip(boundaries, boundaries[1:])):
        midpoint = (a+b)/2
        image = draw_overlay(w, h, plan, fonts, [t for s,e,t in captions if s <= midpoint < e],
                             [n for s,e,n in annotations if s <= midpoint < e], f'{midpoint:.2f}s (edited)')
        name = f'c{i:04}.png'
        image.save(images / name)
        if b-a > 0.00001:
            timeline.extend([f"file 'captions/{name}'", f'duration {b-a:.6f}'])
    timeline.append("file 'captions/blank.png'")
    (work / 'captions.ffconcat').write_text('\n'.join(timeline)+'\n')
    make_cover(src, plan, work, job/'cover.jpg')
    (job / 'subtitles.srt').write_text('\n\n'.join(f'{i}\n{clock(a)} --> {clock(b)}\n{t}' for i, (a,b,t) in enumerate(captions,1)))
    # Single encode: cut, concat and burn in RGBA overlays (works without libass/drawtext), preserving phone autorotation.
    filters, labels = [], []
    for i, (a, b) in enumerate(kept):
        filters.extend([f'[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS,fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1[v{i}]',
                        f'[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}]'])
        labels.append(f'[v{i}][a{i}]')
    filters.append(''.join(labels)+f'concat=n={len(kept)}:v=1:a=1[cut][a]')
    filters.append('[1:v]format=rgba[s]')
    filters.append('[cut][s]overlay=eof_action=pass:format=auto[v]')
    (work / 'render.ffscript').write_text(';\n'.join(filters))
    output = job / 'video.mp4'
    partial = job / 'video.partial.mp4'
    run(['ffmpeg', '-v', 'error', '-i', src['path'], '-f', 'concat', '-safe', '0', '-i', work / 'captions.ffconcat',
         '-filter_complex_script', work / 'render.ffscript', '-map', '[v]', '-map', '[a]', '-t', str(duration), '-r', '30',
         '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
         '-movflags', '+faststart', '-y', partial])
    partial.replace(output)
    # Independent platform cover, not a silent intro inserted into the spoken video.
    write(job / 'publish.json', {'source_sha256':src['sha256'], 'video':str(output.resolve()),
          'cover':str((job/'cover.jpg').resolve()), 'platforms':plan['platforms']})
    if not (job/'publish-status.json').exists():
        write(job/'publish-status.json', {'xiaohongshu':{'status':'not_prepared'},
              'wechat_channels':{'status':'not_prepared','reason':'Prepare and verify the manual upload handoff.'}})
    actual = float(probe(output)['format']['duration'])
    if abs(actual-duration)>0.2:
        raise RuntimeError('Rendered duration differs from edit timeline')
    write(job/'render-check.json',{'expected_duration':duration,'actual_duration':actual,'caption_count':len(captions),
          'width':w,'height':h,'editorial_sha256':sha256_file(job/'editorial.json')})
    print('Rendered. Agent must visually inspect caption frames and cover, decode-check video, then publish.')

def check(job):
    """Deterministic QA and a compact visual review, without external services."""
    manifest, src, plan = read(job/'publish.json'), read(job/'source.json'), read(job/'editorial.json')
    rendered = read(job/'render-check.json').get('editorial_sha256')
    if rendered and rendered != sha256_file(job/'editorial.json'):
        raise ValueError('editorial.json changed after the last render; run render again before check')
    video = Path(manifest['video'])
    info = probe(video)
    duration = float(info['format']['duration'])
    cuts = plan.get('cuts', [])
    kept = keep_ranges(src['duration'], cuts)
    if abs(duration-sum(b-a for a,b in kept)) > 0.2:
        raise ValueError('Rendered duration differs from edit timeline')
    if not any(s['codec_type']=='audio' for s in info['streams']):
        raise ValueError('Final video has no audio stream')
    run(['ffmpeg','-v','error','-i',video,'-f','null','-'])
    marks = [(0.5,'start'),(duration/2,'middle'),(max(0,duration-1),'end')]
    marks += [((mapped(n['start'],kept)+mapped(n['end'],kept))/2,f'note {n["title"]}') for n in plan.get('annotations',[])]
    for i,(a,b) in enumerate(sorted(cuts),1):
        t = mapped(a,kept) if a > 0 else 0
        marks += [(t-0.15,f'cut{i} before'),(t+0.15,f'cut{i} after')]
    labels = {}
    for t,label in marks:
        t = round(max(0,min(duration-0.05,t)),3)
        labels[t] = labels[t]+' / '+label if t in labels else label
    points = sorted(labels)
    thumbs = []
    for i,t in enumerate(points):
        path = job/'work'/f'qa-{i:03}.jpg'
        run(['ffmpeg','-v','error','-ss',t,'-i',video,'-frames:v','1','-vf','scale=360:-2','-y',path])
        with Image.open(path) as frame:
            thumb = frame.convert('RGB').copy()
        strip = Image.new('RGB',(thumb.width,thumb.height+30),'#202020')
        strip.paste(thumb,(0,30))
        ImageDraw.Draw(strip).text((8,8),f'{t:.3f}s {labels[t]}',fill='white',font=ImageFont.truetype(FONT,16))
        thumbs.append(strip)
    cols = min(3,len(thumbs)); tw,th = thumbs[0].size
    sheet = Image.new('RGB',(cols*tw,((len(thumbs)+cols-1)//cols)*th),'#202020')
    for i,thumb in enumerate(thumbs): sheet.paste(thumb,((i%cols)*tw,(i//cols)*th))
    sheet.save(job/'work/qa-contact-sheet.jpg',quality=90)
    for key,label in [('xiaohongshu','小红书'),('wechat_channels','视频号')]:
        if key in manifest['platforms']:
            copy = manifest['platforms'][key]
            (job/f'{label}发布文案.txt').write_text(copy['title']+'\n\n'+copy['description']+'\n\n'+tag_line(copy['tags'])+'\n')
    result = {'full_decode_passed':True,'duration':duration,'caption_count':len(plan['captions']),
              'cuts':cuts,'review_times':points,'video_sha256':sha256_file(video),
              'contact_sheet':str((job/'work/qa-contact-sheet.jpg').resolve()),'cover':manifest['cover'],
              'visual_review':'required','audio_listening':'not_verified'}
    write(job/'qa-check.json',result)
    print(json.dumps(result,ensure_ascii=False))
    return result

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action',required=True)
    p = sub.add_parser('prepare'); p.add_argument('source',type=Path); p.add_argument('job',type=Path)
    p = sub.add_parser('render'); p.add_argument('job',type=Path)
    p = sub.add_parser('check'); p.add_argument('job',type=Path)
    args = parser.parse_args()
    if args.action=='prepare': prepare(args.source,args.job.resolve())
    elif args.action=='render': render(args.job.resolve())
    else: check(args.job.resolve())

if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError) as error:
        print(f'Cannot complete: {error}', file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as error:
        print(f'Cannot complete: external command failed ({error.returncode}): {" ".join(error.cmd[:3])} ...', file=sys.stderr)
        sys.exit(1)
