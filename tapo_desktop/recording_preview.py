"""Bounded local first-frame fallback when a camera has no stored JPEG."""
import asyncio
import json
import shutil
import subprocess


async def recording_bytes(camera,start,end,cancelled):
    from pytapo.media_stream._utils import StreamType
    session=camera.getMediaSession(StreamType.Download)
    session.set_window_size(10)
    request={'type':'request','seq':1,'params':{'download':{
        'client_id':camera.getUserID(),'channels':[0],'media_type':0,
        'start_time':str(start),'end_time':str(min(end,start+4)),
        'player_id':camera.playerID},'method':'get'}}
    data=bytearray()
    try:
        async with asyncio.timeout(7):
            async with session:
                stream=session.transceive(json.dumps(request),no_data_timeout=4)
                try:
                    async for response in stream:
                        if cancelled():raise asyncio.CancelledError()
                        if response.mimetype=='video/mp2t':
                            data.extend(response.plaintext[:max(0,2_000_000-len(data))])
                            if len(data)>=500_000:break
                        elif response.mimetype=='application/json':
                            packet=json.loads(response.plaintext)
                            params=packet.get('params') or {}
                            if packet.get('type')=='response' and params.get('error_code',0) not in (0,None):break
                            if params.get('event_type')=='stream_status' and params.get('status')=='finished':break
                finally:await stream.aclose()
    except TimeoutError:
        if not data:raise
    return bytes(data)


def frame_from_bytes(data):
    if not data or not shutil.which('ffmpeg'):return None
    result=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-threads','1',
        '-f','mpegts','-i','pipe:0','-frames:v','1','-an','-vf','scale=640:-2',
        '-threads','1','-f','image2pipe','-vcodec','mjpeg','pipe:1'],
        input=data,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5,check=False)
    image=result.stdout
    return image if result.returncode==0 and image.startswith(b'\xff\xd8') and len(image)<=5_000_000 else None
