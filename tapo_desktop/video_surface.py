"""Bounded video presentation for multi-camera walls, without native video windows."""
import threading
from PySide6.QtCore import Qt,QSize,QRect,QTimer
from PySide6.QtGui import QImage,QPainter,QColor
from PySide6.QtWidgets import QWidget,QSizePolicy
from PySide6.QtMultimedia import QVideoSink,QVideoFrame


class VideoSurface(QWidget):
    """Keep the latest frame only; paint at most ten times a second."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._lock=threading.Lock();self._latest=None;self._image=QImage();self._accepting=False
        self.presented_frames=0
        self._sink=QVideoSink(self)
        # Retain only the newest frame; image conversion and painting are rate limited.
        self._sink.videoFrameChanged.connect(self.receive_frame)
        self._timer=QTimer(self);self._timer.setInterval(100)
        self._timer.timeout.connect(self.present_latest)

    def videoSink(self):return self._sink

    def sizeHint(self):return QSize(320,180)
    def minimumSizeHint(self):return QSize(1,1)

    def receive_frame(self,frame):
        with self._lock:
            previous=self._latest
            self._latest=QVideoFrame(frame) if self._accepting and frame.isValid() else None
        del previous

    def present_latest(self):
        if not self.isVisible():return
        with self._lock:
            frame=self._latest;self._latest=None
        if frame is None:return
        image=frame.toImage()
        if image.isNull():return
        self._image=image;self.presented_frames+=1;self.update()

    def start_capture(self):
        with self._lock:self._accepting=True

    def clear(self):
        with self._lock:
            self._accepting=False
            previous=self._latest;self._latest=None
        del previous
        self._image=QImage();self.presented_frames=0
        self._sink.setVideoFrame(QVideoFrame())
        self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#121b18'))
        if not self._image.isNull():
            size=self._image.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
            target=QRect((self.width()-size.width())//2,(self.height()-size.height())//2,size.width(),size.height())
            painter.drawImage(target,self._image)
        painter.end()

    def showEvent(self,event):
        super().showEvent(event);self._timer.start()

    def hideEvent(self,event):
        self._timer.stop();super().hideEvent(event)
