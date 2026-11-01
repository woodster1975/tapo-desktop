import os,tempfile,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import Mock,patch
from PySide6.QtWidgets import QApplication
from tapo_desktop.storage import Camera,thumbnail_path
from tapo_desktop.thumbnails import ThumbnailLoader


class ThumbnailQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'XDG_CONFIG_HOME':self.tmp.name,'LOCALAPPDATA':self.tmp.name});self.env.start()
        self.loader=ThumbnailLoader();self.camera=Camera('test','Test','192.168.0.10')
        self.loader.set_context(self.camera,'20261031')
        self.rows=[{'start':i*10,'end':i*10+5,'recording_type':'2'} for i in range(12)]
    def tearDown(self):self.loader.reset();self.loader.cancel_active();self.loader.deleteLater();self.app.processEvents();self.env.stop();self.tmp.cleanup()
    def test_scrolling_replaces_old_queue_and_skips_continuous_and_misses(self):
        loader=self.loader;loader.set_visible(self.rows[:4])
        self.assertEqual(len(loader.queue),4)
        loader.cache[loader.key(self.rows[5])]={'available':False}
        continuous={**self.rows[6],'recording_type':'1'}
        loader.set_visible([self.rows[4],self.rows[5],continuous])
        self.assertEqual(loader.queue,[(loader.key(self.rows[4]),False)])
    def test_visible_active_request_not_duplicated(self):
        self.loader.active=self.loader.key(self.rows[0]);self.loader.set_visible(self.rows[:2])
        self.assertEqual(self.loader.queue,[(self.loader.key(self.rows[1]),False)])
    def test_cached_images_avoid_camera_requests(self):
        file=thumbnail_path(self.camera,'20261031',0,5);file.parent.mkdir(parents=True);file.write_bytes(b'cached image')
        self.loader.set_visible(self.rows[:1]);self.assertFalse(self.loader.queue)
        self.assertEqual(self.loader.cached(self.rows[0])['path'],str(file))

    def test_repeated_cache_hits_do_not_repeat_filesystem_queries(self):
        from types import SimpleNamespace
        file=Mock();file.is_file.return_value=True;file.stat.return_value=SimpleNamespace(st_size=100)
        with patch('tapo_desktop.thumbnails.thumbnail_path',return_value=file) as lookup:
            for _ in range(100):self.loader.cached(self.rows[0])
        lookup.assert_called_once();file.stat.assert_called_once()
    def test_foreground_priority_cancels_process_without_blocking_wait(self):
        loader=self.loader;loader.enabled=True;process=Mock();loader.proc=process;loader.active=loader.key(self.rows[0])
        loader.set_enabled(False)
        process.kill.assert_called_once();process.waitForFinished.assert_not_called();self.assertIsNone(loader.proc)
    def test_stale_result_after_camera_change_is_discarded(self):
        loader=self.loader;old=loader.key(self.rows[0]);ready=Mock();loader.ready.connect(ready)
        loader.set_context(Camera('other','Other','192.168.0.11'),'20261031')
        loader.deliver(old,{'available':False});ready.assert_not_called();self.assertFalse(loader.cache)
    def test_timeout_miss_is_cached_and_queue_continues(self):
        loader=self.loader;key=loader.key(self.rows[0]);loader.enabled=True;loader.active=key;loader.proc=Mock()
        loader.queue=[(loader.key(self.rows[1]),False)];loader.timed_out()
        self.assertEqual(loader.cache[key],{'available':False});self.assertTrue(loader.dispatch.isActive())
    def test_retry_only_selected_missing_item(self):
        loader=self.loader;key=loader.key(self.rows[0]);loader.cache[key]={'available':False}
        loader.retry(self.rows[0]);self.assertNotIn(key,loader.cache);self.assertEqual(loader.queue,[(key,True)])
    def test_scroll_recomputation_preserves_explicit_retry(self):
        loader=self.loader;loader.set_visible(self.rows[:2]);loader.retry(self.rows[0])
        loader.set_visible(self.rows[:3])
        self.assertEqual(loader.queue[0],(loader.key(self.rows[0]),True))
        self.assertEqual(len(loader.queue),3)
    def test_new_visible_page_cancels_slow_offscreen_request(self):
        loader=self.loader;loader.proc=Mock();old=loader.proc;loader.active=loader.key(self.rows[0])
        loader.active_fallback=True
        loader.set_visible(self.rows[5:8],ahead=self.rows[8:11])
        old.kill.assert_called_once();self.assertIsNone(loader.active)
        self.assertEqual([key for key,_ in loader.queue],[loader.key(r) for r in self.rows[5:11]])
    def test_visible_rows_precede_bounded_next_page(self):
        self.loader.set_visible(self.rows[:3],ahead=self.rows[2:6])
        self.assertEqual([key for key,_ in self.loader.queue],[self.loader.key(r) for r in self.rows[:6]])
    def test_only_one_process_starts_and_payload_has_no_passwords(self):
        loader=self.loader;loader.enabled=True;loader.set_visible(self.rows[:2]);process=Mock()
        with patch('tapo_desktop.thumbnails.QProcess',return_value=process) as factory:
            loader.pump();loader.pump();factory.assert_called_once()
        started=process.started.connect.call_args.args[0];started()
        payload=process.write.call_args.args[0]
        self.assertNotIn(b'password',payload)
        self.assertIs(loader.proc,process)

    def test_next_preview_reuses_worker_after_incremental_result(self):
        import json
        loader=self.loader;loader.enabled=True;loader.set_visible(self.rows[:2]);process=Mock()
        with patch('tapo_desktop.thumbnails.QProcess',return_value=process) as factory:
            loader.pump()
            process.readAllStandardOutput.return_value=json.dumps({'event':'result','data':{'available':False}}).encode()+b'\n'
            loader.read_output(process)
            self.assertIsNone(loader.active)
            self.assertFalse(loader.deadline.isActive())
            self.assertIn(loader.key(self.rows[0]),loader.cache)
            loader.pump()
            factory.assert_called_once()
            self.assertEqual(loader.active,loader.key(self.rows[1]))
            payload=json.loads(process.write.call_args.args[0])
            self.assertEqual(payload['start'],10)

    def test_idle_worker_survives_context_change_without_reimporting(self):
        process=Mock();self.loader.proc=process
        self.loader.set_context(self.camera,'20261101')
        process.kill.assert_not_called()
        self.assertIs(self.loader.proc,process)

    def test_foreground_action_preserves_idle_worker(self):
        loader=self.loader;loader.enabled=True;loader.proc=Mock()
        loader.set_enabled(False)
        loader.proc.kill.assert_not_called()

    def test_next_page_prepares_missing_frames_after_visible_previews(self):
        loader=self.loader;first=loader.key(self.rows[0]);ahead=loader.key(self.rows[1])
        loader.cache[first]={'available':False,'deferred':True}
        loader.set_visible(self.rows[:1],ahead=self.rows[1:2])
        self.assertEqual(loader.queue,[(ahead,False),(first,False)])
        loader.queue=[(first,False)]
        loader.deliver(ahead,{'available':False,'deferred':True})
        self.assertEqual(loader.queue,[(first,False),(ahead,False)])

    def test_scroll_preserves_camera_connection_during_native_preview(self):
        loader=self.loader;loader.proc=Mock();loader.active=loader.key(self.rows[0])
        loader.set_visible(self.rows[5:8])
        loader.proc.kill.assert_not_called()
        self.assertEqual(loader.active,loader.key(self.rows[0]))

    def test_missing_native_preview_does_not_block_later_rows(self):
        import json
        loader=self.loader;loader.enabled=True;loader.set_visible(self.rows[:3]);process=Mock()
        with patch('tapo_desktop.thumbnails.QProcess',return_value=process):
            loader.pump()
        first=loader.active
        process.readAllStandardOutput.return_value=b'{"event":"result","data":{"available":false,"deferred":true}}\n'
        loader.read_output(process)
        self.assertEqual([item[0] for item in loader.queue],[loader.key(r) for r in self.rows[1:3]]+[first])
        loader.pump()
        self.assertTrue(json.loads(process.write.call_args.args[0])['native_only'])
        loader.active=None;loader.queue=[(first,False)];loader.pump()
        self.assertTrue(json.loads(process.write.call_args.args[0])['fallback_only'])

    def test_repeated_viewport_updates_do_not_postpone_dispatch(self):
        loader=self.loader;loader.enabled=True
        with patch.object(loader.dispatch,'start') as start,patch.object(loader.dispatch,'isActive',side_effect=[False,True,True]):
            for _ in range(3):loader.set_visible(self.rows[:2])
            start.assert_called_once_with(80)
