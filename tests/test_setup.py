"""Installation and ASR configuration checks; no real secrets or network calls."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / 'daily-article-video/scripts'
sys.path.insert(0, str(SCRIPTS))
import pipeline
spec = importlib.util.spec_from_file_location('video_setup', SCRIPTS / 'setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def test_install_is_idempotent_and_preserves_local_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = setup.install(Path(tmp), with_deps=False)
            target = Path(result['installed_skill'])
            self.assertTrue((target / 'scripts/pipeline.py').is_file())
            self.assertTrue((target / 'references/ASR_SETUP.md').is_file())
            self.assertTrue((target / 'references/INSTALL.md').is_file())
            self.assertEqual(setup.install(Path(tmp), with_deps=False), result)
            (target / 'SKILL.md').write_text('local customization')
            with self.assertRaises(RuntimeError):
                setup.install(Path(tmp), with_deps=False)
            self.assertEqual((target / 'SKILL.md').read_text(), 'local customization')

    def test_secret_file_permissions_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'private/voice.env'
            setup.save_config(path, {'VOLC_API_KEY': 'synthetic-test-value'})
            if os.name != 'nt':
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(RuntimeError):
                setup.save_config(path, {'VOLC_API_KEY': 'replacement'})
            self.assertIn('synthetic-test-value', path.read_text())

    def test_secret_file_not_written_inside_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.git').mkdir()
            path = root / 'nested/voice.env'
            with self.assertRaises(RuntimeError):
                setup.save_config(path, {'VOLC_API_KEY': 'synthetic'})
            self.assertFalse(path.exists())

    def test_modern_auth_environment_overrides_file_without_requiring_app_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'voice.env'
            path.write_text('VOLC_API_KEY=file-synthetic-key\n')
            with mock.patch.dict(os.environ, {'VOLC_CONFIG_FILE': str(path), 'VOLC_API_KEY': 'env-synthetic-key', 'VOLC_RESOURCE_ID': ''}, clear=True):
                config = pipeline.credentials()
            headers = pipeline.asr_headers(config)
            self.assertEqual(headers['X-Api-Key'], 'env-synthetic-key')
            self.assertNotIn('X-Api-App-Key', headers)
            self.assertEqual(headers['X-Api-Resource-Id'], 'volc.bigasr.auc_turbo')

    def test_legacy_headers_and_placeholder_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'absent.env'
            with mock.patch.dict(os.environ, {'VOLC_CONFIG_FILE': str(path), 'VOLC_APP_ID': 'synthetic-app', 'VOLC_ACCESS_KEY': 'synthetic-token'}, clear=True):
                headers = pipeline.asr_headers(pipeline.credentials())
            self.assertEqual(headers['X-Api-App-Key'], 'synthetic-app')
            self.assertEqual(headers['X-Api-Access-Key'], 'synthetic-token')
            self.assertNotIn('X-Api-Key', headers)
            with mock.patch.dict(os.environ, {'VOLC_CONFIG_FILE': str(path), 'VOLC_API_KEY': 'YOUR_API_KEY'}, clear=True):
                with self.assertRaises(RuntimeError):
                    pipeline.credentials()

    def test_doctor_is_offline_and_does_not_print_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {'VOLC_CONFIG_FILE': str(Path(tmp) / 'absent'), 'VOLC_API_KEY': 'synthetic-secret'}, clear=True):
                with mock.patch('pipeline.urllib.request.urlopen', side_effect=AssertionError('no network')):
                    result = setup.doctor()
            self.assertTrue(result['checks']['asr_configuration_present'])
            self.assertFalse(result['network_tested'])
            self.assertNotIn('synthetic-secret', json.dumps(result))

    def test_online_check_requires_upload_consent(self):
        with mock.patch('pipeline.urllib.request.urlopen', side_effect=AssertionError('no network')):
            with self.assertRaises(RuntimeError):
                setup.verify_audio(Path('nonexistent.wav'), False)

    def test_service_error_does_not_echo_provider_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / 'sample.mp3'
            audio.write_bytes(b'synthetic-audio')
            response = mock.MagicMock()
            response.headers = {'X-Api-Status-Code': '40000000', 'X-Api-Message': 'echoed-sensitive-value'}
            response.read.return_value = b'{"message":"echoed-sensitive-value"}'
            response.__enter__.return_value = response
            with mock.patch.dict(os.environ, {'VOLC_CONFIG_FILE': str(root / 'absent'), 'VOLC_API_KEY': 'synthetic-key'}, clear=True):
                with mock.patch('pipeline.urllib.request.urlopen', return_value=response):
                    with self.assertRaises(RuntimeError) as error:
                        pipeline.transcribe(audio, root / 'response.json')
            self.assertNotIn('echoed-sensitive-value', str(error.exception))
            self.assertFalse((root / 'response.json').exists())

    def test_online_check_mocked_success_requires_word_timestamps(self):
        result = {'result': {'utterances': [{'words': [{'start_time': 0, 'end_time': 300}]}]}}
        with mock.patch.object(setup.shutil, 'which', return_value='/synthetic/ffmpeg'), \
             mock.patch.object(setup.subprocess, 'check_output', return_value='5.0'), \
             mock.patch.object(setup.subprocess, 'run'), \
             mock.patch('pipeline.transcribe', return_value=result):
            verified = setup.verify_audio(Path('synthetic.wav'), True)
            self.assertTrue(verified['word_timestamps'])
            self.assertFalse(verified['transcript_printed'])
            result['result']['utterances'][0]['words'] = []
            with self.assertRaises(RuntimeError):
                setup.verify_audio(Path('synthetic.wav'), True)


if __name__ == '__main__':
    unittest.main()
