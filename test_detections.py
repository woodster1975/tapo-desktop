import asyncio
from datetime import datetime,timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from tapo_desktop.detections import recording_rows,normalize_events,detection_metadata,has_detection,detection_label


class DetectionTests(unittest.TestCase):
    def test_recording_variants_and_no_raw_data(self):
        raw={'items':[{'startTime':'10','endTime':'20','vedio_type':'2','private':'secret'},
                      {'startTime':30,'endTime':40,'video_type':'1'}]}
        rows=recording_rows(raw)
        self.assertTrue(has_detection(rows[0]));self.assertFalse(has_detection(rows[1]))
        self.assertEqual(detection_label(rows[0]),'Detection');self.assertEqual(detection_label(rows[1]),'Continuous')
        self.assertNotIn('private',rows[0])
    def test_malformed_events_unknown_types_and_duplicates(self):
        event={'start_time':'10','end_time':'12','alarm_type':'6','events_1':'58','password':'secret'}
        rows=normalize_events([event,event,{'start_time':'bad'},None])
        self.assertEqual(rows,[{'start':10,'end':12,'type':6,'flags':58}])
        self.assertEqual(detection_label({'events':rows}),'1 event')
        self.assertEqual(detection_label({}),'Not reported')
    def test_camera_time_correction_and_overlaps(self):
        day=datetime(2026,10,31);start=int(day.timestamp())
        cam=SimpleNamespace(getTimeCorrection=lambda:37,getEvents=Mock(return_value=[{'start_time':start+15,'end_time':start+25,'alarm_type':'2'}]))
        rows=[{'start':start+10,'end':start+20},{'start':start+20,'end':start+30},{'start':start+40,'end':start+50}]
        result=detection_metadata(cam,'20261031',rows,lambda:False)
        cam.getEvents.assert_called_once_with(start-37,int((day+timedelta(days=1)).timestamp())-1-37)
        self.assertEqual([len(r['events']) for r in rows],[1,1,0]);self.assertTrue(result['events_complete'])
    def test_saturated_event_window_is_split_and_deduplicated(self):
        start=int(datetime(2026,10,31).timestamp());event={'start_time':start+10,'end_time':start+11,'alarm_type':'4'}
        cam=SimpleNamespace(getTimeCorrection=lambda:0,getEvents=Mock(side_effect=[[event]*1000,[event],[event]]))
        result=detection_metadata(cam,'20261031',[],lambda:False)
        self.assertEqual(cam.getEvents.call_count,3);self.assertEqual(result['event_count'],1)
    def test_cancelled_detection_search_does_not_call_camera(self):
        cam=SimpleNamespace(getTimeCorrection=lambda:0,getEvents=Mock())
        with self.assertRaises(asyncio.CancelledError):detection_metadata(cam,'20261031',[],lambda:True)
        cam.getEvents.assert_not_called()

class DetectionWorkerTests(unittest.TestCase):
    def test_unavailable_events_do_not_hide_recordings(self):
        from unittest.mock import patch
        from dataclasses import asdict
        from tapo_desktop.storage import Camera
        from tapo_desktop import worker
        cam=Mock();cam.getRecordings.return_value=[{'startTime':10,'endTime':20,'vedio_type':'2'}]
        cam.getTimeCorrection.side_effect=RuntimeError('sensitive upstream message')
        with patch('pytapo.Tapo',return_value=cam),patch.object(worker,'get_secret',return_value='fake'),patch.object(worker,'emit'):
            result=worker.result_for({'op':'segments','camera':asdict(Camera('test','Test','192.168.0.10')),'date':'20261031'})
        self.assertFalse(result['events_available']);self.assertEqual(len(result['segments']),1)
        self.assertNotIn('sensitive',str(result));cam.close.assert_called_once()
    def test_continuous_thumbnail_does_not_start_media_session(self):
        from unittest.mock import patch
        from dataclasses import asdict
        from tapo_desktop.storage import Camera
        from tapo_desktop import worker
        cam=Mock();cam.getRecordings.return_value=[{'startTime':10,'endTime':20,'video_type':'1'}]
        with patch('pytapo.Tapo',return_value=cam),patch.object(worker,'get_secret',return_value='fake'),patch.object(worker,'emit'):
            result=worker.result_for({'op':'thumbnail','camera':asdict(Camera('test','Test','192.168.0.10')),'date':'20261031','start':10,'end':20})
        self.assertFalse(result['available']);cam.getMediaSession.assert_not_called();cam.close.assert_called_once()
