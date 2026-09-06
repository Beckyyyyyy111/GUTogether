"""Centralized UI labels, settings keys, and shared numeric defaults."""

# Window and app metadata
APP_WINDOW_TITLE = "Open GUT Interface Playground v0.1b"
APP_WINDOW_GEOMETRY = (100, 100, 1400, 800)

# Tab labels
TAB_WELCOME = "Welcome"
TAB_CONSOLE_OUT = "Console Out"
TAB_DEVICE_CONFIGURATION = "Device Configuration"
TAB_POST_PROCESSING = "Post Processing"

# Welcome tab text and styles
WELCOME_TITLE_TEXT = "Welcome"
WELCOME_TITLE_STYLE = "font-size: 20px; font-weight: 600;"
WELCOME_INTRO_TEXT = (
    "This is the Open GUT Interface playground.\n"
    "Use this tab for project overview, instructions, and visuals.\n"
    "You can replace this content anytime."
)
SECTION_TITLE_STYLE = "font-size: 14px; font-weight: 600;"
SECTION_WORKING_FILES = "Working Files"
SECTION_CONSOLE_OUTPUT = "Python Console Output"
SECTION_AUDIOSEP_SETTINGS = "AudioSep Settings"
SETTINGS_LOADED_TEXT = "Settings loaded."
SETTINGS_SAVED_TEXT = "Settings saved."
SETTINGS_STATUS_STYLE = "color: #666;"

# Settings keys and defaults
SETTING_KEY_AUDIOSEP_BASE_CHECKPOINT = "audiosep_base_checkpoint"
SETTING_KEY_AUDIOSEP_YAML_CONFIG = "audiosep_yaml_config"
SETTING_KEY_MUSIC_SPEECH_CHECKPOINT = "music_speech_checkpoint"
SETTING_KEY_CONSOLE_LINE_LIMIT = "console_line_limit"
SETTING_KEY_WORKING_DIRECTORY = "working_directory"

AUDIOSEP_DIR_NAME = "AudioSep"
WORKING_DIR_NAME = "working_files"
SETTINGS_FILENAME = "app_settings.json"

# Common file filters
FILE_FILTER_AUDIO = "Audio Files (*.wav *.wave *.mp3);;All Files (*)"
FILE_FILTER_CHECKPOINT = "Checkpoint Files (*.ckpt *.pt);;All Files (*)"
FILE_FILTER_YAML = "YAML Files (*.yaml *.yml);;All Files (*)"

# Main window labels and menu
BUTTON_OPEN = "Open"
BUTTON_SAVE_SETTINGS = "Save Settings"
BUTTON_BROWSE_FOLDER = "Browse"
LABEL_WORKING_DIRECTORY = "Working Directory"
LABEL_CONSOLE_LINE_LIMIT = "Console Line Limit"
LABEL_AUDIOSEP_CHUNK_SECONDS = "PyTorch Chunk Length"
LABEL_AUDIOSEP_CHUNK_HINT = "Longer chunk length usually requires more RAM."
LABEL_AUDIOSEP_BASE_CHECKPOINT = "AudioSep Base Checkpoint"
LABEL_AUDIOSEP_YAML_CONFIG = "AudioSep YAML Config"
LABEL_MUSIC_SPEECH_CHECKPOINT = "Music-Speech Checkpoint"
LABEL_NO_FILE_LOADED = "No file loaded"
LABEL_FILE_LOADED_PREFIX = "Loaded"
LABEL_FILENAME_STYLE_IDLE = "color: #666; font-size: 11px;"
LABEL_FILENAME_STYLE_ACTIVE = "color: #333;"
MENU_FILE = "File"
MENU_OPEN_AUDIO_FILE = "Open Audio File"
MENU_EXIT = "Exit"
PROMPT_PICK_WORKING_DIRECTORY = "Pick Working Directory"
PROMPT_PICK_AUDIOSEP_CHECKPOINT = "Pick AudioSep checkpoint"
PROMPT_PICK_AUDIOSEP_YAML_CONFIG = "Pick AudioSep YAML config"
PROMPT_PICK_MUSIC_SPEECH_CHECKPOINT = "Pick music_speech checkpoint"

# Busy/progress texts
BUSY_PREFIX_DEFAULT = "Processing"
TASK_TITLE_LOADING_AUDIO = "Loading Audio"
TASK_ERROR_FALLBACK_TITLE = "Processing Error"
TASK_DETAIL_RENDERING_PLOTS = "Rendering plots"
TASK_DETAIL_DONE = "Done"
BUSY_DIALOG_MIN_WIDTH = 420
OPEN_BUTTON_MAX_WIDTH = 70
CONSOLE_LINE_LIMIT_MIN = 100
CONSOLE_LINE_LIMIT_MAX = 10000
CONSOLE_LINE_LIMIT_DEFAULT = 1000
SETTING_KEY_AUDIOSEP_CHUNK_SECONDS = "audiosep_chunk_seconds"
AUDIOSEP_CHUNK_SECONDS_OPTIONS = [5, 10, 20, 30, 60, 90, 120]
AUDIOSEP_CHUNK_SECONDS_DEFAULT = 20

# Audio viewer labels and defaults
LABEL_LEFT_CHANNEL = "L Channel:"
LABEL_RIGHT_CHANNEL = "R Channel:"
LABEL_SINGLE_CHANNEL = "Channel:"
TITLE_LEFT_CHANNEL = "L Channel"
TITLE_RIGHT_CHANNEL = "R Channel"
TITLE_MONO_CHANNEL = "Channel"
LABEL_TIME_AXIS = "Time (s)"
LABEL_AMPLITUDE_OR_FREQUENCY_AXIS = "Amplitude / Frequency"
LABEL_AMPLITUDE_AXIS = "Amplitude"
LABEL_FREQUENCY_AXIS = "Frequency (Hz)"

VIEW_MODE_WAVEFORM = "Waveform"
VIEW_MODE_SPECTROGRAM = "Spectrogram"
BUTTON_AUTO_RANGE = "Auto Range"
BUTTON_REPLOT = "Replot"

LABEL_SPEC_MAX_FREQ = "Spectrogram Max Freq:"
LABEL_WAVEFORM_MAX_SAMPLES = "Waveform Max Samples:"

SPECTROGRAM_MIN_FREQ_HZ = 100.0
SPECTROGRAM_MAX_FREQ_HZ = 100000.0
SPECTROGRAM_FREQ_STEP_HZ = 100.0
SPECTROGRAM_FREQ_SUFFIX = " Hz"
DEFAULT_SPECTROGRAM_FREQ_HZ = 11000.0
DEFAULT_SPECTROGRAM_LEVELS = (-30, 20)
DEFAULT_COLORBAR_WIDTH = 80

WAVEFORM_MAX_SAMPLES_MIN = 1000
WAVEFORM_MAX_SAMPLES_MAX = 10_000_000
WAVEFORM_MAX_SAMPLES_STEP = 1000
WAVEFORM_MAX_SAMPLES_DEFAULT = 100000
WAVEFORM_Y_MIN = -1.0
WAVEFORM_Y_MAX = 1.0

PLAY_BUTTON_TEXT = "Play"
PAUSE_BUTTON_TEXT = "Pause"
AUTO_FOLLOW_BUTTON_TEXT = "Auto Follow"
TIME_LABEL_DEFAULT = "00:00 / 00:00"
PLAYBACK_UNAVAILABLE_TITLE = "Playback Unavailable"
PLAYBACK_UNAVAILABLE_MESSAGE = (
    "PyQt6 multimedia backend is not available. Please install/update PyQt6 "
    "multimedia support and restart the app."
)
PROCESSED_PLAYBACK_UNAVAILABLE_MESSAGE = "PyQt6 multimedia backend is not available."
PLAYBACK_NO_PROCESSED_OUTPUT_MESSAGE = "No filtering has been done yet. You can listen to original audio now."

COLORBAR_PRESET = "viridis"

# Annotation/filtering defaults
PANEL_TITLE_PROCESSING = "Processing"
TAB_FILTERING = "Filtering"
TAB_ANNOTATION = "Annotation"
TITLE_ORIGINAL_SPECTROGRAM = "Original Spectrogram"
TITLE_FILTERED_SPECTROGRAM = "Filtered Spectrogram"
LABEL_FILTER_UNIT = "Filter Unit:"
LABEL_CHANNEL = "Channel:"
LABEL_CHANNEL_TEMPLATE = "Channel {index}"
CHANNEL_1_LABEL = "Channel 1"
LABEL_NAME = "Name:"
LABEL_START = "Start:"
LABEL_STOP = "Stop:"
LABEL_COMMENT = "Comment:"
LABEL_COLOR = "Color:"
LABEL_CHANNEL_SELECT = "Channel:"
LABEL_STEREO = "Stereo"
LABEL_LEFT_SHORT = "L"
LABEL_RIGHT_SHORT = "R"

# Annotation channel options
ANNOTATION_CHANNEL_MONO = "Mono"
ANNOTATION_CHANNEL_LEFT = "Left only"
ANNOTATION_CHANNEL_RIGHT = "Right only"
ANNOTATION_CHANNEL_BOTH = "Both"

# Default annotation colors (palette for auto-assignment)
ANNOTATION_DEFAULT_COLORS = [
    "#FF6B6B",  # Red
    "#4ECDC4",  # Teal
    "#45B7D1",  # Blue
    "#FFA07A",  # Light Salmon
    "#98D8C8",  # Mint
    "#F7DC6F",  # Yellow
    "#BB8FCE",  # Purple
    "#85C1E2",  # Light Blue
]

# Keyboard shortcuts for annotation (key codes: 49='1', 50='2', 51='3')
KEYBOARD_SHORTCUT_SINGLE_CHANNEL = 49
KEYBOARD_SHORTCUT_BOTH_CHANNELS = 50
KEYBOARD_SHORTCUT_RIGHT_CHANNEL = 51

# Annotation UI buttons
BUTTON_LOAD_ANNOTATION_JSON = "Load Annotations"
BUTTON_EXPORT_ANNOTATION_JSON = "Export Annotations"
FILTER_PREVIEW_Y_MAX_HZ = 11000.0
FILTER_TEMP_DIR_NAME = "gut_filter_results"
TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
ANNOTATION_LIST_ITEM_TEMPLATE = "{name} ({start:.3f}s - {stop:.3f}s)"

ANNOTATION_TIME_MAX_SECONDS = 3600
ANNOTATION_TIME_DECIMALS = 3
COMMENT_BOX_HEIGHT = 35

BUTTON_ADD = "Add"
BUTTON_UPDATE = "Update"
BUTTON_DELETE = "Delete"
BUTTON_EXPORT_SEGMENT = "Export Segment"
BUTTON_APPLYING_FILTER = "Applying Filter"
BUTTON_PLAY_PROCESSED = "Play Processed"
BUTTON_PAUSE_PROCESSED = "Pause Processed"
BUTTON_STOP = "Stop"

TEXT_FILTER_STATUS_IDLE = "Load audio to preview and apply filters."
TEXT_NO_FILTERS_FOUND = "No filter modules found in filters/."
TEXT_FILTER_APPLIED_STATUS = "Applied {stem}."
TEXT_PROGRESS_PREPARING_FILTER_INPUTS = "Preparing filter inputs"
TEXT_PROGRESS_BUILDING_FILTER_OUTPUT = "Building filtered output"
TEXT_PROGRESS_WRITING_LOGS = "Writing logs and refreshing previews"

MSG_WARNING_TITLE = "Warning"
MSG_ERROR_TITLE = "Error"
MSG_FILTER_ERROR_TITLE = "Filter Error"
MSG_PLAYBACK_TITLE = "Playback"
MSG_SUCCESS_TITLE = "Success"

MSG_LOAD_AUDIO_BEFORE_FILTER = "Load audio before applying filters."
MSG_NO_FILTER_SELECTED = "No filter unit selected."
MSG_FAILED_LOAD_FILTER_MODULES = "Failed to load filter modules: {error}"
MSG_FAILED_READ_FILTER_SCHEMA = "Failed to read filter schema: {error}"
MSG_FAILED_APPLY_FILTER = "Failed to apply filter: {error}"
MSG_FAILED_LOAD_ANNOTATIONS = "Failed to load annotations: {error}"
MSG_FAILED_SAVE_ANNOTATIONS = "Failed to save annotations: {error}"
MSG_ANNOTATION_NAME_REQUIRED = "Please enter an annotation name."
MSG_START_BEFORE_STOP = "Start time must be before stop time."
MSG_SELECT_ANNOTATION_TO_UPDATE = "Please select an annotation to update."
MSG_SELECT_ANNOTATION_TO_DELETE = "Please select an annotation to delete."
MSG_SELECT_ANNOTATION_TO_EXPORT = "Please select an annotation to export."
MSG_NO_AUDIO_LOADED = "No audio loaded."
MSG_SELECT_EXPORT_CHANNEL_OPTION = "Select at least one channel export option."
MSG_EXPORT_FAILED = "Export failed: {error}"
MSG_EXPORTED_SUCCESS = "Exported: {files}"

PROMPT_EXPORT_ANNOTATION_BASE = "Export Annotation Base Name"
FILE_FILTER_WAVE = "WAVE Files (*.wav)"
JSON_SUFFIX = ".json"
FILTERED_EXPORT_STEREO_SUFFIX = "_LR.wav"
FILTERED_EXPORT_LEFT_SUFFIX = "_L.wav"
FILTERED_EXPORT_RIGHT_SUFFIX = "_R.wav"
FILTERED_EXPORT_MONO_SUFFIX = "_mono.wav"

FILTER_BUSY_TITLE = "Applying Filter"
FILTER_BUSY_LABEL = "Applying filter: 0%"
FILTER_OUTPUT_LOG_TEMPLATE = "{name},{params},{exported}\n"
FILTER_LOG_NAME_TEMPLATE = "{name}_{timestamp}.txt"
FILTER_EXPORT_NAME_TEMPLATE = "{stem}_{timestamp}.wav"

# Device Configuration Panel
DEVICE_CONFIG_TITLE = "PCB Configuration"
DEVICE_CONFIG_SECTION_OPERATION = "Operation Mode"
DEVICE_CONFIG_SECTION_AUDIO = "Audio Settings"
DEVICE_CONFIG_SECTION_RECORDING = "Recording Options"

DEVICE_CONFIG_RECORDING = "Recording"
DEVICE_CONFIG_PLAYBACK = "Playback"
DEVICE_CONFIG_LOOPBACK = "Loopback"

DEVICE_CONFIG_LABEL_SAMPLING_RATE = "Sampling Rate"
DEVICE_CONFIG_SAMPLING_RATES = [2000, 4000, 8000, 16000]

DEVICE_CONFIG_LABEL_MICROPHONES = "Microphones"
DEVICE_CONFIG_MIC_FRONT_ONLY = "Front Only (Ambient, Mono)"
DEVICE_CONFIG_MIC_BACK_ONLY = "Back Only (Gastrointestinal, Mono)"
DEVICE_CONFIG_MIC_BOTH = "Both (Stereo)"

DEVICE_CONFIG_LABEL_DURATION = "Recording Duration (hh:mm:ss)"
DEVICE_CONFIG_LABEL_FILENAME = "Output File Name"
DEVICE_CONFIG_DEFAULT_FILENAME = "output"

DEVICE_CONFIG_PREVIEW_TITLE = "Configuration Preview (JSON)"
DEVICE_CONFIG_EXPORT_BTN = "Export Config"
DEVICE_CONFIG_EXPORT_FILTER = "JSON Files (*.json);;All Files (*)"

# Numeric defaults used in splitters/layout
SPLITTER_DEFAULT_TWO_PANE_SIZES = [980, 420]
SPLITTER_DEFAULT_VERTICAL_PREVIEW_SIZES = [200, 200]
SPLITTER_DEFAULT_AUDIO_PLOT_SIZES = [400, 400]
