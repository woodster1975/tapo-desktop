#!/usr/bin/env python3
"""Local Tapo microSD browser/downloader; Python 3.10+."""
import argparse
import asyncio
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import getpass
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo


def date_arg(value):
    try:
        return datetime.strptime(value.replace('-', ''), '%Y%m%d').strftime('%Y%m%d')
    except ValueError:
        raise argparse.ArgumentTypeError('Use YYYYMMDD or YYYY-MM-DD') from None


def records(raw):
    """Handle indexed camera dictionaries without assuming their key names."""
    result = []
    def walk(node):
        if isinstance(node, dict):
            if 'startTime' in node and 'endTime' in node:
                start, end = int(node['startTime']), int(node['endTime'])
                if end <= start:
                    raise ValueError('Invalid recording interval')
                result.append((start, end))
            else:
                for value in node.values():
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(raw)
    if raw and not result:
        raise ValueError('Unrecognized recording response')
    return sorted(set(result))


def dates(raw):
    found = set()
    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, (str, int)) and re.fullmatch(r'\d{8}', str(node)):
            found.add(date_arg(str(node)))
    walk(raw)
    if raw and not found:
        raise ValueError('Unrecognized recording-date response')
    return sorted(found)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', required=True, help='Camera LAN IP address')
    p.add_argument('--timezone', default='Europe/London', help='Display timezone (IANA name)')
    p.add_argument('--transport', choices=['auto', 'pytapo', 'tpap'], default='auto')
    p.add_argument('--keyring', action='store_true', help='Read Tapo password from desktop keyring (service=tapo-poc, account=owner)')
    p.add_argument('--camera-account', action='store_true', help='Use a separate camera account for control login')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('check', help='Authenticate and confirm selected API availability')
    d = sub.add_parser('dates')
    d.add_argument('--from-date', type=date_arg, default='20000101')
    d.add_argument('--to-date', type=date_arg, default=datetime.now().strftime('%Y%m%d'))
    s = sub.add_parser('segments')
    s.add_argument('date', type=date_arg)
    s.add_argument('--json', action='store_true')
    d = sub.add_parser('download')
    d.add_argument('date', type=date_arg)
    d.add_argument('--start', required=True, type=int, help='Exact startTime from segments')
    d.add_argument('--end', required=True, type=int, help='Exact endTime from segments')
    d.add_argument('--output-dir', type=Path, default=Path('clips'))
    d.add_argument('--window-size', type=int, choices=range(1, 501), metavar='1..500', default=50)
    d.add_argument('--method', choices=['download', 'playback'], default='download')
    d.add_argument('--timeout', type=int, default=1800, help='Overall download timeout in seconds')
    return p


class CredentialError(RuntimeError):
    """Safe credential-provider error without secret contents."""


def keyring_password():
    if not shutil.which('secret-tool'):
        raise CredentialError('Install libsecret-tools to use --keyring')
    try:
        result = subprocess.run(
            ['secret-tool', 'lookup', 'service', 'tapo-poc', 'account', 'owner'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise CredentialError('Keyring unavailable or locked; unlock your desktop keyring and retry') from None
    # stdout is a pipe: secret-tool does not append a terminal newline.
    if result.returncode != 0 or not result.stdout:
        raise CredentialError('Tapo keyring entry unavailable; check the entry and unlock your desktop keyring')
    try:
        return result.stdout.decode('utf-8')
    except UnicodeError:
        raise CredentialError('Keyring entry is not valid text') from None


def secret(env, prompt):
    value = os.environ.pop(env, None)
    if value is None:
        if not sys.stdin.isatty():
            raise ValueError(f'Set {env} or run in an interactive terminal')
        value = getpass.getpass(prompt)
    if not value:
        raise ValueError('Empty password')
    return value


class ClipError(RuntimeError):
    """Safe application-generated message, containing no protocol data."""


def download_clip(cam, a, downloader_cls):
    # PyTapo synchronous control calls run their own event loop. Finish them
    # before starting the media loop; getUserID is cached for Downloader.
    correction = cam.getTimeCorrection()
    cam.getUserID()
    return asyncio.run(save_clip(cam, a, downloader_cls, correction))


async def save_clip(cam, a, downloader_cls, correction, progress=None):
    if a.timeout <= 0:
        raise ValueError('Timeout must be positive')
    for executable in ('ffmpeg', 'ffprobe'):
        if not shutil.which(executable):
            raise ValueError(f'Install {executable} first')
    if correction is False or not isinstance(correction, (int, float)):
        raise ValueError('Camera clock unavailable')
    target_dir = a.output_dir.expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = target_dir / f'{a.date}_{a.start}-{a.end}.mp4'
    if target.exists():
        raise FileExistsError('Destination exists; choose another output directory')
    # Same filesystem staging keeps incomplete media out of the final filename.
    with tempfile.TemporaryDirectory(prefix='.tapo-', dir=target_dir) as stage:
        staged = Path(stage) / 'clip.mp4'
        dl = downloader_cls(cam, a.start, a.end, correction,
                            outputDirectory=stage + os.sep, padding=0,
                            overwriteFiles=False, window_size=a.window_size,
                            fileName=staged.name, method=a.method,
                            stall_timeout=120, progressInterval=2)
        async with asyncio.timeout(a.timeout) if sys.version_info >= (3, 11) else legacy_timeout(a.timeout):
            async for status in dl.download():
                action = status.get('currentAction', '')
                if progress:
                    progress(status)
                if action in ('Camera busy', 'Recording in progress', 'Skipping'):
                    raise ClipError(action)
        if not staged.is_file() or staged.stat().st_size == 0:
            raise ClipError('Download produced no media')
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                                'format=duration:stream=codec_type', '-of', 'json', str(staged)],
                               capture_output=True, text=True, timeout=30, check=True)
        info = json.loads(probe.stdout)
        duration = float(info['format']['duration'])
        if not any(s.get('codec_type') == 'video' for s in info.get('streams', [])) or duration < max(0.1, a.end-a.start-5):
            raise ClipError('Incomplete or invalid video')
        os.chmod(staged, 0o600)
        os.link(staged, target)  # atomic no-clobber publication
    return target


class legacy_timeout:
    """Python 3.10 equivalent of asyncio.timeout."""
    def __init__(self, seconds):
        self.seconds = seconds
    async def __aenter__(self):
        self.task = asyncio.current_task()
        self.fired = False
        def cancel():
            self.fired = True
            self.task.cancel()
        self.timer = asyncio.get_running_loop().call_later(self.seconds, cancel)
    async def __aexit__(self, kind, value, tb):
        self.timer.cancel()
        if self.fired and kind is asyncio.CancelledError:
            raise TimeoutError('Download timeout') from None


def main(argv=None):
    a = parser().parse_args(argv)
    cam = None
    os.umask(0o077)
    logging.disable(logging.CRITICAL)  # Never print upstream protocol responses/secrets.
    try:
        ip = ipaddress.ip_address(a.host)
        if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError('Use the camera private LAN IPv4 address')
        tz = ZoneInfo(a.timezone)
        if a.command == 'dates' and a.from_date > a.to_date:
            raise ValueError('Date range is reversed')
        if a.command == 'download' and a.end <= a.start:
            raise ValueError('End must be after start')
        # Check dependencies before requesting any credentials.
        try:
            with open(os.devnull, 'w') as null, redirect_stdout(null), redirect_stderr(null):
                from pytapo import Tapo
                from pytapo.media_stream.downloader import Downloader
        except ImportError as exc:
            name = getattr(exc, 'name', None)
            module = name if isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_.]+', name) else 'unknown'
            print(f'Python dependency unavailable: {module}. In this folder run: bash setup.sh\n'
                  'Then run: .venv/bin/python tapo_poc.py --host ' + a.host + ' check', file=sys.stderr)
            return 1
        cloud = keyring_password() if a.keyring else secret('TAPO_CLOUD_PASSWORD', 'Tapo account password (hidden): ')
        os.environ.pop('TAPO_CLOUD_PASSWORD', None)
        user, password = 'admin', cloud
        if a.camera_account:
            user = os.environ.pop('TAPO_CAMERA_USER', None) or input('Camera account username: ')
            password = secret('TAPO_CAMERA_PASSWORD', 'Camera account password (hidden): ')
        # Suppress upstream output as well as exception text, which may contain tokens.
        with open(os.devnull, 'w') as null, redirect_stdout(null), redirect_stderr(null):
            cam = Tapo(a.host, user, password, cloudPassword=cloud,
                       printDebugInformation=False, printWarnInformation=False,
                       redactConfidentialInformation=True,
                       transportMethod=None if a.transport == 'auto' else a.transport)
            if a.command == 'check':
                result = 'Authenticated; recording search and download API loaded.'
            elif a.command == 'dates':
                result = '\n'.join(dates(cam.getRecordingsList(a.from_date, a.to_date))) or 'No recording dates.'
            else:
                clips = records(cam.getRecordings(a.date))
                if a.command == 'segments':
                    rows = [{'startTime': s, 'endTime': e,
                             'start': datetime.fromtimestamp(s, timezone.utc).astimezone(tz).isoformat(),
                             'end': datetime.fromtimestamp(e, timezone.utc).astimezone(tz).isoformat(),
                             'seconds': e-s} for s, e in clips]
                    result = json.dumps(rows, indent=2) if a.json else '\n'.join(
                        f"{r['startTime']} {r['endTime']}  {r['start']} → {r['end']} ({r['seconds']}s)" for r in rows) or 'No segments.'
                else:
                    if (a.start, a.end) not in clips:
                        raise ValueError('Selected interval is not in the current segment list')
                    result = 'Saved ' + str(download_clip(cam, a, Downloader))
        print(result)
        return 0
    except (KeyboardInterrupt, EOFError):
        print('Cancelled.', file=sys.stderr)
        return 130
    except (ClipError, CredentialError) as exc:
        print('Operation failed: ' + str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        # Only expose numeric API codes, never raw exception/protocol text.
        codes = sorted(set(re.findall(r'(?<!\d)-\d{4,6}(?!\d)', str(exc))))
        print('Operation failed (' + type(exc).__name__ + ')' +
              ('; camera code ' + ', '.join(codes) if codes else '') +
              '. See README troubleshooting. No credentials or raw response printed.', file=sys.stderr)
        return 1
    finally:
        if cam is not None:
            try:
                with open(os.devnull, 'w') as null, redirect_stdout(null), redirect_stderr(null):
                    cam.close()
            except Exception:
                pass


if __name__ == '__main__':
    sys.exit(main())
