"""Nonblocking live recording control; credentials stay inside the worker."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from .processes import worker_command


class LiveRecorder(QObject):
    changed = Signal()
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None; self.state = 'idle'; self.seconds = 0
        self.result = None; self.error = None; self.buffer = b''
        self.deadline = QTimer(self);self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.timed_out)

    @property
    def active(self):return self.proc is not None

    def start(self, camera, destination):
        if self.active:return
        self.result = None;self.error = None;self.buffer = b'';self.seconds = 0
        proc = QProcess(self);self.proc = proc;self.state = 'starting'
        payload = {'op': 'record_live', 'camera': asdict(camera), 'destination': str(destination)}
        executable,args=worker_command()
        def started():
            proc.write((json.dumps(payload)+'\n').encode())
            if self.state == 'stopping':proc.write(b'{"cancel":true}\n')
        proc.started.connect(started)
        proc.readyReadStandardOutput.connect(lambda:self.read(proc))
        proc.readyReadStandardError.connect(lambda:proc.readAllStandardError())
        proc.finished.connect(lambda *_:self.finished(proc))
        proc.errorOccurred.connect(lambda error:self.process_error(proc,error))
        self.deadline.start(60000);self.changed.emit();proc.start(executable,args)

    def stop(self):
        if not self.active or self.state == 'stopping':return
        self.state = 'stopping'
        if self.proc.state() == QProcess.ProcessState.Running:
            self.proc.write(b'{"cancel":true}\n')
        self.deadline.start(15000);self.changed.emit()

    def read(self, proc):
        data = bytes(proc.readAllStandardOutput())
        if proc is not self.proc:return
        self.buffer = (self.buffer+data)[-65536:]
        while b'\n' in self.buffer:
            line,self.buffer = self.buffer.split(b'\n',1)
            try:event = json.loads(line)
            except (ValueError,UnicodeError):continue
            kind = event.get('event')
            if kind in ('recording','recording_progress'):
                self.seconds = event.get('seconds',0)
                if self.state != 'stopping':
                    self.state = 'recording';self.deadline.start(15000)
                self.changed.emit()
            elif kind == 'result':self.result = event['data']
            elif kind == 'error':self.error = event.get('message','Live recording failed.')

    def finished(self, proc):
        if proc is not self.proc:return
        self.read(proc);self.proc = None;self.state = 'idle';self.deadline.stop()
        proc.deleteLater();self.changed.emit()
        if self.result is not None:self.completed.emit(self.result)
        else:self.failed.emit(self.error or 'Live recording stopped unexpectedly. Check the recording folder for an unfinished .partial.mkv file.')

    def process_error(self, proc, error):
        if proc is self.proc and error == QProcess.ProcessError.FailedToStart:
            self.error = 'Could not start live recording. Run setup again and retry.'
            self.finished(proc)

    def timed_out(self):
        if self.proc:
            self.error = 'Live recording timed out. Check the camera and recording folder for an unfinished .partial.mkv file.'
            self.proc.kill()
