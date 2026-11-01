import json,os,threading,urllib.request,urllib.error,unittest
from unittest.mock import Mock,patch,AsyncMock
from dataclasses import asdict
from tapo_desktop.storage import Camera,UserError
from tapo_desktop.recording_stream import serve


class LoopbackRelayTests(unittest.TestCase):
    def test_loopback_token_guard_and_progressive_body(self):
        result={};threads=[]
        def event(kind,**data):
            if kind!='stream':return
            self.assertTrue(data['url'].startswith('http://127.0.0.1:'))
            def client():
                try:
                    root=data['url'].rsplit('/',2)[0]
                    try:urllib.request.urlopen(root+'/wrong',timeout=5)
                    except urllib.error.HTTPError as exc:
                        result['wrong_status']=exc.code;exc.close()
                    with urllib.request.urlopen(data['url'],timeout=5) as response:result['body']=response.read()
                except Exception as exc:result['error']=type(exc).__name__
            thread=threading.Thread(target=client);threads.append(thread);thread.start()
        async def fake(camera,start,end,writer,cancelled):writer.write(b'recording data')
        with patch('tapo_desktop.recording_stream.relay',new=fake):
            self.assertEqual(serve(None,10,20,event,lambda:False),{'streamed':True})
        for thread in threads:thread.join(5)
        self.assertNotIn('error',result);self.assertEqual(result['wrong_status'],404);self.assertEqual(result['body'],b'recording data')
    def test_removed_recording_never_starts_relay(self):
        from tapo_desktop import worker
        cam=Mock();cam.getRecordings.return_value=[{'startTime':10,'endTime':20}]
        with patch('pytapo.Tapo',return_value=cam),patch.object(worker,'get_secret',return_value='fake'),patch.object(worker,'emit'),patch('tapo_desktop.recording_stream.serve') as relay:
            with self.assertRaises(UserError):worker.result_for({'op':'playback','camera':asdict(Camera('test','Test','192.168.0.10')),'date':'20261031','start':30,'end':40})
        relay.assert_not_called()
