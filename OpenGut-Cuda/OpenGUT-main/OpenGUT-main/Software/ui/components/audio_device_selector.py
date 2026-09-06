"""Audio output device selector with test tone functionality."""

import importlib
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox, QPushButton, QMessageBox

QMediaDevices = None
try:
    qt_multimedia = importlib.import_module("PyQt6.QtMultimedia")
    QMediaDevices = qt_multimedia.QMediaDevices
except Exception:
    pass

class AudioDeviceSelector(QWidget):
    """Widget for selecting audio output device with test tone capability."""

    def __init__(self, on_device_changed=None, on_test_requested=None):
        super().__init__()
        self.selected_device_description = None
        self._virtual_hint_shown_for = None
        self.on_device_changed_callback = on_device_changed
        self.on_test_requested_callback = on_test_requested
        self.init_ui()

    @staticmethod
    def _is_virtual_sink_device(description):
        if not description:
            return False
        text = str(description).lower()
        return any(token in text for token in ("blackhole", "soundflower", "loopback", "virtual"))

    def _maybe_show_virtual_sink_hint(self):
        if not self._is_virtual_sink_device(self.selected_device_description):
            return
        if self._virtual_hint_shown_for == self.selected_device_description:
            return

        self._virtual_hint_shown_for = self.selected_device_description
        QMessageBox.information(
            self,
            "Virtual Output Selected",
            "You selected a virtual output device. This often does not produce audible sound by itself.\n\n"
            "To hear audio, monitor this virtual device to speakers/headphones using:\n"
            "- macOS Audio MIDI Setup (Multi-Output Device), or\n"
            "- your DAW/loopback monitor route.",
        )

    def init_ui(self):
        """Initialize the audio device selector UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Audio Output Device:"))

        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        layout.addWidget(self.device_combo)

        self.test_btn = QPushButton("Test (440Hz)")
        self.test_btn.clicked.connect(self.request_test_tone)
        layout.addWidget(self.test_btn)

        layout.addStretch()

        self.refresh_devices()

    def refresh_devices(self):
        """Enumerate and populate audio output devices from Qt multimedia."""
        self.device_combo.blockSignals(True)
        self.device_combo.clear()

        if QMediaDevices is None:
            self.device_combo.addItem("Qt multimedia devices unavailable", "")
            self.test_btn.setEnabled(False)
            self.device_combo.blockSignals(False)
            return

        outputs = list(QMediaDevices.audioOutputs())
        if not outputs:
            self.device_combo.addItem("No output devices", "")
            self.test_btn.setEnabled(False)
            self.device_combo.blockSignals(False)
            return

        default_output = QMediaDevices.defaultAudioOutput()
        default_description = default_output.description() if default_output is not None else ""

        for output in outputs:
            description = output.description()
            marker = " (default)" if description == default_description else ""
            self.device_combo.addItem(f"{description}{marker}", description)

        selected_idx = -1
        for i in range(self.device_combo.count()):
            payload = self.device_combo.itemData(i)
            if isinstance(payload, str) and payload == default_description:
                selected_idx = i
                break
        if selected_idx < 0:
            selected_idx = 0
        self.device_combo.setCurrentIndex(selected_idx)
        payload = self.device_combo.currentData()
        self.selected_device_description = payload if isinstance(payload, str) else None

        self.test_btn.setEnabled(self.selected_device_description is not None)
        self.device_combo.blockSignals(False)

        self._maybe_show_virtual_sink_hint()

        if self.on_device_changed_callback is not None and self.selected_device_description:
            self.on_device_changed_callback(self.selected_device_description)

    def on_device_changed(self, index):
        """Handle device selection change."""
        payload = self.device_combo.currentData()
        if not isinstance(payload, str):
            return
        self.selected_device_description = payload
        if not self.selected_device_description:
            return

        self._maybe_show_virtual_sink_hint()

        if self.on_device_changed_callback is not None:
            self.on_device_changed_callback(self.selected_device_description)

    def request_test_tone(self):
        """Request output-device test tone playback via callback."""
        if self.on_test_requested_callback is not None:
            self.on_test_requested_callback()

    def get_selected_device_description(self):
        """Return the currently selected Qt audio output description."""
        return self.selected_device_description
