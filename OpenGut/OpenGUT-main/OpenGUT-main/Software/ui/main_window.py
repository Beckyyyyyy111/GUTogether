"""
Main window for the audio annotation GUI application.
Manages a tabbed interface with device configuration and post-processing modes.
"""

import sys
import logging
from pathlib import Path

from PyQt6.QtWidgets import QMainWindow, QProgressDialog, QSplitter, QVBoxLayout, QHBoxLayout, QWidget, QMessageBox, QTabWidget, QPushButton, QLabel, QFileDialog, QPlainTextEdit, QSpinBox, QComboBox
from PyQt6.QtCore import QThread, Qt
from PyQt6.QtGui import QTextCursor
import pyqtgraph as pg
from .audio_viewer import AudioLoadWorker, AudioViewerWidget
from .annotation_panel import AnnotationPanelWidget
from .device_config_panel import DeviceConfigPanel
from .components.settings_widgets import LabeledBrowseField
from .components.audio_device_selector import AudioDeviceSelector
from app_settings import load_settings, save_settings
from const import (
    APP_WINDOW_GEOMETRY,
    APP_WINDOW_TITLE,
    AUDIOSEP_CHUNK_SECONDS_DEFAULT,
    AUDIOSEP_CHUNK_SECONDS_OPTIONS,
    BUSY_PREFIX_DEFAULT,
    BUSY_DIALOG_MIN_WIDTH,
    BUTTON_BROWSE_FOLDER,
    BUTTON_OPEN,
    BUTTON_SAVE_SETTINGS,
    CONSOLE_LINE_LIMIT_DEFAULT,
    CONSOLE_LINE_LIMIT_MAX,
    CONSOLE_LINE_LIMIT_MIN,
    FILE_FILTER_AUDIO,
    FILE_FILTER_CHECKPOINT,
    FILE_FILTER_YAML,
    LABEL_AUDIOSEP_CHUNK_HINT,
    LABEL_AUDIOSEP_CHUNK_SECONDS,
    LABEL_CONSOLE_LINE_LIMIT,
    LABEL_FILENAME_STYLE_ACTIVE,
    LABEL_FILENAME_STYLE_IDLE,
    LABEL_WORKING_DIRECTORY,
    LABEL_AUDIOSEP_BASE_CHECKPOINT,
    LABEL_AUDIOSEP_YAML_CONFIG,
    LABEL_MUSIC_SPEECH_CHECKPOINT,
    LABEL_FILE_LOADED_PREFIX,
    LABEL_NO_FILE_LOADED,
    MENU_EXIT,
    MENU_FILE,
    MENU_OPEN_AUDIO_FILE,
    OPEN_BUTTON_MAX_WIDTH,
    PROMPT_PICK_AUDIOSEP_CHECKPOINT,
    PROMPT_PICK_AUDIOSEP_YAML_CONFIG,
    PROMPT_PICK_MUSIC_SPEECH_CHECKPOINT,
    PROMPT_PICK_WORKING_DIRECTORY,
    SECTION_AUDIOSEP_SETTINGS,
    SECTION_CONSOLE_OUTPUT,
    SPLITTER_DEFAULT_TWO_PANE_SIZES,
    TASK_DETAIL_DONE,
    TASK_DETAIL_RENDERING_PLOTS,
    SECTION_TITLE_STYLE,
    SECTION_WORKING_FILES,
    SETTINGS_LOADED_TEXT,
    SETTINGS_SAVED_TEXT,
    SETTINGS_STATUS_STYLE,
    SETTING_KEY_AUDIOSEP_BASE_CHECKPOINT,
    SETTING_KEY_AUDIOSEP_CHUNK_SECONDS,
    SETTING_KEY_CONSOLE_LINE_LIMIT,
    SETTING_KEY_AUDIOSEP_YAML_CONFIG,
    SETTING_KEY_MUSIC_SPEECH_CHECKPOINT,
    SETTING_KEY_WORKING_DIRECTORY,
    TAB_CONSOLE_OUT,
    TAB_DEVICE_CONFIGURATION,
    TAB_POST_PROCESSING,
    TAB_WELCOME,
    TASK_ERROR_FALLBACK_TITLE,
    TASK_TITLE_LOADING_AUDIO,
    WELCOME_INTRO_TEXT,
    WELCOME_TITLE_STYLE,
    WELCOME_TITLE_TEXT,
)



class ConsoleStreamProxy:
    """Plain Python stream proxy used for console mirroring.

    Using a non-QObject stream avoids RuntimeError during app shutdown when
    external libraries (for example colorama) query stream attributes after
    Qt objects have already been destroyed.
    """

    def __init__(self, original_stream, on_text=None):
        self.original_stream = original_stream
        self.on_text = on_text
        self._closed = False

    def write(self, text):
        value = "" if text is None else str(text)
        if self.original_stream is not None:
            self.original_stream.write(value)
            self.original_stream.flush()
        if value and callable(self.on_text):
            try:
                self.on_text(value)
            except Exception:
                # Ignore UI write errors during shutdown.
                pass

    def flush(self):
        if self.original_stream is not None:
            self.original_stream.flush()

    def isatty(self):
        return bool(self.original_stream is not None and hasattr(self.original_stream, "isatty") and self.original_stream.isatty())

    def fileno(self):
        if self.original_stream is not None and hasattr(self.original_stream, "fileno"):
            return self.original_stream.fileno()
        raise OSError("Stream has no file descriptor")

    @property
    def encoding(self):
        return getattr(self.original_stream, "encoding", "utf-8")

    @property
    def closed(self):
        if self._closed:
            return True
        return bool(self.original_stream is not None and getattr(self.original_stream, "closed", False))

    def close(self):
        self._closed = True


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_WINDOW_TITLE)
        self.setGeometry(*APP_WINDOW_GEOMETRY)
        self.busy_dialog = None
        self.active_worker_thread = None
        self.active_worker = None
        self.busy_task_title = ""
        self.busy_label_prefix = ""
        self.app_settings = load_settings()
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.stdout_proxy = None
        self.stderr_proxy = None
        self._patched_logging_handlers = []
        
        # Create main widget with VBox layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create tab widget
        self.tab_widget = QTabWidget()

        # Tab 0: Welcome
        welcome_widget = QWidget()
        welcome_layout = QVBoxLayout(welcome_widget)
        welcome_layout.setContentsMargins(16, 16, 16, 16)
        welcome_layout.setSpacing(10)

        welcome_title = QLabel(WELCOME_TITLE_TEXT)
        welcome_title.setStyleSheet(WELCOME_TITLE_STYLE)
        welcome_layout.addWidget(welcome_title)

        welcome_intro = QLabel(WELCOME_INTRO_TEXT)
        welcome_intro.setWordWrap(True)
        welcome_layout.addWidget(welcome_intro)

        # Audio output device selection
        audio_device_title = QLabel("Audio Output")
        audio_device_title.setStyleSheet(SECTION_TITLE_STYLE)
        welcome_layout.addWidget(audio_device_title)

        self.audio_device_selector = AudioDeviceSelector()
        welcome_layout.addWidget(self.audio_device_selector)

        # Working directory setting for post-processing outputs
        workspace_title = QLabel(SECTION_WORKING_FILES)
        workspace_title.setStyleSheet(SECTION_TITLE_STYLE)
        welcome_layout.addWidget(workspace_title)

        self.working_dir_field = LabeledBrowseField(
            LABEL_WORKING_DIRECTORY,
            self.app_settings.get(SETTING_KEY_WORKING_DIRECTORY, ""),
            button_text=BUTTON_BROWSE_FOLDER,
        )
        self.working_dir_field.button.clicked.connect(self.browse_for_working_directory)
        welcome_layout.addLayout(self.working_dir_field.build_layout())

        console_title = QLabel(SECTION_CONSOLE_OUTPUT)
        console_title.setStyleSheet(SECTION_TITLE_STYLE)
        welcome_layout.addWidget(console_title)

        console_limit_layout = QHBoxLayout()
        console_limit_layout.setContentsMargins(0, 0, 0, 0)
        console_limit_layout.addWidget(QLabel(LABEL_CONSOLE_LINE_LIMIT))
        self.console_line_limit_spin = QSpinBox()
        self.console_line_limit_spin.setRange(CONSOLE_LINE_LIMIT_MIN, CONSOLE_LINE_LIMIT_MAX)
        self.console_line_limit_spin.setValue(int(self.app_settings.get(SETTING_KEY_CONSOLE_LINE_LIMIT, CONSOLE_LINE_LIMIT_DEFAULT)))
        self.console_line_limit_spin.valueChanged.connect(self.on_console_line_limit_changed)
        console_limit_layout.addWidget(self.console_line_limit_spin)
        console_limit_layout.addStretch()
        welcome_layout.addLayout(console_limit_layout)

        chunk_layout = QHBoxLayout()
        chunk_layout.setContentsMargins(0, 0, 0, 0)
        chunk_layout.addWidget(QLabel(LABEL_AUDIOSEP_CHUNK_SECONDS))
        self.audiosep_chunk_combo = QComboBox()
        for seconds in AUDIOSEP_CHUNK_SECONDS_OPTIONS:
            self.audiosep_chunk_combo.addItem(f"{seconds}s", seconds)
        saved_chunk = int(self.app_settings.get(SETTING_KEY_AUDIOSEP_CHUNK_SECONDS, AUDIOSEP_CHUNK_SECONDS_DEFAULT))
        idx = self.audiosep_chunk_combo.findData(saved_chunk)
        self.audiosep_chunk_combo.setCurrentIndex(idx if idx >= 0 else self.audiosep_chunk_combo.findData(AUDIOSEP_CHUNK_SECONDS_DEFAULT))
        chunk_layout.addWidget(self.audiosep_chunk_combo)
        chunk_layout.addStretch()
        welcome_layout.addLayout(chunk_layout)

        chunk_hint = QLabel(LABEL_AUDIOSEP_CHUNK_HINT)
        chunk_hint.setStyleSheet(SETTINGS_STATUS_STYLE)
        chunk_hint.setWordWrap(True)
        welcome_layout.addWidget(chunk_hint)

        # AudioSep model path settings
        settings_title = QLabel(SECTION_AUDIOSEP_SETTINGS)
        settings_title.setStyleSheet(SECTION_TITLE_STYLE)
        welcome_layout.addWidget(settings_title)

        self.audiosep_ckpt_field = LabeledBrowseField(
            LABEL_AUDIOSEP_BASE_CHECKPOINT,
            self.app_settings.get(SETTING_KEY_AUDIOSEP_BASE_CHECKPOINT, ""),
        )
        self.audiosep_yaml_field = LabeledBrowseField(
            LABEL_AUDIOSEP_YAML_CONFIG,
            self.app_settings.get(SETTING_KEY_AUDIOSEP_YAML_CONFIG, ""),
        )
        self.music_speech_ckpt_field = LabeledBrowseField(
            LABEL_MUSIC_SPEECH_CHECKPOINT,
            self.app_settings.get(SETTING_KEY_MUSIC_SPEECH_CHECKPOINT, ""),
        )

        self.audiosep_ckpt_field.button.clicked.connect(
            lambda: self.browse_for_path(
                self.audiosep_ckpt_field.line_edit,
                PROMPT_PICK_AUDIOSEP_CHECKPOINT,
                FILE_FILTER_CHECKPOINT,
            )
        )
        self.audiosep_yaml_field.button.clicked.connect(
            lambda: self.browse_for_path(
                self.audiosep_yaml_field.line_edit,
                PROMPT_PICK_AUDIOSEP_YAML_CONFIG,
                FILE_FILTER_YAML,
            )
        )
        self.music_speech_ckpt_field.button.clicked.connect(
            lambda: self.browse_for_path(
                self.music_speech_ckpt_field.line_edit,
                PROMPT_PICK_MUSIC_SPEECH_CHECKPOINT,
                FILE_FILTER_CHECKPOINT,
            )
        )

        welcome_layout.addLayout(self.audiosep_ckpt_field.build_layout())
        welcome_layout.addLayout(self.audiosep_yaml_field.build_layout())
        welcome_layout.addLayout(self.music_speech_ckpt_field.build_layout())

        save_settings_btn = QPushButton(BUTTON_SAVE_SETTINGS)
        save_settings_btn.clicked.connect(self.save_welcome_settings)
        welcome_layout.addWidget(save_settings_btn)

        self.settings_status_label = QLabel(SETTINGS_LOADED_TEXT)
        self.settings_status_label.setStyleSheet(SETTINGS_STATUS_STYLE)
        welcome_layout.addWidget(self.settings_status_label)
        welcome_layout.addStretch()

        self.tab_widget.addTab(welcome_widget, TAB_WELCOME)

        console_widget = QWidget()
        console_layout = QVBoxLayout(console_widget)
        console_layout.setContentsMargins(8, 8, 8, 8)
        self.console_output = QPlainTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.document().setMaximumBlockCount(self.console_line_limit_spin.value())
        console_layout.addWidget(self.console_output)
        
        # Tab 2: Device Configuration
        self.device_config_panel = DeviceConfigPanel()
        self.tab_widget.addTab(self.device_config_panel, TAB_DEVICE_CONFIGURATION)
        
        # Tab 3: Post Processing
        post_processing_widget = QWidget()
        post_processing_layout = QVBoxLayout(post_processing_widget)
        post_processing_layout.setContentsMargins(0, 0, 0, 0)
        post_processing_layout.setSpacing(0)
        
        # Create splitter for audio viewer and annotation panel
        self.post_processing_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.post_processing_splitter.setOpaqueResize(True)
        
        # Create audio viewer container with file browser at top
        audio_container = QWidget()
        audio_container_layout = QVBoxLayout(audio_container)
        audio_container_layout.setContentsMargins(0, 0, 0, 0)
        audio_container_layout.setSpacing(2)
        
        # Audio Visualizer section title (placed first, above Open button)
        audio_viewer_title = QLabel("Audio Visualizer")
        audio_viewer_title.setStyleSheet(SECTION_TITLE_STYLE)
        audio_viewer_title.setContentsMargins(9, 0, 0, 0)
        audio_container_layout.addWidget(audio_viewer_title)

        # File browser section
        file_browser_layout = QHBoxLayout()
        file_browser_layout.setContentsMargins(9, 4, 4, 2)
        file_browser_layout.setSpacing(4)

        open_file_btn = QPushButton(BUTTON_OPEN)
        open_file_btn.setMaximumWidth(OPEN_BUTTON_MAX_WIDTH)
        open_file_btn.clicked.connect(self.open_audio_file)
        file_browser_layout.addWidget(open_file_btn)

        self.filename_label = QLabel(LABEL_NO_FILE_LOADED)
        self.filename_label.setStyleSheet(LABEL_FILENAME_STYLE_IDLE)
        file_browser_layout.addWidget(self.filename_label, 1)

        audio_container_layout.addLayout(file_browser_layout)

        # Audio visualization
        self.audio_viewer = AudioViewerWidget()
        audio_container_layout.addWidget(self.audio_viewer, 1)

        # Shared spectrogram colorbar used by the audio viewer
        self.colorbar = pg.HistogramLUTWidget()
        
        self.post_processing_splitter.addWidget(audio_container)

        # Right pane: Annotation panel
        self.annotation_panel = AnnotationPanelWidget()
        self.annotation_panel.set_working_directory(self.app_settings.get(SETTING_KEY_WORKING_DIRECTORY, ""))
        self.annotation_panel.set_busy_handlers(
            self.set_ui_busy,
            self.show_busy_dialog,
            self.update_busy_progress,
            self.clear_busy_state,
            self.run_background_task,
        )
        self.annotation_panel.set_audio_viewer(self.audio_viewer)  # Pass audio viewer for filter preview
        self.post_processing_splitter.addWidget(self.annotation_panel)
        
        # Set initial sizes and stretch factors for post processing splitter
        self.post_processing_splitter.setSizes([1100, 300])
        self.post_processing_splitter.setStretchFactor(0, 5)
        self.post_processing_splitter.setStretchFactor(1, 1)
        
        post_processing_layout.addWidget(self.post_processing_splitter)
        self.tab_widget.addTab(post_processing_widget, TAB_POST_PROCESSING)
        self.tab_widget.addTab(console_widget, TAB_CONSOLE_OUT)
        
        layout.addWidget(self.tab_widget)
        
        # Connect signals with updated annotation panel signature
        self.audio_viewer.selection_changed.connect(self.annotation_panel.update_from_selection)
        
        # Connect filter tab activation to audio viewer filter preview mode
        self.annotation_panel.filter_tab_activated.connect(self.audio_viewer.set_filter_preview_mode)
        
        # Connect filter channel selection to audio viewer filter preview channel
        self.annotation_panel.filter_channel_selector.currentIndexChanged.connect(
            lambda: self.audio_viewer.set_filter_preview_channel(
                int(self.annotation_panel.filter_channel_selector.currentData() or 0)
            )
        )
        
        # Connect annotation system signals
        self.audio_viewer.annotation_created.connect(self.on_annotation_created_from_viewer)
        self.audio_viewer.annotation_block_clicked.connect(self.annotation_panel.select_annotation_by_index)
        self.annotation_panel.annotations_changed.connect(self.audio_viewer.set_annotations)
        self.annotation_panel.draft_annotation_changed.connect(self.audio_viewer.set_pending_annotation)
        self.annotation_panel.draft_annotation_cleared.connect(self.audio_viewer.clear_pending_annotation)
        self.annotation_panel.source_audio_swapped.connect(self.on_source_audio_swapped)
        
        # Connect filter results to audio viewer
        # We'll need to call this when filter is applied in annotation_panel
        
        # Connect colorbar to audio viewer
        self.audio_viewer.set_colorbar(self.colorbar)

        # Connect audio device selector to playback controls
        if hasattr(self.audio_viewer, 'playback_controls') and self.audio_viewer.playback_controls is not None:
            self.audio_device_selector.on_device_changed_callback = self.audio_viewer.set_audio_output_device
            self.audio_device_selector.on_test_requested_callback = self.audio_viewer.play_output_test_tone
            # Set the currently selected device
            selected_device_info = self.audio_device_selector.get_selected_device_description()
            if selected_device_info:
                self.audio_viewer.set_audio_output_device(selected_device_info)

        self.install_console_capture()
        
        # Create menu bar for file operations
        self.create_menu_bar()

    def browse_for_path(self, target_input, title, file_filter):
        """Open a file picker and set selected path into target input."""
        file_path, _ = QFileDialog.getOpenFileName(self, title, str(Path.home()), file_filter)
        if file_path:
            target_input.setText(file_path)

    def save_welcome_settings(self):
        """Persist Welcome tab settings for AudioSep-related paths."""
        self.app_settings.update({
            SETTING_KEY_WORKING_DIRECTORY: self.working_dir_field.line_edit.text().strip(),
            SETTING_KEY_CONSOLE_LINE_LIMIT: int(self.console_line_limit_spin.value()),
            SETTING_KEY_AUDIOSEP_CHUNK_SECONDS: int(self.audiosep_chunk_combo.currentData() or AUDIOSEP_CHUNK_SECONDS_DEFAULT),
            SETTING_KEY_AUDIOSEP_BASE_CHECKPOINT: self.audiosep_ckpt_field.line_edit.text().strip(),
            SETTING_KEY_AUDIOSEP_YAML_CONFIG: self.audiosep_yaml_field.line_edit.text().strip(),
            SETTING_KEY_MUSIC_SPEECH_CHECKPOINT: self.music_speech_ckpt_field.line_edit.text().strip(),
        })
        save_settings(self.app_settings)
        self.annotation_panel.set_working_directory(self.app_settings.get(SETTING_KEY_WORKING_DIRECTORY, ""))
        self.settings_status_label.setText(SETTINGS_SAVED_TEXT)

    def on_console_line_limit_changed(self, value):
        """Apply the configured console line cap immediately."""
        if hasattr(self, "console_output") and self.console_output is not None:
            self.console_output.document().setMaximumBlockCount(int(value))

    def install_console_capture(self):
        """Mirror stdout/stderr into the Console Out tab while preserving terminal output."""
        self.stdout_proxy = ConsoleStreamProxy(self.original_stdout, self.append_console_text)
        self.stderr_proxy = ConsoleStreamProxy(self.original_stderr, self.append_console_text)
        sys.stdout = self.stdout_proxy
        sys.stderr = self.stderr_proxy

        # Rebind existing logging StreamHandlers that were created before stream proxying.
        self._patched_logging_handlers = []
        logger_names = [""] + list(logging.root.manager.loggerDict.keys())
        for logger_name in logger_names:
            logger = logging.getLogger(logger_name)
            for handler in logger.handlers:
                if not isinstance(handler, logging.StreamHandler):
                    continue
                previous_stream = getattr(handler, "stream", None)
                if previous_stream is self.original_stdout:
                    handler.setStream(self.stdout_proxy)
                    self._patched_logging_handlers.append((handler, previous_stream))
                elif previous_stream is self.original_stderr:
                    handler.setStream(self.stderr_proxy)
                    self._patched_logging_handlers.append((handler, previous_stream))

    def restore_console_capture(self):
        """Restore original stdout/stderr streams on shutdown."""
        for handler, stream in self._patched_logging_handlers:
            try:
                handler.setStream(stream)
            except Exception:
                pass
        self._patched_logging_handlers = []

        if sys.stdout is self.stdout_proxy:
            sys.stdout = self.original_stdout
        if sys.stderr is self.stderr_proxy:
            sys.stderr = self.original_stderr

        if self.stdout_proxy is not None:
            try:
                self.stdout_proxy.close()
            except Exception:
                pass
        if self.stderr_proxy is not None:
            try:
                self.stderr_proxy.close()
            except Exception:
                pass

    def append_console_text(self, text):
        """Append mirrored console text into the read-only console widget."""
        if not hasattr(self, "console_output") or self.console_output is None or not text:
            return
        try:
            cursor = self.console_output.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(text)
            self.console_output.setTextCursor(cursor)
            self.console_output.ensureCursorVisible()
        except RuntimeError:
            # Console widget may already be destroyed during shutdown.
            return

    def browse_for_working_directory(self):
        """Pick and set the working directory used by post-processing outputs."""
        start_dir = self.working_dir_field.line_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, PROMPT_PICK_WORKING_DIRECTORY, start_dir)
        if folder:
            self.working_dir_field.line_edit.setText(folder)

    def create_menu_bar(self):
        """Create the menu bar with File menu."""
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu(MENU_FILE)
        
        open_action = file_menu.addAction(MENU_OPEN_AUDIO_FILE)
        open_action.triggered.connect(self.open_audio_file)
        
        file_menu.addSeparator()
        exit_action = file_menu.addAction(MENU_EXIT)
        exit_action.triggered.connect(self.close)

    def open_audio_file(self):
        """Open a file dialog to select an audio file and load it."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            MENU_OPEN_AUDIO_FILE,
            str(Path.home()), 
            FILE_FILTER_AUDIO,
        )
        
        if file_path:
            # Update filename label
            file_name = Path(file_path).name
            self.filename_label.setText(f"{LABEL_FILE_LOADED_PREFIX}: {file_name}")
            self.filename_label.setStyleSheet(LABEL_FILENAME_STYLE_ACTIVE)
            self.on_file_selected(file_path)

    def set_ui_busy(self, is_busy):
        """Enable or disable the main interactive panes while work is running."""
        self.audio_viewer.setEnabled(not is_busy)
        self.annotation_panel.setEnabled(not is_busy)
        self.post_processing_splitter.setEnabled(not is_busy)
        if is_busy:
            self.setCursor(Qt.CursorShape.WaitCursor)
        else:
            self.unsetCursor()

    def show_busy_dialog(self, title, label_text, value=0, maximum=100):
        """Show or update the modal busy dialog used for background tasks."""
        if self.busy_dialog is None:
            self.busy_dialog = QProgressDialog(self)
            self.busy_dialog.setCancelButton(None)
            self.busy_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
            self.busy_dialog.setMinimumDuration(0)
            self.busy_dialog.setAutoClose(False)
            self.busy_dialog.setAutoReset(False)
            self.busy_dialog.setMinimumWidth(BUSY_DIALOG_MIN_WIDTH)
        self.busy_dialog.setWindowTitle(title)
        self.busy_dialog.setRange(0, maximum)
        self.busy_dialog.setLabelText(label_text)
        self.busy_dialog.setValue(value)
        self.busy_dialog.show()

    def update_busy_progress(self, value, detail_text=""):
        """Update progress text and bar for the current background task."""
        if self.busy_dialog is None:
            return
        prefix = self.busy_label_prefix if self.busy_label_prefix else BUSY_PREFIX_DEFAULT
        label_text = f"{prefix}: {value}%"
        if detail_text:
            label_text = f"{label_text}\n{detail_text}"
        self.busy_dialog.setLabelText(label_text)
        self.busy_dialog.setValue(value)

    def clear_busy_state(self):
        """Close the busy dialog and restore interaction."""
        if self.busy_dialog is not None:
            self.busy_dialog.hide()
            self.busy_dialog.reset()
        self.set_ui_busy(False)
        self.busy_task_title = ""
        self.busy_label_prefix = ""

    def run_background_task(self, worker, title, label_prefix, finished_slot):
        """Run a worker object in a thread while showing modal progress."""
        if self.active_worker_thread is not None:
            return

        self.busy_task_title = title
        self.busy_label_prefix = label_prefix
        self.set_ui_busy(True)
        self.show_busy_dialog(title, f"{label_prefix}: 0%", 0)

        self.active_worker_thread = QThread(self)
        self.active_worker = worker
        worker.moveToThread(self.active_worker_thread)

        self.active_worker_thread.started.connect(worker.run)
        worker.progress.connect(self.update_busy_progress)
        worker.finished.connect(finished_slot)
        worker.finished.connect(self.on_background_task_finished)
        worker.error.connect(self.on_background_task_error)
        worker.finished.connect(self.active_worker_thread.quit)
        worker.error.connect(self.active_worker_thread.quit)
        self.active_worker_thread.finished.connect(worker.deleteLater)
        self.active_worker_thread.finished.connect(self.active_worker_thread.deleteLater)
        self.active_worker_thread.finished.connect(self.on_worker_thread_finished)
        self.active_worker_thread.start()

    def on_file_selected(self, file_path):
        """Load audio in the background while the UI is temporarily disabled."""
        file_name = Path(file_path).name
        worker = AudioLoadWorker(file_path)
        self.run_background_task(worker, TASK_TITLE_LOADING_AUDIO, f"Loading {file_name}", self.on_audio_loaded)

    def on_audio_loaded(self, file_path, y, sr, is_mono):
        """Apply decoded audio on the main thread after worker completion."""
        try:
            self.update_busy_progress(95, TASK_DETAIL_RENDERING_PLOTS)
            self.audio_viewer.apply_loaded_audio(file_path, y, sr, is_mono)
            self.annotation_panel.set_audio_data(y, sr, is_mono, file_path)
            # Pass annotations to audio viewer for visualization
            self.audio_viewer.set_annotations(self.annotation_panel.annotations)
            self.update_busy_progress(100, TASK_DETAIL_DONE)
        except Exception as exc:
            QMessageBox.critical(self, TASK_TITLE_LOADING_AUDIO, str(exc))
        finally:
            # Keep dialog lifecycle robust even if a slot after worker completion raises.
            self.clear_busy_state()

    def on_annotation_created_from_viewer(self, start_time, end_time, channel):
        """Handle annotation creation from interactive selection in audio viewer."""
        # Update annotation panel UI with the new times and channel
        self.annotation_panel.update_from_selection(start_time, end_time)
        # Set the channel selector by stable data value
        idx = self.annotation_panel.channel_combo.findData(channel)
        if idx >= 0:
            self.annotation_panel.channel_combo.setCurrentIndex(idx)

    def on_source_audio_swapped(self, file_path, y, sr, is_mono):
        """Apply swapped source audio to the viewer while keeping annotation context."""
        self.audio_viewer.apply_loaded_audio(file_path, y, sr, is_mono)
        self.audio_viewer.set_annotations(self.annotation_panel.annotations)
        file_name = Path(file_path).name
        self.filename_label.setText(f"{LABEL_FILE_LOADED_PREFIX}: {file_name}")
        self.filename_label.setStyleSheet(LABEL_FILENAME_STYLE_ACTIVE)

    def on_background_task_finished(self, *_args):
        """Restore UI state after a background task completes successfully."""
        self.clear_busy_state()

    def on_background_task_error(self, error_message):
        """Restore UI state and display a task error."""
        task_title = self.busy_task_title or TASK_ERROR_FALLBACK_TITLE
        self.clear_busy_state()
        QMessageBox.critical(self, task_title, error_message)

    def on_worker_thread_finished(self):
        """Clear active worker references once the thread is fully torn down."""
        self.active_worker_thread = None
        self.active_worker = None

    def closeEvent(self, event):
        """Restore redirected streams before closing the window."""
        if hasattr(self, "audio_viewer") and self.audio_viewer is not None:
            try:
                self.audio_viewer.cleanup_multimedia()
            except Exception:
                pass
        self.restore_console_capture()
        super().closeEvent(event)
