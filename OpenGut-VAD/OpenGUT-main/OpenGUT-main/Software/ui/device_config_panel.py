"""
Device Configuration Panel for PCB audio recording settings.
Generates and exports config.json for gastrointestinal sound recording device.
"""

import json
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QCheckBox,
                             QComboBox, QLineEdit, QPlainTextEdit, QPushButton, QLabel,
                             QFileDialog, QMessageBox)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QTimer

from const import (
    DEVICE_CONFIG_TITLE,
    DEVICE_CONFIG_SECTION_OPERATION,
    DEVICE_CONFIG_SECTION_AUDIO,
    DEVICE_CONFIG_SECTION_RECORDING,
    DEVICE_CONFIG_RECORDING,
    DEVICE_CONFIG_PLAYBACK,
    DEVICE_CONFIG_LOOPBACK,
    DEVICE_CONFIG_LABEL_SAMPLING_RATE,
    DEVICE_CONFIG_SAMPLING_RATES,
    DEVICE_CONFIG_LABEL_MICROPHONES,
    DEVICE_CONFIG_MIC_FRONT_ONLY,
    DEVICE_CONFIG_MIC_BACK_ONLY,
    DEVICE_CONFIG_MIC_BOTH,
    DEVICE_CONFIG_LABEL_DURATION,
    DEVICE_CONFIG_LABEL_FILENAME,
    DEVICE_CONFIG_DEFAULT_FILENAME,
    DEVICE_CONFIG_PREVIEW_TITLE,
    DEVICE_CONFIG_EXPORT_BTN,
    DEVICE_CONFIG_EXPORT_FILTER,
    SECTION_TITLE_STYLE,
)


class DeviceConfigPanel(QWidget):
    """Widget for configuring PCB device settings and exporting JSON config."""

    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        """Initialize the device configuration UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # Load Config button at top
        load_button_layout = QHBoxLayout()
        load_button_layout.addStretch()
        self.load_config_btn = QPushButton("Load Config")
        self.load_config_btn.setMaximumWidth(120)
        self.load_config_btn.clicked.connect(self.on_load_config)
        load_button_layout.addWidget(self.load_config_btn)
        main_layout.addLayout(load_button_layout)

        # Title
        title = QLabel(DEVICE_CONFIG_TITLE)
        title.setStyleSheet(SECTION_TITLE_STYLE)
        main_layout.addWidget(title)

        # Content area: form groups on the left, PCB image on the right
        content_hbox = QHBoxLayout()
        content_hbox.setSpacing(12)

        left_vbox = QVBoxLayout()
        left_vbox.setSpacing(8)

        # Operation Mode section
        operation_group = QGroupBox(DEVICE_CONFIG_SECTION_OPERATION)
        self.operation_group = operation_group
        operation_layout = QVBoxLayout(operation_group)
        operation_layout.setSpacing(6)

        self.recording_check = QCheckBox(DEVICE_CONFIG_RECORDING)
        self.recording_check.stateChanged.connect(self.on_recording_changed)
        operation_layout.addWidget(self.recording_check)

        playback_loopback_layout = QHBoxLayout()
        playback_loopback_layout.setSpacing(12)
        self.playback_check = QCheckBox(DEVICE_CONFIG_PLAYBACK)
        self.playback_check.stateChanged.connect(self.on_playback_changed)
        playback_loopback_layout.addWidget(self.playback_check)

        self.loopback_check = QCheckBox(DEVICE_CONFIG_LOOPBACK)
        self.loopback_check.stateChanged.connect(self.on_loopback_changed)
        playback_loopback_layout.addWidget(self.loopback_check)
        playback_loopback_layout.addStretch()
        operation_layout.addLayout(playback_loopback_layout)

        # Audio filename for Playback/Loopback
        audio_file_layout = QHBoxLayout()
        audio_file_layout.setSpacing(8)
        audio_file_layout.addWidget(QLabel("Audio File Name:"))
        self.audio_filename_input = QLineEdit()
        self.audio_filename_input.setPlaceholderText("e.g., audio_sample.wav")
        self.audio_filename_input.setMaximumWidth(250)
        self.audio_filename_input.textChanged.connect(self.on_config_changed)
        audio_file_layout.addWidget(self.audio_filename_input)
        audio_file_layout.addStretch()
        operation_layout.addLayout(audio_file_layout)

        left_vbox.addWidget(operation_group)

        # Audio Settings section
        audio_group = QGroupBox(DEVICE_CONFIG_SECTION_AUDIO)
        self.audio_group = audio_group
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.setSpacing(8)

        # Sampling rate
        sr_layout = QHBoxLayout()
        sr_layout.setSpacing(8)
        sr_layout.addWidget(QLabel(DEVICE_CONFIG_LABEL_SAMPLING_RATE))
        self.sampling_rate_combo = QComboBox()
        for rate in DEVICE_CONFIG_SAMPLING_RATES:
            self.sampling_rate_combo.addItem(f"{rate} Hz", rate)
        self.sampling_rate_combo.setCurrentIndex(3)  # Default 16000 Hz
        self.sampling_rate_combo.currentIndexChanged.connect(self.on_config_changed)
        sr_layout.addWidget(self.sampling_rate_combo)
        sr_layout.addStretch()
        audio_layout.addLayout(sr_layout)

        # Microphones
        mic_layout = QHBoxLayout()
        mic_layout.setSpacing(8)
        mic_layout.addWidget(QLabel(DEVICE_CONFIG_LABEL_MICROPHONES))
        self.microphones_combo = QComboBox()
        self.microphones_combo.addItem(DEVICE_CONFIG_MIC_FRONT_ONLY, "front_only")
        self.microphones_combo.addItem(DEVICE_CONFIG_MIC_BACK_ONLY, "back_only")
        self.microphones_combo.addItem(DEVICE_CONFIG_MIC_BOTH, "stereo")
        self.microphones_combo.setCurrentIndex(0)  # Default front only
        self.microphones_combo.currentIndexChanged.connect(self.on_config_changed)
        mic_layout.addWidget(self.microphones_combo)
        mic_layout.addStretch()
        audio_layout.addLayout(mic_layout)

        left_vbox.addWidget(audio_group)

        # Recording Options section (shown when Recording is checked)
        recording_group = QGroupBox(DEVICE_CONFIG_SECTION_RECORDING)
        recording_layout = QVBoxLayout(recording_group)
        recording_layout.setSpacing(8)

        # Duration
        duration_layout = QVBoxLayout()
        duration_layout.setSpacing(4)
        
        duration_input_layout = QHBoxLayout()
        duration_input_layout.setSpacing(8)
        duration_input_layout.addWidget(QLabel(DEVICE_CONFIG_LABEL_DURATION))
        self.duration_input = QLineEdit()
        self.duration_input.setText("00:30:00")
        self.duration_input.setPlaceholderText("hh:mm:ss")
        self.duration_input.textChanged.connect(self.on_config_changed)
        self.duration_input.setMaximumWidth(150)
        duration_input_layout.addWidget(self.duration_input)
        duration_input_layout.addStretch()
        duration_layout.addLayout(duration_input_layout)
        
        duration_desc = QLabel("(Note: Duration will be exported as total seconds)")
        duration_desc.setStyleSheet("color: gray; font-size: 11px;")
        duration_layout.addWidget(duration_desc)
        recording_layout.addLayout(duration_layout)

        # Filename
        filename_layout = QHBoxLayout()
        filename_layout.setSpacing(8)
        filename_layout.addWidget(QLabel(DEVICE_CONFIG_LABEL_FILENAME))
        self.filename_input = QLineEdit()
        self.filename_input.setText(DEVICE_CONFIG_DEFAULT_FILENAME)
        self.filename_input.textChanged.connect(self.on_config_changed)
        filename_layout.addWidget(self.filename_input)
        filename_layout.addStretch()
        recording_layout.addLayout(filename_layout)

        recording_group.setEnabled(False)
        self.recording_group = recording_group
        left_vbox.addWidget(recording_group)
        self.left_group_spacing = left_vbox.spacing()

        content_hbox.addLayout(left_vbox, 1)

        # PCB reference image on the right
        right_vbox = QVBoxLayout()
        right_vbox.setContentsMargins(0, 0, 0, 0)
        right_vbox.setSpacing(0)
        right_vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.right_vbox = right_vbox
        _pcb_path = Path(__file__).resolve().parent / "images" / "pcb.png"
        if _pcb_path.exists():
            self.pcb_label = QLabel()
            self.pcb_pixmap = QPixmap(str(_pcb_path))
            self.pcb_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.pcb_label.setToolTip("OpenGUT PCB recording device")
            right_vbox.addWidget(self.pcb_label)
        else:
            self.pcb_label = None
            self.pcb_pixmap = None
        right_vbox.addStretch()
        content_hbox.addLayout(right_vbox)

        main_layout.addLayout(content_hbox)

        # JSON Preview section
        preview_label = QLabel(DEVICE_CONFIG_PREVIEW_TITLE)
        preview_label.setStyleSheet(SECTION_TITLE_STYLE)
        main_layout.addWidget(preview_label)

        self.json_preview = QPlainTextEdit()
        self.json_preview.setReadOnly(True)
        self.json_preview.setMaximumHeight(250)
        self.json_preview.setMinimumHeight(150)
        main_layout.addWidget(self.json_preview)

        # Export button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        self.export_btn = QPushButton(DEVICE_CONFIG_EXPORT_BTN)
        self.export_btn.setMaximumWidth(150)
        self.export_btn.clicked.connect(self.on_export_config)
        button_layout.addWidget(self.export_btn)
        main_layout.addLayout(button_layout)

        main_layout.addStretch()

        self.update_preview()
        QTimer.singleShot(0, self.update_pcb_image_alignment)

    def update_pcb_image_alignment(self):
        """Align PCB image with the left configuration group stack."""
        if self.pcb_label is None or self.pcb_pixmap is None:
            return

        # Use size hints to avoid resize feedback loops from live geometry.
        operation_height = self.operation_group.sizeHint().height()
        audio_height = self.audio_group.sizeHint().height()
        recording_height = self.recording_group.sizeHint().height()
        total_height = operation_height + audio_height + recording_height + (self.left_group_spacing * 2)

        top_offset = self.operation_group.fontMetrics().height() + 10
        target_height = max(120, total_height - top_offset)
        scaled = self.pcb_pixmap.scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation)

        current_pixmap = self.pcb_label.pixmap()
        if current_pixmap is not None and current_pixmap.size() == scaled.size():
            return

        self.right_vbox.setContentsMargins(0, top_offset, 0, 0)
        self.pcb_label.setPixmap(scaled)
        self.pcb_label.setFixedSize(scaled.size())

    def on_recording_changed(self, state):
        """Enable/disable recording options group based on recording checkbox."""
        self.recording_group.setEnabled(self.recording_check.isChecked())
        self.on_config_changed()
        QTimer.singleShot(0, self.update_pcb_image_alignment)

    def _enforce_playback_loopback_exclusivity(self, source):
        """Keep playback/loopback mutually exclusive based on the toggled source."""
        if source == "playback" and self.playback_check.isChecked() and self.loopback_check.isChecked():
            self.loopback_check.blockSignals(True)
            self.loopback_check.setChecked(False)
            self.loopback_check.blockSignals(False)
        elif source == "loopback" and self.loopback_check.isChecked() and self.playback_check.isChecked():
            self.playback_check.blockSignals(True)
            self.playback_check.setChecked(False)
            self.playback_check.blockSignals(False)

    def on_playback_changed(self, state):
        """Ensure Playback and Loopback are mutually exclusive."""
        self._enforce_playback_loopback_exclusivity("playback")
        self.on_config_changed()

    def on_loopback_changed(self, state):
        """Ensure Playback and Loopback are mutually exclusive."""
        self._enforce_playback_loopback_exclusivity("loopback")
        self.on_config_changed()

    def on_config_changed(self):
        """Update JSON preview when any configuration changes."""
        # Re-enable recording group if recording is checked
        if self.recording_check.isChecked() != self.recording_group.isEnabled():
            self.recording_group.setEnabled(self.recording_check.isChecked())
        self.update_preview()

    def duration_to_seconds(self, duration_str):
        """Convert hh:mm:ss format to total seconds."""
        try:
            parts = duration_str.split(":")
            if len(parts) != 3:
                return None
            hours, minutes, seconds = map(int, parts)
            total_seconds = hours * 3600 + minutes * 60 + seconds
            return total_seconds
        except (ValueError, AttributeError):
            return None

    def get_config_dict(self):
        """Build the configuration dictionary from current UI state."""
        config = {
            "operation_mode": {
                "recording": self.recording_check.isChecked(),
                "playback": self.playback_check.isChecked(),
                "loopback": self.loopback_check.isChecked(),
            },
            "sampling_rate": int(self.sampling_rate_combo.currentData() or 16000),
            "microphones": str(self.microphones_combo.currentData() or "front_only"),
        }
        
        # Add recording-specific fields
        if self.recording_check.isChecked():
            config["recording_duration_seconds"] = self.duration_to_seconds(self.duration_input.text())
            config["file_name"] = self.filename_input.text()
        
        # Add playback/loopback audio filename if applicable
        if self.playback_check.isChecked() or self.loopback_check.isChecked():
            config["audio_file_name"] = self.audio_filename_input.text().strip()
        
        return config

    def update_preview(self):
        """Update the JSON preview pane with current configuration."""
        config = self.get_config_dict()
        json_str = json.dumps(config, indent=2)
        self.json_preview.setPlainText(json_str)

    def on_load_config(self):
        """Load existing config.json and populate UI fields."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Device Configuration",
            "",
            "JSON Files (*.json);;All Files (*)",
        )

        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            
            # Load operation modes
            op_mode = config.get("operation_mode", {})
            self.recording_check.blockSignals(True)
            self.playback_check.blockSignals(True)
            self.loopback_check.blockSignals(True)
            
            self.recording_check.setChecked(op_mode.get("recording", False))
            self.playback_check.setChecked(op_mode.get("playback", False))
            self.loopback_check.setChecked(op_mode.get("loopback", False))
            
            self.recording_check.blockSignals(False)
            self.playback_check.blockSignals(False)
            self.loopback_check.blockSignals(False)
            
            # Load sampling rate
            sample_rate = config.get("sampling_rate", 16000)
            idx = self.sampling_rate_combo.findData(sample_rate)
            if idx >= 0:
                self.sampling_rate_combo.setCurrentIndex(idx)
            
            # Load microphones
            mic_mode = config.get("microphones", "front_only")
            idx = self.microphones_combo.findData(mic_mode)
            if idx >= 0:
                self.microphones_combo.setCurrentIndex(idx)
            
            # Load recording duration (convert seconds back to hh:mm:ss)
            duration_seconds = config.get("recording_duration_seconds")
            if duration_seconds is not None:
                hours = int(duration_seconds) // 3600
                minutes = (int(duration_seconds) % 3600) // 60
                secs = int(duration_seconds) % 60
                self.duration_input.setText(f"{hours:02d}:{minutes:02d}:{secs:02d}")
            
            # Load filename
            self.filename_input.setText(config.get("file_name", ""))
            
            # Load audio filename
            self.audio_filename_input.setText(config.get("audio_file_name", ""))
            
            # Update UI state
            self.recording_group.setEnabled(self.recording_check.isChecked())
            self.on_config_changed()
            
            QMessageBox.information(self, "Success", f"Config loaded from:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Load Failed", f"Error loading config:\n{str(e)}")

    def on_export_config(self):
        """Export configuration as JSON file."""
        if (self.playback_check.isChecked() or self.loopback_check.isChecked()) and not self.audio_filename_input.text().strip():
            QMessageBox.warning(
                self,
                "Missing Audio File Name",
                "Playback/Loopback mode requires an audio file name before exporting config.json.",
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Device Configuration",
            "config.json",
            DEVICE_CONFIG_EXPORT_FILTER,
        )

        if not file_path:
            return

        try:
            config = self.get_config_dict()
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            QMessageBox.information(self, "Success", f"Config exported to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Error exporting config:\n{str(e)}")
