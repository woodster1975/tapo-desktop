"""Serialized, viewport-driven thumbnail workers; never occupy the foreground job."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
from PySide6.QtCore import QObject,QProcess,QTimer,Signal
from .storage import thumbnail_path
from .processes import worker_command


class ThumbnailLoader(QObject):
    ready=Signal(object,object)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.context=None;self.camera=None;self.date=None
        self.cache={};self.queue=[];self.active=None;self.proc=None;self.enabled=False
        self.visible_keys=set();self.prefetch_keys=set();self.active_fallback=False;self.generation=0
        self.dispatch=QTimer(self);self.dispatch.setSingleShot(True);self.dispatch.timeout.connect(self.pump)
        self.deadline=QTimer(self);self.deadline.setSingleShot(True);self.deadline.setInterval(30000)
        self.deadline.timeout.connect(self.timed_out)

    def set_context(self,camera,date):
        context=(camera.id,camera.host,date) if camera and date else None
        if context==self.context:return
        self.reset();self.context=context;self.camera=camera;self.date=date

    def reset(self):
        self.generation+=1
        self.dispatch.stop();self.queue=[];self.cache={}
        if self.active is not None:self.cancel_active()
        self.context=None;self.camera=None;self.date=None;self.visible_keys=set();self.prefetch_keys=set()

    def cancel_active(self):
        self.deadline.stop()
        process=self.proc;self.proc=None;self.active=None
        if process:process.kill()  # Async: never wait on a decoder/network worker in the UI.

    def set_enabled(self,enabled):
        if enabled==self.enabled:return
        self.enabled=enabled
        if not enabled:
            self.dispatch.stop()
            if self.active is not None:self.cancel_active()
        elif self.queue:self.dispatch.start(80)

    def key(self,row):return (*self.context,int(row['start']),int(row['end']))

    def cached(self,row):
        if self.context is None:return None
        key=self.key(row)
        if key in self.cache:return self.cache[key]
        file=thumbnail_path(self.camera,self.date,row['start'],row['end'])
        try:
            if file.is_file() and 0<file.stat().st_size<=5_000_000:
                result={'available':True,'path':str(file)}
                self.cache[key]=result
                return result
        except OSError:pass
        return None

    def set_visible(self,rows,ahead=()):
        if self.context is None:return
        visible_keys={self.key(row) for row in rows}
        self.visible_keys=visible_keys
        forced=[item for item in self.queue if item[1] and item[0] in visible_keys]
        forced_keys={item[0] for item in forced}
        pending=[];fallback=[]
        for row in rows:
            key=self.key(row)
            if row.get('recording_type')=='1':continue
            data=self.cached(row)
            if key!=self.active and key not in forced_keys:
                if data is None:pending.append((key,False))
                elif data.get('deferred'):fallback.append((key,False))
        # Preserve the login while a short JPEG request finishes. Only interrupt
        # expensive video extraction when scrolling away from its row.
        if (pending or fallback) and self.active is not None and self.active not in visible_keys and self.active_fallback:
            self.cancel_active()
        requested=visible_keys|forced_keys
        prefetch=[];ahead_fallback=[];self.prefetch_keys=set()
        for row in ahead:
            key=self.key(row)
            if key in requested or row.get('recording_type')=='1':continue
            self.prefetch_keys.add(key)
            if key==self.active:continue
            data=self.cached(row)
            if data is None:prefetch.append((key,False))
            elif data.get('deferred'):ahead_fallback.append((key,False))
            requested.add(key)
        self.queue=forced+pending+prefetch+fallback+ahead_fallback
        if self.enabled and self.queue and self.active is None and not self.dispatch.isActive():self.dispatch.start(80)

    def retry(self,row):
        if self.context is None or row.get('recording_type')=='1':return
        key=self.key(row);self.cache.pop(key,None)
        if key==self.active:return
        self.queue=[(key,True)]+[item for item in self.queue if item[0]!=key]
        if self.enabled and self.active is None:self.dispatch.start(0)

    def pump(self):
        if not self.enabled or self.active is not None or not self.queue or self.context is None:return
        key,refresh=self.queue.pop(0)
        if key[:3]!=self.context:self.dispatch.start(0);return
        payload={'op':'thumbnail','camera':asdict(self.camera),'date':self.date,
                 'start':key[-2],'end':key[-1],'refresh':refresh,'preview_session':True,'session_scope':self.generation}
        self.active_fallback=bool(refresh or self.cache.get(key,{}).get('deferred'))
        payload.update(native_only=not self.active_fallback, fallback_only=self.active_fallback and not refresh)
        self.active=key
        if self.proc is not None:
            self.deadline.start(30000)
            self.proc.write((json.dumps(payload)+'\n').encode())
            return
        process=QProcess(self);self.proc=process
        process._thumbnail_buffer=b''
        executable,args=worker_command()
        process.started.connect(lambda:process.write((json.dumps(payload)+'\n').encode()))
        process.readyReadStandardOutput.connect(lambda:self.read_output(process))
        process.readyReadStandardError.connect(lambda:process.readAllStandardError())
        process.finished.connect(lambda *_:self.finished(process))
        process.errorOccurred.connect(lambda error:self.failed_to_start(process,key,error))
        # Cold imports on this Windows machine exceeded the old 30s deadline.
        # Allow startup once; warm media requests retain the shorter deadline.
        self.deadline.start(120000);process.start(executable,args)

    def read_output(self,process):
        try:data=bytes(process.readAllStandardOutput())
        except RuntimeError:return  # Parent teardown can already have deleted QProcess.
        # Worker emits sanitized metadata only; retain a bounded result buffer.
        process._thumbnail_buffer=(process._thumbnail_buffer+data)[-65536:]
        if process is not self.proc:return
        while b'\n' in process._thumbnail_buffer:
            line,process._thumbnail_buffer=process._thumbnail_buffer.split(b'\n',1)
            try:event=json.loads(line)
            except (ValueError,TypeError):continue
            if event.get('event')=='result' and self.active is not None:
                key=self.active;self.active=None;self.deadline.stop()
                self.deliver(key,event['data'])

    def finished(self,process):
        self.read_output(process)
        try:process.deleteLater()
        except RuntimeError:return
        if process is not self.proc:return
        key=self.active
        self.deadline.stop();self.proc=None;self.active=None
        if key:self.deliver(key,{'available':False})

    def deliver(self,key,result):
        if self.context is not None and key[:3]==self.context:
            self.cache[key]=result
            self.ready.emit(key,result)
            if result.get('deferred') and key in (self.visible_keys|self.prefetch_keys) and not any(item[0]==key for item in self.queue):
                self.queue.append((key,False))
        if self.enabled and self.queue:self.dispatch.start(120)

    def failed_to_start(self,process,key,error):
        if error==QProcess.ProcessError.FailedToStart and process is self.proc:
            self.cancel_active();process.deleteLater();self.deliver(key,{'available':False})

    def timed_out(self):
        key=self.active;self.cancel_active()
        if key:self.deliver(key,{'available':False})
