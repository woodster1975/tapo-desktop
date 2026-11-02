"""Native Linux/Windows viewer. Camera operations live in isolated child processes."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import uuid
import time

# Suppress native multimedia diagnostics, which can include authenticated URLs.
os.environ.setdefault('QT_LOGGING_RULES', 'qt.multimedia.*=false')
os.environ.setdefault('QT_MEDIA_BACKEND', 'ffmpeg')
os.environ.setdefault('QT_FFMPEG_PROTOCOL_WHITELIST', 'file,crypto,data,http,rtsp,tcp,udp,rtp')
from PySide6.QtCore import Qt, QDate, QProcess, QTimer, QUrl, QSettings, QStandardPaths, Signal, qInstallMessageHandler, QSize, QEvent
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen, QDesktopServices, QKeySequence, QShortcut, QPixmap, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSplitter, QButtonGroup, QComboBox, QProgressBar,
    QSlider, QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QMessageBox, QFileDialog,
    QStackedWidget, QSizePolicy, QCheckBox)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget
from .storage import Camera, UserError, load_cameras, save_cameras, cache_dir, load_shared_live_settings
from .theme import STYLE
from .wall import CameraWall
from .detections import has_detection, detection_label
from .thumbnails import ThumbnailLoader
from .playback_process import RecordingPlayback
from .live_recorder import LiveRecorder
from .processes import worker_command
from . import __version__


def label(text='', name=None, wrap=False):
    w = QLabel(text)
    w.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def button(text, callback=None, name=None):
    w = QPushButton(text)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    if name:
        w.setObjectName(name)
    if callback:
        w.clicked.connect(callback)
    return w


def stamp(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().strftime('%H:%M:%S')


def duration(seconds):
    seconds = int(seconds)
    return f'{seconds//60}:{seconds%60:02d}'


def rtsp_url(data):
    """Build authenticated URLs in memory; QUrl escapes reserved characters."""
    url=QUrl();url.setScheme('rtsp');url.setHost(data['host']);url.setPort(554)
    url.setPath('/'+data['stream']);url.setUserName(data['username']);url.setPassword(data['password'])
    return url


def live_error_message(message='', *, timeout=False):
    # Classify internally; never display a raw Qt/FFmpeg message or URL.
    text=message.lower()
    if any(token in text for token in ('401','unauthorized','authentication failed','authorization failed')):
        return 'The camera rejected its Camera Account username or password. Open Credentials and update the Live view account for this camera. Use the account configured in the Tapo app, not your Tapo login.'
    if any(token in text for token in ('connection refused','unreachable','host not found')):
        return 'The RTSP service could not be reached. Check the camera IP, network access and RTSP port 554, then retry.'
    if timeout or 'timed out' in text:
        return 'Live video timed out. Check this camera’s Camera Account credentials, network/firewall and other open viewers, then retry.'
    return 'Live video could not start. Check the Camera Account credentials saved for this camera. If the same account works in VLC, try Lower bandwidth in Edit camera and reconnect.'


def credential_save_message(cloud_saved,shared,live_configured):
    if not live_configured:
        prefix='Tapo account password saved. ' if cloud_saved else 'Shared live-view mode selected. '
        return prefix+'Add Camera Account credentials to enable live view.'
    prefix='Tapo account password and ' if cloud_saved else ''
    if shared:return prefix+('shared' if cloud_saved else 'Shared')+' live-view credentials saved for all cameras using them.'
    return prefix+('camera-specific' if cloud_saved else 'Camera-specific')+' live-view credentials saved.'


class DayTimeline(QWidget):
    selected = Signal(int)
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(78)
        self.rows, self.active = [], -1
        self.setAccessibleName('Recording activity across the selected day')
        self.setToolTip('Recording intervals across the day. Select a clip in the list for exact times.')

    def set_rows(self, rows):
        self.rows, self.active = rows, -1
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, left = self.width()-32, 16
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#dce4da'))
        p.drawRoundedRect(left, 16, width, 16, 4, 4)
        for i,r in enumerate(self.rows):
            dt = datetime.fromtimestamp(r['start'])
            second = dt.hour*3600+dt.minute*60+dt.second
            x = left + width*second/86400
            w = max(2, width*(r['end']-r['start'])/86400)
            p.setBrush(QColor('#175e4b' if i == self.active else '#80a28d'))
            p.drawRoundedRect(int(x), 12 if i == self.active else 16, int(w), 24 if i == self.active else 16, 2, 2)
        p.setPen(QColor('#50645c'))
        p.setFont(QFont('Lato',10))
        for hour in (0,6,12,18,24):
            x = int(left + width*hour/24)
            text=f'{hour:02d}:00'
            offset=p.fontMetrics().horizontalAdvance(text) if hour==24 else (12 if hour else 0)
            p.drawText(x-offset, 56, text)
        p.end()


class CameraDialog(QDialog):
    def __init__(self, camera, parent):
        super().__init__(parent)
        self.setWindowTitle('Edit camera' if camera else 'Add camera')
        self.setMinimumWidth(440)
        self.original = camera
        layout = QVBoxLayout(self)
        layout.addWidget(label('Camera details','section'))
        layout.addWidget(label('Use the camera’s address on your local network.','muted',True))
        form = QFormLayout()
        self.name = QLineEdit(camera.name if camera else '')
        self.host = QLineEdit(camera.host if camera else '')
        self.model = QComboBox(); self.model.addItems(['C310','C320WS','Other Tapo'])
        if camera:
            self.model.setCurrentText(camera.model)
        self.quality = QComboBox(); self.quality.addItems(['Full quality','Lower bandwidth'])
        self.quality.setCurrentIndex(0 if not camera or camera.stream=='stream1' else 1)
        for text,w in [('Name',self.name),('Camera IP',self.host),('Model',self.model),('Live video',self.quality)]:
            form.addRow(text,w)
        layout.addLayout(form)
        self.error = label('', 'error',True); layout.addWidget(self.error)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.validate); controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def validate(self):
        try:
            self.camera = Camera.from_dict({'id':self.original.id if self.original else uuid.uuid4().hex[:12],
                'name':self.name.text().strip(),'host':self.host.text().strip(),'model':self.model.currentText(),
                'username':self.original.username if self.original else '',
                'stream':'stream1' if self.quality.currentIndex()==0 else 'stream2',
                'use_shared_credentials':self.original.use_shared_credentials if self.original else True})
            self.accept()
        except Exception:
            self.error.setText('Enter a camera name and a private LAN IPv4 address, such as 192.168.1.100.')


class CredentialsDialog(QDialog):
    def __init__(self, camera, parent):
        super().__init__(parent)
        self.setWindowTitle('Credentials · '+camera.name+' · '+camera.host)
        self.setMinimumWidth(520)
        self.setModal(True)
        layout=QVBoxLayout(self); layout.setSpacing(16)
        layout.addWidget(label('Connect securely','title'))
        layout.addWidget(label('Passwords are saved in your operating system’s credential store. Leave a password blank to keep the saved value.','muted',True))
        layout.addWidget(label('Recordings · shared Tapo account','section'))
        form=QFormLayout()
        self.cloud=QLineEdit(); self.cloud.setEchoMode(QLineEdit.EchoMode.Password)
        self.cloud.setPlaceholderText('Already saved? Leave blank')
        form.addRow('Tapo password',self.cloud); layout.addLayout(form)
        layout.addWidget(label('Live view · Camera Account','section'))
        self.use_shared=QCheckBox('Use shared credentials for this camera (default)')
        self.use_shared.setChecked(camera.use_shared_credentials);layout.addWidget(self.use_shared)
        self.scope_hint=label('', 'muted',True);layout.addWidget(self.scope_hint)
        layout.addWidget(label('Create this account in the Tapo app: camera settings → Advanced Settings → Camera Account. This is separate from your Tapo login.','muted',True))
        form=QFormLayout()
        shared=load_shared_live_settings()
        self.drafts={True:{'username':shared['username'],'password':''},False:{'username':camera.username,'password':''}}
        self.current_scope=camera.use_shared_credentials
        self.camera_host=camera.host
        self.user=QLineEdit(self.drafts[self.current_scope]['username']); self.user.setPlaceholderText('Camera Account username')
        self.password=QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText('Camera Account password')
        form.addRow('Username',self.user);form.addRow('Password',self.password)
        layout.addLayout(form)
        self.use_shared.toggled.connect(self.change_scope)
        self.update_scope_hint()
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.validate);controls.rejected.connect(self.reject);layout.addWidget(controls)
        self.error=label('','error',True);layout.addWidget(self.error)

    def update_scope_hint(self):
        self.scope_hint.setText('Username and password below apply to every camera using shared credentials.' if self.use_shared.isChecked() else 'Only '+self.camera_host+' uses the username and password below.')

    def change_scope(self,shared):
        self.drafts[self.current_scope]={'username':self.user.text(),'password':self.password.text()}
        self.current_scope=shared
        self.user.setText(self.drafts[shared]['username']);self.password.setText(self.drafts[shared]['password'])
        self.update_scope_hint()

    def validate(self):
        if (not self.use_shared.isChecked() or self.password.text()) and not self.user.text().strip():
            self.error.setText('Enter the Camera Account username with its password.');return
        self.accept()


class DiscoveryDialog(QDialog):
    scan_requested = Signal(str,str)
    cancel_requested = Signal()

    def __init__(self,cameras,parent,*,networks=None,demo=False):
        super().__init__(parent)
        from .discovery import local_networks
        import ipaddress
        self.setWindowTitle('Find cameras');self.resize(760,540);self.setMinimumSize(680,480)
        self.existing={c.host for c in cameras};self.rows=[];self.running=False;self.close_pending=False
        self.demo=demo
        layout=QVBoxLayout(self);layout.setContentsMargins(24,24,24,24);layout.setSpacing(14)
        layout.addWidget(label('Find cameras on your network','title'))
        layout.addWidget(label('Scan an attached local network for Tapo devices. No passwords or camera login attempts are used.','muted',True))
        options=QHBoxLayout();self.network=QComboBox();self.network.setAccessibleName('Local network to scan')
        attached=local_networks() if networks is None else networks
        for n in attached:self.network.addItem(f"{n['network']}  ·  {n['adapter']}",n)
        best=0
        for i,n in enumerate(attached):
            net=ipaddress.IPv4Network(n['network'])
            if any(ipaddress.IPv4Address(c.host) in net for c in cameras):best=i;break
        if attached:self.network.setCurrentIndex(best)
        options.addWidget(self.network,1)
        self.scan_btn=button('Scan network',self.scan_clicked,'primary');options.addWidget(self.scan_btn)
        layout.addLayout(options)
        self.status=label('Choose a network, then scan. This usually takes about 5–10 seconds.','muted',True)
        if not attached:self.status.setText('No active local IPv4 network found. Connect to your camera network, then reopen this window.')
        if demo:self.status.setText('Demo mode · network discovery is disabled.')
        layout.addWidget(self.status)
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.setTextVisible(False);self.progress.hide();layout.addWidget(self.progress)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Model','IP address','Device','Status'])
        self.table.verticalHeader().hide();self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.itemSelectionChanged.connect(self.selection_changed);layout.addWidget(self.table,1)
        layout.addWidget(label('Only new cameras can be added. Other Tapo devices are listed for information. If a camera is missing, check your firewall or use Add camera.','muted',True))
        actions=QHBoxLayout();actions.addStretch()
        self.close_btn=button('Close',self.reject);actions.addWidget(self.close_btn)
        self.add_btn=button('Add selected cameras',self.accept,'primary');self.add_btn.setEnabled(False);actions.addWidget(self.add_btn)
        layout.addLayout(actions)
        self.scan_btn.setEnabled(bool(attached) and not demo)

    def scan_clicked(self):
        if self.running:
            self.status.setText('Stopping scan…');self.scan_btn.setEnabled(False);self.cancel_requested.emit();return
        if not self.network.currentData():return
        self.running=True;self.rows=[];self.table.setRowCount(0);self.network.setEnabled(False)
        self.add_btn.setEnabled(False);self.scan_btn.setText('Stop scan');self.progress.show()
        self.status.setText('Scanning… waiting for local device announcements.')
        selected=self.network.currentData()
        self.scan_requested.emit(selected['network'],selected['address'])

    def finished_scan(self):
        self.running=False;self.network.setEnabled(True);self.scan_btn.setText('Scan again')
        self.scan_btn.setEnabled(self.network.count()>0 and not self.demo);self.progress.hide()
        if self.close_pending:super().reject()

    def got_results(self,data):
        self.finished_scan();self.rows=data['devices'];self.table.setRowCount(len(self.rows))
        for i,row in enumerate(self.rows):
            status='Already added' if row['host'] in self.existing else ('Ready to add' if row['is_camera'] else 'Not a camera')
            selectable=status=='Ready to add'
            for col,text in enumerate((row['model'],row['host'],row['kind'],status)):
                item=QTableWidgetItem(text)
                item.setToolTip(status)
                if not selectable:item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(i,col,item)
        count=len(self.rows)
        self.status.setText(f'{count} Tapo device'+('s' if count!=1 else '')+f" found on {data['network']}." if count else 'No Tapo devices responded. Check the selected adapter, firewall and camera power, or add the IP manually.')
        if data.get('warnings'):self.status.setText(self.status.text()+' '+' '.join(data['warnings']))
        self.selection_changed()

    def failed(self,message):
        self.finished_scan();self.status.setText(message)

    def cancelled(self):
        self.finished_scan();self.status.setText('Scan stopped. You can scan again.')

    def selection_changed(self):
        self.add_btn.setEnabled(bool(self.selected_devices()) and not self.running)

    def selected_devices(self):
        indices=sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        return [self.rows[i] for i in indices if i<len(self.rows) and self.rows[i]['is_camera'] and self.rows[i]['host'] not in self.existing]

    def reject(self):
        if self.running:
            self.close_pending=True;self.status.setText('Stopping scan before closing…')
            self.scan_btn.setEnabled(False);self.cancel_requested.emit()
        else:super().reject()

    def closeEvent(self,event):
        if self.running:self.reject();event.ignore()
        else:event.accept()


class MainWindow(QMainWindow):
    def __init__(self, demo=False):
        super().__init__()
        self.demo=demo
        self.setWindowTitle('Tapo Desk '+__version__ + (' · Demo' if demo else ''))
        self.resize(1440,900);self.setMinimumSize(1060,700)
        self.settings=QSettings('TapoDesk','TapoDesk')
        try:
            self.cameras=load_cameras()
        except UserError as e:
            self.cameras=[]
            QTimer.singleShot(0,lambda message=str(e): self.show_error(message))
        self.camera=None;self.rows=[];self.proc=None;self.pending=None;self.buffer=b''
        self.media_path=None;self.mode='recordings';self.busy=False;self.job_result=None
        self.wall_requested=False;self.active_operation=None
        self.streaming=False;self.stream_duration=0;self.audio_stalled=False
        self.position_time=time.monotonic();self.last_position=0
        self.live_recorder=LiveRecorder(self);self.close_after_recording=False
        self.preview_signatures={};self.selected_preview=None;self.row_lookup={}
        self.build_ui()
        self.thumbnail_loader=ThumbnailLoader(self);self.thumbnail_loader.ready.connect(self.thumbnail_ready)
        self.thumbnail_timer=QTimer(self);self.thumbnail_timer.setSingleShot(True)
        self.thumbnail_timer.setInterval(120);self.thumbnail_timer.timeout.connect(self.load_visible_thumbnails)
        self.table.verticalScrollBar().valueChanged.connect(self.schedule_thumbnails)
        self.table.verticalScrollBar().rangeChanged.connect(self.schedule_thumbnails)
        self.table.verticalScrollBar().sliderReleased.connect(self.schedule_thumbnails)
        self.table.viewport().installEventFilter(self)
        self.player=QMediaPlayer(self)
        self.audio=QAudioOutput(self);self.audio.setVolume(0.6)
        self.player.setAudioOutput(self.audio);self.player.setVideoOutput(self.video)
        self.player.durationChanged.connect(self.seek.setMaximum)
        self.player.positionChanged.connect(self.position_changed)
        self.player.playbackStateChanged.connect(self.playback_changed)
        self.player.errorOccurred.connect(self.media_error)
        self.player.mediaStatusChanged.connect(self.recording_status)
        self.recording_stream=RecordingPlayback(self);self.recording_stream.ready.connect(self.got_recording_stream)
        self.recording_stream.failed.connect(self.recording_stream_failed)
        self.audio_output.currentIndexChanged.connect(self.change_audio_output)
        self.change_audio_output()
        self.playback_watchdog=QTimer(self);self.playback_watchdog.setInterval(500)
        self.playback_watchdog.timeout.connect(self.check_playback)
        self.live_recorder.changed.connect(self.update_live_recording)
        self.live_recorder.completed.connect(self.live_recording_completed)
        self.live_recorder.failed.connect(self.live_recording_failed)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.live_deadline=QTimer(self);self.live_deadline.setSingleShot(True);self.live_deadline.setInterval(20000)
        self.live_deadline.timeout.connect(lambda:self.media_error(None, timeout=True))
        QShortcut(QKeySequence('Space'),self,activated=self.toggle_play)
        QShortcut(QKeySequence('Ctrl+R'),self,activated=self.refresh_dates)
        QShortcut(QKeySequence('Escape'),self,activated=self.escape_action)
        self.populate_cameras()
        if self.cameras:
            self.camera_list.setCurrentRow(0)
        else:
            self.status.setText("Add a camera or use Find cameras to get started.")
            self.update_controls()

    def build_ui(self):
        central=QWidget();self.setCentralWidget(central)
        shell=QHBoxLayout(central);shell.setContentsMargins(0,0,0,0);shell.setSpacing(0)
        rail=QFrame();rail.setObjectName('rail');rail.setFixedWidth(224)
        nav=QVBoxLayout(rail);nav.setContentsMargins(20,28,20,20);nav.setSpacing(16)
        nav.addWidget(label('Tapo Desk','brand'))
        nav.addWidget(label('Your cameras, locally.','muted'))
        nav.addSpacing(24);nav.addWidget(label('Cameras','section'))
        self.find_btn=button('Find cameras',self.find_cameras);nav.addWidget(self.find_btn)
        self.camera_list=QListWidget();self.camera_list.setAccessibleName('Cameras')
        self.camera_list.currentRowChanged.connect(self.select_camera);nav.addWidget(self.camera_list,1)
        self.add_btn=button('Add camera',self.add_camera);nav.addWidget(self.add_btn)
        self.edit_btn=button('Edit camera',self.edit_camera);nav.addWidget(self.edit_btn)
        self.credentials_btn=button('Credentials',self.credentials);nav.addWidget(self.credentials_btn)
        nav.addSpacing(12)
        nav.addWidget(button('Open downloads',self.open_downloads))
        self.cache_btn=button('Clear playback cache',self.clear_cache);nav.addWidget(self.cache_btn)
        nav.addWidget(label('Local network access\nUnofficial Tapo client','muted',True))
        shell.addWidget(rail)
        content=QWidget();base=QVBoxLayout(content);base.setContentsMargins(28,24,28,16);base.setSpacing(18)
        head=QHBoxLayout()
        titles=QVBoxLayout();titles.setSpacing(5)
        self.heading=label('Choose a camera','title');self.subheading=label('Add a camera to begin.','muted')
        titles.addWidget(self.heading);titles.addWidget(self.subheading);head.addLayout(titles,1)
        self.connection=label('Not connected','muted');head.addWidget(self.connection)
        base.addLayout(head)
        tabs=QHBoxLayout();tabs.setSpacing(8)
        self.live_tab=button('Live view',lambda:self.set_mode('live'),'tab')
        self.record_tab=button('Recordings',lambda:self.set_mode('recordings'),'tab')
        self.wall_tab=button('Camera wall',lambda:self.set_mode('wall'),'tab')
        group=QButtonGroup(self);group.setExclusive(True)
        for b in (self.live_tab,self.record_tab,self.wall_tab):
            b.setCheckable(True);group.addButton(b);tabs.addWidget(b)
        self.record_tab.setChecked(True);tabs.addStretch()
        self.audio_output=QComboBox();self.audio_output.setAccessibleName('Audio output device')
        self.audio_output.setToolTip('Audio output for live view and recordings. Choose another output if audio stalls.')
        self.audio_output.setFixedWidth(190);self.audio_output.addItem('Audio: system default',None)
        self.audio_devices=QMediaDevices.audioOutputs()
        chosen=self.settings.value('audio_output','')
        for device in self.audio_devices:
            key=bytes(device.id()).hex();self.audio_output.addItem(device.description(),key)
            if key==chosen:self.audio_output.setCurrentIndex(self.audio_output.count()-1)
        tabs.addWidget(self.audio_output)
        self.wall_quality=QComboBox();self.wall_quality.setAccessibleName('Camera wall video quality')
        self.wall_quality.addItem('Wall: smooth video','stream2');self.wall_quality.addItem('Wall: full detail','stream1')
        self.wall_quality.setCurrentIndex(1 if self.settings.value('wall_quality','stream2')=='stream1' else 0)
        self.wall_quality.setToolTip('Grid stream quality. Expanding a camera automatically uses full quality; returning restores this setting.')
        self.wall_quality.currentIndexChanged.connect(self.wall_quality_changed);self.wall_quality.hide()
        self.back_btn=button('Back to all cameras',self.wall_show_all);self.back_btn.hide();tabs.addWidget(self.back_btn)
        tabs.addWidget(self.wall_quality)
        self.refresh_btn=button('Refresh recordings',self.refresh_dates);tabs.addWidget(self.refresh_btn)
        base.addLayout(tabs)
        split=QSplitter(Qt.Orientation.Horizontal)
        viewer=QWidget();vl=QVBoxLayout(viewer);vl.setContentsMargins(0,0,12,0);vl.setSpacing(12)
        self.stage=QFrame();self.stage.setObjectName('stage');self.stage.setMinimumHeight(220)
        stage_l=QVBoxLayout(self.stage);stage_l.setContentsMargins(0,0,0,0)
        self.video_stack=QStackedWidget();stage_l.addWidget(self.video_stack)
        empty=QWidget();el=QVBoxLayout(empty);el.setContentsMargins(36,36,36,36);el.addStretch()
        self.stage_title=label('Find a moment','stageTitle');self.stage_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stage_hint=label('Choose a recording date, select a clip, then press Play.','stageHint',True)
        self.stage_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(self.stage_title);el.addWidget(self.stage_hint);el.addStretch()
        self.video_stack.addWidget(empty)
        self.video=QVideoWidget();self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video_stack.addWidget(self.video)
        self.wall=CameraWall(rtsp_url,live_error_message)
        self.wall.focus_changed.connect(self.wall_focus_changed);self.wall.status_changed.connect(self.wall_status_changed)
        self.video_stack.addWidget(self.wall)
        vl.addWidget(self.stage,1)
        self.caption=label('No clip selected','muted');vl.addWidget(self.caption)
        transport=QHBoxLayout()
        self.play_btn=button('Play',self.play_selected,'primary');transport.addWidget(self.play_btn)
        self.pause_btn=button('Pause',self.toggle_play);transport.addWidget(self.pause_btn)
        self.stop_btn=button('Stop',self.stop_media);transport.addWidget(self.stop_btn)
        self.live_record_btn=button('Record live',self.toggle_live_recording,'recordLive')
        self.live_record_btn.setToolTip('Save footage at the current live-view quality. Camera audio is saved even when viewing is muted.')
        transport.addWidget(self.live_record_btn)
        self.time_label=label('0:00 / 0:00','muted');transport.addWidget(self.time_label)
        transport.addStretch()
        self.mute_btn=button('Mute',self.toggle_mute);transport.addWidget(self.mute_btn)
        vl.addLayout(transport)
        self.capture_panel=QWidget();capture=QHBoxLayout(self.capture_panel);capture.setContentsMargins(0,0,0,0)
        self.capture_status=label('Save live footage to this laptop.','muted',True);capture.addWidget(self.capture_status,1)
        self.capture_open_btn=button('Open folder',self.open_live_recordings);capture.addWidget(self.capture_open_btn)
        self.capture_folder_btn=button('Save location…',self.choose_live_recording_folder);capture.addWidget(self.capture_folder_btn)
        vl.addWidget(self.capture_panel)
        self.seek=QSlider(Qt.Orientation.Horizontal);self.seek.setRange(0,0);self.seek.setAccessibleName('Playback position');vl.addWidget(self.seek)
        self.timeline_label=label('Recording activity · local time','muted');vl.addWidget(self.timeline_label)
        self.timeline=DayTimeline();vl.addWidget(self.timeline)
        split.addWidget(viewer)
        self.record_panel=QWidget();rl=QVBoxLayout(self.record_panel);rl.setContentsMargins(12,0,0,0);rl.setSpacing(8)
        rl.addWidget(label('On the microSD card','section'))
        self.date_combo=QComboBox();self.date_combo.setAccessibleName('Recording date');self.date_combo.setPlaceholderText('Load recording dates')
        self.date_combo.setMaxVisibleItems(10)
        self.date_combo.currentIndexChanged.connect(self.load_segments);rl.addWidget(self.date_combo)
        self.count_label=label('Refresh to find recordings.','muted');rl.addWidget(self.count_label)
        self.record_filter=QComboBox();self.record_filter.setAccessibleName('Filter recordings by detection')
        self.record_filter.addItem('All recordings',False);self.record_filter.addItem('With detections',True)
        self.record_filter.currentIndexChanged.connect(self.filter_recordings);rl.addWidget(self.record_filter)
        self.all_rows=[]
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['Preview','Start / length','Detection'])
        self.table.verticalHeader().hide();self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Fixed);self.table.setColumnWidth(0,96)
        self.table.setIconSize(QSize(80,45))
        self.table.setMinimumWidth(300);self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.itemSelectionChanged.connect(self.clip_selected)
        self.table.doubleClicked.connect(lambda _:self.play_selected())
        rl.addWidget(self.table,1)
        preview=QHBoxLayout();preview.setSpacing(12)
        self.thumbnail=label('No preview','muted',True);self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setFixedSize(120,68);self.thumbnail.setAccessibleName('Selected recording thumbnail')
        preview.addWidget(self.thumbnail)
        preview_actions=QVBoxLayout()
        self.thumbnail_btn=button('Retry preview',self.load_thumbnail);preview_actions.addWidget(self.thumbnail_btn)
        self.thumbnail_btn.setToolTip('Visible previews load automatically in the background. Retry a missing preview for the selected recording.')
        preview_actions.addStretch();preview.addLayout(preview_actions,1)
        rl.addLayout(preview)
        self.event_details=label('Select a recording to inspect its detections.','muted',True)
        self.event_details.setMaximumHeight(60);rl.addWidget(self.event_details)
        self.download_btn=button('Download selected clip',self.download_selected,'primary');rl.addWidget(self.download_btn)
        self.download_btn.setToolTip('Save a complete copy where you choose. Play streams the recording without saving a full clip.')
        split.addWidget(self.record_panel);split.setSizes([800,340]);split.setStretchFactor(0,1)
        base.addWidget(split,1)
        bottom=QHBoxLayout();self.status=label('Ready.','status',True);bottom.addWidget(self.status,1)
        self.cancel_btn=button('Cancel',self.cancel_job);self.cancel_btn.hide();bottom.addWidget(self.cancel_btn)
        base.addLayout(bottom)
        self.progress=QProgressBar();self.progress.setTextVisible(False);self.progress.hide();base.addWidget(self.progress)
        if self.demo:
            self.status.setText('Demo · illustrative recordings only. No camera or credential access.')
        shell.addWidget(content,1)

    def populate_cameras(self):
        self.camera_list.blockSignals(True);self.camera_list.clear()
        for c in self.cameras:
            item=QListWidgetItem(f'{c.name}\n{c.host}');item.setToolTip(f'{c.model} · {c.host}')
            self.camera_list.addItem(item)
        self.camera_list.blockSignals(False)

    def select_camera(self,index):
        if self.live_recorder.active:return
        if index<0 or index>=len(self.cameras):return
        if self.mode=='wall':
            self.set_wall_camera_context(self.cameras[index])
            if set(self.wall.tiles)=={c.id for c in self.cameras}:
                self.wall.set_focus(self.camera.id)
            else:self.set_mode('wall')
            return
        self.stop_media();self.camera=self.cameras[index];self.rows=[];self.media_path=None
        self.heading.setText(self.camera.name);self.subheading.setText(f'{self.camera.model}  ·  {self.camera.host}')
        self.connection.setText('Not connected' if not self.demo else 'Demo camera')
        self.date_combo.blockSignals(True);self.date_combo.clear();self.date_combo.blockSignals(False)
        self.fill_rows([]);self.count_label.setText('Refresh to find recordings.')
        self.set_mode(self.mode)
        if self.demo:self.demo_rows()

    def set_mode(self,mode):
        if self.busy or self.live_recorder.active:return
        self.stop_media();self.mode=mode
        self.live_tab.setChecked(mode=='live');self.record_tab.setChecked(mode=='recordings');self.wall_tab.setChecked(mode=='wall')
        self.back_btn.hide();self.wall_quality.setVisible(mode=='wall');self.time_label.setVisible(mode=='recordings')
        self.audio_output.setVisible(mode!='wall')
        self.mute_btn.setEnabled(mode!='wall');self.mute_btn.setText('Unmute focused' if mode=='wall' else ('Unmute' if self.audio.isMuted() else 'Mute'))
        self.record_panel.setVisible(mode=='recordings');self.timeline.setVisible(mode=='recordings')
        self.timeline_label.setVisible(mode=='recordings');self.refresh_btn.setVisible(mode=='recordings')
        self.seek.setVisible(mode=='recordings');self.pause_btn.setVisible(mode=='recordings')
        self.live_record_btn.setVisible(mode=='live');self.capture_panel.setVisible(mode=='live')
        self.play_btn.setText('Connect cameras' if mode=='wall' else ('Connect live' if mode=='live' else 'Play clip'))
        self.stage_title.setText('See what’s happening' if mode=='live' else 'Find a moment')
        self.stage_hint.setText('Connect using this camera’s Camera Account, saved in Credentials.' if mode=='live' else 'Choose a recording date, select a clip, then press Play.')
        self.caption.setText('Live view · ready to connect' if mode=='live' else 'No clip selected')
        if mode=='wall':
            self.video_stack.setCurrentIndex(2)
            if self.demo:self.wall.configure(self.cameras)
            else:self.start_wall()
        elif self.camera:
            self.heading.setText(self.camera.name);self.subheading.setText(f'{self.camera.model}  ·  {self.camera.host}')
        self.update_controls()

    def update_controls(self):
        available=self.camera is not None and not self.busy
        capturing=self.live_recorder.active
        for w in (self.camera_list,self.find_btn,self.add_btn,self.edit_btn,self.credentials_btn,self.live_tab,self.record_tab,self.wall_tab,self.wall_quality,self.refresh_btn,self.date_combo,self.table,self.record_filter,self.cache_btn):
            w.setEnabled(not self.busy and not capturing)
        self.play_btn.setEnabled((not self.busy and bool(self.cameras)) if self.mode=='wall' else (available and (self.mode=='live' or self.table.currentRow()>=0)))
        if capturing:self.play_btn.setEnabled(False)
        self.live_record_btn.setEnabled((capturing and self.live_recorder.state!='stopping') or
            (not capturing and available and not self.demo and self.mode=='live' and self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState and not self.player.source().isEmpty()))
        self.capture_folder_btn.setEnabled(not capturing)
        self.download_btn.setEnabled(available and self.table.currentRow()>=0 and self.mode=='recordings')
        row=self.table.currentRow()
        self.thumbnail_btn.setEnabled(available and self.mode=='recordings' and 0<=row<len(self.rows) and self.rows[row].get('recording_type')!='1')
        self.back_btn.setEnabled(not self.busy)
        if self.mode=='wall':self.mute_btn.setEnabled(not self.busy and self.wall.focused_id is not None)
        self.pause_btn.setEnabled(not self.busy and (self.media_path is not None or self.streaming))
        self.seek.setEnabled(not self.busy and not self.streaming and self.media_path is not None)
        self.cancel_btn.setVisible(self.busy)
        self.progress.setVisible(self.busy)
        if hasattr(self,'thumbnail_loader'):
            self.thumbnail_loader.set_enabled(not self.demo and not self.busy and self.mode=='recordings' and not self.streaming)
            self.schedule_thumbnails()

    def live_recording_folder(self):
        base=QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MoviesLocation) or str(Path.home()/'Videos')
        return Path(self.settings.value('live_recording_dir',str(Path(base)/'Tapo Desk')))

    def choose_live_recording_folder(self):
        if self.live_recorder.active:return
        folder=QFileDialog.getExistingDirectory(self,'Save live recordings',str(self.live_recording_folder()))
        if folder:
            self.settings.setValue('live_recording_dir',folder)
            self.capture_status.setText('Live recordings will be saved in '+Path(folder).name+'.')
            self.capture_status.setToolTip(folder)

    def open_live_recordings(self):
        folder=self.live_recording_folder()
        try:folder.mkdir(parents=True,exist_ok=True)
        except OSError:self.show_error('The live recording folder is not writable. Choose another Save location.');return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def toggle_live_recording(self):
        if self.live_recorder.active:self.live_recorder.stop();return
        if self.demo or self.mode!='live' or self.busy or not self.camera:return
        if self.player.playbackState()!=QMediaPlayer.PlaybackState.PlayingState or self.player.source().isEmpty():
            self.show_error('Connect live view before starting a recording.');return
        import re
        name=re.sub(r'[^\w-]+','-',self.camera.name,flags=re.ASCII).strip('-')[:40] or self.camera.id
        destination=self.live_recording_folder()/(name+'-'+datetime.now().strftime('%Y-%m-%d_%H-%M-%S')+'-'+uuid.uuid4().hex[:6]+'.mkv')
        self.capture_name=self.camera.name
        self.capture_status.setStyleSheet('');self.capture_status.setToolTip(str(destination))
        self.live_recorder.start(self.camera,destination)

    def update_live_recording(self):
        state=self.live_recorder.state;active=self.live_recorder.active
        self.live_record_btn.setText({'starting':'Cancel recording','recording':'Stop recording','stopping':'Finishing…'}.get(state,'Record live'))
        if self.live_record_btn.property('recording')!=active:
            self.live_record_btn.setProperty('recording',active)
            self.live_record_btn.style().unpolish(self.live_record_btn);self.live_record_btn.style().polish(self.live_record_btn)
        if state=='starting':self.capture_status.setText('Starting recording · '+self.capture_name)
        elif state=='recording':self.capture_status.setText('Recording · '+duration(self.live_recorder.seconds)+' · '+self.capture_name)
        elif state=='stopping':self.capture_status.setText('Finishing and saving recording…')
        self.update_controls()

    def live_recording_completed(self,data):
        if data.get('recorded'):
            path=Path(data['path']);prefix='Saved interrupted recording' if data.get('interrupted') else 'Saved recording'
            self.capture_status.setText(prefix+' · '+duration(data.get('seconds',0))+' · '+path.name)
            self.capture_status.setToolTip(str(path))
        else:self.capture_status.setText('Recording cancelled before footage arrived.')
        if self.close_after_recording:QTimer.singleShot(0,self.close)

    def live_recording_failed(self,message):
        self.capture_status.setText(message);self.capture_status.setStyleSheet('color: #a13e34;')
        # Keep a save failure visible instead of closing over potentially
        # unfinished footage. A subsequent close can exit normally.
        self.close_after_recording=False

    def show_error(self,text):
        self.status.setText(text);self.status.setStyleSheet('color: #a13e34;')

    def start_job(self,op,callback,error_callback=None,cancel_callback=None,**values):
        if self.busy:return
        if self.demo:
            self.status.setText('Demo mode: connect cameras in the normal application to use this action.')
            return
        self.busy=True;self.update_controls();self.cancel_btn.setEnabled(op not in ('store','store_shared_live','store_camera_live','migrate_shared_live','export'));self.status.setStyleSheet('');self.status.setText('Scanning local network…' if op=='discover' else 'Connecting…')
        self.progress.setRange(0,0)
        self.active_operation=op
        self.pending=callback;self.pending_error=error_callback;self.pending_cancel=cancel_callback;self.job_result=None;self.buffer=b''
        self.proc=QProcess(self)
        proc=self.proc
        proc.readyReadStandardOutput.connect(self.read_events)
        proc.readyReadStandardError.connect(lambda:proc.readAllStandardError())
        proc.finished.connect(self.job_finished)
        proc.errorOccurred.connect(self.job_process_error)
        payload={'op':op,'camera':asdict(self.camera) if self.camera else None,**values}
        executable,args=worker_command()
        proc.started.connect(lambda:proc.write((json.dumps(payload)+'\n').encode()))
        proc.start(executable,args)

    def read_events(self):
        if not self.proc:return
        self.buffer+=bytes(self.proc.readAllStandardOutput())
        while b'\n' in self.buffer:
            line,self.buffer=self.buffer.split(b'\n',1)
            try:event=json.loads(line)
            except (ValueError,UnicodeError):continue
            if event['event']=='progress':
                self.status.setText(event['action'])
                percent=event.get('percent')
                self.progress.setRange(0,100 if percent is not None else 0)
                if percent is not None:self.progress.setValue(percent)
            else:self.job_result=event

    def job_process_error(self,error):
        if error==QProcess.ProcessError.FailedToStart:
            self.job_finished(-1,QProcess.ExitStatus.CrashExit)

    def job_finished(self,*args):
        if not self.proc:return
        self.read_events();proc=self.proc;self.proc=None;self.busy=False;self.active_operation=None;self.update_controls();proc.deleteLater()
        event=self.job_result;callback=self.pending;self.pending=None
        error_callback=self.pending_error;cancel_callback=self.pending_cancel
        self.pending_error=self.pending_cancel=None
        if not event:
            message='The background worker stopped unexpectedly. Retry the operation.'
            self.show_error(message)
            if error_callback:error_callback(message)
            return
        if event['event']=='error':
            codes=event.get('codes',[])
            message=event['message']+(' Camera code: '+', '.join(codes) if codes else '')
            self.show_error(message)
            if error_callback:error_callback(message)
            return
        if event['event']=='cancelled':
            self.status.setText('Cancelled.')
            if cancel_callback:cancel_callback()
            return
        self.status.setText('Ready.')
        if callback:callback(event['data'])

    def cancel_job(self):
        if self.proc:
            self.proc.write(b'{"cancel":true}\n');self.status.setText('Cancelling… finishing the current camera request.')
            self.cancel_btn.setEnabled(False)
            QTimer.singleShot(500,lambda:self.cancel_btn.setEnabled(True))

    def refresh_dates(self):
        if self.live_recorder.active:return
        if self.mode=='wall':self.start_wall();return
        if not self.camera or self.busy:return
        self.stop_media()
        if self.demo:self.demo_rows();return
        self.start_job('dates',self.got_dates)

    def got_dates(self,data):
        self.connection.setText('Connected locally')
        self.date_combo.blockSignals(True);self.date_combo.clear()
        for d in reversed(data['dates']):
            date=datetime.strptime(d,'%Y%m%d');self.date_combo.addItem(date.strftime('%a, %d %b %Y'),d)
        if data['dates']:self.date_combo.setCurrentIndex(0)
        self.date_combo.blockSignals(False)
        if data['dates']:self.load_segments()
        else:self.fill_rows([]);self.count_label.setText('No recording dates found. Check the microSD card in Tapo.')

    def load_segments(self,*args):
        if not self.camera or self.busy or not self.date_combo.currentData():return
        if self.demo:return
        self.thumbnail_loader.reset();self.stop_media();self.fill_rows([])
        self.count_label.setText('Loading recordings…')
        self.start_job('segments',self.got_segments,date=self.date_combo.currentData())

    def got_segments(self,data):
        self.fill_rows(data['segments'])
        if not data.get('events_available'):
            self.status.setText('Detailed detection times unavailable. Recording markers and playback remain available.')
        elif not data.get('events_complete',True):
            self.status.setText('Camera event limit reached. Some detection details may be missing.')
        else:self.status.setText(f'{data.get("event_count",0)} camera detections found. Event type codes are reported by the camera; no AI summary is generated.')

    def filter_recordings(self,*args):
        self.stop_media()
        rows=[row for row in self.all_rows if has_detection(row)] if self.record_filter.currentData() else self.all_rows
        self.fill_rows(rows,filtered=True)

    def fill_rows(self,rows,filtered=False):
        if hasattr(self,'thumbnail_loader'):
            self.thumbnail_loader.set_context(self.camera,self.date_combo.currentData())
        if not filtered:
            self.all_rows=rows
            if self.record_filter.currentData():rows=[row for row in rows if has_detection(row)]
        self.rows=rows;self.media_path=None;self.table.blockSignals(True);self.table.setUpdatesEnabled(False);self.table.setRowCount(len(rows))
        self.table.clearSelection()
        self.row_lookup={(r['start'],r['end']):i for i,r in enumerate(rows)}
        self.preview_signatures={};self.selected_preview=None
        self.thumbnail.clear();self.thumbnail.setText('No preview')
        self.event_details.setText('Select a recording to inspect its detections.');self.event_details.setToolTip('')
        for row,r in enumerate(rows):
            for col,value in enumerate(('Continuous' if r.get('recording_type')=='1' else 'Pending',stamp(r['start'])+'\n'+duration(r['end']-r['start']),detection_label(r))):
                item=QTableWidgetItem(value)
                item.setToolTip(datetime.fromtimestamp(r['start'], timezone.utc).astimezone().isoformat()+' → '+datetime.fromtimestamp(r['end'], timezone.utc).astimezone().isoformat())
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row,col,item)
        self.timeline.set_rows(rows)
        self.table.blockSignals(False);self.table.setUpdatesEnabled(True)
        self.count_label.setText(f'{len(rows)} recordings · times shown locally' if rows else ('No recordings with detections for this date.' if self.record_filter.currentData() else 'No recordings for this date.'))
        if rows:self.table.selectRow(0)
        self.update_controls()

    def clip_selected(self):
        if self.mode=='wall':return
        # The stage must never show one clip with another clip's identity.
        self.stop_media()
        self.selected_preview=None
        row=self.table.currentRow();self.timeline.active=row;self.timeline.update()
        if 0<=row<len(self.rows):
            r=self.rows[row];self.caption.setText(f'{stamp(r["start"])} – {stamp(r["end"])}  ·  {duration(r["end"]-r["start"])}  ·  {self.camera.name}')
            self.thumbnail.clear();self.thumbnail.setText('Continuous recording' if r.get('recording_type')=='1' else 'Loading automatically')
            details=[f'{stamp(e["start"])}–{stamp(e["end"])} · Camera type {e["type"] if e["type"] is not None else "unknown"}' for e in r.get('events',[])]
            self.event_details.setToolTip('\n'.join(details))
            self.event_details.setText('\n'.join(details[:2])+ (f'\n+ {len(details)-2} more (hover for all)' if len(details)>2 else '') if details else ('Detection recording; exact event times not reported.' if has_detection(r) else 'No detailed detections reported for this recording.'))
        self.update_controls()

    def eventFilter(self,watched,event):
        if watched is self.table.viewport() and event.type() in (QEvent.Type.Resize,QEvent.Type.Show):
            self.schedule_thumbnails()
        return super().eventFilter(watched,event)

    def schedule_thumbnails(self,*args):
        # Throttle instead of restarting a debounce on every wheel/touchpad event.
        if self.mode!='recordings':return
        if hasattr(self,'thumbnail_timer') and not self.thumbnail_timer.isActive():self.thumbnail_timer.start()

    def visible_recordings(self):
        if not self.rows or not self.table.isVisible():return []
        first=self.table.rowAt(0)
        if first<0:return []
        last=self.table.rowAt(max(0,self.table.viewport().height()-1))
        if last<0:last=len(self.rows)-1
        return self.rows[first:min(last+1,len(self.rows))]

    def load_visible_thumbnails(self):
        if self.mode!='recordings' or self.demo or self.busy:return
        loader=self.thumbnail_loader
        loader.set_context(self.camera,self.date_combo.currentData())
        visible=self.visible_recordings()
        for recording in visible:
            data=loader.cached(recording)
            if data is not None:self.thumbnail_ready(loader.key(recording),data)
        last=self.table.rowAt(max(0,self.table.viewport().height()-1))
        ahead=self.rows[last+1:last+1+len(visible)] if last>=0 else []
        loader.set_visible(visible,ahead=ahead)

    def thumbnail_ready(self,key,data):
        if not self.camera or key[:3]!=(self.camera.id,self.camera.host,self.date_combo.currentData()):return
        row=self.row_lookup.get(key[-2:])
        if row is None:return
        signature=(data.get('path'),bool(data.get('available')),bool(data.get('deferred')))
        paint_row=self.preview_signatures.get(key)!=signature
        paint_selected=row==self.table.currentRow() and self.selected_preview!=(key,signature)
        if not paint_row and not paint_selected:return
        item=self.table.item(row,0)
        pixmap=QPixmap(data['path']) if data.get('available') else QPixmap()
        if paint_row and not pixmap.isNull():
            item.setIcon(QIcon(pixmap.scaled(80,45,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)))
            item.setText('');item.setToolTip('Camera recording thumbnail')
        elif paint_row:
            item.setIcon(QIcon());item.setText('Preparing…' if data.get('deferred') else 'No preview');item.setToolTip('Preparing a preview from the recording.' if data.get('deferred') else 'The camera returned no thumbnail. Playback and download are still available.')
        self.preview_signatures[key]=signature
        if paint_selected:
            self.selected_preview=(key,signature)
            self.thumbnail.clear()
            if pixmap.isNull():self.thumbnail.setText('Preparing preview…' if data.get('deferred') else 'No preview available')
            else:self.thumbnail.setPixmap(pixmap.scaled(self.thumbnail.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))

    def load_thumbnail(self):
        row=self.table.currentRow()
        if self.busy or not self.camera or not 0<=row<len(self.rows):return
        self.thumbnail_loader.set_context(self.camera,self.date_combo.currentData())
        self.preview_signatures.pop(self.thumbnail_loader.key(self.rows[row]),None);self.selected_preview=None
        self.thumbnail.clear();self.thumbnail.setText('Retrying preview…')
        self.thumbnail_loader.retry(self.rows[row])

    def play_selected(self):
        if self.live_recorder.active:return
        if self.mode=='wall':self.start_wall();return
        if self.busy or not self.camera:return
        self.stop_media()
        if self.mode=='live':
            self.start_job('live',self.got_live);return
        row=self.table.currentRow()
        if row<0:return
        r=self.rows[row]
        if self.demo:return
        self.streaming=True;self.stream_duration=(r['end']-r['start'])*1000
        self.position_time=time.monotonic();self.last_position=0
        self.recording_stream.start(self.camera,self.date_combo.currentData(),r['start'],r['end'])
        self.status.setText('Connecting to recorded playback…');self.update_controls()

    def got_recording_stream(self,url):
        if not self.streaming or self.mode!='recordings':return
        self.player.setSource(QUrl(url));self.player.play()
        self.status.setText('Streaming recording from camera. Download saves a complete copy.')
        self.position_time=time.monotonic();self.live_deadline.start()

    def recording_stream_failed(self,message):
        if not self.streaming:return
        self.stop_media();self.show_error(message)

    def recording_status(self,status):
        if status==QMediaPlayer.MediaStatus.EndOfMedia and self.streaming:
            self.streaming=False;self.recording_stream.stop();self.status.setText('Recording ended.');self.update_controls()

    def got_live(self,data):
        self.media_path=None;self.player.setSource(rtsp_url(data));self.player.play()
        self.status.setText('Connecting to live view…');self.connection.setText('Connecting live…')
        self.live_deadline.start()

    def play_file(self,data):
        self.streaming=False;self.position_time=time.monotonic();self.last_position=0
        self.media_path=data['path'];self.player.setSource(QUrl.fromLocalFile(self.media_path));self.player.play()
        self.status.setText('Playing local recording.');self.update_controls()

    def playback_changed(self,state):
        if hasattr(self,'playback_watchdog'):
            if state==QMediaPlayer.PlaybackState.PlayingState:self.playback_watchdog.start()
            else:self.playback_watchdog.stop()
        if self.mode=='wall':return
        if state==QMediaPlayer.PlaybackState.PlayingState:
            self.video_stack.setCurrentIndex(1);self.live_deadline.stop()
            self.connection.setText('Live · connected' if self.mode=='live' else 'Playing recording')
            self.pause_btn.setText('Pause')
        elif state==QMediaPlayer.PlaybackState.PausedState:self.pause_btn.setText('Resume')
        self.update_controls()

    def media_error(self,error=None,message='',*,timeout=False):
        if self.mode=='wall':return
        self.stop_media()
        text=live_error_message(message,timeout=timeout) if self.mode=='live' else 'This clip could not play. Download it and open it in VLC, or check the Qt multimedia installation.'
        self.show_error(text)

    def position_changed(self,pos):
        if pos!=self.last_position:self.last_position=pos;self.position_time=time.monotonic()
        if not self.seek.isSliderDown():self.seek.setValue(pos)
        total=self.stream_duration if self.streaming else self.player.duration()
        self.time_label.setText(f'{duration(pos/1000)} / {duration(total/1000)}')

    def change_audio_output(self,*args):
        key=self.audio_output.currentData();device=QMediaDevices.defaultAudioOutput()
        for candidate in self.audio_devices:
            if bytes(candidate.id()).hex()==key:device=candidate;break
        self.audio.setDevice(device);self.settings.setValue('audio_output',key or '')
        self.audio_stalled=False;self.audio.setMuted(False);self.player.setAudioOutput(self.audio)
        if hasattr(self,'mute_btn'):self.mute_btn.setText('Mute')
        self.position_time=time.monotonic()

    def check_playback(self):
        if self.mode=='wall' or self.player.playbackState()!=QMediaPlayer.PlaybackState.PlayingState:return
        if self.player.position()<=0 or time.monotonic()-self.position_time<3:return
        if self.player.audioOutput() is not None and not self.audio_stalled:
            self.audio_stalled=True;self.player.setAudioOutput(None);self.audio.setMuted(True)
            self.mute_btn.setText('Unmute');self.position_time=time.monotonic()
            self.status.setText('Audio output stalled; continuing video muted. Choose another Audio output to restore sound.')

    def toggle_play(self):
        if self.mode=='wall':return
        if self.busy:return
        if self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState:self.player.pause()
        elif not self.player.source().isEmpty():self.player.play()

    def toggle_mute(self):
        if self.mode=='wall':
            self.wall.toggle_focused_audio();self.wall_status_changed();return
        self.audio.setMuted(not self.audio.isMuted());self.mute_btn.setText('Unmute' if self.audio.isMuted() else 'Mute')
        self.player.setAudioOutput(None if self.audio.isMuted() else self.audio)
        self.audio_stalled=False;self.position_time=time.monotonic()

    def stop_media(self):
        if hasattr(self,'live_recorder'):self.live_recorder.stop()
        self.streaming=False
        if hasattr(self,'recording_stream'):self.recording_stream.stop()
        self.wall_requested=False
        if self.mode=='wall' and self.busy and self.active_operation=='live_wall':self.cancel_job()
        if hasattr(self,'player'):
            self.live_deadline.stop();self.player.stop();self.player.setSource(QUrl())
            self.wall.stop_all()
            self.video_stack.setCurrentIndex(2 if self.mode=='wall' else 0);self.connection.setText('Stopped' if self.mode=='wall' else 'Ready')
            self.pause_btn.setText('Pause');self.seek.setValue(0);self.time_label.setText('0:00 / 0:00')
            self.media_path=None;self.update_controls()

    def escape_action(self):
        if self.mode=='wall' and self.wall.focused_id and not self.busy:self.wall.show_all()
        else:self.stop_media()

    def set_wall_camera_context(self,camera):
        if self.camera is not camera:
            self.camera=camera;self.rows=[];self.media_path=None
            self.date_combo.blockSignals(True);self.date_combo.clear();self.date_combo.blockSignals(False)
            self.fill_rows([])
        index=next((i for i,c in enumerate(self.cameras) if c.id==camera.id),-1)
        self.camera_list.blockSignals(True);self.camera_list.setCurrentRow(index);self.camera_list.blockSignals(False)

    def wall_focus_changed(self,camera_id):
        if self.mode!='wall':return
        self.back_btn.setVisible(camera_id is not None)
        if camera_id:
            camera=next(c for c in self.cameras if c.id==camera_id)
            self.set_wall_camera_context(camera)
            self.heading.setText(camera.name);self.subheading.setText(camera.host+' · focused live view')
            self.caption.setText('Double-click again, press Esc, or choose Back to all cameras.')
        else:
            self.heading.setText('All cameras');self.subheading.setText(f'{len(self.cameras)} cameras · live view')
            self.caption.setText('Double-click a tile to focus. Press Enter when a tile has keyboard focus. Audio is muted by default.')
        self.wall_status_changed();self.update_controls()

    def wall_status_changed(self):
        if self.mode!='wall':return
        self.connection.setText(self.wall.summary())
        muted=not self.wall.focused_id or self.wall.tiles[self.wall.focused_id].audio.isMuted()
        self.mute_btn.setText('Unmute focused' if muted else 'Mute focused')

    def wall_show_all(self):
        if self.mode=='wall':self.wall.show_all()

    def start_wall(self):
        if self.busy:return
        if self.mode!='wall':self.set_mode('wall');return
        if not self.cameras:self.show_error('Add a camera to start the camera wall.');return
        self.stop_media()
        # Reconfigure to incorporate edits and newly added cameras before connecting.
        self.wall.configure(self.cameras)
        if self.demo:
            self.status.setText('Demo camera wall · no camera connections.');return
        self.wall_requested=True
        self.start_job('live_wall',self.got_wall,cameras=[{**asdict(c),'stream':self.wall_quality.currentData()} for c in self.cameras])

    def wall_quality_changed(self,*args):
        self.settings.setValue('wall_quality',self.wall_quality.currentData())
        if self.mode=='wall' and not self.busy:self.start_wall()

    def got_wall(self,data):
        if not self.wall_requested or self.mode!='wall':return
        self.video_stack.setCurrentIndex(2);self.wall.connect_streams(data)
        self.status.setText('Camera wall · double-click a tile to focus. Stop disconnects all cameras.')

    def download_selected(self):
        row=self.table.currentRow()
        if row<0 or self.busy:return
        self.stop_media();r=self.rows[row];date=self.date_combo.currentData()
        folder=self.settings.value('download_dir',str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation))/'Tapo Desk'))
        name=f'{self.camera.name}_{date}_{r["start"]}-{r["end"]}.mp4'
        name=''.join(c if c.isalnum() or c in '._-' else '_' for c in name)
        dest,_=QFileDialog.getSaveFileName(self,'Save recording',str(Path(folder)/name),'MP4 video (*.mp4)')
        if not dest:return
        if not dest.lower().endswith('.mp4'):dest+='.mp4'
        if Path(dest).exists():self.show_error('That file already exists. Choose a new name to keep both copies.');return
        self.settings.setValue('download_dir',str(Path(dest).parent))
        def prepared(data):
            self.start_job('export',lambda d:self.status.setText('Saved '+d['path']),source=data['path'],destination=dest)
        self.start_job('download',prepared,date=date,start=r['start'],end=r['end'])

    def find_cameras(self):
        if self.busy:return
        self.stop_media()
        dialog=DiscoveryDialog(self.cameras,self,demo=self.demo)
        dialog.scan_requested.connect(lambda network,address:self.start_job('discover',dialog.got_results,
            error_callback=dialog.failed,cancel_callback=dialog.cancelled,network=network,address=address))
        dialog.cancel_requested.connect(self.cancel_job)
        if dialog.exec():
            self.add_discovered(dialog.selected_devices())
        dialog.deleteLater()

    def add_discovered(self,devices):
        existing={c.host for c in self.cameras};new=[]
        for row in devices:
            if not row['is_camera'] or row['host'] in existing:continue
            camera=Camera.from_dict({'id':uuid.uuid4().hex[:12],'name':row['model'],
                                     'host':row['host'],'model':row['model']})
            new.append(camera);existing.add(camera.host)
        if not new:return
        # Save the candidate list before replacing the current visible profiles.
        try:save_cameras(self.cameras+new)
        except Exception:
            self.show_error('Discovered cameras could not be saved. Check folder permissions and retry.');return
        self.cameras.extend(new);self.populate_cameras();self.camera_list.setCurrentRow(len(self.cameras)-len(new))
        self.status.setText(f'Added {len(new)} camera'+('s.' if len(new)!=1 else '.'))

    def add_camera(self):
        if self.busy:return
        dialog=CameraDialog(None,self)
        if dialog.exec():
            self.cameras.append(dialog.camera)
            self.persist();self.populate_cameras();self.camera_list.setCurrentRow(len(self.cameras)-1)

    def edit_camera(self):
        if not self.camera or self.busy:return
        i=self.camera_list.currentRow();dialog=CameraDialog(self.camera,self)
        if dialog.exec():
            self.cameras[i]=dialog.camera;self.persist();self.populate_cameras()
            if self.mode=='wall':self.set_wall_camera_context(dialog.camera);self.set_mode('wall')
            else:self.camera_list.setCurrentRow(i)

    def persist(self):
        try:save_cameras(self.cameras)
        except Exception:
            self.show_error('Camera settings could not be saved. Check folder permissions.');return False
        return True

    def credentials(self):
        if not self.camera or self.busy:return
        try:dialog=CredentialsDialog(self.camera,self)
        except UserError as exc:self.show_error(str(exc));return
        if not dialog.exec():return
        cloud=dialog.cloud.text();password=dialog.password.text();username=dialog.user.text().strip()
        shared=dialog.use_shared.isChecked()
        dialog.cloud.clear();dialog.password.clear();dialog.drafts.clear();dialog.deleteLater()
        camera=self.camera
        def complete(_=None):
            camera.use_shared_credentials=shared
            if not shared:camera.username=username
            if self.persist():
                self.status.setText(credential_save_message(bool(cloud),shared,bool(username)))
        def save_live(_=None):
            if shared and username:
                self.start_job('store_shared_live',complete,username=username,password=password)
            elif not shared:
                self.start_job('store_camera_live',complete,password=password,camera_id=camera.id)
            else:complete()
        if cloud:self.start_job('store',save_live,kind='cloud',password=cloud)
        else:save_live()

    def clear_cache(self):
        if self.busy:return
        reply=QMessageBox.question(self,'Clear playback cache','Remove prepared playback copies and recording thumbnails? Exported downloads are kept.')
        if reply!=QMessageBox.StandardButton.Yes:return
        self.stop_media();self.media_path=None;self.thumbnail.clear();self.thumbnail.setText('No preview')
        self.thumbnail_loader.reset()
        import shutil
        try:
            for path in cache_dir().iterdir():
                if path.is_dir():shutil.rmtree(path)
            self.fill_rows(self.all_rows);self.status.setText('Playback cache cleared.');self.update_controls()
        except OSError:self.show_error('Some cache files are in use. Stop playback and retry.')

    def open_downloads(self):
        folder=Path(self.settings.value('download_dir',str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation))/'Tapo Desk')))
        folder.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def demo_rows(self):
        dt=datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)
        self.date_combo.blockSignals(True);self.date_combo.clear()
        self.date_combo.addItem(dt.strftime('%a, %d %b %Y'),dt.strftime('%Y%m%d'));self.date_combo.setCurrentIndex(0);self.date_combo.blockSignals(False)
        starts=[7*3600+14*60,8*3600+6*60,9*3600+32*60,10*3600+7*60+32,12*3600+3*60,13*3600+11*60,15*3600+42*60]
        rows=[{'start':int(dt.timestamp())+s,'end':int(dt.timestamp())+s+length} for s,length in zip(starts,[70,96,42,40,82,70,38])]
        for index,row in enumerate(rows):
            row['recording_type']='1' if index==2 else '2'
            row['events']=[] if index==2 else [{'start':row['start']+5,'end':row['start']+18,'type':2,'flags':None}]
        self.fill_rows(rows);self.status.setText('Demo · illustrative recordings only. No camera or credential access.')

    def closeEvent(self,event):
        if self.live_recorder.active:
            self.close_after_recording=True;self.live_recorder.stop();event.ignore();return
        if self.busy:
            self.cancel_job();self.show_error('Cancelling the active operation. Close the window again once it finishes.')
            event.ignore();return
        self.stop_media();self.thumbnail_timer.stop();self.thumbnail_loader.set_enabled(False);self.thumbnail_loader.reset();self.thumbnail_loader.cancel_active();event.accept()


def main():
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('TapoDesk.Desktop')
        ctypes.windll.kernel32.CreateMutexW.restype=ctypes.c_void_p
        app_mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'TapoDesk.Desktop')
        # Keep the named object until process exit so upgrades/uninstall cannot
        # replace files while this app is watching or finalizing a recording.
    # Qt's FFmpeg backend can write authenticated stream URLs to native stderr.
    # Drop native diagnostics as well as Qt messages; errors surface as safe UI copy.
    try:
        with open(os.devnull, 'w') as null:
            os.dup2(null.fileno(), 2)
    except OSError:
        pass
    qInstallMessageHandler(lambda *_:None)
    app=QApplication(sys.argv);app.setApplicationName('Tapo Desk');app.setOrganizationName('TapoDesk')
    assets=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'assets'
    app.setWindowIcon(QIcon(str(assets/'tapo-desk.ico')))
    for name in ('Lato-Regular.ttf','Lato-Bold.ttf'):
        QFontDatabase.addApplicationFont(str(assets/name))
    app.setStyle('Fusion');app.setStyleSheet(STYLE)
    smoke='--smoke-test' in sys.argv
    window=MainWindow('--demo' in sys.argv or smoke);window.show()
    if smoke and '--smoke-report' in sys.argv:
        from .processes import probe_startup
        probe_startup(app,sys.argv[sys.argv.index('--smoke-report')+1])
    elif smoke:QTimer.singleShot(1500,app.quit)
    sys.exit(app.exec())
