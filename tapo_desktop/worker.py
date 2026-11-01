"""One operation per child process. Only sanitized JSON events reach the UI."""
import asyncio
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import threading
from types import SimpleNamespace
from .storage import Camera, UserError, get_secret, put_secret, cache_dir, export_clip, shared_live_credentials, store_shared_live_account, migrate_shared_live_account

_out = sys.stdout
_cancel = threading.Event()
_converting = threading.Event()


def emit(event, **values):
    _out.write(json.dumps({'event': event, **values}) + '\n')
    _out.flush()


def progress(status):
    total = float(status.get('total', 0))
    done = float(status.get('progress', 0))
    percent = max(0, min(99, round(done / total * 100))) if total > 0 and math.isfinite(done) else None
    allowed = {'Downloading','Retrying','Converting','Converting [shorter]','Recording in progress','Camera busy','Skipping'}
    action = status.get('currentAction', '')
    if action.startswith('Converting'):
        _converting.set()
    emit('progress', action=action if action in allowed else 'Preparing clip', percent=percent)


async def media_job(cam, args, correction):
    from pytapo.media_stream.downloader import Downloader
    from .camera_api import save_clip
    task = asyncio.create_task(save_clip(cam, args, Downloader, correction, progress))
    async def watch():
        while not task.done():
            if _cancel.is_set() and not _converting.is_set():
                task.cancel()
                return
            await asyncio.sleep(0.1)
    watcher = asyncio.create_task(watch())
    try:
        return await task
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def result_for(request, preview_session=None):
    op = request['op']
    if op == 'process_status':
        if sys.platform!='win32':return {'console_window':False,'subprocesses_hidden':False}
        import ctypes
        from asyncio.windows_utils import Popen as AsyncPopen
        import subprocess
        return {'console_window':bool(ctypes.windll.kernel32.GetConsoleWindow()),
            'subprocesses_hidden':bool(getattr(subprocess.Popen,'_tapo_headless',False)),
            'async_subprocesses_hidden':issubclass(AsyncPopen,subprocess.Popen)}
    if op == 'discover':
        from .discovery import scan
        emit('progress',action='Scanning the local network…',percent=None)
        return asyncio.run(scan(request['network'],address=request.get('address'),cancelled=_cancel,
            on_progress=lambda count:emit('progress',action=f'Scanning… {count} Tapo devices found',percent=None)))
    if op == 'live_wall':
        rows=[];shared=None;shared_error=None
        for raw in request['cameras']:
            if _cancel.is_set():raise asyncio.CancelledError()
            camera=Camera.from_dict(raw)
            try:
                if camera.use_shared_credentials:
                    if shared_error:raise UserError(shared_error)
                    if shared is None:
                        try:shared=shared_live_credentials()
                        except UserError as exc:
                            shared_error=str(exc);raise
                    username,password=shared
                else:
                    if not camera.username:raise UserError('Add this camera’s Camera Account in Credentials.')
                    username,password=camera.username,get_secret('camera',camera.id)
                rows.append({'id':camera.id,'host':camera.host,'stream':camera.stream,
                             'username':username,'password':password})
            except UserError as exc:
                rows.append({'id':camera.id,'error':str(exc)})
        return {'cameras':rows}
    if op == 'migrate_shared_live':
        settings=migrate_shared_live_account()
        return {'configured':bool(settings['username'])}
    if op == 'store_camera_live':
        if request.get('password'):
            put_secret('camera',request['password'],request['camera_id'])
        else:
            get_secret('camera',request['camera_id'])
        return {'saved':True}
    if op == 'store_shared_live':
        store_shared_live_account(request['username'],request.get('password',''))
        return {'saved':True}
    if op == 'store':
        put_secret(request['kind'], request['password'], request.get('camera_id'))
        return {'saved': True}
    camera = Camera.from_dict(request['camera'])
    if op == 'record_live':
        from .live_recording import camera_url, record_stream
        credentials = result_for({'op':'live', 'camera':request['camera']})
        return record_stream(camera_url(credentials), request['destination'], emit, _cancel.is_set)
    if op == 'live':
        if camera.use_shared_credentials:
            username,password=shared_live_credentials()
        else:
            username=camera.username
            if username:password=get_secret('camera',camera.id)
        if not username:
            raise UserError('Add the Camera Account username and password in Credentials to use live view.')
        return {'username': username, 'password': password,
                'host': camera.host, 'stream': camera.stream}
    if op == 'export':
        export_clip(request['source'], request['destination'])
        return {'path': request['destination']}
    emit('progress', action='Loading camera support', percent=None)
    from pytapo import Tapo
    from .camera_api import records, dates, ClipError
    emit('progress', action='Reading saved credentials', percent=None)
    cloud = get_secret('cloud') if not preview_session else None
    cam = None
    try:
        emit('progress', action='Connecting to camera', percent=None)
        if preview_session:
            cam = preview_session['camera']
        else:
            cam = Tapo(camera.host, 'admin', cloud, cloudPassword=cloud,
                       printDebugInformation=False, printWarnInformation=False,
                       redactConfidentialInformation=True)
            if preview_session is not None:preview_session['camera']=cam
        if _cancel.is_set():
            raise asyncio.CancelledError()
        if op == 'dates':
            # End range explicitly includes today's camera date in normal installations.
            return {'dates': dates(cam.getRecordingsList(end_date=(datetime.now()+timedelta(days=1)).strftime('%Y%m%d')))}
        if op == 'info':
            # Whitelist metadata; device IDs, aliases, network and account fields are excluded.
            raw = cam.getBasicInfo()
            block = raw.get('device_info', {}).get('basic_info', raw)
            allowed = ('device_model', 'model', 'sw_version', 'hw_version', 'firmware_version', 'hardware_version')
            return {k:str(block[k]) for k in allowed if k in block}
        date = request['date']
        if preview_session is not None and 'recordings' in preview_session:
            raw_recordings=preview_session['recordings']
        else:
            raw_recordings=cam.getRecordings(date)
            if preview_session is not None:preview_session['recordings']=raw_recordings
        clips = records(raw_recordings)
        if op == 'playback':
            start,end=int(request['start']),int(request['end'])
            if (start,end) not in clips:raise UserError('This recording is no longer on the card. Refresh and retry.')
            cam.getUserID()
            from .recording_stream import serve
            return serve(cam,start,end,emit,_cancel.is_set)
        if op == 'segments':
            from .detections import recording_rows,detection_metadata
            rows=recording_rows(raw_recordings)
            try:
                metadata=detection_metadata(cam,date,rows,_cancel.is_set)
            except Exception:
                metadata={'events_available':False,'events_complete':False,'event_count':0}
            return {'segments':rows,**metadata}
        if op == 'thumbnail':
            from .detections import recording_rows
            start,end=int(request['start']),int(request['end'])
            row=next((r for r in recording_rows(raw_recordings) if (r['start'],r['end'])==(start,end)),None)
            if row is None:raise UserError('This recording is no longer on the microSD card. Refresh and select another clip.')
            if row['recording_type']=='1':
                return {'available':False,'message':'Continuous recordings do not have camera thumbnails.'}
            from .storage import thumbnail_path
            file=thumbnail_path(camera,date,start,end)
            output=file.parent
            output.mkdir(parents=True,exist_ok=True,mode=0o700)
            if not request.get('refresh') and file.is_file() and file.stat().st_size:return {'available':True,'path':str(file)}
            # Cache synchronous control calls before entering PyTapo's async media loop.
            cam.getUserID()
            try:
                from pytapo.media_stream.snapshot import getRecordingSnapshot
                async def snapshot():
                    # Missing camera JPEGs otherwise delay every visible row by six
                    # seconds before the recorded-frame fallback can even start.
                    timeout=6 if request.get('refresh') else 3
                    task=asyncio.create_task(getRecordingSnapshot(cam,start,timeout=timeout))
                    try:
                        for _ in range(100):
                            if _cancel.is_set():raise asyncio.CancelledError()
                            if task.done():return task.result()
                            await asyncio.sleep(0.1)
                        return None
                    finally:
                        if not task.done():task.cancel()
                        await asyncio.gather(task,return_exceptions=True)
                image=None if request.get('fallback_only') else asyncio.run(snapshot())
            except Exception:
                image=None
            source='camera'
            if not image or not image.startswith(b'\xff\xd8') or len(image)>5_000_000:
                if request.get('native_only'):
                    return {'available':False,'deferred':True}
                # Some valid event recordings have no camera-maintained JPEG.
                # Retrieve only a bounded sample and retain its first video frame.
                from .recording_preview import recording_bytes,frame_from_bytes
                try:
                    data=asyncio.run(recording_bytes(cam,start,end,_cancel.is_set))
                    if _cancel.is_set():raise asyncio.CancelledError()
                    image=frame_from_bytes(data);source='recording-frame'
                except Exception:
                    image=None
            if not image or not image.startswith(b'\xff\xd8') or len(image)>5_000_000:
                return {'available':False,'message':'No camera thumbnail or recorded-frame preview was available. Playback and download can still be tried.'}
            fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'wb') as handle:handle.write(image)
            return {'available':True,'path':str(file),'source':source}
        if op != 'download':
            raise UserError('Unknown camera operation.')
        start, end = int(request['start']), int(request['end'])
        if (start,end) not in clips:
            raise UserError('This recording is no longer on the microSD card. Refresh the date and select another clip.')
        output = cache_dir()/(camera.id+'-'+camera.host.replace('.','_'))
        output.mkdir(exist_ok=True, mode=0o700)
        file = output/f'{date}_{start}-{end}.mp4'
        if file.is_file() and file.stat().st_size:
            return {'path':str(file),'cached':True}
        correction = cam.getTimeCorrection()
        cam.getUserID()
        args = SimpleNamespace(timeout=1800, output_dir=output, date=date, start=start,end=end,
                               window_size=50,method='download')
        try:
            path = asyncio.run(media_job(cam,args,correction))
        except ClipError as exc:
            raise UserError(str(exc)) from None
        if _cancel.is_set():
            raise asyncio.CancelledError()
        return {'path':str(path),'cached':False}
    finally:
        if cam and preview_session is None:
            try:
                cam.close()
            except Exception:
                pass


def listen():
    for line in sys.stdin:
        if line.strip():
            _cancel.set()


def main():
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    try:
        request = json.loads(sys.stdin.readline())
        if request.get('preview_session') and request.get('op')=='thumbnail':
            preview_requests(request)
            return
        threading.Thread(target=listen,daemon=True).start()
        # Never forward PyTapo/FFmpeg/keyring logs or protocol exception strings.
        with open(os.devnull,'w') as null, redirect_stdout(null), redirect_stderr(null):
            result = result_for(request)
        if _cancel.is_set() and request['op'] not in ('store','store_shared_live','store_camera_live','migrate_shared_live','export','record_live'):
            emit('cancelled')
        else:
            emit('result', data=result)
    except asyncio.CancelledError:
        emit('cancelled')
    except UserError as exc:
        emit('error', message=str(exc))
    except Exception as exc:
        codes = sorted(set(re.findall(r'(?<!\d)-\d{4,6}(?!\d)', str(exc))))
        msg = 'Camera operation failed. Check the camera is online, close other viewers, then retry.'
        if isinstance(exc, FileNotFoundError):
            msg = 'FFmpeg or a required file is missing. Check installation and retry.'
        emit('error', message=msg, codes=codes, kind=type(exc).__name__)


def preview_requests(request):
    """Reuse login and the day's recording list, with one media request at a time.

    The UI kills active work on cancellation; idle processes retain imports.
    Camera/date changes always discard the old camera and recording list.
    """
    session={}
    scope=None
    try:
        with open(os.devnull,'w') as null, redirect_stdout(null), redirect_stderr(null):
            while True:
                if request.get('op')!='thumbnail':return
                requested_scope=(request['camera'],request['date'],request.get('session_scope'))
                if requested_scope!=scope:
                    if session.get('camera'):
                        try:session['camera'].close()
                        except Exception:pass
                    session={};scope=requested_scope
                try:
                    result=result_for(request,session)
                except Exception:
                    # Discard a failed session; the next worker may reconnect safely.
                    emit('result',data={'available':False})
                    return
                emit('result',data=result)
                line=sys.stdin.readline()
                if not line:return
                request=json.loads(line)
    finally:
        if session.get('camera'):
            try:session['camera'].close()
            except Exception:pass
