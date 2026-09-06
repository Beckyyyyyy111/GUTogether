"""
Annotation panel widget for managing audio annotations.
Provides controls for creating, editing, and exporting annotated segments.
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                             QLineEdit, QDoubleSpinBox, QTextEdit, QPushButton, QLabel,
                             QFileDialog, QMessageBox, QSplitter, QCheckBox, QTabWidget,
                             QComboBox, QSpinBox, QColorDialog, QDialog,
                             QDialogButtonBox)
from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot, QUrl
from PyQt6.QtGui import QDesktopServices, QColor, QPixmap, QIcon
import inspect
import soundfile as sf
import numpy as np
import json
import tempfile
from datetime import datetime
from pathlib import Path

from .annotation_model import Annotation
from filters.filter_loader import discover_filters
from const import (
    ANNOTATION_TIME_DECIMALS,
    ANNOTATION_TIME_MAX_SECONDS,
    ANNOTATION_DEFAULT_COLORS,
    ANNOTATION_CHANNEL_MONO,
    ANNOTATION_CHANNEL_LEFT,
    ANNOTATION_CHANNEL_RIGHT,
    ANNOTATION_CHANNEL_BOTH,
    BUTTON_ADD,
    BUTTON_APPLYING_FILTER,
    BUTTON_DELETE,
    BUTTON_EXPORT_SEGMENT,
    BUTTON_UPDATE,
    BUTTON_LOAD_ANNOTATION_JSON,
    BUTTON_EXPORT_ANNOTATION_JSON,
    CHANNEL_1_LABEL,
    COMMENT_BOX_HEIGHT,
    FILE_FILTER_WAVE,
    FILTERED_EXPORT_LEFT_SUFFIX,
    FILTERED_EXPORT_MONO_SUFFIX,
    FILTERED_EXPORT_RIGHT_SUFFIX,
    FILTERED_EXPORT_STEREO_SUFFIX,
    FILTER_BUSY_LABEL,
    FILTER_BUSY_TITLE,
    FILTER_OUTPUT_LOG_TEMPLATE,
    FILTER_TEMP_DIR_NAME,
    JSON_SUFFIX,
    LABEL_CHANNEL,
    LABEL_CHANNEL_TEMPLATE,
    LABEL_CHANNEL_SELECT,
    LABEL_COLOR,
    LABEL_COMMENT,
    LABEL_FILTER_UNIT,
    LABEL_LEFT_SHORT,
    LABEL_NAME,
    LABEL_RIGHT_SHORT,
    LABEL_START,
    LABEL_STEREO,
    LABEL_STOP,
    MSG_ANNOTATION_NAME_REQUIRED,
    MSG_FILTER_ERROR_TITLE,
    MSG_FAILED_APPLY_FILTER,
    MSG_FAILED_LOAD_ANNOTATIONS,
    MSG_FAILED_LOAD_FILTER_MODULES,
    MSG_FAILED_READ_FILTER_SCHEMA,
    MSG_FAILED_SAVE_ANNOTATIONS,
    MSG_EXPORT_FAILED,
    MSG_EXPORTED_SUCCESS,
    MSG_ERROR_TITLE,
    MSG_LOAD_AUDIO_BEFORE_FILTER,
    MSG_NO_AUDIO_LOADED,
    MSG_NO_FILTER_SELECTED,
    MSG_SELECT_ANNOTATION_TO_DELETE,
    MSG_SELECT_ANNOTATION_TO_EXPORT,
    MSG_SELECT_ANNOTATION_TO_UPDATE,
    MSG_SELECT_EXPORT_CHANNEL_OPTION,
    MSG_START_BEFORE_STOP,
    MSG_SUCCESS_TITLE,
    MSG_WARNING_TITLE,
    PROMPT_EXPORT_ANNOTATION_BASE,
    PANEL_TITLE_PROCESSING,
    TAB_ANNOTATION,
    TAB_FILTERING,
    TEXT_FILTER_APPLIED_STATUS,
    TEXT_FILTER_STATUS_IDLE,
    TEXT_NO_FILTERS_FOUND,
    TEXT_PROGRESS_BUILDING_FILTER_OUTPUT,
    TEXT_PROGRESS_PREPARING_FILTER_INPUTS,
    TEXT_PROGRESS_WRITING_LOGS,
    TIMESTAMP_FORMAT,
    ANNOTATION_LIST_ITEM_TEMPLATE,
)


def normalize_signal_length(signal_data, target_len):
    """Match filter output length to source channel length."""
    output = np.asarray(signal_data, dtype=np.float32).flatten()
    if len(output) == target_len:
        return output
    if len(output) <= 1:
        return np.zeros(target_len, dtype=np.float32)

    src_x = np.linspace(0.0, 1.0, num=len(output), endpoint=True)
    dst_x = np.linspace(0.0, 1.0, num=target_len, endpoint=True)
    return np.interp(dst_x, src_x, output).astype(np.float32)


def sanitize_name_part(value):
    text = "" if value is None else str(value)
    allowed = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_"):
            allowed.append(ch)
        else:
            allowed.append("_")
    compact = "".join(allowed).strip("_")
    return compact or "unknown"


class FilterApplyWorker(QObject):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, loaded_filter, audio, sr, channel_index, params, current_audio_path, output_dir):
        super().__init__()
        self.loaded_filter = loaded_filter
        self.audio = np.asarray(audio, dtype=np.float32)
        self.sr = int(sr)
        self.channel_index = int(channel_index)
        self.params = dict(params)
        self.current_audio_path = current_audio_path
        self.output_dir = str(output_dir)

    def _backend_progress(self, value, detail_text=""):
        """Map backend progress into the main busy dialog range."""
        clamped = max(0, min(int(value), 100))
        mapped = 15 + int(clamped * 0.55)
        self.progress.emit(mapped, detail_text)

    @pyqtSlot()
    def run(self):
        try:
            self.progress.emit(10, TEXT_PROGRESS_PREPARING_FILTER_INPUTS)

            apply_signature = inspect.signature(self.loaded_filter.instance.apply)
            apply_kwargs = {}
            if "progress_callback" in apply_signature.parameters:
                apply_kwargs["progress_callback"] = self._backend_progress

            output_channel = self.loaded_filter.instance.apply(
                self.audio,
                self.sr,
                self.channel_index,
                self.params,
                self.current_audio_path,
                self.output_dir,
                **apply_kwargs,
            )
            self.progress.emit(75, TEXT_PROGRESS_BUILDING_FILTER_OUTPUT)

            target_len = self.audio.shape[-1]
            normalized = normalize_signal_length(output_channel, target_len)
            self.finished.emit(
                {
                    "normalized": normalized,
                    "channel_index": self.channel_index,
                    "params": self.params,
                    "file_stem": self.loaded_filter.file_stem,
                    "output_dir": self.output_dir,
                }
            )
        except Exception as exc:
            self.error.emit(str(exc))


class AnnotationPanelWidget(QWidget):
    # Signal emitted when filter tab is activated/deactivated
    filter_tab_activated = pyqtSignal(bool)  # True when filtering tab is active
    # Signal emitted when a new annotation is created from interactive selection
    annotation_created = pyqtSignal(str, float, float, str)  # name, start, stop, channel
    # Signal emitted when annotations list changes (add, update, delete)
    annotations_changed = pyqtSignal(list)  # Emits list of Annotation objects
    # Signal emitted while editing a newly selected draft annotation region
    draft_annotation_changed = pyqtSignal(float, float, str, str)  # start, stop, color, channel
    draft_annotation_cleared = pyqtSignal()
    source_audio_swapped = pyqtSignal(str, object, int, bool)  # new_path, audio, sr, is_mono
    
    def __init__(self):
        super().__init__()
        self.annotations = []  # List of Annotation objects
        self.current_audio = None
        self.current_sr = None
        self.is_mono = True
        self.current_audio_path = None
        self.color_index = 0  # For cycling through default colors
        self.has_pending_selection = False
        self.loaded_filters = []
        self.filter_param_widgets = {}
        self.filtered_channel = None
        self.filtered_channel_index = None
        self.filtered_output_path = None
        self.filtered_output_dir = None
        self.last_swap_log_path = None
        self.source_swap_history = []
        self.filter_temp_dir = Path(tempfile.gettempdir()) / FILTER_TEMP_DIR_NAME
        self.filter_temp_dir.mkdir(parents=True, exist_ok=True)
        self.working_directory = None
        self.set_busy_callback = None
        self.show_busy_callback = None
        self.update_busy_callback = None
        self.clear_busy_callback = None
        self.run_background_task_callback = None
        self.audio_viewer = None  # Reference to audio viewer for filter preview updates

        self.init_ui()
    
    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Create tab widget for filtering and annotation tabs
        self.tab_widget = QTabWidget()
        
        # Create splitter for list and details in annotation tab
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Top section: List of annotations
        self.annotation_list = QListWidget()
        self.annotation_list.itemClicked.connect(self.on_annotation_selected)
        splitter.addWidget(self.annotation_list)
        
        # Bottom section: Annotation details
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(4, 4, 4, 4)
        details_layout.setSpacing(3)
        
        # Annotation name
        name_layout = QHBoxLayout()
        name_layout.setSpacing(4)
        name_layout.addWidget(QLabel(LABEL_NAME))
        self.name_input = QLineEdit()
        name_layout.addWidget(self.name_input)
        details_layout.addLayout(name_layout)
        
        # Start and Stop time on one row
        time_layout = QHBoxLayout()
        time_layout.setSpacing(4)
        time_layout.addWidget(QLabel(LABEL_START))
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0, ANNOTATION_TIME_MAX_SECONDS)
        self.start_spin.setDecimals(ANNOTATION_TIME_DECIMALS)
        time_layout.addWidget(self.start_spin)
        time_layout.addWidget(QLabel(LABEL_STOP))
        self.stop_spin = QDoubleSpinBox()
        self.stop_spin.setRange(0, ANNOTATION_TIME_MAX_SECONDS)
        self.stop_spin.setDecimals(ANNOTATION_TIME_DECIMALS)
        time_layout.addWidget(self.stop_spin)
        details_layout.addLayout(time_layout)
        
        # Color and Channel selectors
        color_channel_layout = QHBoxLayout()
        color_channel_layout.setSpacing(4)
        
        # Color picker
        color_channel_layout.addWidget(QLabel(LABEL_COLOR))
        self.color_button = QPushButton()
        self.color_button.setMaximumWidth(60)
        self.color_button.setMinimumHeight(24)
        self.color_button.clicked.connect(self.pick_color)
        self.annotation_color = ANNOTATION_DEFAULT_COLORS[0]
        self.update_color_button()
        color_channel_layout.addWidget(self.color_button)
        
        # Channel selector
        self.channel_label = QLabel(LABEL_CHANNEL_SELECT)
        color_channel_layout.addWidget(self.channel_label)
        self.channel_combo = QComboBox()
        self.channel_combo.currentTextChanged.connect(lambda _text: self.emit_draft_annotation())
        color_channel_layout.addWidget(self.channel_combo)
        color_channel_layout.addStretch()
        details_layout.addLayout(color_channel_layout)
        self.populate_annotation_channel_options(is_mono=True)
        
        # Comment (label and input on one row)
        comment_row_layout = QHBoxLayout()
        comment_row_layout.setSpacing(4)
        comment_row_layout.addWidget(QLabel(LABEL_COMMENT))
        self.comment_input = QTextEdit()
        self.comment_input.setMaximumHeight(COMMENT_BOX_HEIGHT)
        self.comment_input.setMinimumHeight(COMMENT_BOX_HEIGHT)
        comment_row_layout.addWidget(self.comment_input)
        details_layout.addLayout(comment_row_layout)

        self.start_spin.valueChanged.connect(lambda _value: self.emit_draft_annotation())
        self.stop_spin.valueChanged.connect(lambda _value: self.emit_draft_annotation())
        
        # CRUD buttons
        action_layout = QHBoxLayout()
        action_layout.setSpacing(2)
        self.add_btn = QPushButton(BUTTON_ADD)
        self.add_btn.clicked.connect(self.add_annotation)
        action_layout.addWidget(self.add_btn)
        self.update_btn = QPushButton(BUTTON_UPDATE)
        self.update_btn.clicked.connect(self.update_annotation)
        action_layout.addWidget(self.update_btn)
        self.delete_btn = QPushButton(BUTTON_DELETE)
        self.delete_btn.clicked.connect(self.delete_annotation)
        self.delete_btn.setStyleSheet("color: #8B0000; font-weight: 600;")
        action_layout.addWidget(self.delete_btn)
        details_layout.addLayout(action_layout)

        splitter.addWidget(details_widget)
        splitter.setSizes([150, 220])
        
        # Annotation tab content
        annotation_tab = QWidget()
        annotation_tab_layout = QVBoxLayout(annotation_tab)
        annotation_tab_layout.setContentsMargins(0, 0, 0, 0)
        annotation_tab_layout.addWidget(splitter)

        # Export section (annotation tab only)
        export_section_layout = QVBoxLayout()
        export_section_layout.setContentsMargins(4, 4, 4, 4)
        export_section_layout.setSpacing(4)

        metadata_layout = QHBoxLayout()
        metadata_layout.setSpacing(2)

        self.load_annotations_btn = QPushButton(BUTTON_LOAD_ANNOTATION_JSON)
        self.load_annotations_btn.clicked.connect(self.load_annotations_from_file)
        metadata_layout.addWidget(self.load_annotations_btn)

        self.export_annotations_btn = QPushButton(BUTTON_EXPORT_ANNOTATION_JSON)
        self.export_annotations_btn.clicked.connect(self.export_annotations_to_file)
        metadata_layout.addWidget(self.export_annotations_btn)

        metadata_layout.addStretch()
        export_section_layout.addLayout(metadata_layout)

        export_layout = QHBoxLayout()
        export_layout.setSpacing(2)

        self.export_btn = QPushButton(BUTTON_EXPORT_SEGMENT)
        self.export_btn.clicked.connect(self.export_segment)
        export_layout.addWidget(self.export_btn)
        self.export_all_btn = QPushButton("Export All Segments")
        self.export_all_btn.clicked.connect(self.export_all_segments)
        export_layout.addWidget(self.export_all_btn)
        export_layout.addStretch()
        export_section_layout.addLayout(export_layout)

        annotation_tab_layout.addLayout(export_section_layout)
        
        # Filtering tab
        filtering_tab = QWidget()
        filtering_tab_layout = QVBoxLayout(filtering_tab)
        filtering_tab_layout.setContentsMargins(4, 4, 4, 4)
        filtering_tab_layout.setSpacing(6)

        filter_control_layout = QVBoxLayout()
        filter_control_layout.setSpacing(4)

        filter_selector_row = QHBoxLayout()
        filter_selector_row.setSpacing(6)
        filter_selector_row.addWidget(QLabel(LABEL_FILTER_UNIT))
        self.filter_selector = QComboBox()
        self.filter_selector.currentIndexChanged.connect(self.on_filter_selected)
        filter_selector_row.addWidget(self.filter_selector, 1)
        filter_control_layout.addLayout(filter_selector_row)

        channel_row = QHBoxLayout()
        channel_row.setSpacing(6)
        self.filter_channel_label = QLabel(LABEL_CHANNEL)
        channel_row.addWidget(self.filter_channel_label)
        self.filter_channel_selector = QComboBox()
        self.filter_channel_selector.addItem(CHANNEL_1_LABEL, 0)
        self.filter_channel_selector.currentIndexChanged.connect(lambda _idx: self.refresh_filter_previews())
        channel_row.addWidget(self.filter_channel_selector)
        channel_row.addStretch()
        filter_control_layout.addLayout(channel_row)
        # Hidden until audio is loaded; visibility is managed by update_filter_channel_options.
        self.filter_channel_label.setVisible(False)
        self.filter_channel_selector.setVisible(False)

        filtering_tab_layout.addLayout(filter_control_layout)

        self.filter_params_layout = QVBoxLayout()
        filtering_tab_layout.addLayout(self.filter_params_layout)

        apply_row = QHBoxLayout()
        apply_row.setContentsMargins(0, 0, 0, 0)
        self.apply_filter_btn = QPushButton(BUTTON_APPLYING_FILTER)
        self.apply_filter_btn.clicked.connect(self.apply_selected_filter)
        apply_row.addWidget(self.apply_filter_btn)

        self.swap_filtered_btn = QPushButton("Swap Source With Filtered Output")
        self.swap_filtered_btn.setEnabled(False)
        self.swap_filtered_btn.clicked.connect(self.swap_source_with_filtered_output)
        apply_row.addWidget(self.swap_filtered_btn)
        apply_row.addStretch()
        filtering_tab_layout.addLayout(apply_row)

        # Use audio viewer spectrograms instead of separate preview plots
        filtering_tab_layout.addStretch()

        # Filter results display with button to open output folder
        results_layout = QHBoxLayout()
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(6)
        self.filter_status_label = QLabel(TEXT_FILTER_STATUS_IDLE)
        results_layout.addWidget(self.filter_status_label, 1)
        self.show_results_btn = QPushButton("Show Results")
        self.show_results_btn.setMaximumWidth(120)
        self.show_results_btn.clicked.connect(self.on_show_filter_results)
        self.show_results_btn.setEnabled(False)
        results_layout.addWidget(self.show_results_btn)
        filtering_tab_layout.addLayout(results_layout)
        
        # Add tabs (Annotation first, then Filtering)
        self.tab_widget.addTab(annotation_tab, TAB_ANNOTATION)
        self.tab_widget.addTab(filtering_tab, TAB_FILTERING)
        
        # Connect tab changes to filter preview mode signal
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        
        main_layout.addWidget(self.tab_widget, 1)
        self.setLayout(main_layout)
        self.current_selection = None
        self.load_filter_plugins()

    def set_busy_handlers(self, set_busy, show_busy, update_busy, clear_busy, run_background_task=None):
        """Register main-window busy handlers for long filter processing."""
        self.set_busy_callback = set_busy
        self.show_busy_callback = show_busy
        self.update_busy_callback = update_busy
        self.clear_busy_callback = clear_busy
        self.run_background_task_callback = run_background_task

    def set_audio_viewer(self, audio_viewer):
        """Set reference to audio viewer for filter preview updates."""
        self.audio_viewer = audio_viewer

    def show_filter_busy(self):
        """Enter busy mode while running filter backends."""
        if self.set_busy_callback is not None:
            self.set_busy_callback(True)
        if self.show_busy_callback is not None:
            self.show_busy_callback(FILTER_BUSY_TITLE, FILTER_BUSY_LABEL, 0)

    def update_filter_busy(self, value, detail_text=""):
        """Update busy dialog progress if callbacks are available."""
        if self.update_busy_callback is not None:
            self.update_busy_callback(value, detail_text)

    def clear_filter_busy(self):
        """Exit busy mode after filter processing."""
        if self.clear_busy_callback is not None:
            self.clear_busy_callback()
        elif self.set_busy_callback is not None:
            self.set_busy_callback(False)

    def set_working_directory(self, directory_path):
        """Set preferred working directory for filter outputs and metadata."""
        value = str(directory_path).strip() if directory_path is not None else ""
        self.working_directory = value or None

    def get_filter_output_dir(self):
        """Return preferred output directory for filtered artifacts."""
        if self.working_directory:
            output_dir = Path(self.working_directory)
            output_dir.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
            return output_dir
        if self.current_audio_path:
            output_dir = Path(self.current_audio_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
            return output_dir
        return self.filter_temp_dir

    def load_filter_plugins(self):
        """Discover filter modules from the dedicated filters folder."""
        filters_dir = Path(__file__).resolve().parent.parent / "filters"
        try:
            self.loaded_filters = discover_filters(filters_dir)
        except Exception as exc:
            self.loaded_filters = []
            QMessageBox.warning(self, MSG_FILTER_ERROR_TITLE, MSG_FAILED_LOAD_FILTER_MODULES.format(error=exc))

        self.filter_selector.blockSignals(True)
        self.filter_selector.clear()
        for loaded in self.loaded_filters:
            filter_name = getattr(loaded.instance, "name", loaded.file_stem)
            self.filter_selector.addItem(filter_name)
        self.filter_selector.blockSignals(False)

        if self.loaded_filters:
            self.on_filter_selected(0)
        else:
            self.filter_status_label.setText(TEXT_NO_FILTERS_FOUND)

    def current_filter(self):
        """Return selected loaded filter descriptor."""
        idx = self.filter_selector.currentIndex()
        if idx < 0 or idx >= len(self.loaded_filters):
            return None
        return self.loaded_filters[idx]

    def clear_filter_param_widgets(self):
        """Clear dynamic filter parameter controls."""
        self.filter_param_widgets.clear()
        while self.filter_params_layout.count():
            item = self.filter_params_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout is not None:
                while child_layout.count():
                    child_item = child_layout.takeAt(0)
                    child_widget = child_item.widget()
                    if child_widget is not None:
                        child_widget.deleteLater()

    def on_filter_selected(self, _index):
        """Rebuild parameter controls for the selected filter module."""
        self.clear_filter_param_widgets()
        loaded = self.current_filter()
        if loaded is None:
            return

        schema = []
        try:
            schema = loaded.instance.get_parameter_schema()
        except Exception as exc:
            QMessageBox.warning(self, MSG_FILTER_ERROR_TITLE, MSG_FAILED_READ_FILTER_SCHEMA.format(error=exc))
            return

        for param in schema:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            label = QLabel(param.get("label", param.get("key", "param")))
            row_layout.addWidget(label)

            key = param.get("key")
            ptype = param.get("type", "text")
            default = param.get("default")

            if ptype == "int":
                widget = QSpinBox()
                widget.setRange(int(param.get("min", -100000)), int(param.get("max", 100000)))
                widget.setSingleStep(int(param.get("step", 1)))
                widget.setValue(int(default if default is not None else 0))
            elif ptype == "float":
                widget = QDoubleSpinBox()
                widget.setDecimals(3)
                widget.setRange(float(param.get("min", -1e9)), float(param.get("max", 1e9)))
                widget.setSingleStep(float(param.get("step", 0.1)))
                widget.setValue(float(default if default is not None else 0.0))
            elif ptype == "choice":
                widget = QComboBox()
                for option in param.get("choices", []):
                    widget.addItem(str(option))
                if default is not None:
                    default_text = str(default)
                    idx = widget.findText(default_text)
                    if idx >= 0:
                        widget.setCurrentIndex(idx)
            else:
                if str(key).lower() == "prompt":
                    widget = QTextEdit()
                    widget.setPlainText(str(default if default is not None else ""))
                    widget.setMinimumHeight(70)
                    widget.setMaximumHeight(120)
                else:
                    widget = QLineEdit(str(default if default is not None else ""))

            row_layout.addWidget(widget, 1)
            self.filter_params_layout.addWidget(row)
            self.filter_param_widgets[key] = (ptype, widget)

        self.filter_params_layout.addStretch()

    def collect_filter_parameters(self):
        """Read current dynamic parameter UI values into a dict."""
        values = {}
        for key, (ptype, widget) in self.filter_param_widgets.items():
            if ptype == "int":
                values[key] = int(widget.value())
            elif ptype == "float":
                values[key] = float(widget.value())
            elif ptype == "choice":
                values[key] = widget.currentText()
            else:
                if isinstance(widget, QTextEdit):
                    values[key] = widget.toPlainText()
                else:
                    values[key] = widget.text()
        return values

    def update_filter_channel_options(self):
        """Refresh channel selector options based on current audio."""
        self.filter_channel_selector.clear()
        if self.current_audio is None:
            self.filter_channel_label.setVisible(False)
            self.filter_channel_selector.setVisible(False)
            return

        # Mono files are normalized to 2 display channels upstream, so prefer the
        # explicit source flag to decide whether channel selection should be shown.
        is_effective_mono = self.is_mono or len(self.current_audio.shape) == 1 or (
            len(self.current_audio.shape) > 1 and self.current_audio.shape[0] <= 1
        )
        channels = 1 if is_effective_mono else self.current_audio.shape[0]

        if channels <= 1:
            self.filter_channel_selector.addItem(CHANNEL_1_LABEL, 0)
            self.filter_channel_label.setVisible(False)
            self.filter_channel_selector.setVisible(False)
        else:
            self.filter_channel_label.setVisible(True)
            self.filter_channel_selector.setVisible(True)
            # Stereo UX: prefer L/R channel labels.
            self.filter_channel_selector.addItem(LABEL_LEFT_SHORT, 0)
            self.filter_channel_selector.addItem(LABEL_RIGHT_SHORT, 1)
            for idx in range(2, channels):
                self.filter_channel_selector.addItem(LABEL_CHANNEL_TEMPLATE.format(index=idx + 1), idx)

    def channel_signal(self, audio, channel_index):
        """Return a channel signal regardless of mono/stereo shape."""
        if len(audio.shape) == 1:
            return audio
        safe_index = max(0, min(channel_index, audio.shape[0] - 1))
        return audio[safe_index]

    def refresh_filter_previews(self):
        """Filter previews now use the main audio viewer spectrograms for consistency."""
        pass

    def normalize_length(self, signal_data, target_len):
        """Match filter output length to source channel length."""
        return normalize_signal_length(signal_data, target_len)

    def _current_source_stem(self):
        if self.current_audio_path:
            return sanitize_name_part(Path(self.current_audio_path).stem)
        return "audio"

    def _current_filter_side(self, channel_index):
        if self.is_mono:
            return "mono"
        return "left" if int(channel_index) == 0 else "right"

    def _build_filter_output_stem(self, filter_file_stem, channel_index, unix_time):
        source_stem = self._current_source_stem()
        filter_stem = sanitize_name_part(filter_file_stem)
        side = self._current_filter_side(channel_index)
        return f"{source_stem}_{filter_stem}_{unix_time}_{side}"

    def write_filter_log(self, filter_file_stem, params, exported_file_path, channel_index):
        """Write filter application metadata to a timestamped log file."""
        unix_time = int(datetime.now().timestamp())
        filter_name = sanitize_name_part(filter_file_stem)
        output_stem = self._build_filter_output_stem(filter_name, channel_index, unix_time)
        log_name = f"{output_stem}.txt"

        log_dir = self.get_filter_output_dir()
        log_dir.mkdir(parents=True, exist_ok=True)

        param_text = ",".join([f"{k}={v}" for k, v in params.items()])
        exported_name = Path(exported_file_path).name
        line = FILTER_OUTPUT_LOG_TEMPLATE.format(name=filter_name, params=param_text, exported=exported_name)

        log_path = log_dir / log_name
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(line)

        return log_path

    def swap_source_with_filtered_output(self):
        """Swap current source audio with the latest filtered output for subsequent processing."""
        if self.current_audio is None or self.current_sr is None:
            QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_NO_AUDIO_LOADED)
            return
        if self.filtered_channel is None:
            QMessageBox.warning(self, MSG_WARNING_TITLE, "Apply a filter before swapping source audio.")
            return

        reply = QMessageBox.question(
            self,
            "Swap Source Audio",
            "Use the latest filtered output as the new source audio for subsequent processing?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        previous_source_path = self.current_audio_path
        source_audio = np.asarray(self.current_audio, dtype=np.float32)
        target_len = source_audio.shape[-1] if source_audio.ndim > 1 else len(source_audio)
        filtered = normalize_signal_length(self.filtered_channel, target_len)

        if source_audio.ndim == 1:
            swapped_audio = filtered
        else:
            swapped_audio = np.array(source_audio, copy=True)
            if self.is_mono:
                swapped_audio[0] = filtered
                if swapped_audio.shape[0] > 1:
                    swapped_audio[1] = filtered
            else:
                channel_idx = int(self.filtered_channel_index or 0)
                channel_idx = max(0, min(channel_idx, swapped_audio.shape[0] - 1))
                swapped_audio[channel_idx] = filtered

        output_dir = self.get_filter_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        unix_time = int(datetime.now().timestamp())
        swapped_name = f"{self._current_source_stem()}_swapped_{unix_time}.wav"
        swapped_path = output_dir / swapped_name

        if self.is_mono:
            if np.ndim(swapped_audio) > 1:
                sf.write(str(swapped_path), np.asarray(swapped_audio[0], dtype=np.float32), int(self.current_sr))
            else:
                sf.write(str(swapped_path), np.asarray(swapped_audio, dtype=np.float32), int(self.current_sr))
        else:
            sf.write(str(swapped_path), np.asarray(swapped_audio, dtype=np.float32).T, int(self.current_sr))

        self.current_audio = np.asarray(swapped_audio, dtype=np.float32)
        self.current_audio_path = str(swapped_path)
        self.filtered_output_dir = str(output_dir)

        swap_event = {
            "timestamp": datetime.now().isoformat(),
            "previous_source_audio": str(previous_source_path) if previous_source_path else "",
            "swapped_source_audio": str(swapped_path),
            "filtered_output_audio": str(self.filtered_output_path) if self.filtered_output_path else "",
            "filtered_channel_index": int(self.filtered_channel_index) if self.filtered_channel_index is not None else 0,
            "annotation_json_previous": str(Path(previous_source_path).with_suffix(JSON_SUFFIX)) if previous_source_path else "",
            "annotation_json_swapped": str(Path(swapped_path).with_suffix(JSON_SUFFIX)),
        }
        self.source_swap_history.append(swap_event)

        self.save_annotations_to_json()
        self.last_swap_log_path = str(Path(self.current_audio_path).with_suffix(JSON_SUFFIX))

        self.source_audio_swapped.emit(str(swapped_path), self.current_audio, int(self.current_sr), bool(self.is_mono))
        self.refresh_filter_previews()
        self.filter_status_label.setText(
            "Audio source swapped. Info saved to annotation JSON file."
        )

        QMessageBox.information(
            self,
            MSG_SUCCESS_TITLE,
            "Audio source swapped.\n\nInfo saved to annotation JSON file.",
        )

    def apply_selected_filter(self):
        """Run selected modular filter and update the filtered spectrogram preview."""
        if self.current_audio is None or self.current_sr is None:
            QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_LOAD_AUDIO_BEFORE_FILTER)
            return

        loaded = self.current_filter()
        if loaded is None:
            QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_NO_FILTER_SELECTED)
            return

        channel_index = int(self.filter_channel_selector.currentData() or 0)
        params = self.collect_filter_parameters()
        output_dir = self.get_filter_output_dir()
        if self.run_background_task_callback is None:
            QMessageBox.critical(self, MSG_FILTER_ERROR_TITLE, MSG_FAILED_APPLY_FILTER.format(error="Background task runner is not configured."))
            return

        worker = FilterApplyWorker(
            loaded,
            self.current_audio,
            self.current_sr,
            channel_index,
            params,
            self.current_audio_path,
            output_dir,
        )
        self.run_background_task_callback(worker, FILTER_BUSY_TITLE, FILTER_BUSY_TITLE, self.on_filter_applied)

    def on_filter_applied(self, result):
        """Finalize filter output on the UI thread after the backend worker finishes."""
        try:
            normalized = np.asarray(result["normalized"], dtype=np.float32)
            channel_index = int(result["channel_index"])
            params = result["params"]
            file_stem = result["file_stem"]
            output_dir = Path(result["output_dir"])

            self.update_filter_busy(80, TEXT_PROGRESS_BUILDING_FILTER_OUTPUT)

            self.filtered_channel = normalized
            self.filtered_channel_index = channel_index

            if self.audio_viewer is not None:
                self.audio_viewer.set_filter_preview_output(normalized)

            unix_time = int(datetime.now().timestamp())
            export_name = f"{self._build_filter_output_stem(file_stem, channel_index, unix_time)}.wav"
            export_path = output_dir / export_name
            sample_rate = int(self.current_sr)

            sf.write(str(export_path), normalized, sample_rate)

            self.filtered_output_path = str(export_path)
            self.filtered_output_dir = str(output_dir)
            self.update_filter_busy(92, TEXT_PROGRESS_WRITING_LOGS)
            log_path = self.write_filter_log(file_stem, params, export_path, channel_index)
            self.refresh_filter_previews()
            self.update_filter_busy(100, "Done")

            self.filter_status_label.setText(
                TEXT_FILTER_APPLIED_STATUS.format(stem=file_stem, result=export_path.name, log=log_path.name)
            )
            self.show_results_btn.setEnabled(True)
            self.swap_filtered_btn.setEnabled(True)
        except Exception as exc:
            QMessageBox.critical(self, MSG_FILTER_ERROR_TITLE, MSG_FAILED_APPLY_FILTER.format(error=exc))
        finally:
            # Keep dialog lifecycle robust even if UI-thread finalization fails.
            self.clear_filter_busy()
    
    def on_show_filter_results(self):
        """Open the system file explorer to the filter output directory."""
        if self.filtered_output_dir:
            folder_url = QUrl.fromLocalFile(self.filtered_output_dir)
            QDesktopServices.openUrl(folder_url)

    def populate_annotation_channel_options(self, is_mono):
        """Populate and show/hide annotation channel options based on audio type."""
        self.channel_combo.blockSignals(True)
        self.channel_combo.clear()
        if is_mono:
            self.channel_label.setVisible(False)
            self.channel_combo.setVisible(False)
            self.channel_combo.addItem(ANNOTATION_CHANNEL_MONO, "mono")
        else:
            self.channel_label.setVisible(True)
            self.channel_combo.setVisible(True)
            self.channel_combo.addItem(ANNOTATION_CHANNEL_LEFT, "left")
            self.channel_combo.addItem(ANNOTATION_CHANNEL_RIGHT, "right")
            self.channel_combo.addItem(ANNOTATION_CHANNEL_BOTH, "both")
            self.channel_combo.setCurrentIndex(0)
        self.channel_combo.blockSignals(False)

    def set_audio_data(self, y, sr, is_mono=False, file_path=None):
        """Set the current audio data and load matching JSON annotations if available."""
        self.current_audio = y
        self.current_sr = sr
        self.is_mono = is_mono
        self.current_audio_path = file_path
        self.filtered_channel = None
        self.filtered_channel_index = None
        self.filtered_output_path = None
        self.filtered_output_dir = None
        self.last_swap_log_path = None
        self.source_swap_history = []
        self.show_results_btn.setEnabled(False)
        self.swap_filtered_btn.setEnabled(False)
        
        # Update spin box limits based on audio duration
        duration = y.shape[1] / sr if len(y.shape) > 1 else len(y) / sr
        self.start_spin.setRange(0, duration)
        self.stop_spin.setRange(0, duration)
        self.stop_spin.setValue(duration)

        self.populate_annotation_channel_options(is_mono)
        self.update_filter_channel_options()
        self.refresh_filter_previews()
        
        # Load annotations from JSON file if it exists
        if file_path:
            self.load_annotations_from_json(file_path)
        else:
            self.annotations = []
            self.refresh_list()

    def _annotation_payload(self):
        """Build the persisted JSON payload for annotations and swap history."""
        annotations_data = [
            ann.to_dict() if isinstance(ann, Annotation) else ann
            for ann in self.annotations
        ]
        return {
            "annotations": annotations_data,
            "source_swap_log": self.source_swap_history,
        }

    def _load_annotation_payload(self, data):
        """Apply JSON payload into in-memory annotation/swap-history state."""
        self.annotations = []
        for ann_data in data.get("annotations", []):
            ann = Annotation.from_dict(ann_data) if isinstance(ann_data, dict) else ann_data
            self.annotations.append(ann)
        self.source_swap_history = list(data.get("source_swap_log", []))

    def load_annotations_from_json(self, audio_file_path):
        """Load annotations from a JSON file matching the audio file."""
        json_path = Path(audio_file_path).with_suffix(JSON_SUFFIX)
        if json_path.exists():
            try:
                with open(json_path, 'r') as f:
                    data = json.load(f)
                    self._load_annotation_payload(data)
                self.refresh_list()
            except Exception as e:
                QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_FAILED_LOAD_ANNOTATIONS.format(error=str(e)))
                self.annotations = []
                self.source_swap_history = []
                self.refresh_list()
        else:
            self.annotations = []
            self.source_swap_history = []
            self.refresh_list()

    def save_annotations_to_json(self):
        """Save annotations to a JSON file matching the audio file."""
        if self.current_audio_path is None:
            return
        
        json_path = Path(self.current_audio_path).with_suffix(JSON_SUFFIX)
        try:
            with open(json_path, 'w') as f:
                json.dump(self._annotation_payload(), f, indent=2)
            # Emit signal that annotations changed
            self.annotations_changed.emit(self.annotations)
        except Exception as e:
            QMessageBox.warning(self, MSG_ERROR_TITLE, MSG_FAILED_SAVE_ANNOTATIONS.format(error=str(e)))

    def load_annotations_from_file(self):
        """Load annotations from a user-selected JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Annotation Metadata",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                self._load_annotation_payload(data)
            self.refresh_list()
            self.clear_inputs()
            QMessageBox.information(self, MSG_SUCCESS_TITLE, f"Loaded annotations from:\n{file_path}")
            # Auto-save to the current audio file's corresponding json
            self.save_annotations_to_json()
        except Exception as e:
            QMessageBox.critical(self, MSG_ERROR_TITLE, f"Failed to load annotations:\n{str(e)}")

    def export_annotations_to_file(self):
        """Export annotations to a user-selected JSON file."""
        if not self.annotations:
            QMessageBox.warning(self, MSG_WARNING_TITLE, "No annotations to export.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Annotation Metadata",
            "annotations.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            with open(file_path, 'w') as f:
                json.dump(self._annotation_payload(), f, indent=2)
            QMessageBox.information(self, MSG_SUCCESS_TITLE, f"Annotations exported to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, MSG_ERROR_TITLE, f"Failed to export annotations:\n{str(e)}")

    def on_tab_changed(self, tab_index):
        """Handle tab changes - notify when filtering tab is activated."""
        # Tab 0 = Annotation, Tab 1 = Filtering
        is_filtering_tab = (tab_index == 1)
        self.filter_tab_activated.emit(is_filtering_tab)

    def add_annotation(self):
        """Add a new annotation using Annotation model."""
        if not self.name_input.text().strip():
            QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_ANNOTATION_NAME_REQUIRED)
            return
        
        start = self.start_spin.value()
        stop = self.stop_spin.value()
        
        if start >= stop:
            QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_START_BEFORE_STOP)
            return
        
        ann = Annotation(
            name=self.name_input.text().strip(),
            start=start,
            stop=stop,
            comment=self.comment_input.toPlainText(),
            color=self.annotation_color,
            channel=str(self.channel_combo.currentData() or "mono"),
            created_timestamp=datetime.now().isoformat(),
            modified_timestamp=datetime.now().isoformat(),
        )
        
        is_valid, error_msg = ann.validate()
        if not is_valid:
            QMessageBox.warning(self, MSG_WARNING_TITLE, error_msg)
            return
        
        self.annotations.append(ann)
        self.refresh_list()
        self.clear_inputs()
        self.save_annotations_to_json()
    
    def update_annotation(self):
        """Update selected annotation using Annotation model."""
        if self.current_selection is None:
            QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_SELECT_ANNOTATION_TO_UPDATE)
            return
        
        start = self.start_spin.value()
        stop = self.stop_spin.value()
        
        if start >= stop:
            QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_START_BEFORE_STOP)
            return
        
        ann = self.annotations[self.current_selection]
        ann.name = self.name_input.text().strip()
        ann.start = start
        ann.stop = stop
        ann.comment = self.comment_input.toPlainText()
        ann.color = self.annotation_color
        ann.channel = str(self.channel_combo.currentData() or "mono")
        ann.modified_timestamp = datetime.now().isoformat()
        
        is_valid, error_msg = ann.validate()
        if not is_valid:
            QMessageBox.warning(self, MSG_WARNING_TITLE, error_msg)
            return
        
        self.refresh_list()
        self.save_annotations_to_json()
    
    def delete_annotation(self):
        """Delete selected annotation."""
        if self.current_selection is None:
            QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_SELECT_ANNOTATION_TO_DELETE)
            return
        
        del self.annotations[self.current_selection]
        self.refresh_list()
        self.clear_inputs()
        self.current_selection = None
        self.save_annotations_to_json()
    
    def export_segment(self):
        """Export annotated segment as WAVE file."""
        if self.current_selection is None:
            QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_SELECT_ANNOTATION_TO_EXPORT)
            return
        
        if self.current_audio is None or self.current_sr is None:
            QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_NO_AUDIO_LOADED)
            return
        
        ann = self.annotations[self.current_selection]

        export_cfg = self.get_export_segment_options(default_name=ann.name)
        if export_cfg is None:
            return

        file_path = export_cfg["file_path"]

        try:
            export_stereo = bool(export_cfg["stereo"])
            export_left = bool(export_cfg["left"])
            export_right = bool(export_cfg["right"])

            if (not self.is_mono) and (not (export_stereo or export_left or export_right)):
                QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_SELECT_EXPORT_CHANNEL_OPTION)
                return

            start_sample = int(ann.start * self.current_sr)
            stop_sample = int(ann.stop * self.current_sr)
            
            segment = self.current_audio[:, start_sample:stop_sample]

            output_base = Path(file_path)
            out_dir = output_base.parent
            stem = output_base.stem

            exported_files = []
            if self.is_mono:
                mono_path = out_dir / f"{stem}{FILTERED_EXPORT_MONO_SUFFIX}"
                sf.write(str(mono_path), segment[0], self.current_sr)
                exported_files.append(mono_path.name)
            elif export_stereo:
                stereo_path = out_dir / f"{stem}{FILTERED_EXPORT_STEREO_SUFFIX}"
                sf.write(str(stereo_path), segment.T, self.current_sr)
                exported_files.append(stereo_path.name)

            if export_left:
                left_path = out_dir / f"{stem}{FILTERED_EXPORT_LEFT_SUFFIX}"
                sf.write(str(left_path), segment[0], self.current_sr)
                exported_files.append(left_path.name)

            if export_right and not self.is_mono:
                right_path = out_dir / f"{stem}{FILTERED_EXPORT_RIGHT_SUFFIX}"
                sf.write(str(right_path), segment[1], self.current_sr)
                exported_files.append(right_path.name)
            
            QMessageBox.information(self, MSG_SUCCESS_TITLE, MSG_EXPORTED_SUCCESS.format(files=', '.join(exported_files)))
        except Exception as e:
            QMessageBox.critical(self, MSG_ERROR_TITLE, MSG_EXPORT_FAILED.format(error=str(e)))

    def export_all_segments(self):
        """Export all annotated segments as WAVE files to a chosen folder."""
        if not self.annotations:
            QMessageBox.warning(self, MSG_WARNING_TITLE, "No annotations to export.")
            return
        if self.current_audio is None or self.current_sr is None:
            QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_NO_AUDIO_LOADED)
            return

        out_dir_str = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if not out_dir_str:
            return
        out_dir = Path(out_dir_str)

        # Channel selection dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Export All Segments — Channel Options")
        dialog.setModal(True)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(10, 10, 10, 10)
        dlg_layout.setSpacing(8)

        channel_row = QHBoxLayout()
        channel_row.addWidget(QLabel("Channels:"))
        stereo_check = QCheckBox(LABEL_STEREO)
        left_check = QCheckBox(LABEL_LEFT_SHORT)
        right_check = QCheckBox(LABEL_RIGHT_SHORT)
        if self.is_mono:
            stereo_check.setChecked(False)
            stereo_check.setEnabled(False)
            left_check.setChecked(True)
            left_check.setEnabled(False)
            right_check.setChecked(False)
            right_check.setEnabled(False)
        else:
            stereo_check.setChecked(True)
        channel_row.addWidget(stereo_check)
        channel_row.addWidget(left_check)
        channel_row.addWidget(right_check)
        channel_row.addStretch()
        dlg_layout.addLayout(channel_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dlg_layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        export_stereo = stereo_check.isChecked()
        export_left = left_check.isChecked()
        export_right = right_check.isChecked()

        if not self.is_mono and not any([export_stereo, export_left, export_right]):
            QMessageBox.warning(self, MSG_WARNING_TITLE, MSG_SELECT_EXPORT_CHANNEL_OPTION)
            return

        exported_count = 0
        errors = []
        for i, ann in enumerate(self.annotations):
            try:
                start_sample = int(ann.start * self.current_sr)
                stop_sample = min(int(ann.stop * self.current_sr), self.current_audio.shape[1])
                segment = self.current_audio[:, start_sample:stop_sample]
                stem = ann.name if ann.name else f"segment_{i}"

                if self.is_mono:
                    mono_path = out_dir / f"{stem}{FILTERED_EXPORT_MONO_SUFFIX}"
                    sf.write(str(mono_path), segment[0], self.current_sr)
                    exported_count += 1
                else:
                    if export_stereo:
                        sf.write(str(out_dir / f"{stem}{FILTERED_EXPORT_STEREO_SUFFIX}"), segment.T, self.current_sr)
                        exported_count += 1
                    if export_left:
                        sf.write(str(out_dir / f"{stem}{FILTERED_EXPORT_LEFT_SUFFIX}"), segment[0], self.current_sr)
                        exported_count += 1
                    if export_right:
                        sf.write(str(out_dir / f"{stem}{FILTERED_EXPORT_RIGHT_SUFFIX}"), segment[1], self.current_sr)
                        exported_count += 1
            except Exception as e:
                errors.append(f"{ann.name}: {str(e)}")

        if errors:
            QMessageBox.warning(self, MSG_WARNING_TITLE, f"Some exports failed:\n" + "\n".join(errors))
        else:
            QMessageBox.information(self, MSG_SUCCESS_TITLE, f"Exported {exported_count} file(s) to:\n{out_dir_str}")

    def get_export_segment_options(self, default_name):
        """Show export dialog with target path and channel options, then return chosen options."""
        dialog = QDialog(self)
        dialog.setWindowTitle(PROMPT_EXPORT_ANNOTATION_BASE)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Export File:"))
        path_input = QLineEdit(str(default_name))
        path_row.addWidget(path_input, 1)
        browse_btn = QPushButton("Browse")

        def on_browse():
            selected, _ = QFileDialog.getSaveFileName(
                self,
                PROMPT_EXPORT_ANNOTATION_BASE,
                path_input.text().strip() or str(default_name),
                FILE_FILTER_WAVE,
            )
            if selected:
                path_input.setText(selected)

        browse_btn.clicked.connect(on_browse)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        channel_row = QHBoxLayout()
        channel_row.addWidget(QLabel("Channels:"))
        stereo_check = QCheckBox(LABEL_STEREO)
        left_check = QCheckBox(LABEL_LEFT_SHORT)
        right_check = QCheckBox(LABEL_RIGHT_SHORT)

        if self.is_mono:
            stereo_check.setChecked(False)
            stereo_check.setEnabled(False)
            left_check.setChecked(True)
            left_check.setEnabled(False)
            right_check.setChecked(False)
            right_check.setEnabled(False)
        else:
            stereo_check.setChecked(True)

        channel_row.addWidget(stereo_check)
        channel_row.addWidget(left_check)
        channel_row.addWidget(right_check)
        channel_row.addStretch()
        layout.addLayout(channel_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        file_path = path_input.text().strip()
        if not file_path:
            QMessageBox.warning(self, MSG_WARNING_TITLE, "Please specify an export file path.")
            return None

        if not file_path.lower().endswith(".wav"):
            file_path = f"{file_path}.wav"

        return {
            "file_path": file_path,
            "stereo": stereo_check.isChecked(),
            "left": left_check.isChecked(),
            "right": right_check.isChecked(),
        }
    
    def on_annotation_selected(self, item):
        """Handle annotation selection."""
        idx = self.annotation_list.row(item)
        self.current_selection = idx
        self.has_pending_selection = False
        self.draft_annotation_cleared.emit()
        ann = self.annotations[idx]
        
        self.name_input.setText(ann.name)
        self.start_spin.setValue(ann.start)
        self.stop_spin.setValue(ann.stop)
        self.comment_input.setPlainText(ann.comment)
        self.annotation_color = ann.color
        self.update_color_button()
        
        # Set channel selector
        channel_value = ann.channel.lower() if ann.channel else "mono"
        idx = self.channel_combo.findData(channel_value)
        if idx >= 0:
            self.channel_combo.setCurrentIndex(idx)

    def select_annotation_by_index(self, index):
        """Programmatically select an annotation and show its details in the pane."""
        if index is None or index < 0 or index >= len(self.annotations):
            return
        self.annotation_list.setCurrentRow(index)
        item = self.annotation_list.item(index)
        if item is not None:
            self.on_annotation_selected(item)
    
    def refresh_list(self):
        """Refresh annotation list display with color indicators."""
        self.annotation_list.clear()
        for i, ann in enumerate(self.annotations):
            # Create item with color indicator
            item_text = ANNOTATION_LIST_ITEM_TEMPLATE.format(
                name=ann.name,
                start=ann.start,
                stop=ann.stop,
            )
            item = QListWidgetItem(item_text)
            
            # Set background color for visual indication
            try:
                color = QColor(ann.color)
                item.setBackground(color)
                # Set text color to be readable on the background
                item.setForeground(QColor("white") if color.lightness() < 128 else QColor("black"))
            except:
                pass
            
            self.annotation_list.addItem(item)
    
    def pick_color(self):
        """Open color picker dialog."""
        color_dialog = QColorDialog(QColor(self.annotation_color), self)
        if color_dialog.exec():
            self.annotation_color = color_dialog.selectedColor().name()
            self.update_color_button()
            self.emit_draft_annotation()
    
    def update_color_button(self):
        """Update color button appearance."""
        pixmap = QPixmap(60, 24)
        pixmap.fill(QColor(self.annotation_color))
        self.color_button.setIcon(QIcon(pixmap))
    
    def clear_inputs(self):
        """Clear all input fields."""
        self.name_input.clear()
        self.start_spin.setValue(0)
        self.stop_spin.setValue(0)
        self.comment_input.clear()
        self.annotation_color = ANNOTATION_DEFAULT_COLORS[self.color_index % len(ANNOTATION_DEFAULT_COLORS)]
        self.update_color_button()
        if self.channel_combo.count() > 0:
            self.channel_combo.setCurrentIndex(0)
        self.color_index += 1
        self.has_pending_selection = False
        self.draft_annotation_cleared.emit()
    
    def update_from_selection(self, start_time, end_time):
        """Update UI when selection changes in audio viewer."""
        self.current_selection = None
        self.has_pending_selection = True
        self.start_spin.setValue(start_time)
        self.stop_spin.setValue(end_time)
        # Auto-generate a name if it's empty
        if not self.name_input.text().strip():
            self.name_input.setText(f"Annotation_{int(start_time)}to{int(end_time)}")
        self.emit_draft_annotation()

    def emit_draft_annotation(self):
        """Emit the current draft annotation geometry/color while editing a new selection."""
        if not self.has_pending_selection:
            return
        start = float(self.start_spin.value())
        stop = float(self.stop_spin.value())
        if stop <= start:
            return
        channel = str(self.channel_combo.currentData() or "mono")
        self.draft_annotation_changed.emit(start, stop, self.annotation_color, channel)
