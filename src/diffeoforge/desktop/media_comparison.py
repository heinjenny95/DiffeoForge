"""Side-by-side media without recomputing analysis or blocking the GUI."""

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QGridLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget


class ComparisonGrid(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumHeight(320)
        self.reset()

    def reset(self):
        old = self.takeWidget()
        if old is not None:
            old.deleteLater()
        page = QWidget()
        self.grid = QGridLayout(page)
        self.setWidget(page)
        self.cells = []

    def add(self, title, content):
        cell = QWidget()
        layout = QVBoxLayout(cell)
        label = QLabel(title)
        label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(label)
        layout.addWidget(content, 1)
        index = len(self.cells)
        self.grid.addWidget(cell, index // 3, index % 3)
        self.cells.append(content)


class VideoComparison(ComparisonGrid):
    position_changed = Signal(int)
    duration_changed = Signal(int)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.players = []
        self.clock = QTimer(self)
        self.clock.setInterval(100)
        self.clock.timeout.connect(self._sync)

    def clear(self):
        self.clock.stop()
        for player in self.players:
            player.stop()
            player.setSource(QUrl())
            player.deleteLater()
        self.players = []
        self.reset()

    def load(self, entries):
        self.clear()
        for title, path in entries:
            image = QLabel()
            image.setMinimumSize(260, 190)
            image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.add(title, image)
            player = QMediaPlayer(self)
            player.setLoops(QMediaPlayer.Loops.Infinite)
            sink = QVideoSink(player)
            player.setVideoSink(sink)

            def frame_changed(frame, label=image):
                if frame.isValid():
                    label.setPixmap(
                        QPixmap.fromImage(frame.toImage()).scaled(
                            label.size(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )

            sink.videoFrameChanged.connect(frame_changed)
            player.errorOccurred.connect(lambda _code, text: self.failed.emit(text))
            self.players.append(player)
            if len(self.players) == 1:
                player.positionChanged.connect(self.position_changed.emit)
                player.durationChanged.connect(self.duration_changed.emit)
            player.setSource(QUrl.fromLocalFile(str(path)))

    def seek(self, position):
        for player in self.players:
            player.setPosition(position)

    def pause(self):
        self.clock.stop()
        for player in self.players:
            player.pause()

    def toggle(self):
        if not self.players:
            return
        if self.players[0].playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.seek(self.players[0].position())
            for player in self.players:
                player.play()
            self.clock.start()

    def _sync(self):
        if not self.players:
            return
        position = self.players[0].position()
        for player in self.players[1:]:
            if abs(player.position() - position) > 120:
                player.setPosition(position)
