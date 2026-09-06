# OpenGUT Software - Device Configuration / Sound Processing / Annotation / File Export

A Qt6-based Python GUI application for OpenGUT project. Originally developed by OpenGUT engineering team.
- Preview and annotate audio files with interactive waveform and spectrogram visualization.

## Features

- **OpenGUT Device Configuration**: Simple GUI to configure an OpenGUT hardware and export settings in JSON format
- **Audio Visualization**: Interactive waveform and spectrogram displays for L/R channels using librosa and pyqtgraph
- **Audio Processing (Filtering)**: Audio processing - filtering input audio with 1) high-pass filter implemented with SciPy package, or 2) [AudioSep](https://github.com/ryohajika/AudioSep) ML-based engine using natural language
- **Annotation System**: Create, edit, and manage annotations with:
  - Annotation name
  - Start and stop time markers
  - Comments
  - Export annotated segments as WAVE files

## Installation

0. Install Python 3.12.13
```bash
# if you're on macOS, Homebrew and Pyenv are installed
pyenv install 3.12.13
# you may want to setup a virtualenv
```

1. Clone this project
```bash
git clone https://github.com/OpenGUT/OpenGUT
cd OpenGUT/Software
git submodule init && git submodule update
```

2. Install dependencies:
```bash
pip install -r requirements_pyenv3.12.13_venv.txt
```

3. Run the application:
```bash
python main.py
```

## Data Collection Usage

1. Prepare a microSD card for the OpenGUT PCB board
2. On the GUI, go to "Device Config" tab to export `config.json` file and download it to the microSD card
3. Load the microSD card on the PCB board and do data sampling


## Post Processing Usage

1. **Load Audio**: Use the file browser on the left to navigate and select a WAVE file
2. **Visualize**: The center pane shows the audio waveform or spectrogram (toggle with dropdown)
3. **Annotate**: Use the right pane to:
   - Enter annotation details (name, timing, comments)
   - Click "Add Annotation" to create new annotations
   - Select annotations from the list to edit or delete
   - Click "Export Segment" to save annotated sections as new WAVE files

#### Details are available from OpenGUT Official Documentation page: https://opengut.github.io

## Project Structure

```
.
├── app_settings.py                           # Application settings script
├── app_settings.json                         # JSON settings file that will be loaded/updated whenever we run this software **(if missing it will be generated automatically)**
├── const.py                                  # Constant values definition, mostly UI components labeling
├── main.py                                   # Application entry point
├── requirements_pyenv3.12.13_venv.txt        # Python dependencies including those libraries we need to run AudioSep
├── requirements.txt                          # Python dependencies
├── ui/
│   ├── __init__.py
│   ├── main_window.py      # Main window layout
│   ├── file_browser.py     # File tree widget
│   ├── audio_viewer.py     # Visualization widget
│   └── annotation_panel.py # Annotation controls
├── filters
│   ├── __init__.py
│   ├── template_filter.py  # Base filter script (user custom template)
│   ├── filter_loader.py    # Simple script that look up and load filters available
│   ├── scipy_highpass_filter.py              # Butterworth filter implemented with SciPy
│   ├── audiosep_filter.py  # Experimental filter with AudioSep library (No batch processing, experimental)
│   └── audiosep_filter2.py # Experimental filter with AudioSep library (batch processing enabled, experimental)
└── README.md               # This README
```

## Requirements
Refer `requirements_pyenv3.12.13_venv.txt` for the details.
This software has been built and tested on macOS26, Python 3.12.13. Also,

- PyQt6==6.6.1
- librosa==0.10.0
- pyqtgraph==0.13.7
- numpy==1.24.3
- scipy==1.11.4
- soundfile==0.12.1

For the AudioSep filtering, we also used

- tokenizers>=0.14.0,<0.15
- transformers==4.34.0
- torch==2.10.0
- gradio==3.47.1