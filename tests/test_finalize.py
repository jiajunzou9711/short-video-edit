"""Deletion boundary tests; only synthetic jobs are created and removed."""
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'daily-article-video/scripts'))
from finalize import purge as _purge

def purge(job, **kwargs):
    return _purge(job, output_root=ROOT, **kwargs)

ROOT = None


class PurgeTests(unittest.TestCase):
    def setUp(self):
        global ROOT
        self.root_temp = tempfile.TemporaryDirectory(prefix='daily-video-purge-root-')
        self.addCleanup(self.root_temp.cleanup)
        ROOT = Path(self.root_temp.name)
        self.temp = tempfile.TemporaryDirectory(prefix='job-', dir=ROOT)
        self.job = Path(self.temp.name)
        (self.job/'source.json').write_text(json.dumps({'path':'/tmp/external-original.MOV'}))
        (self.job/'editorial.json').write_text(json.dumps({'source_evidence':[]}))
        (self.job/'video.mp4').write_bytes(b'synthetic-final')
        (self.job/'cover-wechat-channels.jpg').write_bytes(b'synthetic-cover')
        (self.job/'work').mkdir()
        (self.job/'work/asr.json').write_text('{}')

    def tearDown(self):
        self.temp.cleanup()

    def test_requires_upload_confirmation(self):
        with self.assertRaises(ValueError):
            purge(self.job, apply=True)
        self.assertTrue((self.job/'video.mp4').exists())

    def test_preview_preserves_then_apply_removes_everything(self):
        report = purge(self.job, uploads_confirmed=True)
        self.assertGreater(report['bytes'], 0)
        self.assertTrue((self.job/'video.mp4').exists())
        purge(self.job, uploads_confirmed=True, apply=True)
        self.assertFalse(self.job.exists())

    def test_original_inside_job_blocks_deletion(self):
        original = self.job/'original.MOV'
        original.write_bytes(b'user-original')
        (self.job/'source.json').write_text(json.dumps({'path':str(original)}))
        with self.assertRaises(ValueError):
            purge(self.job, uploads_confirmed=True, apply=True)
        self.assertTrue(original.exists())

    def _original(self, content=b'user-original'):
        import hashlib
        original = Path(self.outside.name)/'original.MOV'
        original.write_bytes(b'user-original')
        (self.job/'source.json').write_text(json.dumps({'path':str(original),'sha256':hashlib.sha256(content).hexdigest()}))
        return original

    def test_delete_original_requires_matching_hash(self):
        self.outside = tempfile.TemporaryDirectory(); self.addCleanup(self.outside.cleanup)
        original = self._original(content=b'different-file')
        with self.assertRaises(ValueError):
            purge(self.job, uploads_confirmed=True, apply=True, delete_original=True)
        self.assertTrue(original.exists())
        self.assertTrue(self.job.exists())

    def test_delete_original_preview_then_apply(self):
        self.outside = tempfile.TemporaryDirectory(); self.addCleanup(self.outside.cleanup)
        original = self._original()
        report = purge(self.job, uploads_confirmed=True, delete_original=True)
        self.assertEqual(report['delete_original'], str(original.resolve()))
        self.assertTrue(original.exists())
        purge(self.job, uploads_confirmed=True, apply=True, delete_original=True)
        self.assertFalse(original.exists())
        self.assertFalse(self.job.exists())

    def test_outside_output_refused(self):
        with tempfile.TemporaryDirectory() as external:
            with self.assertRaises(ValueError):
                purge(Path(external), uploads_confirmed=True, apply=True)
            self.assertTrue(Path(external).exists())


if __name__ == '__main__':
    unittest.main()
