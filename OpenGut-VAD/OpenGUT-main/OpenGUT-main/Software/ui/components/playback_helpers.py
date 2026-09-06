"""Reusable playback helpers for time formatting, controls, and playhead overlays."""

import importlib

from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QSlider, QLabel
from PyQt6.QtCore import Qt, QUrl
import pyqtgraph as pg
from const import AUTO_FOLLOW_BUTTON_TEXT, PLAY_BUTTON_TEXT, TIME_LABEL_DEFAULT


QMediaPlayer = None
QAudioOutput = None
QAudioDevice = None
QMediaDevices = None
try:
    qt_multimedia = importlib.import_module("PyQt6.QtMultimedia")
    QMediaPlayer = qt_multimedia.QMediaPlayer
    QAudioOutput = qt_multimedia.QAudioOutput
    QAudioDevice = qt_multimedia.QAudioDevice
    QMediaDevices = qt_multimedia.QMediaDevices
except Exception:
    pass


def format_mm_ss(seconds):
    """Format seconds to MM:SS."""
    value = max(0, int(seconds))
    minutes = value // 60
    secs = value % 60
    return f"{minutes:02d}:{secs:02d}"


class PlayheadOverlayManager:
    """Manage playhead lines for one or two plots: playback position (inverted color) and seekbar position (yellow)."""

    def __init__(self, left_plot, right_plot):
        self.left_plot = left_plot
        self.right_plot = right_plot
        # Playback position (inverted color - white on dark, dark on light)
        self.playhead_left = None
        self.playhead_right = None
        # Seekbar position (yellow - shows where user is dragging the seekbar)
        self.seekbar_left = None
        self.seekbar_right = None

    def create(self, include_right=True, position_sec=0.0):
        # Playback position: inverted color (white by default, will be updated dynamically)
        playhead_pen = pg.mkPen((255, 255, 255), width=2)
        self.playhead_left = pg.InfiniteLine(pos=position_sec, angle=90, movable=False, pen=playhead_pen)
        self.left_plot.addItem(self.playhead_left)

        self.playhead_right = pg.InfiniteLine(pos=position_sec, angle=90, movable=False, pen=playhead_pen)
        if include_right:
            self.right_plot.addItem(self.playhead_right)
        
        # Seekbar position: yellow line to show where seekbar is pointing
        seekbar_pen = pg.mkPen((255, 230, 80), width=2)
        self.seekbar_left = pg.InfiniteLine(pos=position_sec, angle=90, movable=False, pen=seekbar_pen)
        self.left_plot.addItem(self.seekbar_left)
        
        self.seekbar_right = pg.InfiniteLine(pos=position_sec, angle=90, movable=False, pen=seekbar_pen)
        if include_right:
            self.right_plot.addItem(self.seekbar_right)

    def update(self, position_sec, include_right=True):
        """Update playback position (inverted color line)."""
        if self.playhead_left is not None:
            self.playhead_left.setValue(position_sec)
        if self.playhead_right is not None and include_right:
            self.playhead_right.setValue(position_sec)
    
    def update_seekbar(self, position_sec, include_right=True):
        """Update seekbar position (yellow line showing where user is dragging)."""
        if self.seekbar_left is not None:
            self.seekbar_left.setValue(position_sec)
        if self.seekbar_right is not None and include_right:
            self.seekbar_right.setValue(position_sec)


class PlaybackControlsManager:
    """Own playback GUI controls and multimedia player instance."""

    def __init__(
        self,
        parent,
        on_toggle,
        on_seek_pressed,
        on_seek_moved,
        on_seek_released,
        on_position_changed,
        on_state_changed,
    ):
        self.layout = QHBoxLayout()

        self.play_pause_btn = QPushButton(PLAY_BUTTON_TEXT)
        self.play_pause_btn.setEnabled(False)
        self.play_pause_btn.clicked.connect(on_toggle)
        self.layout.addWidget(self.play_pause_btn)

        self.auto_follow_btn = QPushButton(AUTO_FOLLOW_BUTTON_TEXT)
        self.auto_follow_btn.setCheckable(True)
        self.auto_follow_btn.setChecked(True)
        self.layout.addWidget(self.auto_follow_btn)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setEnabled(False)
        self.seek_slider.sliderPressed.connect(on_seek_pressed)
        self.seek_slider.sliderMoved.connect(on_seek_moved)
        self.seek_slider.sliderReleased.connect(on_seek_released)
        self.layout.addWidget(self.seek_slider, 1)

        self.time_label = QLabel(TIME_LABEL_DEFAULT)
        self.layout.addWidget(self.time_label)

        self.audio_output = None
        self.player = None
        self.playback_available = QMediaPlayer is not None and QAudioOutput is not None
        if self.playback_available:
            self.audio_output = QAudioOutput(parent)
            try:
                self.audio_output.setMuted(False)
                self.audio_output.setVolume(1.0)
            except Exception:
                pass
            self.player = QMediaPlayer(parent)
            self.player.setAudioOutput(self.audio_output)
            self.player.positionChanged.connect(on_position_changed)
            self.player.playbackStateChanged.connect(on_state_changed)

    def configure_duration(self, duration_sec):
        """Set seek slider range from audio duration and reset position."""
        self.seek_slider.setRange(0, int(duration_sec * 1000))
        self.seek_slider.setValue(0)
        self.seek_slider.setEnabled(True)
        self.play_pause_btn.setEnabled(True)

    def set_source(self, file_path):
        """Load media source into player if playback backend is available."""
        if self.player is None:
            return
        # Ensure output is audible after cleanup paths that temporarily mute it.
        if self.audio_output is not None:
            try:
                self.audio_output.setMuted(False)
                self.audio_output.setVolume(1.0)
            except Exception:
                pass
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(file_path))

    def set_time_label(self, text):
        self.time_label.setText(text)

    def set_play_button_text(self, text):
        self.play_pause_btn.setText(text)

    def set_audio_device(self, device_info):
        """Set audio output to the Qt multimedia output matching description."""
        if self.audio_output is None or QMediaDevices is None:
            return

        try:
            if isinstance(device_info, dict):
                device_description = device_info.get("description")
            else:
                device_description = device_info

            if not device_description:
                self.audio_output.setDevice(QMediaDevices.defaultAudioOutput())
                return

            audio_devices = QMediaDevices.audioOutputs()
            selected_norm = str(device_description).strip().lower()
            for qa_device in audio_devices:
                qa_desc = qa_device.description()
                qa_norm = str(qa_desc).strip().lower()
                if qa_desc == device_description or selected_norm in qa_norm or qa_norm in selected_norm:
                    self.audio_output.setDevice(qa_device)
                    self.audio_output.setMuted(False)
                    self.audio_output.setVolume(1.0)
                    return

            # Fallback to system default output.
            self.audio_output.setDevice(QMediaDevices.defaultAudioOutput())
            self.audio_output.setMuted(False)
            self.audio_output.setVolume(1.0)
        except Exception:
            pass

    def sync_seek_position(self, position_ms):
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(position_ms)
        self.seek_slider.blockSignals(False)
