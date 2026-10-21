#!/usr/bin/env python3
"""Agent-neutral installation, local diagnostics, and explicit ASR connection testing."""
import argparse
import getpass
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv

SKILL = Path(__file__).resolve().parents[1]
EXCLUDED = {'.venv', '__pycache__', '.DS_Store'}


def snapshot(directory):
    return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob('*')
            if p.is_file() and not any(part in EXCLUDED for part in p.relative_to(directory).parts)}


def install(skills_dir, with_deps=True):
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10 or newer is required.')
    target = skills_dir.expanduser().resolve() / SKILL.name
    if target.exists():
        if target.is_symlink() or snapshot(target) != snapshot(SKILL):
            raise RuntimeError('Existing skill differs; compare it before upgrading. Nothing overwritten.')
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns(*EXCLUDED))
    python = target / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if with_deps:
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(target / '.venv')
        subprocess.run([str(python), '-m', 'pip', 'install', 'Pillow>=10'], check=True)
    return {'installed_skill': str(target), 'python': str(python) if with_deps else sys.executable,
            'next': 'Run doctor with this Python; configure missing ASR credentials locally.'}


def config_path():
    return Path(os.environ.get('VOLC_CONFIG_FILE', str(Path.home() / '.config/volc.env'))).expanduser()


def save_config(path, values):
    """Refuse accidental overwrite and repository-local secret storage."""
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise RuntimeError('Configuration already exists; edit it locally rather than overwriting.')
    if any((parent / '.git').exists() for parent in [path.parent, *path.parents]):
        raise RuntimeError('Store credentials outside Git repositories.')
    path.parent.mkdir(parents=True, exist_ok=True)
    if any('\n' in value or '\r' in value for value in values.values()):
        raise RuntimeError('Configuration values must each be one line.')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(''.join(f'{key}={value}\n' for key, value in values.items()))


def configure():
    if not sys.stdin.isatty():
        raise RuntimeError('Open an interactive local terminal for secure credential entry; do not send secrets through agent chat.')
    mode = input('Authentication: [1] API Key (default), [2] legacy App ID + Access Token: ').strip()
    if mode not in {'', '1', '2'}:
        raise RuntimeError('Choose 1 or 2.')
    if mode == '2':
        values = {'VOLC_APP_ID': getpass.getpass('App ID (hidden): ').strip(),
                  'VOLC_ACCESS_KEY': getpass.getpass('Access Token (hidden): ').strip()}
    else:
        values = {'VOLC_API_KEY': getpass.getpass('Doubao Voice API Key (hidden): ').strip()}
    if not all(values.values()):
        raise RuntimeError('Empty credentials were not saved.')
    values['VOLC_RESOURCE_ID'] = input('Resource ID [volc.bigasr.auc_turbo]: ').strip() or 'volc.bigasr.auc_turbo'
    save_config(config_path(), values)
    return {'configuration_saved': True, 'network_tested': False,
            'permissions': 'Owner-only file on POSIX; check the user ACL on Windows.'}


def doctor():
    checks = {'python_3_10_or_newer': sys.version_info >= (3, 10),
              'pillow': importlib.util.find_spec('PIL') is not None,
              'ffmpeg': shutil.which('ffmpeg') is not None,
              'ffprobe': shutil.which('ffprobe') is not None,
              'caption_font': Path(os.environ.get('DAILY_VIDEO_FONT', '/System/Library/Fonts/STHeiti Medium.ttc')).is_file(),
              'card_font': Path(os.environ.get('DAILY_VIDEO_CARD_FONT', '/System/Library/Fonts/Hiragino Sans GB.ttc')).is_file()}
    # Import only after dependencies are available. No request is made.
    if checks['pillow']:
        from pipeline import credentials
        try:
            credentials()
            checks['asr_configuration_present'] = True
        except RuntimeError:
            checks['asr_configuration_present'] = False
    else:
        checks['asr_configuration_present'] = False
    return {'checks': checks, 'local_ready': all(checks.values()), 'network_tested': False,
            'note': 'Presence checks do not verify service permissions, billing, font rendering, or transcription quality.'}


def verify_audio(audio, consent):
    if not consent:
        raise RuntimeError('This uploads the named audio to Doubao Voice and may incur fees. Obtain consent, then pass --allow-upload.')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('Install ffmpeg and ffprobe first.')
    from pipeline import transcribe
    # Use a short user-provided sample, never an entire video implicitly.
    duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                             '-of', 'default=noprint_wrappers=1:nokey=1', str(audio)], text=True))
    if not 0 < duration <= 30:
        raise RuntimeError('Choose a short audio sample of at most 30 seconds.')
    with tempfile.TemporaryDirectory(prefix='short-video-asr-check-') as tmp:
        sample = Path(tmp) / 'sample.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(audio), '-vn', '-ac', '1', '-ar', '16000',
                        '-b:a', '64k', '-y', str(sample)], check=True)
        result = transcribe(sample, Path(tmp) / 'response.json')
        utterances = result['result']['utterances']
        timed_words = [word for item in utterances for word in item.get('words', [])
                       if word.get('start_time', -1) >= 0 and word.get('end_time', -1) > word.get('start_time', -1)]
        if not timed_words:
            raise RuntimeError('ASR responded without word timestamps; the subtitle workflow is not ready.')
        return {'network_tested': True, 'word_timestamps': True, 'utterance_count': len(utterances),
                'transcript_printed': False, 'local_temporary_audio_and_response_removed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('install')
    command.add_argument('--skills-dir', type=Path, required=True, help='Host agent skill directory; inspect the host before choosing it')
    command.add_argument('--skip-deps', action='store_true', help='Copy only; does not declare dependencies ready')
    commands.add_parser('doctor')
    commands.add_parser('configure-asr')
    command = commands.add_parser('verify-asr')
    command.add_argument('--audio', type=Path, required=True)
    command.add_argument('--allow-upload', action='store_true')
    args = parser.parse_args()
    if args.command == 'install':
        result = install(args.skills_dir, not args.skip_deps)
    elif args.command == 'doctor':
        result = doctor()
    elif args.command == 'configure-asr':
        result = configure()
    else:
        result = verify_audio(args.audio, args.allow_upload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == 'doctor' and not result['local_ready']:
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
        # Only known safe, value-free messages are emitted for configuration errors.
        # Subprocess failures may contain user paths; never dump request objects or environment.
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, RuntimeError) else 'Setup failed; check dependencies, paths and the selected command.', file=sys.stderr)
        sys.exit(1)
