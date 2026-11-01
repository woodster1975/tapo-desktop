#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Source installations may keep FFmpeg beside the app instead of changing PATH.
if sys.platform == 'win32':
    ffmpeg_dirs = ([Path(sys._MEIPASS) / 'tools' / 'ffmpeg'] if getattr(sys, 'frozen', False) else [])
    ffmpeg_dirs += [Path(sys.executable).resolve().parent.parent / 'tools' / 'ffmpeg',
                   Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'TapoDesk' / 'tools' / 'ffmpeg',
                   Path(__file__).resolve().parent / 'tools' / 'ffmpeg']
    for ffmpeg_dir in ffmpeg_dirs:
        if (ffmpeg_dir / 'ffmpeg.exe').is_file() and (ffmpeg_dir / 'ffprobe.exe').is_file():
            os.environ['PATH'] = str(ffmpeg_dir) + os.pathsep + os.environ.get('PATH', '')
            break
if sys.version_info < (3, 11):
    raise SystemExit('Tapo Desk requires Python 3.11 or newer (3.12 recommended).')
if '--worker' in sys.argv:
    from tapo_desktop.processes import prepare_worker_process
    prepare_worker_process()
    from tapo_desktop.worker import main
    main()
else:
    from tapo_desktop.app import main
    main()
