#!/usr/bin/env python3
"""Prepare a handoff, or purge a job after the user confirms both uploads."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def finalize(job, apply=False, output_root=None):
    if job.is_symlink():
        raise ValueError('Refusing symlink job')
    job = job.resolve()
    root = (Path(output_root) if output_root is not None else Path.cwd() / 'output/daily-video').resolve()
    if job.parent != root or job.is_symlink():
        raise ValueError('Only direct job directories under project output/daily-video are supported')
    manifest = json.loads((job / 'publish.json').read_text())
    status = json.loads((job / 'publish-status.json').read_text())
    video = Path(manifest['video']).resolve()
    if video.parent != job or not video.is_file():
        raise ValueError('Final video must exist inside this job')
    if not json.loads((job / 'editorial.json').read_text()).get('reviewed'):
        raise ValueError('Editorial review must be complete')
    xhs = status.get('xiaohongshu', {})
    if xhs.get('status') not in {'awaiting_user_publish', 'pending_review', 'published'} or not xhs.get('uploaded'):
        raise ValueError('Finish and verify Xiaohongshu preparation before cleanup')
    digest = sha256_file(video)
    if xhs.get('video_sha256') != digest:
        raise ValueError('Uploaded video hash must match final video')
    keep = {video.name, 'cover.jpg', 'cover-xiaohongshu.jpg', 'cover-wechat-channels.jpg', 'subtitles.srt',
            'editorial.json', 'source.json', 'publish.json', 'publish-status.json',
            'render-check.json', '发布文案.txt', '视频号发布文案.txt', '质检说明.md', 'cleanup.json'}
    original = Path(json.loads((job / 'source.json').read_text())['path']).resolve()
    if original.parent == job:
        keep.add(original.name)
    screenshot = Path(xhs.get('screenshot', '')).resolve()
    if screenshot.parent == job:
        keep.add(screenshot.name)
    generated = []
    for path in job.iterdir():
        if path.name in keep:
            continue
        if path.name == 'work' or path.name == 'cover-preview.jpg' or (
            path.is_file() and (path.match('video*.mp4') or path.match('terms*preview.jpg') or path.match('xiaohongshu-ready*.jpg'))):
            if path.is_symlink():
                raise ValueError(f'Refusing symlink: {path}')
            generated.append(path)
    total = sum(f.stat().st_size for p in generated for f in (p.rglob('*') if p.is_dir() else [p]) if f.is_file())
    if apply:
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-f', 'null', '-'], check=True)
        wx = manifest['platforms']['wechat_channels']
        (job / '视频号发布文案.txt').write_text(wx['title'] + '\n\n' + wx['description'] + '\n\n' + ' '.join('#' + t.lstrip('#') for t in wx['tags']) + '\n')
        for path in generated:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        report = {'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'final_video': str(video), 'final_sha256': digest, 'full_decode_passed': True,
                  'removed': [p.name for p in generated], 'bytes_removed': total,
                  'original_sources_untouched': True}
        (job / 'cleanup.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return {'apply': apply, 'final_video': str(video), 'remove': [p.name for p in generated], 'bytes': total}


def purge(job, uploads_confirmed=False, apply=False, delete_original=False, output_root=None):
    if job.is_symlink():
        raise ValueError('Refusing symlink job')
    job = job.resolve()
    root = (Path(output_root) if output_root is not None else Path.cwd() / 'output/daily-video').resolve()
    if job.parent != root or not job.is_dir():
        raise ValueError('Only an existing job directory under output/daily-video can be purged')
    if not uploads_confirmed:
        raise ValueError('Need user confirmation that both platform uploads succeeded and cleanup is requested')
    recorded = json.loads((job / 'source.json').read_text())
    if Path(recorded['path']).is_symlink():
        raise ValueError('Original video path is a symlink; delete it manually after checking')
    source = Path(recorded['path']).resolve()
    evidence = json.loads((job / 'editorial.json').read_text()).get('source_evidence', [])
    originals = [source] + [Path(e['pdf']).resolve() for e in evidence if e.get('pdf')]
    if any(p.is_relative_to(job) for p in originals):
        raise ValueError('An original video or PDF is inside this job; preserve it before purging')
    total = sum(p.stat().st_size for p in job.rglob('*') if p.is_file() and not p.is_symlink())
    report = {'apply': apply, 'purge_directory': str(job), 'bytes': total}
    if delete_original:
        # Delete only the exact file recorded in source.json, and only if its content is unchanged.
        if source.exists():
            if not source.is_file() or sha256_file(source) != recorded['sha256']:
                raise ValueError('Original video at the recorded path does not match source.json SHA-256; nothing deleted')
            report['delete_original'] = str(source)
        else:
            report['original_already_absent'] = str(source)
    if apply:
        if report.get('delete_original'):
            source.unlink()
        shutil.rmtree(job)
        if job.exists():
            raise RuntimeError('Job cleanup incomplete')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path)
    parser.add_argument('--output-root', type=Path, default=Path.cwd() / 'output/daily-video', help='Approved parent directory of jobs; defaults to current workspace output/daily-video')
    parser.add_argument('--apply', action='store_true', help='Delete verified generated intermediates; default is preview')
    parser.add_argument('--purge', action='store_true', help='Delete all job artifacts after user requests cleanup')
    parser.add_argument('--uploads-confirmed', action='store_true', help='Agent has received user confirmation of both successful uploads')
    parser.add_argument('--delete-original', action='store_true', help='With --purge: also delete the original video recorded in source.json after SHA-256 match')
    args = parser.parse_args()
    if args.delete_original and not args.purge:
        parser.error('--delete-original requires --purge')
    result = purge(args.job, args.uploads_confirmed, args.apply, args.delete_original, args.output_root) if args.purge else finalize(args.job, args.apply, args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
