"""Run with python3 -m unittest discover -s tests -v; no external services or publishing."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from PIL import ImageFont

spec = importlib.util.spec_from_file_location('pipeline', Path(__file__).resolve().parents[1] / 'daily-article-video/scripts/pipeline.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

class MediaTests(unittest.TestCase):
    def test_first_use_prepare_cache_pause_and_render(self):
        """Exercise the first media job with real FFmpeg and a mocked ASR boundary."""
        with tempfile.TemporaryDirectory(prefix='daily-video-first-use-') as tmp:
            root = Path(tmp); source = root/'synthetic.mp4'; job = root/'job'
            p.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                   'color=c=darkslategray:s=360x640:r=25:d=6', '-f', 'lavfi', '-i',
                   r'aevalsrc=if(between(t\,2\,4)\,0\,0.3*sin(2*PI*440*t)):s=16000:d=6',
                   '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-y', source])
            raw = {'result': {'utterances': [
                {'start_time': 200, 'end_time': 1800, 'text': '首段测试',
                 'words': [{'start_time': 200, 'end_time': 1800, 'text': '首段测试'}]},
                {'start_time': 4200, 'end_time': 5800, 'text': '次段测试',
                 'words': [{'start_time': 4200, 'end_time': 5800, 'text': '次段测试'}]}
            ]}}
            import json
            response = MagicMock()
            response.__enter__.return_value = response
            response.headers = {'X-Api-Status-Code': '20000000'}
            response.read.return_value = json.dumps(raw).encode()
            with patch.object(p, 'credentials', return_value={
                    'VOLC_API_KEY': 'synthetic-key', 'VOLC_RESOURCE_ID': 'volc.bigasr.auc_turbo'}), \
                 patch.object(p.urllib.request, 'urlopen', return_value=response) as request:
                p.prepare(source, job)
                self.assertEqual(request.call_count, 1)
            with patch.object(p.urllib.request, 'urlopen', side_effect=AssertionError('Unexpected request')):
                p.prepare(source, job)
            cuts = p.read(job/'work/suggested-cuts.json')
            self.assertEqual(len(cuts), 1)
            self.assertTrue(2 < cuts[0][0] < cuts[0][1] < 4)
            p.write(job/'editorial.json', {
                'reviewed': True, 'source_evidence': [{'type': 'synthetic fixture; no speech accuracy claim'}],
                'cuts': cuts, 'captions': [
                    {'start': .2, 'end': 1.8, 'text': '首段测试'},
                    {'start': 4.2, 'end': 5.8, 'text': '次段测试'}],
                'cover_title': '首次制作测试', 'cover_time': 1,
                'platforms': {'wechat_channels': {'title': '测试', 'description': '合成媒体测试', 'tags': ['科普']}}
            })
            p.render(job)
            result = p.check(job)
            self.assertTrue(result['full_decode_passed'])
            self.assertAlmostEqual(result['duration'], 6-(cuts[0][1]-cuts[0][0]), places=1)
            self.assertTrue((job/'视频号发布文案.txt').is_file())
            from PIL import Image
            with Image.open(job/'cover.jpg') as cover:
                self.assertEqual(cover.size, (1080, 1440))

    def test_timeline(self):
        kept = p.keep_ranges(5, [[2,3]])
        self.assertAlmostEqual(p.mapped(3.2, kept), 2.2)
        for cuts in ([[1,2],[1.5,3]], [[-1,1]], [[0,6]]):
            with self.assertRaises(ValueError): p.keep_ranges(5, cuts)

    def test_english_wrap(self):
        font = ImageFont.truetype(p.FONT,26)
        lines = p.wrap('剪后时间与英文 Seed-ASR',font,298)
        self.assertIn('Seed-ASR',lines)

    def test_pause_candidates_use_word_gaps(self):
        # One utterance with a 1.2 s pause between words; only part of it is acoustically silent.
        words=[{'start_time':0,'end_time':1000},{'start_time':-1,'end_time':-1},{'start_time':2200,'end_time':3000}]
        cands,cuts=p.pause_candidates([{'start':0,'end':3,'words':words}],[[1.0,2.2]],3)
        self.assertEqual(cands,[{'start':1.0,'end':2.2,'gap':1.2,'acoustic_silence':1.2}])
        self.assertEqual(cuts,[[1.2,2.0]])
        cands,cuts=p.pause_candidates([{'start':0,'end':3,'words':words}],[],3)
        self.assertEqual(cands[0]['acoustic_silence'],0)
        self.assertEqual(cuts,[])

    def _job(self, root, editorial, size='360x640', seconds=3):
        src=root/'input.mp4'; job=root/'job'; (job/'work').mkdir(parents=True)
        p.run(['ffmpeg','-v','error','-f','lavfi','-i',f'color=c=black:s={size}:r=30:d={seconds}',
               '-f','lavfi','-i',f'sine=frequency=440:duration={seconds}','-c:v','libx264','-c:a','aac','-shortest','-y',src])
        p.write(job/'source.json',{'path':str(src),'duration':seconds,'sha256':'test'})
        p.write(job/'editorial.json',{'reviewed':True,'source_evidence':[{'type':'synthetic fixture'}],'cuts':[],
                'cover_title':'测试','cover_time':1,'platforms':{},**editorial})
        return job

    def test_layout_errors_fail_before_encode(self):
        cap=[{'start':.2,'end':2.8,'text':'字幕'}]
        cases=[{'captions':cap,'caption_y_fraction':.78},
               {'captions':cap,'annotation_y_fraction':.6,'annotations':[{'start':.2,'end':2,'title':'说明','text':'解释框压住字幕。'*4}]},
               {'captions':cap,'annotations':[{'start':.2,'end':2,'title':'甲','text':'一'},{'start':1.5,'end':2.5,'title':'乙','text':'二'}]}]
        for editorial in cases:
            with tempfile.TemporaryDirectory(prefix='daily-video-layout-') as tmp:
                job=self._job(Path(tmp),editorial)
                with self.assertRaises(ValueError): p.render(job)
                self.assertFalse((job/'video.mp4').exists())

    def test_check_refuses_stale_render(self):
        with tempfile.TemporaryDirectory(prefix='daily-video-stale-') as tmp:
            job=self._job(Path(tmp),{'captions':[{'start':.2,'end':2.8,'text':'字幕'}]})
            p.render(job)
            plan=p.read(job/'editorial.json'); plan['captions'][0]['text']='改过的字幕'; p.write(job/'editorial.json',plan)
            with self.assertRaises(ValueError): p.check(job)

    def test_rerender_invalidates_previous_upload_and_qa_even_on_failure(self):
        with tempfile.TemporaryDirectory(prefix='daily-video-rerender-') as tmp:
            job = self._job(Path(tmp), {'captions': [{'start': .2, 'end': 2.8, 'text': '字幕'}]})
            p.render(job)
            p.check(job)
            p.write(job/'publish-status.json', {
                'xiaohongshu': {'status': 'awaiting_user_publish', 'uploaded': True},
                'wechat_channels': {'status': 'manual_upload_ready'}})
            (job/'视频号发布文案.txt').write_text('obsolete copy')
            # Cover extraction/encoding can fail after invalidation. Old records
            # must not certify either a failed render or a later successful one.
            with patch.object(p, 'make_cover', side_effect=RuntimeError('synthetic failure')):
                with self.assertRaises(RuntimeError):
                    p.render(job)
            for name in ('publish.json', 'render-check.json', 'qa-check.json', '视频号发布文案.txt'):
                self.assertFalse((job/name).exists())
            status = p.read(job/'publish-status.json')
            self.assertEqual(status['xiaohongshu']['status'], 'not_prepared')
            self.assertNotIn('uploaded', status['xiaohongshu'])
            p.render(job)
            self.assertFalse((job/'qa-check.json').exists())
            self.assertEqual(p.read(job/'publish-status.json')['wechat_channels']['status'], 'not_prepared')
            self.assertTrue(p.check(job)['full_decode_passed'])

    def test_platform_bottom_safe_area(self):
        with tempfile.TemporaryDirectory(prefix='daily-video-safe-area-') as tmp:
            root=Path(tmp); src=root/'input.mp4'; job=root/'job'; (job/'work').mkdir(parents=True)
            p.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=black:s=360x640:r=30:d=3',
                   '-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-c:a','aac','-shortest','-y',src])
            p.write(job/'source.json',{'path':str(src),'duration':3,'sha256':'test'})
            p.write(job/'editorial.json',{'reviewed':True,'source_evidence':[{'type':'synthetic fixture'}],
                'cuts':[],'captions':[{'start':.2,'end':2.8,'text':'字幕不能被平台底部信息遮住'}],
                'caption_y_fraction':.69,'annotation_y_fraction':.50,'annotation_scale':.8,
                'annotations':[{'start':.2,'end':2.8,'title':'说明','english':'Note','text':'解释框也应避开字幕。'}],
                'cover_title':'安全区域测试','cover_time':1,'platforms':{}})
            p.render(job)
            p.run(['ffmpeg','-v','error','-ss','1','-i',job/'video.mp4','-frames:v','1','-y',root/'frame.png'])
            from PIL import Image
            img=Image.open(root/'frame.png').convert('RGB')
            def white(box):
                return sum(1 for r,g,b in img.crop(box).getdata() if min(r,g,b)>210)
            self.assertGreater(white((0,400,360,480)),100)
            # The lower quarter is reserved for platform controls, nickname and description.
            self.assertEqual(white((0,480,360,640)),0)

    def test_render_and_subtitle_time(self):
        with tempfile.TemporaryDirectory(prefix='daily-video-test-') as tmp:
            root=Path(tmp); src=root/'input.mp4'; job=root/'job'; (job/'work').mkdir(parents=True)
            p.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=darkslategray:s=360x640:r=30:d=5',
                   '-f','lavfi','-i','sine=frequency=440:duration=5','-c:v','libx264','-c:a','aac','-shortest','-y',src])
            p.write(job/'source.json',{'path':str(src),'duration':5,'sha256':'test'})
            p.write(job/'editorial.json',{'reviewed':True,'source_evidence':[{'type':'synthetic fixture'}],
                'cuts':[[2,3]],'captions':[{'start':.2,'end':1.7,'text':'中文字幕测试'},
                {'start':3.2,'end':4.8,'text':'剪后时间与英文 Seed-ASR'}],'cover_title':'每日视频流程测试',
                'cover_time':1,'platforms':{'wechat_channels':{'title':'测试','description':'测试文案','tags':['#科普']}},
                'annotation_y_fraction':.035,'annotations':[{'start':3.2,'end':4.0,'title':'术语','english':'Term','text':'简短解释'}]})
            p.render(job)
            qa = p.check(job)
            self.assertTrue(qa['full_decode_passed'])
            self.assertEqual(qa['visual_review'],'required')
            self.assertTrue(Path(qa['contact_sheet']).is_file())
            self.assertIn('测试文案',(job/'视频号发布文案.txt').read_text())
            self.assertIn('\n#科普\n',(job/'视频号发布文案.txt').read_text())
            self.assertNotIn('##',(job/'视频号发布文案.txt').read_text())
            self.assertIn(1.85,qa['review_times'])
            self.assertIn(2.15,qa['review_times'])
            self.assertAlmostEqual(float(p.probe(job/'video.mp4')['format']['duration']),4,places=1)
            self.assertIn('00:00:02,200 --> 00:00:03,800',(job/'subtitles.srt').read_text())
            p.run(['ffmpeg','-v','error','-i',job/'video.mp4','-f','null','-'])
            p.run(['ffmpeg','-v','error','-ss','2.7','-i',job/'video.mp4','-frames:v','1','-y',root/'caption.png'])
            from PIL import Image
            img=Image.open(root/'caption.png').convert('RGB')
            # White burned-in glyphs in the expected subtitle area, not merely a generated sidecar.
            white=sum(1 for r,g,b in img.crop((0,430,360,480)).getdata() if min(r,g,b)>210)
            self.assertGreater(white,100)
            accent=sum(1 for r,g,b in img.crop((0,0,360,130)).getdata() if b>180 and g>150 and r<180)
            self.assertGreater(accent,20)
            p.run(['ffmpeg','-v','error','-ss','3.3','-i',job/'video.mp4','-frames:v','1','-y',root/'after.png'])
            after=Image.open(root/'after.png').convert('RGB')
            accent_after=sum(1 for r,g,b in after.crop((0,0,360,130)).getdata() if b>180 and g>150 and r<180)
            self.assertEqual(accent_after,0)

if __name__=='__main__': unittest.main()
