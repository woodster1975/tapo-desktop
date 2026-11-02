import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import asdict
import tempfile
import unittest
from unittest.mock import patch
from tapo_desktop.storage import Camera,UserError
from tapo_desktop import worker


class WallWorkerTests(unittest.TestCase):
    def test_shared_credentials_read_once_and_errors_independent(self):
        cameras=[Camera('a','A','192.168.0.10'),Camera('b','B','192.168.0.11'),
                 Camera('c','C','192.168.0.12',username='other',use_shared_credentials=False)]
        with patch.object(worker,'shared_live_credentials',return_value=('shared','fake')) as shared,patch.object(worker,'get_secret',side_effect=UserError('Override unavailable')):
            result=worker.result_for({'op':'live_wall','cameras':[asdict(c) for c in cameras]})
        shared.assert_called_once()
        rows=result['cameras']
        self.assertEqual(rows[0]['username'],'shared');self.assertEqual(rows[1]['username'],'shared')
        self.assertEqual(rows[2],{'id':'c','error':'Override unavailable'})
    def test_shared_error_is_cached_without_authentication(self):
        cameras=[asdict(Camera(str(i),'Cam','192.168.0.'+str(i+10))) for i in range(3)]
        with patch.object(worker,'shared_live_credentials',side_effect=UserError('Unlock keyring')) as shared:
            result=worker.result_for({'op':'live_wall','cameras':cameras})
        shared.assert_called_once();self.assertTrue(all('error' in row for row in result['cameras']))


class WallUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(lambda *_:None)
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'XDG_CONFIG_HOME':self.tmp.name,'LOCALAPPDATA':self.tmp.name});self.env.start()
        from tapo_desktop.app import MainWindow
        from tapo_desktop.storage import save_cameras
        save_cameras([Camera('first','First','192.168.1.10'),Camera('second','Second','192.168.1.11')])
        self.w=MainWindow(demo=True)
        self.w.cameras.append(Camera('third','Third','192.168.0.162'))
        self.w.show();self.w.set_mode('wall');self.app.processEvents()
    def tearDown(self):
        self.w.busy=False;self.w.close();self.w.deleteLater();self.app.processEvents();self.env.stop();self.tmp.cleanup()
    def test_double_click_focus_and_return_preserves_players(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        tiles=list(self.w.wall.tiles.values());players=[tile.player for tile in tiles]
        QTest.mouseDClick(tiles[1].video,Qt.MouseButton.LeftButton)
        self.assertEqual(self.w.wall.focused_id,tiles[1].camera.id)
        self.assertTrue(tiles[0].isHidden());self.assertFalse(tiles[1].isHidden())
        self.assertFalse(self.w.back_btn.isHidden())
        self.w.back_btn.click();self.assertIsNone(self.w.wall.focused_id)
        self.assertTrue(all(not tile.isHidden() for tile in tiles))
        self.assertEqual([tile.player for tile in tiles],players)
    def test_focus_switches_only_selected_stream_and_restores_grid(self):
        from PySide6.QtCore import QUrl
        tiles=list(self.w.wall.tiles.values())
        for tile in tiles:
            tile.base_source=QUrl('rtsp://192.168.0.10:554/stream2')
            tile.source=QUrl(tile.base_source)
        with patch.object(tiles[0],'reconnect') as first,patch.object(tiles[1],'reconnect') as second:
            self.w.wall.set_focus(tiles[0].camera.id)
            self.assertEqual(tiles[0].source.path(),'/stream1');first.assert_called_once();second.assert_not_called()
            self.w.wall.set_focus(tiles[1].camera.id)
            self.assertEqual(tiles[0].source.path(),'/stream2')
            self.assertEqual(tiles[1].source.path(),'/stream1')
            self.w.wall.show_all()
            self.assertEqual(tiles[1].source.path(),'/stream2')
            self.assertEqual(first.call_count,2);self.assertEqual(second.call_count,2)
    def test_focus_before_connection_and_full_quality_grid(self):
        tile=next(iter(self.w.wall.tiles.values()))
        self.w.wall.set_focus(tile.camera.id)
        with patch.object(tile,'reconnect') as reconnect:
            tile.connect_stream({'host':tile.camera.host,'username':'test','password':'fake','stream':'stream2'})
            self.assertEqual(tile.source.path(),'/stream1')
            self.w.wall.show_all();self.assertEqual(tile.source.path(),'/stream2')
            tile.connect_stream({'host':tile.camera.host,'username':'test','password':'fake','stream':'stream1'})
            reconnect.reset_mock()
            self.w.wall.set_focus(tile.camera.id);self.w.wall.show_all()
            reconnect.assert_not_called()
            tile.stop();self.w.wall.set_focus(tile.camera.id)
            reconnect.assert_not_called();self.assertIsNone(tile.base_source)

    def test_keyboard_focus_escape_and_audio(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        tiles=list(self.w.wall.tiles.values());tiles[0].setFocus()
        QTest.keyClick(tiles[0],Qt.Key.Key_Return)
        self.assertEqual(self.w.wall.focused_id,tiles[0].camera.id)
        self.w.toggle_mute();self.assertFalse(tiles[0].audio.isMuted())
        self.assertTrue(all(t.audio.isMuted() for t in tiles[1:]))
        self.w.escape_action();self.assertIsNone(self.w.wall.focused_id)
        self.assertTrue(all(t.audio.isMuted() for t in tiles))
    def test_focusing_updates_camera_context_without_stale_recordings(self):
        third=self.w.cameras[-1];self.w.wall.set_focus(third.id)
        self.assertEqual(self.w.camera,third);self.assertEqual(self.w.rows,[])
        self.assertEqual(self.w.table.rowCount(),0)
        self.w.set_mode('recordings')
        self.assertEqual(self.w.camera,third)
        self.assertTrue(all(t.player.source().isEmpty() for t in self.w.wall.tiles.values()))
    def test_tile_failure_does_not_stop_neighbor(self):
        tiles=list(self.w.wall.tiles.values())
        with patch.object(tiles[1].player,'stop') as stop:
            tiles[0].show_failure('Camera offline')
            stop.assert_not_called()
        self.assertEqual(tiles[0].state,'Unavailable')
    def test_stop_clears_all_sources_and_late_callback(self):
        self.w.wall_requested=True;self.w.stop_media()
        with patch.object(self.w.wall,'connect_streams') as connect:
            self.w.got_wall({'cameras':[]});connect.assert_not_called()
        self.assertTrue(all(t.player.source().isEmpty() for t in self.w.wall.tiles.values()))
    def test_grid_dimensions_stay_bounded_after_repeated_zoom(self):
        for _ in range(200):
            self.w.wall.set_focus('c320ws');self.w.wall.show_all()
        self.assertLessEqual(self.w.wall.grid.rowCount(),len(self.w.cameras))
        self.assertLessEqual(self.w.wall.grid.columnCount(),len(self.w.cameras))

    def test_reconfigure_reuses_players(self):
        players={key:tile.player for key,tile in self.w.wall.tiles.items()}
        for _ in range(20):self.w.wall.configure(self.w.cameras)
        self.assertEqual(players,{key:tile.player for key,tile in self.w.wall.tiles.items()})
        from PySide6.QtMultimedia import QMediaPlayer
        self.assertEqual(len(self.w.wall.findChildren(QMediaPlayer)),len(self.w.cameras))

    def test_stop_cancels_staggered_connections(self):
        wall=self.w.wall
        wall.connect_streams({'cameras':[{'id':key,'error':'No test connection'} for key in wall.tiles]})
        self.assertEqual(len(wall.pending_connections),len(wall.tiles))
        with patch.object(next(iter(wall.tiles.values())),'connect_stream') as connect:
            wall.stop_all();self.app.processEvents();connect.assert_not_called()
        self.assertFalse(wall.connection_timer.isActive());self.assertFalse(wall.pending_connections)

    def test_error_teardown_waits_until_signal_returns(self):
        tile=next(iter(self.w.wall.tiles.values()))
        with patch.object(tile.player,'stop') as stop:
            tile.show_failure('Test failure');stop.assert_not_called()
            self.app.processEvents();self.assertTrue(stop.called)

    def test_wall_defaults_to_low_bandwidth_without_changing_profile(self):
        self.assertEqual(self.w.wall_quality.currentData(),'stream2')
        self.assertTrue(all(camera.stream=='stream1' for camera in self.w.cameras))
        self.w.demo=False
        with patch.object(self.w,'start_job') as job:
            self.w.start_wall()
            self.assertTrue(all(c['stream']=='stream2' for c in job.call_args.kwargs['cameras']))
        self.w.wall_requested=False

    def test_wall_surface_has_no_native_video_widgets_and_keeps_latest_frame(self):
        from PySide6.QtGui import QImage,QColor
        from PySide6.QtMultimedia import QVideoFrame
        from PySide6.QtMultimediaWidgets import QVideoWidget
        from tapo_desktop.video_surface import VideoSurface
        surface=VideoSurface(self.w)
        surface.resize(320,180);surface.show();self.app.processEvents();surface.start_capture()
        for name in ('red','green','blue'):
            image=QImage(64,36,QImage.Format.Format_RGB32);image.fill(QColor(name))
            surface.receive_frame(QVideoFrame(image))
        surface.present_latest()
        self.assertEqual(surface.presented_frames,1)
        self.assertEqual(surface._image.pixelColor(0,0),QColor('blue'))
        self.assertIsNone(surface._latest)
        self.assertFalse(self.w.wall.findChildren(QVideoWidget))
        self.assertEqual(surface.sizeHint().width(),320)
        surface.clear()
        self.assertTrue(surface._image.isNull());self.assertIsNone(surface._latest)
        surface.receive_frame(QVideoFrame(image));self.assertIsNone(surface._latest)
        surface.hide();self.assertFalse(surface._timer.isActive());surface.deleteLater()

    def test_frames_released_before_decoder_stop(self):
        tile=next(iter(self.w.wall.tiles.values()));events=[]
        tile.state='Live'
        with patch.object(tile.video,'clear',side_effect=lambda:events.append('frames')),patch.object(tile.player,'stop',side_effect=lambda:events.append('decoder')):
            tile.stop()
        self.assertEqual(events[:2],['frames','decoder'])

    def test_status_waits_for_decoded_frame(self):
        from PySide6.QtMultimedia import QVideoFrame
        tile=next(iter(self.w.wall.tiles.values()))
        tile.state='Connecting';tile.frame_arrived(QVideoFrame())
        self.assertEqual(tile.state,'Connecting')


if __name__=='__main__':unittest.main()
