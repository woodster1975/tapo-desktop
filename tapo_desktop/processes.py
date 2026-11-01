"""Shared worker launch policy: GUI entry point never needs a console."""
from pathlib import Path
import subprocess
import sys


def worker_command():
    if getattr(sys,'frozen',False):
        if sys.platform=='win32':
            internal=Path(getattr(sys,'_MEIPASS',Path(sys.executable).parent/'_internal'))
            return str(internal/'TapoDeskWorker.exe'),['--worker']
        return sys.executable,['--worker']
    executable=str(Path(sys.executable).with_name('python.exe')) if sys.platform=='win32' else sys.executable
    return executable,[str(Path(__file__).resolve().parents[1]/'run.py'),'--worker']


def prepare_worker_process():
    """All worker subprocesses, including upstream FFmpeg jobs, are headless.

    Install before importing asyncio/PyTapo so their Popen subclasses inherit
    the same policy. This affects only the isolated noninteractive worker.
    """
    if sys.platform!='win32' or getattr(subprocess.Popen,'_tapo_headless',False):return
    base=subprocess.Popen
    class HeadlessPopen(base):
        _tapo_headless=True
        def __init__(self,*args,**kwargs):
            flags=kwargs.get('creationflags',0)
            kwargs['creationflags']=(flags & ~subprocess.CREATE_NEW_CONSOLE)|subprocess.CREATE_NO_WINDOW
            super().__init__(*args,**kwargs)
    subprocess.Popen=HeadlessPopen


def probe_startup(app,destination):
    """Non-camera packaging check through the real GUI-to-worker pipe."""
    import json
    from PySide6.QtCore import QProcess,QTimer
    proc=QProcess(app);timer=QTimer(app);timer.setSingleShot(True)
    app._startup_probe=(proc,timer)
    completed=False
    def finish(*_):
        nonlocal completed
        if completed:return
        completed=True;timer.stop();data={}
        for line in bytes(proc.readAllStandardOutput()).splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('event')=='result':data=event['data']
        gui_console=False
        if sys.platform=='win32':
            import ctypes
            gui_console=bool(ctypes.windll.kernel32.GetConsoleWindow())
        ok=bool(data) and not gui_console and not data.get('console_window',True)
        if sys.platform=='win32':ok=ok and data.get('subprocesses_hidden',False) and data.get('async_subprocesses_hidden',False)
        Path(destination).write_text(json.dumps({'gui_console':gui_console,'worker':data,'ok':ok},indent=2))
        app.exit(0 if ok else 1)
    proc.started.connect(lambda:proc.write(b'{"op":"process_status"}\n'))
    proc.finished.connect(finish)
    proc.errorOccurred.connect(lambda error:finish() if error==QProcess.ProcessError.FailedToStart else None)
    timer.timeout.connect(lambda:proc.kill())
    executable,args=worker_command();timer.start(30000);proc.start(executable,args)
