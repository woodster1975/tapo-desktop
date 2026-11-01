import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
from types import SimpleNamespace
import tempfile,os,unittest,shutil,subprocess
from unittest.mock import Mock,AsyncMock,patch
from tapo_desktop.recording_preview import recording_bytes,frame_from_bytes


class PreviewFrameTests(unittest.TestCase):
    def camera(self,responses):
        class Session:
            set_window_size=Mock()
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def transceive(self,*args,**kwargs):
                for response in responses:yield response
        return SimpleNamespace(playerID='test',getUserID=lambda:1,getMediaSession=lambda *_:Session())
    def test_sample_is_bounded_and_request_never_covers_full_long_clip(self):
        import json
        captured=[]
        class Session:
            def set_window_size(self,n):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def transceive(self,payload,**kwargs):
                captured.append(json.loads(payload));yield SimpleNamespace(mimetype='video/mp2t',plaintext=b'x'*3_000_000)
        camera=SimpleNamespace(playerID='test',getUserID=lambda:1,getMediaSession=lambda *_:Session())
        data=asyncio.run(recording_bytes(camera,100,1200,lambda:False))
        self.assertLessEqual(len(data),2_000_000)
        request=captured[0]['params']['download'];self.assertEqual(request['end_time'],'104')
    def test_cancellation_propagates(self):
        camera=self.camera([SimpleNamespace(mimetype='video/mp2t',plaintext=b'x')])
        with self.assertRaises(asyncio.CancelledError):asyncio.run(recording_bytes(camera,1,5,lambda:True))
    def test_camera_refusal_does_not_collect_video(self):
        camera=self.camera([SimpleNamespace(mimetype='application/json',plaintext=b'{"type":"response","params":{"error_code":-52405}}')])
        self.assertEqual(asyncio.run(recording_bytes(camera,1,5,lambda:False)),b'')
    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg not installed')
    def test_extracts_jpeg_from_generated_transport_stream(self):
        raw=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=green:s=320x180:r=10','-t','1','-c:v','libx264','-threads','1','-f','mpegts','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10,check=True).stdout
        image=frame_from_bytes(raw);self.assertTrue(image.startswith(b'\xff\xd8'))
        self.assertLess(len(image),5_000_000)
    def test_empty_data_never_runs_decoder(self):
        with patch('tapo_desktop.recording_preview.subprocess.run') as run:
            self.assertIsNone(frame_from_bytes(b''));run.assert_not_called()


class PreviewFallbackWorkerTests(unittest.TestCase):
    def test_retained_worker_discards_camera_session_on_refresh(self):
        import io,json
        from tapo_desktop import worker
        first={'op':'thumbnail','camera':{'id':'test'},'date':'20261101','session_scope':1}
        second={**first,'session_scope':2}
        cameras=[Mock(),Mock()];sessions=[]
        def result(request,session):
            sessions.append(session);session['camera']=cameras[len(sessions)-1]
            return {'available':False}
        with patch.object(worker,'result_for',side_effect=result),patch.object(worker,'emit'),patch('sys.stdin',io.StringIO(json.dumps(second)+'\n')):
            worker.preview_requests(first)
        self.assertIsNot(sessions[0],sessions[1])
        for camera in cameras:camera.close.assert_called_once()

    def test_native_pass_defers_video_and_fallback_does_not_repeat_native_wait(self):
        from tapo_desktop import worker
        from tapo_desktop.storage import Camera
        camera=Camera('test','Test','192.168.0.10');cam=Mock()
        cam.getRecordings.return_value=[{'startTime':10,'endTime':20,'vedio_type':'2'}]
        request={'op':'thumbnail','camera':asdict(camera),'date':'20261101','start':10,'end':20}
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_CONFIG_HOME':directory,'LOCALAPPDATA':directory}),patch('pytapo.Tapo',return_value=cam),patch.object(worker,'get_secret',return_value='fake'),patch.object(worker,'emit'),patch('pytapo.media_stream.snapshot.getRecordingSnapshot',new=AsyncMock(return_value=None)) as snapshot,patch('tapo_desktop.recording_preview.recording_bytes',new=AsyncMock(return_value=b'video')) as sample,patch('tapo_desktop.recording_preview.frame_from_bytes',return_value=b'\xff\xd8jpeg'):
            session={}
            result=worker.result_for({**request,'native_only':True},session)
            self.assertTrue(result['deferred']);sample.assert_not_awaited()
            result=worker.result_for({**request,'fallback_only':True},session)
            self.assertTrue(result['available']);self.assertEqual(result['source'],'recording-frame')
            snapshot.assert_awaited_once();sample.assert_awaited_once()

    def test_preview_session_reuses_login_and_recording_list(self):
        from tapo_desktop import worker
        from tapo_desktop.storage import Camera
        camera=Camera('test','Test','192.168.0.10');cam=Mock()
        cam.getRecordings.return_value=[{'startTime':10,'endTime':20,'vedio_type':'2'}, {'startTime':30,'endTime':40,'vedio_type':'2'}]
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_CONFIG_HOME':directory,'LOCALAPPDATA':directory}),patch('pytapo.Tapo',return_value=cam) as connect,patch.object(worker,'get_secret',return_value='fake') as secret,patch.object(worker,'emit'),patch('pytapo.media_stream.snapshot.getRecordingSnapshot',new=AsyncMock(return_value=b'\xff\xd8jpeg')):
            session={}
            for start,end in [(10,20),(30,40)]:
                result=worker.result_for({'op':'thumbnail','camera':asdict(camera),'date':'20261031','start':start,'end':end},session)
                self.assertTrue(result['available'])
            connect.assert_called_once();secret.assert_called_once()
            cam.getRecordings.assert_called_once_with('20261031')
            cam.close.assert_not_called()

    def test_missing_native_jpeg_uses_recording_frame_and_private_cache(self):
        from tapo_desktop import worker
        from tapo_desktop.storage import Camera
        camera=Camera('test','Test','192.168.0.10');cam=Mock()
        cam.getRecordings.return_value=[{'startTime':10,'endTime':20,'vedio_type':'2'}]
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_CONFIG_HOME':directory,'LOCALAPPDATA':directory}),patch('pytapo.Tapo',return_value=cam),patch.object(worker,'get_secret',return_value='fake'),patch.object(worker,'emit'),patch('pytapo.media_stream.snapshot.getRecordingSnapshot',new=AsyncMock(return_value=None)),patch('tapo_desktop.recording_preview.recording_bytes',new=AsyncMock(return_value=b'video')) as sample,patch('tapo_desktop.recording_preview.frame_from_bytes',return_value=b'\xff\xd8jpeg'):
            result=worker.result_for({'op':'thumbnail','camera':asdict(camera),'date':'20261031','start':10,'end':20})
            self.assertTrue(result['available']);self.assertEqual(result['source'],'recording-frame');sample.assert_awaited_once()
            from pathlib import Path
            self.assertEqual(Path(result['path']).read_bytes(),b'\xff\xd8jpeg')
            if os.name!='nt':self.assertEqual(Path(result['path']).stat().st_mode&0o777,0o600)
    def test_native_jpeg_does_not_request_recording_sample(self):
        from tapo_desktop import worker
        from tapo_desktop.storage import Camera
        camera=Camera('test','Test','192.168.0.10');cam=Mock();cam.getRecordings.return_value=[{'startTime':10,'endTime':20,'vedio_type':'2'}]
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'XDG_CONFIG_HOME':directory,'LOCALAPPDATA':directory}),patch('pytapo.Tapo',return_value=cam),patch.object(worker,'get_secret',return_value='fake'),patch.object(worker,'emit'),patch('pytapo.media_stream.snapshot.getRecordingSnapshot',new=AsyncMock(return_value=b'\xff\xd8jpeg')),patch('tapo_desktop.recording_preview.recording_bytes',new=AsyncMock()) as sample:
            result=worker.result_for({'op':'thumbnail','camera':asdict(camera),'date':'20261031','start':10,'end':20})
            self.assertEqual(result['source'],'camera');sample.assert_not_called()
