"""Own one cancellable recording relay independently of foreground operations."""
from dataclasses import asdict
import json,sys
from pathlib import Path
from PySide6.QtCore import QObject,QProcess,Signal
from .processes import worker_command


class RecordingPlayback(QObject):
    ready=Signal(str)
    failed=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.proc=None;self.buffer=b''
    def start(self,camera,date,start,end):
        self.stop();proc=QProcess(self);self.proc=proc;self.buffer=b''
        payload={'op':'playback','camera':asdict(camera),'date':date,'start':start,'end':end}
        executable,args=worker_command()
        proc.started.connect(lambda:proc.write((json.dumps(payload)+'\n').encode()))
        proc.readyReadStandardOutput.connect(lambda:self.read(proc));proc.readyReadStandardError.connect(lambda:proc.readAllStandardError())
        proc.finished.connect(lambda *_:self.finished(proc));proc.errorOccurred.connect(lambda error:self.error(proc,error))
        proc.start(executable,args)
    def read(self,proc):
        data=bytes(proc.readAllStandardOutput())
        if proc is not self.proc:return
        self.buffer+=data
        while b'\n' in self.buffer:
            line,self.buffer=self.buffer.split(b'\n',1)
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('event')=='stream':self.ready.emit(event['url'])
            elif event.get('event')=='error':
                self.error_kind=event.get('kind','UserError');self.error_where=event.get('where',[]);self.error_codes=event.get('codes',[]);self.failed.emit(event['message'])
    def finished(self,proc):
        self.read(proc);proc.deleteLater()
        if proc is self.proc:
            self.proc=None
            if proc.exitCode()!=0:self.failed.emit('Recording stream stopped unexpectedly. Retry playback or download the clip.')
    def error(self,proc,error):
        if proc is self.proc and error==QProcess.ProcessError.FailedToStart:
            self.proc=None;proc.deleteLater();self.failed.emit('Could not start recorded playback. Retry the operation.')
    def stop(self):
        proc=self.proc;self.proc=None;self.buffer=b''
        if proc:proc.kill()
