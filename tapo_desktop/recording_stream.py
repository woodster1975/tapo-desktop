"""Private loopback relay for progressive recording playback; no clip is saved."""
import asyncio
import json
import secrets
import shutil
import time
from http.server import BaseHTTPRequestHandler,HTTPServer
from .storage import UserError


async def relay(camera,start,end,writer,cancelled):
    from pytapo.media_stream._utils import StreamType
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise UserError('Install FFmpeg to stream recordings.')
    process=await asyncio.create_subprocess_exec(ffmpeg,'-hide_banner','-loglevel','error',
        '-fflags','+genpts','-probesize','32768','-analyzeduration','500000','-i','pipe:0',
        '-map','0:v:0','-map','0:a?','-c:v','copy','-c:a','aac','-ar','48000',
        '-t',str(end-start),'-flush_packets','1','-f','mpegts','pipe:1',
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
    session=camera.getMediaSession(StreamType.Download);session.set_window_size(20)
    request={'type':'request','seq':1,'params':{'download':{'client_id':camera.getUserID(),
        'channels':[0],'media_type':0,'start_time':str(start),'end_time':str(end),
        'player_id':camera.playerID},'method':'get'}}
    async def feed():
        try:
            async with session:
                stream=session.transceive(json.dumps(request),no_data_timeout=15)
                try:
                    async for response in stream:
                        if cancelled():raise asyncio.CancelledError()
                        if response.mimetype=='video/mp2t':
                            process.stdin.write(response.plaintext);await process.stdin.drain()
                        elif response.mimetype=='application/json':
                            packet=json.loads(response.plaintext);params=packet.get('params') or {}
                            if packet.get('type')=='response' and params.get('error_code',0) not in (0,None):
                                raise UserError('Camera could not start recorded playback. Close other viewers and retry.')
                            if params.get('event_type')=='stream_status' and params.get('status')=='finished':break
                finally:await stream.aclose()
        finally:
            process.stdin.close()
    task=asyncio.create_task(feed());sent=0
    try:
        async with asyncio.timeout(max(60,end-start+30)):
            while True:
                chunk=await process.stdout.read(65536)
                if not chunk:break
                if cancelled():raise asyncio.CancelledError()
                await asyncio.to_thread(writer.write,chunk);sent+=len(chunk)
            await task
            if await process.wait()!=0 or not sent:raise UserError('Camera returned no playable recording stream. Try Download selected clip.')
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)
        if process.returncode is None:process.kill()
        await process.wait()


def serve(camera,start,end,emit,cancelled):
    token=secrets.token_urlsafe(24);path='/'+token+'/recording.ts'
    state={'started':False,'error':None}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_HEAD(self):
            if self.path!=path:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type','video/mp2t');self.end_headers()
        def do_GET(self):
            if self.path!=path or state['started']:self.send_error(404);return
            state['started']=True;self.connection.settimeout(20)
            self.send_response(200);self.send_header('Content-Type','video/mp2t')
            self.send_header('Cache-Control','no-store');self.send_header('Connection','close');self.end_headers()
            try:asyncio.run(relay(camera,start,end,self.wfile,cancelled))
            except (BrokenPipeError,ConnectionResetError):pass
            except Exception as exc:state['error']=exc
    server=HTTPServer(('127.0.0.1',0),Handler);server.timeout=0.5
    try:
        emit('stream',url=f'http://127.0.0.1:{server.server_port}{path}')
        deadline=time.monotonic()+20
        while not state['started'] and not cancelled() and time.monotonic()<deadline:server.handle_request()
        if state['error']:raise UserError('Recorded playback stopped. Close other camera viewers and retry, or download the clip.')
        if not state['started'] and not cancelled():raise UserError('The recording player did not connect. Retry playback.')
        return {'streamed':True}
    finally:server.server_close()
