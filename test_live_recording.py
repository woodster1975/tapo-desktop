import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from tapo_desktop.live_recording import camera_url, record_stream, normalize_packet_clock
from tapo_desktop.storage import Camera, UserError


@unittest.skipUnless(importlib.util.find_spec('av') and shutil.which('ffmpeg'), 'PyAV and FFmpeg required')
class LiveRecordingMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.folder=Path(cls.temp.name)
        cls.source=cls.folder/'source.mkv'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=10',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=8000','-t','4','-c:v','libx264',
            '-preset','ultrafast','-g','10','-bf','0','-c:a','pcm_alaw',str(cls.source)],
            check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_copies_video_and_preserves_camera_audio(self):
        import av
        destination=self.folder/'complete.mkv';events=[]
        result=record_stream(str(self.source),destination,lambda event,**data:events.append(event),lambda:False,network=False)
        self.assertTrue(result['recorded']);self.assertTrue(result['audio']);self.assertFalse(result['interrupted'])
        self.assertIn('recording',events);self.assertGreater(result['seconds'],3)
        def video_packets(path):
            with av.open(str(path)) as file:
                return [bytes(packet) for packet in file.demux(video=0) if packet.size]
        self.assertEqual(video_packets(self.source),video_packets(destination))
        def audio_samples(path):
            with av.open(str(path)) as file:
                return b''.join(bytes(frame.planes[0])[:frame.samples*2] for frame in file.decode(audio=0))
        self.assertEqual(audio_samples(self.source),audio_samples(destination))
        self.assertTrue(any(audio_samples(destination)))
        with av.open(str(destination)) as file:
            self.assertEqual(file.streams.audio[0].codec_context.name,'pcm_s16le')
            self.assertTrue(result['audio_converted'])
            self.assertGreater(sum(1 for _ in file.decode(video=0)),0)
        self.assertFalse(list(self.folder.glob('*.partial.mkv')))

    def test_stop_finalizes_a_playable_shorter_clip(self):
        import av
        calls=0
        def cancelled():
            nonlocal calls
            calls+=1;return calls>18
        result=record_stream(str(self.source),self.folder/'stopped.mkv',lambda *a,**k:None,cancelled,network=False)
        self.assertTrue(result['recorded']);self.assertFalse(result['interrupted'])
        self.assertLess(result['seconds'],4)
        with av.open(result['path']) as file:self.assertGreater(sum(1 for _ in file.decode(video=0)),0)

    def test_existing_recording_is_preserved(self):
        path=self.folder/'existing.mkv';path.write_bytes(b'original')
        with self.assertRaises(UserError):record_stream(str(self.source),path,Mock(),lambda:False,network=False)
        self.assertEqual(path.read_bytes(),b'original')

    def test_cancel_before_start_creates_no_file(self):
        path=self.folder/'cancelled.mkv'
        result=record_stream(str(self.source),path,Mock(),lambda:True,network=False)
        self.assertFalse(result['recorded']);self.assertFalse(path.exists())

    def test_connection_failure_does_not_publish_empty_recording(self):
        path=self.folder/'failed.mkv'
        with self.assertRaises(UserError):record_stream(str(self.folder/'missing'),path,Mock(),lambda:False,network=False)
        self.assertFalse(path.exists());self.assertFalse(list(self.folder.glob('*.partial.mkv')))


class LiveRecordingControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_invalid_camera_video_clocks_are_repaired_without_touching_data(self):
        from fractions import Fraction
        from types import SimpleNamespace
        packet=SimpleNamespace(dts=900,pts=800,time_base=Fraction(1,90000))
        clock=normalize_packet_clock(packet,Fraction(0),previous=900)
        self.assertEqual(clock,990);self.assertGreaterEqual(packet.pts,packet.dts)

    def test_valid_presentation_order_is_preserved(self):
        from fractions import Fraction
        from types import SimpleNamespace
        packet=SimpleNamespace(dts=18000,pts=24000,time_base=Fraction(1,90000))
        normalize_packet_clock(packet,Fraction(1,10),previous=3000)
        self.assertEqual((packet.dts,packet.pts),(9000,15000))

    def test_recording_worker_does_not_import_camera_discovery_library(self):
        from dataclasses import asdict
        from tapo_desktop import worker
        with patch.dict('sys.modules',{'pytapo':None}),patch.object(worker,'shared_live_credentials',return_value=('test','fake')),patch('tapo_desktop.live_recording.record_stream',return_value={'recorded':False}) as record:
            result=worker.result_for({'op':'record_live','camera':asdict(Camera('c','Test','192.168.0.10')),'destination':'test.mkv'})
        self.assertFalse(result['recorded']);record.assert_called_once()

    def test_credentials_are_encoded_in_memory_and_not_sent_by_ui(self):
        from urllib.parse import urlsplit,unquote
        url=camera_url({'username':'test@name','password':'fake:/ @','host':'192.168.0.10','stream':'stream1'})
        self.assertEqual(unquote(urlsplit(url).password),'fake:/ @')
        from tapo_desktop.live_recorder import LiveRecorder
        recorder=LiveRecorder();proc=Mock()
        with patch('tapo_desktop.live_recorder.QProcess',return_value=proc):
            recorder.start(Camera('c','Test','192.168.0.10'),Path('test.mkv'))
            proc.started.connect.call_args.args[0]()
        payload=json.loads(proc.write.call_args.args[0]);self.assertNotIn('password',payload)
        self.assertNotIn('rtsp',str(proc.start.call_args))
        recorder.deadline.stop();recorder.proc=None;recorder.deleteLater()

    def test_starting_is_not_reported_as_recording_until_media_arrives(self):
        from tapo_desktop.live_recorder import LiveRecorder
        recorder=LiveRecorder();proc=Mock()
        with patch('tapo_desktop.live_recorder.QProcess',return_value=proc):recorder.start(Camera('c','Test','192.168.0.10'),'test.mkv')
        self.assertEqual(recorder.state,'starting')
        proc.readAllStandardOutput.return_value=b'{"event":"recording","seconds":1}\n'
        recorder.read(proc);self.assertEqual(recorder.state,'recording')
        recorder.stop();self.assertEqual(recorder.state,'stopping')
        proc.readAllStandardOutput.return_value=b'{"event":"result","data":{"recorded":true,"path":"test.mkv"}}\n'
        completed=Mock();recorder.completed.connect(completed);recorder.finished(proc)
        self.assertFalse(recorder.active);completed.assert_called_once()
