import asyncio
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from tapo_desktop import storage, worker
from tapo_desktop.storage import Camera, UserError


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'XDG_CONFIG_HOME':self.tmp.name,'LOCALAPPDATA':self.tmp.name})
        self.env.start()
    def tearDown(self):
        self.env.stop();self.tmp.cleanup()

    def test_windows_vault_is_persistent_on_this_laptop(self):
        backend=type('Vault',(),{'__module__':'keyring.backends.Windows'})()
        with patch('platform.system',return_value='Windows'),patch('keyring.get_keyring',return_value=backend):
            storage._native_keyring()
        self.assertEqual(backend.persist,'local machine')

    def test_plaintext_and_similarly_named_backends_are_rejected(self):
        for module in ('keyrings.alt.file','keyring.backends.WindowsPlaintext'):
            backend=type('Plaintext',(),{'__module__':module})()
            with patch('platform.system',return_value='Windows'),patch('keyring.get_keyring',return_value=backend):
                with self.assertRaises(UserError):storage.put_secret('cloud','fake-secret')

    def test_preferences_have_no_passwords(self):
        cameras=[Camera('first','First','192.168.1.10'),Camera('second','Second','192.168.1.11')]
        storage.save_cameras(cameras)
        self.assertEqual(storage.load_cameras(),cameras)
        fields=set(json.loads((storage.root_dir()/'cameras.json').read_text())[0])
        self.assertNotIn('password',fields)
        self.assertEqual(len(cameras),2)

    def test_fresh_profile_has_no_cameras(self):
        self.assertEqual(storage.load_cameras(),[])
        self.assertFalse((storage.root_dir()/'cameras.json').exists())

    def test_saved_empty_profile_stays_empty(self):
        storage.save_cameras([])
        self.assertEqual(storage.load_cameras(),[])

    def test_reject_public_hosts_and_path_ids(self):
        for host in ['8.8.8.8','127.0.0.1','169.254.1.2']:
            with self.assertRaises(UserError):Camera.from_dict({'id':'test','name':'X','host':host})
        with self.assertRaises(UserError):Camera.from_dict({'id':'../x','name':'X','host':'192.168.1.2'})

    def test_export_never_overwrites(self):
        src=Path(self.tmp.name)/'src.mp4';dest=Path(self.tmp.name)/'dest.mp4'
        src.write_bytes(b'video')
        storage.export_clip(src,dest);self.assertEqual(dest.read_bytes(),b'video')
        src.write_bytes(b'new')
        with self.assertRaises(UserError):storage.export_clip(src,dest)
        self.assertEqual(dest.read_bytes(),b'video')
        self.assertEqual(len(list(dest.parent.glob('.tapo-export-*'))),0)

    def test_export_fallback_preserves_existing(self):
        src=Path(self.tmp.name)/'src';dest=Path(self.tmp.name)/'dest';src.write_bytes(b'video')
        with patch('os.link',side_effect=OSError):storage.export_clip(src,dest)
        with patch('os.link',side_effect=OSError):
            with self.assertRaises(UserError):storage.export_clip(src,dest)
        self.assertEqual(dest.read_bytes(),b'video')

    def test_secret_lookup_not_in_arguments(self):
        response=subprocess.CompletedProcess([],0,b'canary-password')
        with patch('platform.system',return_value='Linux'),patch('shutil.which',return_value='secret-tool'),patch('subprocess.run',return_value=response) as run:
            self.assertEqual(storage.get_secret('cloud'),'canary-password')
            self.assertNotIn('canary-password',str(run.call_args))
            self.assertEqual(run.call_args.kwargs['stderr'],subprocess.DEVNULL)

    def test_shared_default_and_legacy_migration(self):
        cameras=[Camera('one','One','192.168.0.10',username='shared-user'),Camera('two','Two','192.168.0.11')]
        storage.save_cameras(cameras)
        self.assertTrue(all(c.use_shared_credentials for c in storage.load_cameras()))
        with patch.object(storage,'get_secret',return_value='fake-secret') as get,patch.object(storage,'put_secret') as put:
            self.assertEqual(storage.migrate_shared_live_account(),{'username':'shared-user'})
            get.assert_called_once_with('camera','one');put.assert_called_once_with('shared_camera','fake-secret')
        settings=(storage.root_dir()/'live-account.json').read_text()
        self.assertNotIn('fake-secret',settings)
        self.assertNotIn('legacy_camera_id',settings)
        self.assertEqual(storage.credential_key('shared_camera'),('tapo-desk-camera','shared'))
        self.assertNotEqual(storage.credential_key('shared_camera'),storage.credential_key('cloud'))

    def test_live_resolution_shared_and_override(self):
        with patch.object(worker,'shared_live_credentials',return_value=('shared-user','fake-shared')) as shared,patch.object(worker,'get_secret',return_value='fake-override') as get:
            for i in range(2):
                c=Camera(str(i),'Camera','192.168.0.'+str(i+10))
                result=worker.result_for({'op':'live','camera':asdict(c)})
                self.assertEqual(result['username'],'shared-user');self.assertEqual(result['password'],'fake-shared')
            get.assert_not_called();self.assertEqual(shared.call_count,2)
            c.use_shared_credentials=False;c.username='unique-user'
            result=worker.result_for({'op':'live','camera':asdict(c)})
            self.assertEqual(result['username'],'unique-user');self.assertEqual(result['password'],'fake-override')
            get.assert_called_once_with('camera',c.id)

    def test_blank_shared_password_keeps_stored_secret(self):
        storage.save_shared_live_settings('old-user')
        with patch.object(storage,'get_secret',return_value='kept'),patch.object(storage,'put_secret') as put:
            storage.store_shared_live_account('new-user','')
            put.assert_not_called()
        self.assertEqual(storage.load_shared_live_settings()['username'],'new-user')

    def test_reject_plaintext_keyring(self):
        class Plaintext:pass
        with patch('keyring.get_keyring',return_value=Plaintext()):
            with self.assertRaises(UserError):storage._native_keyring()

    def test_no_live_fallback_to_cloud(self):
        camera=Camera('test','Test','192.168.1.2',use_shared_credentials=False)
        with patch.object(worker,'get_secret') as get:
            with self.assertRaises(UserError):worker.result_for({'op':'live','camera':asdict(camera)})
            get.assert_not_called()


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(lambda *_:None)
        cls.application=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'XDG_CONFIG_HOME':self.tmp.name,'LOCALAPPDATA':self.tmp.name})
        self.env.start()
        from tapo_desktop.app import MainWindow
        storage.save_cameras([Camera('c310','C310','192.168.1.10','C310'),Camera('c320ws','C320WS','192.168.1.11','C320WS')])
        self.w=MainWindow(demo=True)
    def tearDown(self):
        self.w.close();self.env.stop();self.tmp.cleanup()
    def test_empty_camera_list_opens_with_setup_controls(self):
        from tapo_desktop.app import MainWindow
        with patch('tapo_desktop.app.load_cameras',return_value=[]):
            window=MainWindow()
        try:
            self.assertEqual(window.cameras,[])
            self.assertIsNone(window.camera)
            self.assertEqual(window.camera_list.count(),0)
            self.assertTrue(window.find_btn.isEnabled())
            self.assertTrue(window.add_btn.isEnabled())
            self.assertFalse(window.play_btn.isEnabled())
        finally:window.close()

    def test_play_streams_recording_without_download_job(self):
        self.w.demo=False
        with patch.object(self.w.recording_stream,'start') as stream,patch.object(self.w,'start_job') as job:
            self.w.play_selected()
        stream.assert_called_once();job.assert_not_called();self.assertTrue(self.w.streaming)
        self.assertFalse(self.w.seek.isEnabled());self.assertTrue(self.w.pause_btn.isEnabled())
        self.assertFalse(self.w.thumbnail_loader.enabled);self.w.demo=True
    def test_audio_stall_detaches_output_and_keeps_video(self):
        import time
        from PySide6.QtMultimedia import QMediaPlayer
        self.w.position_time=time.monotonic()-4
        with patch.object(self.w.player,'playbackState',return_value=QMediaPlayer.PlaybackState.PlayingState),patch.object(self.w.player,'position',return_value=1207),patch.object(self.w.player,'audioOutput',return_value=self.w.audio),patch.object(self.w.player,'setAudioOutput') as audio:
            self.w.check_playback()
        audio.assert_called_once_with(None);self.assertTrue(self.w.audio_stalled)
        self.assertTrue(self.w.audio.isMuted());self.assertIn('continuing video muted',self.w.status.text())

    def test_live_record_button_requires_connected_video_and_uses_local_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QMediaPlayer
        self.w.set_mode('live');self.w.demo=False
        self.w.update_controls();self.assertFalse(self.w.live_record_btn.isEnabled())
        with patch.object(self.w,'live_recording_folder',return_value=Path(self.tmp.name)),patch.object(self.w.player,'playbackState',return_value=QMediaPlayer.PlaybackState.PlayingState),patch.object(self.w.player,'source',return_value=QUrl('rtsp://192.168.0.10/stream1')),patch.object(self.w.live_recorder,'start') as record:
            self.w.update_controls();self.assertTrue(self.w.live_record_btn.isEnabled())
            self.w.toggle_live_recording()
        self.assertEqual(record.call_args.args[1].parent,Path(self.tmp.name))
        self.assertEqual(record.call_args.args[1].suffix,'.mkv');self.w.demo=True

    def test_recording_prevents_camera_switch_and_close_waits_for_save(self):
        from PySide6.QtGui import QCloseEvent
        from unittest.mock import Mock
        self.w.set_mode('live');self.w.live_recorder.proc=Mock();self.w.live_recorder.state='recording'
        self.w.capture_name='Test camera';self.w.update_live_recording()
        self.assertFalse(self.w.camera_list.isEnabled());self.assertFalse(self.w.record_tab.isEnabled())
        self.assertIn('Recording',self.w.capture_status.text())
        self.w.set_mode('recordings');self.assertEqual(self.w.mode,'live')
        event=QCloseEvent();self.w.closeEvent(event)
        self.assertFalse(event.isAccepted());self.assertEqual(self.w.live_recorder.state,'stopping')
        self.assertFalse(self.w.live_record_btn.isEnabled())
        self.w.live_recording_failed('The recording could not be saved.')
        self.assertFalse(self.w.close_after_recording)
        self.w.live_recorder.proc=None;self.w.live_recorder.state='idle';self.w.live_recorder.deadline.stop()

    def test_idle_playback_watchdog_does_not_wake_up(self):
        from PySide6.QtMultimedia import QMediaPlayer
        self.assertFalse(self.w.playback_watchdog.isActive())
        self.w.playback_changed(QMediaPlayer.PlaybackState.PlayingState)
        self.assertTrue(self.w.playback_watchdog.isActive())
        self.w.playback_changed(QMediaPlayer.PlaybackState.StoppedState)
        self.assertFalse(self.w.playback_watchdog.isActive())

    def test_repeated_viewport_results_do_not_decode_the_same_image_again(self):
        from PySide6.QtGui import QImage,QPixmap
        image=QImage(640,360,QImage.Format.Format_RGB32);image.fill(0xff17604a)
        file=Path(self.tmp.name)/'preview.jpg';image.save(str(file))
        key=self.w.thumbnail_loader.key(self.w.rows[0]);data={'available':True,'path':str(file)}
        with patch('tapo_desktop.app.QPixmap',wraps=QPixmap) as decode:
            for _ in range(30):self.w.thumbnail_ready(key,data)
            decode.assert_called_once()
    def test_stream_time_uses_selected_clip_duration(self):
        self.w.streaming=True;self.w.stream_duration=122000
        self.w.position_changed(2000)
        self.assertEqual(self.w.time_label.text(),'0:02 / 2:02')
    def test_date_and_selection(self):
        self.assertIsNotNone(self.w.date_combo.currentData())
        self.assertEqual(self.w.table.rowCount(),7)
        self.assertTrue(self.w.play_btn.isEnabled())
    def test_detection_filter_preserves_download_boundaries_and_selection(self):
        before=[dict(r) for r in self.w.rows]
        self.w.record_filter.setCurrentIndex(1)
        self.assertEqual(len(self.w.rows),6)
        self.assertEqual(self.w.rows[0]['start'],before[0]['start'])
        self.assertTrue(all(r['events'] for r in self.w.rows))
        self.assertIn('Camera type 2',self.w.event_details.text())
        self.w.record_filter.setCurrentIndex(0);self.w.table.selectRow(2)
        self.assertFalse(self.w.thumbnail_btn.isEnabled())
        self.assertIn('Continuous',self.w.thumbnail.text())
    def test_background_thumbnail_missing_and_stale_camera_result(self):
        loader=self.w.thumbnail_loader
        key=loader.key(self.w.rows[0])
        self.w.thumbnail_ready(key,{'available':False})
        self.assertEqual(self.w.thumbnail.text(),'No preview available')
        with patch.object(loader,'retry') as retry:
            self.w.load_thumbnail();retry.assert_called_once_with(self.w.rows[0])
        other=('other-camera',*key[1:])
        self.w.thumbnail_ready(other,{'available':False})
        self.assertEqual(self.w.thumbnail.text(),'Retrying preview…')
    def test_background_thumbnail_does_not_disable_foreground_controls(self):
        with patch.object(self.w.thumbnail_loader,'retry'):
            self.w.load_thumbnail()
        self.assertFalse(self.w.busy);self.assertTrue(self.w.play_btn.isEnabled())
        self.assertTrue(self.w.camera_list.isEnabled());self.assertTrue(self.w.table.isEnabled())
    def test_local_recording_playback_keeps_preview_loading_enabled(self):
        self.w.demo=False;self.w.media_path='/private/local-recording.mp4';self.w.update_controls()
        self.assertTrue(self.w.thumbnail_loader.enabled)
        self.w.busy=True;self.w.update_controls();self.assertFalse(self.w.thumbnail_loader.enabled)
        self.w.busy=False;self.w.demo=True
    def test_continuous_scroll_does_not_postpone_viewport_update(self):
        from PySide6.QtTest import QTest
        self.w.thumbnail_timer.stop();self.w.schedule_thumbnails();QTest.qWait(45)
        self.w.schedule_thumbnails()
        self.assertLess(self.w.thumbnail_timer.remainingTime(),100)
    def test_only_visible_rows_are_requested(self):
        self.w.show();self.w.resize(1060,700);self.application.processEvents()
        self.w.demo=False
        with patch.object(self.w.thumbnail_loader,'set_visible') as visible,patch.object(self.w.thumbnail_loader,'cached',return_value=None):
            self.w.load_visible_thumbnails()
        requested=visible.call_args.args[0]
        self.assertGreater(len(requested),0);self.assertLess(len(requested),len(self.w.rows))
        self.w.demo=True
    def test_empty_detection_filter_keeps_playback_disabled(self):
        self.w.fill_rows([{'start':10,'end':20,'recording_type':'1','events':[]}])
        self.w.record_filter.setCurrentIndex(1)
        self.assertEqual(self.w.table.rowCount(),0)
        self.assertFalse(self.w.play_btn.isEnabled());self.assertFalse(self.w.thumbnail_btn.isEnabled())
        self.assertIn('No recordings with detections',self.w.count_label.text())

    def test_selecting_another_clip_stops_old_playback(self):
        from PySide6.QtCore import QUrl
        self.w.player.setSource(QUrl.fromLocalFile('/nonexistent/old.mp4'))
        self.w.media_path='old.mp4'
        self.w.table.selectRow(1)
        self.assertTrue(self.w.player.source().isEmpty())
        self.assertIsNone(self.w.media_path)
        self.assertFalse(self.w.pause_btn.isEnabled())
    def test_credentials_shared_default_and_separate_drafts(self):
        from tapo_desktop.app import CredentialsDialog,CameraDialog
        storage.save_shared_live_settings('shared-user')
        self.w.camera.username='override-user'
        dialog=CredentialsDialog(self.w.camera,self.w)
        self.assertTrue(dialog.use_shared.isChecked());self.assertEqual(dialog.user.text(),'shared-user')
        dialog.password.setText('fake-shared-draft');dialog.use_shared.setChecked(False)
        self.assertEqual(dialog.user.text(),'override-user');self.assertEqual(dialog.password.text(),'')
        dialog.password.setText('fake-override-draft');dialog.use_shared.setChecked(True)
        self.assertEqual(dialog.user.text(),'shared-user');self.assertEqual(dialog.password.text(),'fake-shared-draft')
        self.assertIn('every camera',dialog.scope_hint.text());dialog.reject()
        self.w.camera.use_shared_credentials=False
        edit=CameraDialog(self.w.camera,self.w);edit.validate()
        self.assertFalse(edit.camera.use_shared_credentials)

    def test_cloud_only_save_does_not_claim_live_is_configured(self):
        from tapo_desktop.app import credential_save_message
        text=credential_save_message(True,True,False)
        self.assertIn('Tapo account password saved',text)
        self.assertIn('Add Camera Account credentials',text)
        self.assertNotIn('live-view credentials saved',text)
        self.assertIn('Shared live-view credentials saved',credential_save_message(False,True,True))

    def test_rtsp_address_escapes_credentials(self):
        from tapo_desktop.app import rtsp_url,live_error_message
        from PySide6.QtCore import QUrl
        secret='example:p@ss/#?%'
        url=rtsp_url({'host':'192.168.0.21','stream':'stream1','username':'camera-user','password':secret})
        self.assertEqual(url.scheme(),'rtsp');self.assertEqual(url.port(),554)
        self.assertEqual(url.path(),'/stream1');self.assertEqual(url.password(),secret)
        self.assertEqual(url.host(),'192.168.0.21')
        self.assertIn(b'%40',bytes(url.toEncoded()))
        self.assertIn(b'%23',bytes(url.toEncoded()))
        message=live_error_message('401 Unauthorized at rtsp://user:example-secret@host/')
        self.assertIn('rejected',message);self.assertNotIn('example-secret',message)
        self.assertNotIn('rtsp://',message)
    def test_modes(self):
        self.w.set_mode('live');self.assertEqual(self.w.play_btn.text(),'Connect live')
        self.assertTrue(self.w.record_panel.isHidden())
        self.w.set_mode('recordings');self.assertFalse(self.w.record_panel.isHidden())
    def test_switch_camera_resets_clip(self):
        self.w.media_path='old.mp4'
        self.w.camera_list.setCurrentRow(1)
        self.assertIsNone(self.w.media_path)
        self.assertEqual(self.w.camera.host,'192.168.1.11')
    def test_got_dates_loads_latest(self):
        self.w.demo=False
        with patch.object(self.w,'start_job') as start:
            self.w.got_dates({'dates':['20261029','20261030']})
            self.assertEqual(self.w.date_combo.currentData(),'20261030')
            self.assertEqual(start.call_args.args[0],'segments')
    def test_busy_disables_camera_switch(self):
        self.w.busy=True;self.w.update_controls()
        self.assertFalse(self.w.camera_list.isEnabled())
        self.assertFalse(self.w.download_btn.isEnabled())
        self.w.busy=False
    def test_error_recovery(self):
        self.w.show_error('Offline; retry');self.assertIn('Offline',self.w.status.text())
        self.w.busy=False;self.w.update_controls();self.assertTrue(self.w.refresh_btn.isEnabled())


if __name__=='__main__':unittest.main()
