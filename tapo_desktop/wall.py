"""Independent live players; focused cameras automatically use the main stream."""
import math
import time
from PySide6.QtCore import Qt, QEvent, QTimer, QUrl, Signal
from PySide6.QtWidgets import (QFrame, QWidget, QLabel, QPushButton, QVBoxLayout,
                              QHBoxLayout, QGridLayout, QStackedWidget, QScrollArea)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from .video_surface import VideoSurface


def text_label(text,name=None):
    label=QLabel(text);label.setTextFormat(Qt.TextFormat.PlainText)
    if name:label.setObjectName(name)
    label.setWordWrap(True)
    return label


class CameraTile(QFrame):
    activated=Signal(str)
    status_changed=Signal()
    def __init__(self,camera,url_builder,error_formatter,parent=None):
        super().__init__(parent)
        self.camera=camera;self.url_builder=url_builder;self.error_formatter=error_formatter
        self.state='Stopped';self.frames=0;self.source=None;self.last_frame=0.0
        self.base_source=None;self.high_quality=False
        self.setObjectName('cameraTile');self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(camera.name+' '+camera.host+' live camera tile')
        self.setToolTip('Double-click, or press Enter, to focus this camera. Double-click again to return to all cameras.')
        layout=QVBoxLayout(self);layout.setContentsMargins(10,10,10,10);layout.setSpacing(8)
        head=QHBoxLayout()
        self.title=text_label(camera.name+' · '+camera.host,'tileTitle');head.addWidget(self.title,1)
        self.status=text_label('Stopped','tileStatus');head.addWidget(self.status)
        layout.addLayout(head)
        self.stack=QStackedWidget();layout.addWidget(self.stack,1)
        empty=QWidget();empty_layout=QVBoxLayout(empty);empty_layout.setContentsMargins(12,8,12,8)
        empty_layout.addStretch()
        self.hint=text_label('Ready to connect','tileHint');self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.hint);empty_layout.addStretch()
        self.stack.addWidget(empty)
        self.video=VideoSurface()
        self.stack.addWidget(self.video)
        self.retry=QPushButton('Reconnect');self.retry.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry.clicked.connect(self.reconnect);self.retry.hide();layout.addWidget(self.retry)
        self.player=QMediaPlayer(self);self.audio=QAudioOutput(self)
        self.audio.setVolume(0.6);self.audio.setMuted(True)
        self.player.setVideoSink(self.video.videoSink())  # Attach audio only for an explicitly unmuted tile.
        self.video.videoSink().videoFrameChanged.connect(self.frame_arrived)
        self.player.errorOccurred.connect(self.failed)
        self.player.playbackStateChanged.connect(self.playback_changed)
        self.deadline=QTimer(self);self.deadline.setInterval(1000)
        self.deadline.timeout.connect(self.check_stall)
        self.failure_cleanup=QTimer(self);self.failure_cleanup.setSingleShot(True)
        self.failure_cleanup.timeout.connect(self.clear_failed_player)
        for widget in (self,self.title,self.status,self.stack,empty,self.hint,self.video):widget.installEventFilter(self)

    def eventFilter(self,watched,event):
        if event.type()==QEvent.Type.MouseButtonDblClick and event.button()==Qt.MouseButton.LeftButton:
            self.activated.emit(self.camera.id);return True
        return super().eventFilter(watched,event)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter):
            self.activated.emit(self.camera.id);event.accept()
        else:super().keyPressEvent(event)

    def set_state(self,state):
        if self.state==state:return
        self.state=state;self.status.setText(state);self.status_changed.emit()

    def connect_stream(self,data):
        self.stop()
        if data.get('error'):
            self.show_failure(data['error']);return
        self.base_source=self.url_builder(data)
        self.source=self.selected_source()
        self.reconnect()

    def selected_source(self):
        source=QUrl(self.base_source)
        if self.high_quality:source.setPath('/stream1')
        return source

    def set_high_quality(self,enabled):
        self.high_quality=enabled
        if self.base_source is None:return
        source=self.selected_source()
        if source==self.source:return
        self.source=source
        self.reconnect()

    def reconnect(self):
        if self.source is None:return
        self.set_state('Connecting')  # Ignore the intentional stop during a stream switch.
        self.failure_cleanup.stop();self.video.clear();self.player.stop();self.player.setSource(QUrl())
        self.stack.setCurrentIndex(0);self.retry.hide();self.hint.setText('Connecting…')
        self.set_state('Connecting');self.frames=0
        self.last_frame=time.monotonic();self.deadline.start();self.video.start_capture()
        self.player.setSource(self.source);self.player.play()

    def frame_arrived(self,frame):
        if not frame.isValid() or self.state not in ('Connecting','Live'):return
        self.frames+=1;self.last_frame=time.monotonic()
        if self.state!='Live':
            self.stack.setCurrentIndex(1);self.set_state('Live')

    def check_stall(self):
        if self.state in ('Connecting','Live') and time.monotonic()-self.last_frame>20:
            self.failed(timeout=True)

    def set_muted(self,muted):
        self.audio.setMuted(muted)
        self.player.setAudioOutput(None if muted else self.audio)

    def playback_changed(self,state):
        if state==QMediaPlayer.PlaybackState.StoppedState and self.state=='Live':
            self.show_failure('Live stream stopped. Reconnect to try again.')

    def show_failure(self,message):
        self.deadline.stop();self.set_state('Unavailable')
        self.stack.setCurrentIndex(0)
        self.hint.setText(message);self.retry.setVisible(self.source is not None)
        self.failure_cleanup.start(0)  # Do not tear down a decoder inside its error signal.

    def clear_failed_player(self):
        if self.state=='Unavailable':
            self.video.clear();self.player.stop();self.player.setSource(QUrl());self.set_muted(True)

    def failed(self,error=None,message='',*,timeout=False):
        self.show_failure(self.error_formatter(message,timeout=timeout))

    def stop(self):
        self.deadline.stop();self.failure_cleanup.stop();self.video.clear()
        if self.state=='Stopped' and self.player.source().isEmpty() and self.source is None:return
        self.set_state('Stopped')
        self.player.stop();self.player.setSource(QUrl());self.set_muted(True)
        self.source=None;self.base_source=None;self.frames=0;self.stack.setCurrentIndex(0);self.retry.hide()
        self.hint.setText('Ready to connect')


class CameraWall(QWidget):
    focus_changed=Signal(object)
    status_changed=Signal()
    def __init__(self,url_builder,error_formatter,parent=None):
        super().__init__(parent)
        self.url_builder=url_builder;self.error_formatter=error_formatter
        self.tiles={};self.focused_id=None;self.columns=0;self.layout_key=None
        self.pending_connections=[]
        self.connection_timer=QTimer(self);self.connection_timer.setSingleShot(True)
        self.connection_timer.timeout.connect(self.connect_next)
        self.layout_timer=QTimer(self);self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self.reflow)
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.scroll=QScrollArea();self.scroll.setWidgetResizable(True);self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setObjectName('cameraWallScroll');layout.addWidget(self.scroll)
        self.canvas=QWidget();self.canvas.setObjectName('cameraWallCanvas')
        self.grid=QGridLayout(self.canvas);self.grid.setContentsMargins(12,12,12,12);self.grid.setSpacing(12)
        self.scroll.setWidget(self.canvas)
        self.scroll.viewport().installEventFilter(self)

    def configure(self,cameras):
        self.stop_all();self.focused_id=None
        for tile in self.tiles.values():tile.set_high_quality(False)
        wanted={camera.id for camera in cameras}
        for camera_id in list(self.tiles):
            if camera_id not in wanted:
                tile=self.tiles.pop(camera_id);self.grid.removeWidget(tile)
                tile.hide();tile.deleteLater()
        ordered={}
        for camera in cameras:
            tile=self.tiles.get(camera.id)
            if tile is None:
                tile=CameraTile(camera,self.url_builder,self.error_formatter,self.canvas)
                tile.activated.connect(self.toggle_focus);tile.status_changed.connect(self.status_changed)
            else:
                tile.camera=camera;tile.title.setText(camera.name+' · '+camera.host)
            ordered[camera.id]=tile
        self.tiles=ordered;self.layout_key=None
        self.reflow();self.focus_changed.emit(None)

    def reflow(self):
        preferred=1 if len(self.tiles)<2 else (2 if len(self.tiles)<=4 else 3)
        columns=1 if self.focused_id else max(1,min(preferred,max(1,self.scroll.viewport().width()//250)))
        key=(tuple(self.tiles),self.focused_id,columns)
        if key==self.layout_key:return
        self.layout_key=key;self.columns=columns
        while self.grid.count():self.grid.takeAt(0)
        # Reset existing dimensions only. Writing beyond them grows QGridLayout forever.
        for row in range(self.grid.rowCount()):
            self.grid.setRowStretch(row,0);self.grid.setRowMinimumHeight(row,0)
        for col in range(self.grid.columnCount()):
            self.grid.setColumnStretch(col,0);self.grid.setColumnMinimumWidth(col,0)
        if self.focused_id in self.tiles:
            selected=self.tiles[self.focused_id]
            for tile in self.tiles.values():tile.setVisible(tile is selected)
            self.grid.addWidget(selected,0,0);self.grid.setRowStretch(0,1);self.grid.setColumnStretch(0,1)
            self.canvas.setMinimumHeight(0)
            return
        for index,tile in enumerate(self.tiles.values()):
            tile.show();row,col=divmod(index,self.columns)
            self.grid.addWidget(tile,row,col);self.grid.setRowStretch(row,1);self.grid.setColumnStretch(col,1)
        rows=math.ceil(len(self.tiles)/self.columns)
        self.canvas.setMinimumHeight(rows*180+max(0,rows-1)*12+24)

    def eventFilter(self,watched,event):
        if watched is self.scroll.viewport() and event.type()==QEvent.Type.Resize:
            self.layout_timer.start(0)
        return super().eventFilter(watched,event)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.layout_timer.start(0)

    def toggle_focus(self,camera_id):
        self.set_focus(None if camera_id==self.focused_id else camera_id)

    def set_focus(self,camera_id):
        if camera_id is not None and camera_id not in self.tiles:return
        if camera_id==self.focused_id:return
        previous=self.focused_id;self.focused_id=camera_id
        if previous in self.tiles:self.tiles[previous].set_high_quality(False)
        if camera_id:self.tiles[camera_id].set_high_quality(True)
        self.mute_all();self.reflow();self.focus_changed.emit(camera_id)
        if camera_id:self.tiles[camera_id].setFocus()

    def show_all(self):self.set_focus(None)

    def connect_streams(self,data):
        self.connection_timer.stop();self.pending_connections=[]
        by_id={row['id']:row for row in data['cameras']}
        for camera_id,tile in self.tiles.items():
            tile.stop();tile.hint.setText('Waiting to connect…');tile.set_state('Queued')
            self.pending_connections.append((camera_id,by_id.get(camera_id,{'error':'Camera credentials unavailable. Open Credentials and retry.'})))
        if self.pending_connections:self.connection_timer.start(0)
        self.status_changed.emit()

    def connect_next(self):
        if not self.pending_connections:return
        camera_id,data=self.pending_connections.pop(0)
        tile=self.tiles.get(camera_id)
        if tile:tile.connect_stream(data)
        if self.pending_connections:self.connection_timer.start(350)

    def mute_all(self):
        for tile in self.tiles.values():
            if not tile.audio.isMuted():tile.set_muted(True)

    def toggle_focused_audio(self):
        if self.focused_id:
            tile=self.tiles[self.focused_id];muted=tile.audio.isMuted()
            self.mute_all();tile.set_muted(not muted)

    def stop_all(self):
        self.connection_timer.stop();self.pending_connections=[]
        for tile in self.tiles.values():tile.stop()

    def summary(self):
        live=sum(tile.state=='Live' for tile in self.tiles.values())
        pending=sum(tile.state in ('Connecting','Queued') for tile in self.tiles.values())
        return f'{live} / {len(self.tiles)} live'+(' · connecting…' if pending else '')
