"""
Audio visualization widget for displaying waveforms and spectrograms.
Uses librosa for audio processing and pyqtgraph for interactive plotting.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QMessageBox, QSplitter, QPushButton, QDoubleSpinBox, QSpinBox
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, Qt, QTimer, QUrl
from PyQt6.QtGui import QShortcut, QKeySequence
import pyqtgraph as pg
import librosa
import numpy as np
from .components.annotation_interaction import AnnotationInteractionManager
from .components.annotation_overlays import AnnotationOverlayManager
from .components.plot_utils import draw_waveform, draw_spectrogram
from .components.playback_helpers import PlayheadOverlayManager, PlaybackControlsManager, format_mm_ss, QMediaPlayer, QMediaDevices
from const import (
    BUTTON_AUTO_RANGE,
    BUTTON_REPLOT,
    COLORBAR_PRESET,
    DEFAULT_COLORBAR_WIDTH,
    DEFAULT_SPECTROGRAM_FREQ_HZ,
    DEFAULT_SPECTROGRAM_LEVELS,
    LABEL_AMPLITUDE_OR_FREQUENCY_AXIS,
    LABEL_FREQUENCY_AXIS,
    LABEL_LEFT_CHANNEL,
    LABEL_RIGHT_CHANNEL,
    LABEL_SINGLE_CHANNEL,
    LABEL_SPEC_MAX_FREQ,
    LABEL_TIME_AXIS,
    LABEL_WAVEFORM_MAX_SAMPLES,
    PAUSE_BUTTON_TEXT,
    PLAYBACK_NO_PROCESSED_OUTPUT_MESSAGE,
    PLAYBACK_UNAVAILABLE_MESSAGE,
    PLAYBACK_UNAVAILABLE_TITLE,
    PLAY_BUTTON_TEXT,
    SPECTROGRAM_FREQ_STEP_HZ,
    SPECTROGRAM_FREQ_SUFFIX,
    SPECTROGRAM_MAX_FREQ_HZ,
    SPECTROGRAM_MIN_FREQ_HZ,
    SPLITTER_DEFAULT_AUDIO_PLOT_SIZES,
    TITLE_LEFT_CHANNEL,
    TITLE_MONO_CHANNEL,
    TITLE_RIGHT_CHANNEL,
    VIEW_MODE_SPECTROGRAM,
    VIEW_MODE_WAVEFORM,
    WAVEFORM_MAX_SAMPLES_DEFAULT,
    WAVEFORM_MAX_SAMPLES_MAX,
    WAVEFORM_MAX_SAMPLES_MIN,
    WAVEFORM_MAX_SAMPLES_STEP,
    WAVEFORM_Y_MAX,
    WAVEFORM_Y_MIN,
)

class AudioLoadWorker(QObject):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str, object, int, bool)
    error = pyqtSignal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    @pyqtSlot()
    def run(self):
        try:
            file_path, y, sr, is_mono = AudioViewerWidget.prepare_audio_payload(
                self.file_path,
                progress_callback=self.progress.emit,
            )
            self.finished.emit(file_path, y, sr, is_mono)
        except Exception as exc:
            self.error.emit(str(exc))

class AudioViewerWidget(QWidget):
    selection_changed = pyqtSignal(float, float)  # Emits start_time, end_time
    audio_loaded = pyqtSignal(object, int, bool)  # Emits (y, sr, is_mono) when audio is loaded
    annotation_created = pyqtSignal(float, float, str)  # Emits start_time, end_time, channel
    annotation_block_clicked = pyqtSignal(int)  # Emits annotation index
    
    def __init__(self):
        super().__init__()
        self.audio_path = None
        self.y = None
        self.sr = None
        self.selection_region = None
        self.syncing = False  # Flag to prevent recursive view syncing
        self.is_mono = True
        self.current_image_left = None
        self.current_image_right = None
        self.colorbar = None
        # Store view ranges for preserving zoom
        self.left_view_range = None
        self.right_view_range = None
        # Store spectrogram state per file
        self.spectrogram_state = {}
        self.audio_duration_sec = 0.0
        self.user_is_seeking = False
        self.playhead_left = None
        self.playhead_right = None
        self._syncing_colorbar = False
        self.default_spectrogram_levels = DEFAULT_SPECTROGRAM_LEVELS
        self._colorbar_anchor_image = None
        self.current_spectrogram_levels = self.default_spectrogram_levels
        self.current_spectrogram_lut = None
        self.playhead_manager = None
        
        # Annotation support
        self.annotations = []
        self.annotation_blocks = {"left": [], "right": []}
        self.overlay_manager = None
        self.interaction_manager = None
        
        # Filter preview mode state
        self.filter_preview_mode = False  # When True, show input/output spectrograms
        self.filter_preview_channel = 0  # Which channel to show in filter preview
        self.filter_preview_output = None  # Processed audio output
        self.filter_playback_mode = "original"  # "original" or "processed" - which to play in filter mode
        self.processed_player = None  # Separate player for processed audio in filter mode
        self.processed_audio_output = None
        self.output_device_description = None
        self._syncing_player_positions = False
        self.test_tone_player = None
        self.test_tone_temp_path = None

        self.playback_controls = None
        self.player = None
        self.playback_available = False

        self.init_ui()

    def get_active_player(self):
        """Return the currently selected media player for playback controls."""
        if self.filter_preview_mode and self.filter_playback_mode == "processed":
            return self.processed_player
        return self.player

    def should_include_right_playhead(self):
        """Determine whether playhead overlays should be mirrored to the lower plot."""
        return self.filter_preview_mode or not self.is_mono

    def set_audio_output_device(self, device_info):
        """Apply selected output device to both original and processed playback outputs."""
        device_description = str(device_info or "").strip()

        self.output_device_description = device_description
        if self.playback_controls is not None:
            self.playback_controls.set_audio_device(device_info)

        if self.processed_audio_output is None or QMediaDevices is None or not device_description:
            return

        try:
            selected_norm = str(device_description).strip().lower()
            for qa_device in QMediaDevices.audioOutputs():
                qa_desc = qa_device.description()
                qa_norm = str(qa_desc).strip().lower()
                if qa_desc == device_description or selected_norm in qa_norm or qa_norm in selected_norm:
                    self.processed_audio_output.setDevice(qa_device)
                    self.processed_audio_output.setMuted(False)
                    self.processed_audio_output.setVolume(1.0)
                    return
            self.processed_audio_output.setDevice(QMediaDevices.defaultAudioOutput())
            self.processed_audio_output.setMuted(False)
            self.processed_audio_output.setVolume(1.0)
        except Exception:
            pass

    def _cleanup_test_tone_temp(self):
        if self.test_tone_temp_path:
            try:
                import os
                if os.path.exists(self.test_tone_temp_path):
                    os.remove(self.test_tone_temp_path)
            except Exception:
                pass
            self.test_tone_temp_path = None

    def play_output_test_tone(self):
        """Play a 1-second 440 Hz tone via the same shared Qt audio output used for playback."""
        if QMediaPlayer is None:
            QMessageBox.warning(self, PLAYBACK_UNAVAILABLE_TITLE, PLAYBACK_UNAVAILABLE_MESSAGE)
            return
        if self.playback_controls is None or self.playback_controls.audio_output is None:
            QMessageBox.warning(self, PLAYBACK_UNAVAILABLE_TITLE, PLAYBACK_UNAVAILABLE_MESSAGE)
            return

        self._cleanup_test_tone_temp()
        try:
            import tempfile
            import wave

            sr = 44100
            duration_sec = 1.0
            tone_hz = 440.0
            t = np.linspace(0.0, duration_sec, int(sr * duration_sec), endpoint=False)
            tone = (0.25 * np.sin(2 * np.pi * tone_hz * t) * 32767.0).astype(np.int16)

            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                with wave.open(tmp.name, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)  # PCM16
                    wav_file.setframerate(sr)
                    wav_file.writeframes(tone.tobytes())
                self.test_tone_temp_path = tmp.name

            if self.test_tone_player is None:
                self.test_tone_player = QMediaPlayer(self)
                self.test_tone_player.setAudioOutput(self.playback_controls.audio_output)
                self.test_tone_player.errorOccurred.connect(
                    lambda *_args: QMessageBox.warning(
                        self,
                        PLAYBACK_UNAVAILABLE_TITLE,
                        f"Test tone playback failed:\n{self.test_tone_player.errorString()}"
                    )
                )
                self.test_tone_player.mediaStatusChanged.connect(
                    lambda status: self._cleanup_test_tone_temp()
                    if QMediaPlayer is not None and status == QMediaPlayer.MediaStatus.EndOfMedia
                    else None
                )

            # Ensure currently selected output is audible.
            try:
                self.playback_controls.audio_output.setMuted(False)
                self.playback_controls.audio_output.setVolume(1.0)
            except Exception:
                pass

            self.test_tone_player.stop()
            self.test_tone_player.setSource(QUrl.fromLocalFile(self.test_tone_temp_path))
            self.test_tone_player.play()
        except Exception as exc:
            QMessageBox.warning(self, PLAYBACK_UNAVAILABLE_TITLE, f"Failed to play test tone:\n{exc}")
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Control panel for individual channel selection
        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(8, 4, 8, 4)
        control_layout.setSpacing(10)
        
        # Left channel controls
        self.left_controls = QWidget()
        left_control_layout = QVBoxLayout(self.left_controls)
        left_control_layout.setContentsMargins(0, 0, 0, 0)
        left_control_layout.setSpacing(4)
        self.left_channel_label = QLabel(LABEL_LEFT_CHANNEL)
        left_control_layout.addWidget(self.left_channel_label)
        self.left_viz_combo = QComboBox()
        self.left_viz_combo.addItems([VIEW_MODE_WAVEFORM, VIEW_MODE_SPECTROGRAM])
        self.left_viz_combo.currentTextChanged.connect(self.on_visualization_changed)
        left_control_layout.addWidget(self.left_viz_combo)
        
        # Auto-range buttons for left channel
        left_range_layout = QHBoxLayout()
        self.left_auto_range_btn = QPushButton(BUTTON_AUTO_RANGE)
        self.left_auto_range_btn.clicked.connect(self.auto_range_left_plot)
        left_range_layout.addWidget(self.left_auto_range_btn)
        left_control_layout.addLayout(left_range_layout)
        
        control_layout.addWidget(self.left_controls)
        
        # Right channel controls
        self.right_controls = QWidget()
        right_control_layout = QVBoxLayout(self.right_controls)
        right_control_layout.setContentsMargins(0, 0, 0, 0)
        right_control_layout.setSpacing(4)
        right_control_layout.addWidget(QLabel(LABEL_RIGHT_CHANNEL))
        self.right_viz_combo = QComboBox()
        self.right_viz_combo.addItems([VIEW_MODE_WAVEFORM, VIEW_MODE_SPECTROGRAM])
        self.right_viz_combo.currentTextChanged.connect(self.on_visualization_changed)
        right_control_layout.addWidget(self.right_viz_combo)
        
        # Auto-range buttons for right channel
        right_range_layout = QHBoxLayout()
        self.right_auto_range_btn = QPushButton(BUTTON_AUTO_RANGE)
        self.right_auto_range_btn.clicked.connect(self.auto_range_right_plot)
        right_range_layout.addWidget(self.right_auto_range_btn)
        right_control_layout.addLayout(right_range_layout)
        
        control_layout.addWidget(self.right_controls)

        # Shared rendering options
        self.max_freq_spin = QDoubleSpinBox()
        self.max_freq_spin.setDecimals(0)
        self.max_freq_spin.setRange(SPECTROGRAM_MIN_FREQ_HZ, SPECTROGRAM_MAX_FREQ_HZ)
        self.max_freq_spin.setSingleStep(SPECTROGRAM_FREQ_STEP_HZ)
        self.max_freq_spin.setSuffix(SPECTROGRAM_FREQ_SUFFIX)
        self.max_freq_spin.setValue(DEFAULT_SPECTROGRAM_FREQ_HZ)

        self.max_samples_spin = QSpinBox()
        self.max_samples_spin.setRange(WAVEFORM_MAX_SAMPLES_MIN, WAVEFORM_MAX_SAMPLES_MAX)
        self.max_samples_spin.setSingleStep(WAVEFORM_MAX_SAMPLES_STEP)
        self.max_samples_spin.setValue(WAVEFORM_MAX_SAMPLES_DEFAULT)

        self.replot_btn = QPushButton(BUTTON_REPLOT)
        self.replot_btn.clicked.connect(self.replot_current_view)

        # Vertically stacked rendering options
        options_layout = QVBoxLayout()
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(4)
        
        # Max frequency row
        freq_row = QHBoxLayout()
        freq_row.setContentsMargins(0, 0, 0, 0)
        freq_row.setSpacing(4)
        freq_row.addWidget(QLabel(LABEL_SPEC_MAX_FREQ))
        freq_row.addWidget(self.max_freq_spin)
        freq_row.addStretch()
        options_layout.addLayout(freq_row)
        
        # Max samples row
        samples_row = QHBoxLayout()
        samples_row.setContentsMargins(0, 0, 0, 0)
        samples_row.setSpacing(4)
        samples_row.addWidget(QLabel(LABEL_WAVEFORM_MAX_SAMPLES))
        samples_row.addWidget(self.max_samples_spin)
        samples_row.addStretch()
        options_layout.addLayout(samples_row)
        
        # Replot button
        options_layout.addWidget(self.replot_btn)

        options_widget = QWidget()
        options_widget.setLayout(options_layout)
        options_widget.setMaximumWidth(320)
        control_layout.addWidget(options_widget)

        control_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        # Audio info label (SR / channels / duration)
        self.audio_info_label = QLabel("")
        self.audio_info_label.setStyleSheet("color: gray; font-size: 11px;")
        self.audio_info_label.setContentsMargins(8, 0, 0, 0)
        layout.addWidget(self.audio_info_label)

        self.playback_controls = PlaybackControlsManager(
            parent=self,
            on_toggle=self.toggle_playback,
            on_seek_pressed=self.on_seek_pressed,
            on_seek_moved=self.on_seek_moved,
            on_seek_released=self.on_seek_released,
            on_position_changed=self.on_original_player_position_changed,
            on_state_changed=self.on_playback_state_changed,
        )
        self.play_pause_btn = self.playback_controls.play_pause_btn
        self.auto_follow_btn = self.playback_controls.auto_follow_btn
        self.seek_slider = self.playback_controls.seek_slider
        self.time_label = self.playback_controls.time_label
        self.player = self.playback_controls.player
        self.playback_available = self.playback_controls.playback_available

        layout.addLayout(self.playback_controls.layout)
        
        # Filter preview playback mode selector (hidden by default, shown only in filter mode)
        playback_mode_layout = QHBoxLayout()
        playback_mode_layout.setContentsMargins(0, 0, 0, 0)
        self.playback_mode_label = QLabel("Playback:")
        self.playback_mode_selector = QComboBox()
        self.playback_mode_selector.addItem("Original", "original")
        self.playback_mode_selector.addItem("Processed", "processed")
        self.playback_mode_selector.currentIndexChanged.connect(self.on_playback_mode_changed)
        playback_mode_layout.addWidget(self.playback_mode_label)
        playback_mode_layout.addWidget(self.playback_mode_selector)
        playback_mode_layout.addStretch()
        
        playback_mode_widget = QWidget()
        playback_mode_widget.setLayout(playback_mode_layout)
        playback_mode_widget.setVisible(False)  # Hidden until filter preview mode
        self.playback_mode_widget = playback_mode_widget
        layout.addWidget(playback_mode_widget)
        
        # Create splitter for L/R channels
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Left channel plot
        self.plot_left = pg.PlotWidget()
        self.plot_left.setLabel('bottom', LABEL_TIME_AXIS)
        self.plot_left.setLabel('left', LABEL_AMPLITUDE_OR_FREQUENCY_AXIS)
        self.plot_left.setTitle(TITLE_LEFT_CHANNEL)
        # Disable middle mouse button zoom (omni zoom)
        self.plot_left.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        self.plot_left.getViewBox().setMouseEnabled(x=True, y=False)
        self.splitter.addWidget(self.plot_left)
        
        # Right channel plot
        self.plot_right = pg.PlotWidget()
        self.plot_right.setLabel('bottom', LABEL_TIME_AXIS)
        self.plot_right.setLabel('left', LABEL_AMPLITUDE_OR_FREQUENCY_AXIS)
        self.plot_right.setTitle(TITLE_RIGHT_CHANNEL)
        # Disable middle mouse button zoom (omni zoom)
        self.plot_right.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        self.plot_right.getViewBox().setMouseEnabled(x=True, y=False)
        self.splitter.addWidget(self.plot_right)
        
        self.splitter.setSizes(SPLITTER_DEFAULT_AUDIO_PLOT_SIZES)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.playhead_manager = PlayheadOverlayManager(self.plot_left, self.plot_right)
        self.overlay_manager = AnnotationOverlayManager(self.plot_left, self.plot_right, lambda: self.is_mono)
        self.interaction_manager = AnnotationInteractionManager(
            parent_widget=self,
            plot_left=self.plot_left,
            plot_right=self.plot_right,
            is_mono_getter=lambda: self.is_mono,
            annotations_getter=lambda: self.annotations,
            on_annotation_created=lambda s, e, ch: self.annotation_created.emit(s, e, ch),
            on_annotation_block_clicked=lambda idx: self.annotation_block_clicked.emit(idx),
            on_pending_annotation=self.set_pending_annotation,
        )
        
        # Plot area row excludes top controls; colorbar should align with this area only
        self.plot_area_widget = QWidget()
        self.plot_area_layout = QHBoxLayout(self.plot_area_widget)
        self.plot_area_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_area_layout.setSpacing(0)
        self.plot_area_layout.addWidget(self.splitter, 1)

        layout.addWidget(self.plot_area_widget, 1)
        self.setLayout(layout)
        
        # Connect view changes for synchronization
        self.plot_left.getViewBox().sigRangeChanged.connect(self.on_left_view_changed)
        self.plot_right.getViewBox().sigRangeChanged.connect(self.on_right_view_changed)
        
        # Configure wheel zoom to only affect X axis
        self.plot_left.getViewBox().wheelZoomX = True
        # self.plot_left.getViewBox().wheelZoomY = False
        self.plot_right.getViewBox().wheelZoomX = True
        # self.plot_right.getViewBox().wheelZoomY = False
        
        # Initialize UI for mono/stereo
        self.update_ui_for_channels()

        # Space key toggles play/pause from any focused child widget (plot, etc.).
        _space = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        _space.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        _space.activated.connect(self.toggle_playback)


    @staticmethod
    def prepare_audio_payload(file_path, progress_callback=None):
        """Decode an audio file and normalize it to a 2-row array for display."""
        if progress_callback is not None:
            progress_callback(5, "Opening audio file")

        y, sr = librosa.load(file_path, sr=None, mono=False)

        if progress_callback is not None:
            progress_callback(55, "Preparing channel layout")

        is_mono = (len(y.shape) == 1 or (len(y.shape) == 2 and y.shape[0] == 1))
        if is_mono:
            flattened = y.flatten() if len(y.shape) > 1 else y
            y = np.array([flattened, flattened])

        if progress_callback is not None:
            progress_callback(85, "Audio data ready")

        return file_path, y, sr, is_mono
    
    # def load_audio(self, file_path):
    #     """Load and display audio file."""
    #     try:
    #         file_path, y, sr, is_mono = self.prepare_audio_payload(file_path)
    #         self.apply_loaded_audio(file_path, y, sr, is_mono)
    #     except Exception as e:
    #         QMessageBox.critical(self, "Error", f"Failed to load audio: {str(e)}")

    def apply_loaded_audio(self, file_path, y, sr, is_mono):
        """Apply already-decoded audio data to the viewer and refresh the UI."""
        self.audio_path = file_path
        self.y = y
        self.sr = sr
        self.is_mono = is_mono

        self.audio_duration_sec = self.y.shape[1] / self.sr

        ch_count = 1 if is_mono else self.y.shape[0]
        self.audio_info_label.setText(
            f"{ch_count}ch  |  {sr / 1000:.1f} kHz  |  {self.audio_duration_sec:.1f}s"
        )

        # Default spectrogram max frequency to Nyquist for the loaded file.
        nyquist_hz = max(SPECTROGRAM_MIN_FREQ_HZ, float(self.sr) / 2.0)
        self.max_freq_spin.setRange(SPECTROGRAM_MIN_FREQ_HZ, nyquist_hz)
        self.max_freq_spin.setValue(nyquist_hz)

        self.playback_controls.configure_duration(self.audio_duration_sec)
        self.playback_controls.set_time_label(self.format_time_label(0.0))
        self.playback_controls.set_source(file_path)
        self.playback_controls.set_play_button_text(PLAY_BUTTON_TEXT)

        # Restore persisted spectrogram levels per file (or defaults).
        self.current_spectrogram_levels = self.get_stored_spectrogram_levels()

        self.update_ui_for_channels()
        self.display_audio()
        self.audio_loaded.emit(self.y, self.sr, self.is_mono)
    
    def display_audio(self):
        """Display audio based on current visualization mode or filter preview mode."""
        if self.y is None or self.sr is None:
            return
        
        # Store current view ranges before clearing
        self.left_view_range = self.plot_left.getViewBox().viewRange()
        self.right_view_range = self.plot_right.getViewBox().viewRange()
        
        self.plot_left.clear()
        self.plot_right.clear()
        self.current_image_left = None
        self.current_image_right = None

        # Hide colorbar by default
        if self.colorbar is not None:
            self.colorbar.hide()

        # Filter preview mode: show input/output spectrograms
        if self.filter_preview_mode:
            self.display_filter_preview()
        else:
            # Normal mode: show selected visualization for L/R channels
            left_mode = self.left_viz_combo.currentText()
            right_mode = self.right_viz_combo.currentText()

            if left_mode == VIEW_MODE_WAVEFORM:
                self.display_waveform_left()
            else:
                self.display_spectrogram_left()

            if not self.is_mono:
                if right_mode == VIEW_MODE_WAVEFORM:
                    self.display_waveform_right()
                else:
                    self.display_spectrogram_right()

        # Keep both spectrogram channels on the same LUT/levels whenever visible.
        self.refresh_colorbar_and_spectrogram_sync()
        
        # Restore view ranges if they exist
        if self.left_view_range is not None:
            try:
                self.plot_left.getViewBox().setRange(xRange=self.left_view_range[0], padding=0)
            except:
                pass
        
        if self.right_view_range is not None and not self.filter_preview_mode:
            try:
                self.plot_right.getViewBox().setRange(xRange=self.right_view_range[0], padding=0)
            except:
                pass

        self.apply_static_y_ranges()
        self.redraw_annotations()

        self.add_playhead_lines()
        # Run after render so both plot areas use the same left-axis width
        QTimer.singleShot(0, self.sync_plot_axis_layout)
    
    def display_filter_preview(self):
        """Display filter preview mode: input channel (top) and processed output (bottom)."""
        # Ensure channel index is valid
        channel_index = max(0, min(self.filter_preview_channel, self.y.shape[0] - 1))
        
        duration = self.y.shape[1] / self.sr
        
        # Top plot: original input channel spectrogram
        input_signal = self.y[channel_index] if len(self.y.shape) > 1 else self.y
        self.current_image_left = draw_spectrogram(
            self.plot_left,
            input_signal,
            self.sr,
            duration,
            y_max_hz=self.max_freq_spin.value(),
        )
        self.plot_left.setTitle("Original Input")
        
        if self.colorbar is not None:
            self.colorbar.show()
        
        # Bottom plot: processed output spectrogram (if available)
        if self.filter_preview_output is not None:
            output_signal = np.asarray(self.filter_preview_output, dtype=np.float32).flatten()
            output_duration = len(output_signal) / self.sr
            self.current_image_right = draw_spectrogram(
                self.plot_right,
                output_signal,
                self.sr,
                output_duration,
                y_max_hz=self.max_freq_spin.value(),
            )
            self.plot_right.setTitle("Processed Output")
        else:
            # Empty bottom plot when no processed output yet
            self.plot_right.setTitle("Processed Output (empty)")
            self.plot_right.setLabel("bottom", LABEL_TIME_AXIS)
            self.plot_right.setLabel("left", LABEL_FREQUENCY_AXIS)
    
    def display_waveform_left(self):
        """Display waveform for left channel."""
        self.current_image_left = None
        duration = self.y.shape[1] / self.sr
        draw_waveform(
            self.plot_left,
            self.y[0],
            self.sr,
            pg.mkPen('cyan', width=1),
            duration,
            max_samples=self.max_samples_spin.value(),
        )
    
    def display_waveform_right(self):
        """Display waveform for right channel."""
        self.current_image_right = None
        duration = self.y.shape[1] / self.sr
        draw_waveform(
            self.plot_right,
            self.y[1],
            self.sr,
            pg.mkPen('magenta', width=1),
            duration,
            max_samples=self.max_samples_spin.value(),
        )
    
    def display_spectrogram_left(self):
        """Display spectrogram for left channel."""
        duration = self.y.shape[1] / self.sr
        self.current_image_left = draw_spectrogram(
            self.plot_left,
            self.y[0],
            self.sr,
            duration,
            y_max_hz=self.max_freq_spin.value(),
        )
        
        if self.colorbar is not None:
            self.colorbar.show()
    
    def display_spectrogram_right(self):
        """Display spectrogram for right channel."""
        duration = self.y.shape[1] / self.sr
        self.current_image_right = draw_spectrogram(
            self.plot_right,
            self.y[1],
            self.sr,
            duration,
            y_max_hz=self.max_freq_spin.value(),
        )

        if self.colorbar is not None:
            self.colorbar.show()
            
    def on_left_view_changed(self):
        """Sync right plot X-axis when left plot view changes (time only, independent gain)."""
        if not self.syncing:
            self.syncing = True
            # Get the X range from left plot (time axis)
            left_range = self.plot_left.getViewBox().viewRange()
            # Apply only X range to right plot, keep Y range independent
            self.plot_right.getViewBox().setRange(xRange=left_range[0], padding=0)
            self.syncing = False
    
    def on_right_view_changed(self):
        """Sync left plot X-axis when right plot view changes (time only, independent gain)."""
        if not self.syncing:
            self.syncing = True
            # Get the X range from right plot (time axis)
            right_range = self.plot_right.getViewBox().viewRange()
            # Apply only X range to left plot, keep Y range independent
            self.plot_left.getViewBox().setRange(xRange=right_range[0], padding=0)
            self.syncing = False
    
    def on_visualization_changed(self, mode):
        """Handle visualization mode change."""
        if self.y is not None:
            self.display_audio()

    def apply_static_y_ranges(self):
        """Apply fixed Y-axis ranges based on visualization mode."""
        spectrogram_y_max = self.max_freq_spin.value()
        
        if self.filter_preview_mode:
            # In filter preview mode, both plots are always spectrograms
            self.plot_left.setYRange(0.0, spectrogram_y_max, padding=0)
            self.plot_right.setYRange(0.0, spectrogram_y_max, padding=0)
        else:
            # Normal mode: check visualization settings
            if self.left_viz_combo.currentText() == VIEW_MODE_WAVEFORM:
                self.plot_left.setYRange(WAVEFORM_Y_MIN, WAVEFORM_Y_MAX, padding=0)
            else:
                self.plot_left.setYRange(0.0, spectrogram_y_max, padding=0)

            if not self.is_mono:
                if self.right_viz_combo.currentText() == VIEW_MODE_WAVEFORM:
                    self.plot_right.setYRange(WAVEFORM_Y_MIN, WAVEFORM_Y_MAX, padding=0)
                else:
                    self.plot_right.setYRange(0.0, spectrogram_y_max, padding=0)

    def replot_current_view(self):
        """Re-render current plots with active rendering settings."""
        if self.y is None or self.sr is None:
            return
        self.display_audio()

    def auto_range_left_plot(self):
        """Reset left plot X-range while keeping fixed Y-range behavior."""
        if self.y is None or self.sr is None:
            return
        duration = self.y.shape[1] / self.sr
        self.plot_left.setXRange(0, duration, padding=0)
        self.apply_static_y_ranges()

    def auto_range_right_plot(self):
        """Reset right plot X-range while keeping fixed Y-range behavior."""
        if self.y is None or self.sr is None or self.is_mono:
            return
        duration = self.y.shape[1] / self.sr
        self.plot_right.setXRange(0, duration, padding=0)
        self.apply_static_y_ranges()
    
    def update_ui_for_channels(self):
        """Update UI elements based on mono/stereo audio and filter preview mode."""
        # In filter preview mode, always show both plots (input/output)
        if self.filter_preview_mode:
            self.right_controls.hide()  # Hide channel controls in filter preview
            self.plot_right.show()  # But always show the output plot
            self.left_channel_label.hide()
        elif self.is_mono:
            self.right_controls.hide()
            self.plot_right.hide()
            self.left_channel_label.setText(LABEL_SINGLE_CHANNEL)
            self.plot_left.setTitle(TITLE_MONO_CHANNEL)
        else:
            self.right_controls.show()
            self.plot_right.show()
            self.left_channel_label.setText(LABEL_LEFT_CHANNEL)
            self.left_channel_label.show()
            self.plot_left.setTitle(TITLE_LEFT_CHANNEL)
            self.plot_right.setTitle(TITLE_RIGHT_CHANNEL)

    def set_colorbar(self, colorbar):
        """Set the colorbar widget reference."""
        self.colorbar = colorbar
        if self.colorbar is not None:
            # Place colorbar next to plot splitter only (not top controls)
            if self.plot_area_layout.indexOf(self.colorbar) == -1:
                self.colorbar.setMaximumWidth(DEFAULT_COLORBAR_WIDTH)
                self.plot_area_layout.addWidget(self.colorbar)

            # Default spectrogram colormap.
            if hasattr(self.colorbar, 'item') and hasattr(self.colorbar.item, 'gradient'):
                self.colorbar.item.gradient.loadPreset(COLORBAR_PRESET)
                self.current_spectrogram_lut = self.get_gradient_lookup_table(self.colorbar.item.gradient)
            elif hasattr(self.colorbar, 'gradient'):
                self.colorbar.gradient.loadPreset(COLORBAR_PRESET)
                self.current_spectrogram_lut = self.get_gradient_lookup_table(self.colorbar.gradient)

            self.colorbar.hide()  # Initially hidden

            if hasattr(self.colorbar, 'item'):
                self.colorbar.item.setLevels(*self.current_spectrogram_levels)

            # Connect colorbar changes to both spectrogram images.
            if hasattr(self.colorbar, 'item') and hasattr(self.colorbar.item, 'sigLevelsChanged'):
                self.colorbar.item.sigLevelsChanged.connect(self.on_colorbar_levels_changed)
            if hasattr(self.colorbar, 'item') and hasattr(self.colorbar.item, 'sigLookupTableChanged'):
                self.colorbar.item.sigLookupTableChanged.connect(self.on_colorbar_gradient_changed)
            if hasattr(self.colorbar, 'item') and hasattr(self.colorbar.item, 'gradient') and hasattr(self.colorbar.item.gradient, 'sigGradientChanged'):
                self.colorbar.item.gradient.sigGradientChanged.connect(self.on_colorbar_gradient_changed)
            elif hasattr(self.colorbar, 'gradient') and hasattr(self.colorbar.gradient, 'sigGradientChanged'):
                self.colorbar.gradient.sigGradientChanged.connect(self.on_colorbar_gradient_changed)

    def get_stored_spectrogram_levels(self):
        """Get persisted levels for the current file, or defaults."""
        if self.audio_path in self.spectrogram_state:
            return self.spectrogram_state[self.audio_path].get('levels', self.default_spectrogram_levels)
        return self.default_spectrogram_levels

    def get_gradient_lookup_table(self, gradient_obj):
        """Return LUT from a pyqtgraph gradient object across API variants."""
        if gradient_obj is None:
            return None

        # GradientEditorItem commonly supports getLookupTable(nPts[, alpha]).
        try:
            return gradient_obj.getLookupTable(256)
        except TypeError:
            pass
        except Exception:
            return None

        try:
            return gradient_obj.getLookupTable(nPts=256)
        except Exception:
            pass

        # Fallback via ColorMap if available.
        try:
            if hasattr(gradient_obj, 'colorMap'):
                return gradient_obj.colorMap().getLookupTable(0.0, 1.0, 256)
        except Exception:
            return None

        return None

    def get_colorbar_lookup_table(self):
        """Read the active LUT from the histogram gradient."""
        if self.colorbar is None:
            return None
        try:
            if hasattr(self.colorbar, 'item') and hasattr(self.colorbar.item, 'gradient'):
                return self.get_gradient_lookup_table(self.colorbar.item.gradient)
            if hasattr(self.colorbar, 'gradient'):
                return self.get_gradient_lookup_table(self.colorbar.gradient)
        except Exception:
            return None
        return None

    def get_colorbar_levels(self):
        """Read the active levels from the histogram widget."""
        if self.colorbar is not None and hasattr(self.colorbar, 'item'):
            try:
                return self.colorbar.item.getLevels()
            except Exception:
                pass
        return self.get_stored_spectrogram_levels()

    def get_combined_visible_spectrogram_levels(self):
        """Compute min/max across all visible spectrogram images."""
        visible_images = self.get_visible_spectrogram_images()
        if not visible_images:
            return self.current_spectrogram_levels

        mins = []
        maxs = []
        for image in visible_images:
            data = getattr(image, 'image', None)
            if data is None:
                continue
            mins.append(float(np.nanmin(data)))
            maxs.append(float(np.nanmax(data)))

        if not mins or not maxs:
            return self.current_spectrogram_levels

        min_val = min(mins)
        max_val = max(maxs)
        if min_val == max_val:
            max_val = min_val + 1.0
        return (min_val, max_val)

    def apply_current_spectrogram_colors(self):
        """Apply shared LUT/levels to all visible spectrogram images."""
        for image in self.get_visible_spectrogram_images():
            if self.current_spectrogram_lut is not None:
                image.setLookupTable(self.current_spectrogram_lut)
            image.setLevels(self.current_spectrogram_levels)

    def get_visible_spectrogram_images(self):
        """Return spectrogram image items that are currently visible in the UI mode."""
        images = []
        if self.filter_preview_mode:
            if self.current_image_left is not None:
                images.append(self.current_image_left)
            if self.current_image_right is not None:
                images.append(self.current_image_right)
            return images

        if self.left_viz_combo.currentText() == VIEW_MODE_SPECTROGRAM and self.current_image_left is not None:
            images.append(self.current_image_left)
        if (
            not self.is_mono
            and self.right_viz_combo.currentText() == VIEW_MODE_SPECTROGRAM
            and self.current_image_right is not None
        ):
            images.append(self.current_image_right)
        return images

    def anchor_colorbar_image(self):
        """Attach the histogram widget to one visible spectrogram image."""
        if self.colorbar is None:
            return
        images = self.get_visible_spectrogram_images()
        if not images:
            self._colorbar_anchor_image = None
            return
        anchor = images[0]
        if anchor is not self._colorbar_anchor_image:
            self.colorbar.setImageItem(anchor)
            self._colorbar_anchor_image = anchor

    def sync_spectrogram_visual_settings(self):
        """Apply the same LUT and levels to all currently visible spectrogram images."""
        if self.colorbar is None or self._syncing_colorbar:
            return

        visible_images = self.get_visible_spectrogram_images()
        if not visible_images:
            self._colorbar_anchor_image = None
            return

        self._syncing_colorbar = True
        try:
            self.current_spectrogram_levels = self.get_colorbar_levels()
            lut = self.get_colorbar_lookup_table()
            if lut is not None:
                self.current_spectrogram_lut = lut

            self.apply_current_spectrogram_colors()

            # Persist current levels for this file.
            if self.audio_path is not None:
                if self.audio_path not in self.spectrogram_state:
                    self.spectrogram_state[self.audio_path] = {}
                self.spectrogram_state[self.audio_path]['levels'] = self.current_spectrogram_levels
        finally:
            self._syncing_colorbar = False

    def on_colorbar_levels_changed(self, *_args):
        """Handle histogram level changes and mirror to both channels."""
        self.current_spectrogram_levels = self.get_colorbar_levels()
        self.sync_spectrogram_visual_settings()

    def on_colorbar_gradient_changed(self, *_args):
        """Handle histogram gradient/LUT changes and mirror to both channels."""
        lut = self.get_colorbar_lookup_table()
        if lut is not None:
            self.current_spectrogram_lut = lut
        self.sync_spectrogram_visual_settings()

    def refresh_colorbar_and_spectrogram_sync(self):
        """Anchor histogram to one visible spectrogram and mirror settings to all visible ones."""
        if self.colorbar is None:
            return

        visible_images = self.get_visible_spectrogram_images()
        if not visible_images:
            self._colorbar_anchor_image = None
            self.colorbar.hide()
            return

        self.colorbar.show()

        # Use persisted level range for this file if present, else initialize from both channels.
        if self.audio_path in self.spectrogram_state:
            self.current_spectrogram_levels = self.get_stored_spectrogram_levels()
        else:
            self.current_spectrogram_levels = self.get_combined_visible_spectrogram_levels()

        self.anchor_colorbar_image()
        if hasattr(self.colorbar, 'item'):
            self.colorbar.item.setLevels(*self.current_spectrogram_levels)

        lut = self.get_colorbar_lookup_table()
        if lut is not None:
            self.current_spectrogram_lut = lut

        self.sync_spectrogram_visual_settings()
        self.apply_current_spectrogram_colors()
    

    def add_playhead_lines(self):
        """Add vertical playhead and seekbar indicators to both plots after rendering."""
        if self.playhead_manager is not None:
            self.playhead_manager.create(include_right=self.should_include_right_playhead(), position_sec=0.0)
            self.playhead_left = self.playhead_manager.playhead_left
            self.playhead_right = self.playhead_manager.playhead_right

        active_player = self.get_active_player()
        position_sec = 0.0 if active_player is None else (active_player.position() / 1000.0)
        self.update_playhead_position(position_sec)

    def toggle_playback(self):
        """Play/pause audio through the system default output device."""
        player = self.get_active_player()

        # Keep output sinks audible in case backend/device transitions muted them.
        try:
            if self.playback_controls is not None and self.playback_controls.audio_output is not None:
                self.playback_controls.audio_output.setMuted(False)
                self.playback_controls.audio_output.setVolume(1.0)
            if self.processed_audio_output is not None:
                self.processed_audio_output.setMuted(False)
                self.processed_audio_output.setVolume(1.0)
        except Exception:
            pass

        if self.filter_preview_mode and self.filter_playback_mode == "processed":
            if self.filter_preview_output is None or self.processed_player is None:
                QMessageBox.information(
                    self,
                    PLAYBACK_UNAVAILABLE_TITLE,
                    PLAYBACK_NO_PROCESSED_OUTPUT_MESSAGE,
                )
                return
        
        if not self.playback_available or player is None or QMediaPlayer is None:
            QMessageBox.warning(
                self,
                PLAYBACK_UNAVAILABLE_TITLE,
                PLAYBACK_UNAVAILABLE_MESSAGE
            )
            return

        # Last-resort device fallback for active sink when no explicit selection exists.
        try:
            if QMediaDevices is not None and not self.output_device_description:
                if player is self.player and self.playback_controls is not None and self.playback_controls.audio_output is not None:
                    self.playback_controls.audio_output.setDevice(QMediaDevices.defaultAudioOutput())
                elif player is self.processed_player and self.processed_audio_output is not None:
                    self.processed_audio_output.setDevice(QMediaDevices.defaultAudioOutput())
        except Exception:
            pass

        if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            player.pause()
        else:
            player.play()

    def on_playback_state_changed(self, state):
        """Reflect playback state in the play/pause button text."""
        if QMediaPlayer is None:
            return
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_pause_btn.setText(PAUSE_BUTTON_TEXT)
        else:
            self.play_pause_btn.setText(PLAY_BUTTON_TEXT)

    def on_player_position_changed(self, position_ms):
        """Update slider, playhead, and time label as audio plays."""
        position_sec = position_ms / 1000.0
        if not self.user_is_seeking:
            self.playback_controls.sync_seek_position(position_ms)
        self.time_label.setText(self.format_time_label(position_sec))
        # Update playback position (inverted color line)
        self.update_playhead_position(position_sec)
        # Keep playhead centered while actively playing at any zoom level
        active_player = self.get_active_player()
        if (
            active_player is not None
            and QMediaPlayer is not None
            and active_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            and self.auto_follow_btn.isChecked()
            and not self.user_is_seeking
        ):
            self.pan_x_window_to_time(position_sec)

    def on_original_player_position_changed(self, position_ms):
        """Handle original-player position updates and keep processed player aligned."""
        self._sync_other_player_position(source="original", position_ms=position_ms)
        self.on_player_position_changed(position_ms)

    def on_processed_player_position_changed(self, position_ms):
        """Handle processed-player position updates and keep original player aligned."""
        self._sync_other_player_position(source="processed", position_ms=position_ms)
        self.on_player_position_changed(position_ms)

    def _sync_other_player_position(self, source, position_ms):
        """Mirror position updates between original and processed players without recursion."""
        if self._syncing_player_positions:
            return

        other_player = self.processed_player if source == "original" else self.player
        if other_player is None:
            return

        try:
            current_other = int(other_player.position())
        except Exception:
            return

        if abs(current_other - int(position_ms)) < 20:
            return

        self._syncing_player_positions = True
        try:
            other_player.setPosition(int(position_ms))
        finally:
            self._syncing_player_positions = False

    def on_seek_pressed(self):
        """Mark active user seek to avoid feedback loops from player updates."""
        self.user_is_seeking = True

    def on_seek_moved(self, value_ms):
        """Preview seekbar position (yellow line) while dragging and pan current zoom window on X axis."""
        position_sec = value_ms / 1000.0
        self.time_label.setText(self.format_time_label(position_sec))
        # Update seekbar indicator (yellow line) to show where user is dragging
        if self.playhead_manager is not None:
            self.playhead_manager.update_seekbar(position_sec, include_right=self.should_include_right_playhead())
        self.pan_x_window_to_time(position_sec)

    def on_seek_released(self):
        """Commit seek position to media player when dragging ends and jump playhead to that point."""
        value_ms = self.seek_slider.value()
        active_player = self.get_active_player()
        if active_player is not None:
            active_player.setPosition(value_ms)
        # Keep both players aligned in filter preview mode for A/B comparison.
        if self.player is not None:
            self.player.setPosition(value_ms)
        if self.processed_player is not None:
            self.processed_player.setPosition(value_ms)
        self.user_is_seeking = False

    def update_playhead_position(self, position_sec):
        """Move playback position marker (inverted color line) to the specified time in seconds."""
        if self.playhead_manager is not None:
            self.playhead_manager.update(position_sec, include_right=self.should_include_right_playhead())

    def pan_x_window_to_time(self, position_sec):
        """Keep current X zoom span but move it to center around seek position."""
        if self.y is None or self.sr is None:
            return

        duration = self.audio_duration_sec
        left_range = self.plot_left.getViewBox().viewRange()[0]
        window_width = max(0.01, left_range[1] - left_range[0])

        if window_width >= duration:
            start = 0.0
            end = duration
        else:
            half_width = window_width / 2.0
            start = max(0.0, min(position_sec - half_width, duration - window_width))
            end = start + window_width

        self.syncing = True
        self.plot_left.setXRange(start, end, padding=0)
        if self.should_include_right_playhead():
            self.plot_right.setXRange(start, end, padding=0)
        self.syncing = False

    def sync_plot_axis_layout(self):
        """Force matching left-axis widths so both plot view areas align horizontally."""
        left_axis = self.plot_left.getPlotItem().getAxis('left')
        right_axis = self.plot_right.getPlotItem().getAxis('left')
        target_width = max(left_axis.width(), right_axis.width(), 55)
        left_axis.setWidth(target_width)
        right_axis.setWidth(target_width)

    def format_time_label(self, current_sec):
        """Return a MM:SS / MM:SS label for current playback and total length."""
        total_sec = max(0.0, self.audio_duration_sec)
        current_text = self.format_mm_ss(current_sec)
        total_text = self.format_mm_ss(total_sec)
        return f"{current_text} / {total_text}"

    def set_filter_preview_mode(self, enabled):
        """Switch between normal audio viewer mode and filter preview mode."""
        if self.filter_preview_mode == enabled:
            return

        if not enabled and self.processed_player is not None:
            self.processed_player.pause()
        
        self.filter_preview_mode = enabled
        self.filter_preview_output = None

        if enabled:
            # Hide existing annotation overlays in filtering mode.
            self.clear_pending_annotation()
            self.redraw_annotations()
        
        # Show/hide playback mode selector based on mode
        self.playback_mode_widget.setVisible(enabled)
        
        if self.y is not None and self.sr is not None:
            self.update_ui_for_channels()
            self.display_audio()
    
    def set_filter_preview_channel(self, channel_index):
        """Set which channel to display in filter preview mode."""
        self.filter_preview_channel = max(0, min(channel_index, self.y.shape[0] - 1)) if self.y is not None else 0
        if self.filter_preview_mode and self.y is not None:
            self.display_audio()
    
    def set_filter_preview_output(self, output_signal):
        """Set the processed audio output for filter preview bottom plot."""
        self.filter_preview_output = output_signal
        
        # Initialize processed player with the output signal
        if output_signal is not None and QMediaPlayer is not None:
            output_array = np.asarray(output_signal, dtype=np.float32).flatten()
            # Save to temporary file for playback
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                import soundfile as sf
                sf.write(tmp.name, output_array, self.sr)
                tmp_path = tmp.name
        
            # Initialize processed player if not already created
            if self.processed_player is None:
                try:
                    audio_output = self.playback_controls.audio_output if self.playback_controls is not None else None
                    if audio_output is not None:
                        self.processed_audio_output = audio_output
                        self.processed_player = QMediaPlayer(self)
                        self.processed_player.setAudioOutput(audio_output)
                        self.processed_player.positionChanged.connect(self.on_processed_player_position_changed)
                        self.processed_player.playbackStateChanged.connect(self.on_playback_state_changed)
                except Exception:
                    pass
        
            # Set source for processed player
            if self.processed_player is not None:
                self.processed_player.setSource(QUrl.fromLocalFile(tmp_path))
                if self.player is not None:
                    self.processed_player.setPosition(self.player.position())
        
        if self.filter_preview_mode and self.y is not None:
            self.display_audio()

    def on_playback_mode_changed(self, index):
        """Handle playback mode selector change in filter preview mode."""
        self.filter_playback_mode = self.playback_mode_selector.currentData()
        # Stop current playback when switching modes
        if self.player is not None:
            self.player.pause()
        if self.processed_player is not None:
            self.processed_player.pause()
        active_player = self.get_active_player()
        if active_player is not None:
            self.playback_controls.sync_seek_position(active_player.position())
            self.time_label.setText(self.format_time_label(active_player.position() / 1000.0))
            self.update_playhead_position(active_player.position() / 1000.0)
        # Update button text to reflect current player state
        self.on_playback_state_changed(QMediaPlayer.PlaybackState.StoppedState if QMediaPlayer else None)

    def cleanup_multimedia(self):
        """Stop and detach multimedia backends to avoid noisy FFmpeg teardown warnings."""
        if self.interaction_manager is not None:
            try:
                self.interaction_manager.cleanup()
            except Exception:
                pass

        if self.test_tone_player is not None:
            try:
                self.test_tone_player.stop()
                self.test_tone_player.setSource(QUrl())
            except Exception:
                pass
        self._cleanup_test_tone_temp()

        if self.processed_player is not None:
            try:
                self.processed_player.positionChanged.disconnect(self.on_processed_player_position_changed)
            except Exception:
                pass
            try:
                self.processed_player.playbackStateChanged.disconnect(self.on_playback_state_changed)
            except Exception:
                pass
            try:
                self.processed_player.stop()
            except Exception:
                pass
            try:
                self.processed_player.setSource(QUrl())
            except Exception:
                pass
            try:
                self.processed_player.setAudioOutput(None)
            except Exception:
                pass
            try:
                self.processed_player.deleteLater()
            except Exception:
                pass
            self.processed_player = None

        if self.player is not None:
            try:
                self.player.stop()
            except Exception:
                pass
            try:
                self.player.setSource(QUrl())
            except Exception:
                pass

        if self.playback_controls is not None and getattr(self.playback_controls, "audio_output", None) is not None:
            try:
                self.playback_controls.audio_output.setMuted(True)
            except Exception:
                pass

        self.processed_audio_output = None

    @staticmethod
    def format_mm_ss(seconds):
        """Format seconds to MM:SS."""
        return format_mm_ss(seconds)

    # ===== Annotation Support Methods =====
    
    def set_annotations(self, annotations):
        """Set the list of annotations to display."""
        self.annotations = annotations
        if self.overlay_manager is not None:
            self.overlay_manager.set_annotations(self.annotations)
        self.redraw_annotations()
    
    def redraw_annotations(self):
        """Redraw all annotation blocks on the plots."""
        if self.overlay_manager is not None:
            if self.filter_preview_mode:
                self.overlay_manager.redraw_annotations(0)
                self.overlay_manager.clear_pending_annotation()
                return
            self.overlay_manager.redraw_annotations(self.audio_duration_sec)

    def enable_annotation_mode(self, mode):
        """Activate annotation drag-selection mode."""
        if self.y is None:
            return
        if self.interaction_manager is not None:
            self.interaction_manager.enable_annotation_mode(mode)

    def _cancel_annotation_mode(self):
        """Leave annotation mode and restore normal cursor."""
        if self.interaction_manager is not None:
            self.interaction_manager.cancel_annotation_mode()

    def set_pending_annotation(self, start_time, stop_time, color, channel):
        """Show a persistent draft annotation overlay while the user edits details."""
        if self.overlay_manager is not None:
            self.overlay_manager.set_pending_annotation(start_time, stop_time, color, channel)

    def clear_pending_annotation(self):
        """Remove the persistent draft annotation overlay."""
        if self.overlay_manager is not None:
            self.overlay_manager.clear_pending_annotation()

    def keyPressEvent(self, event):
        """Escape cancels annotation mode. Space toggles play/pause."""
        if event.key() == Qt.Key.Key_Space:
            self.toggle_playback()
            event.accept()
        elif self.interaction_manager is not None and self.interaction_manager.handle_key_press(event):
            event.accept()
        else:
            super().keyPressEvent(event)

