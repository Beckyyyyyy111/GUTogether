#!/usr/bin/env python3
"""
Audio Annotation GUI Application
Main entry point for the Qt6-based audio annotation tool.
"""

import sys
from PyQt6.QtCore import qInstallMessageHandler
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow


def _install_qt_message_filter():
    """Silence noisy Qt FFmpeg disconnect warnings that are not actionable for users."""
    suppressed_markers = (
        "QObject::disconnect: wildcard call disconnects from destroyed signal of QFFmpeg::Demuxer::",
        "QObject::disconnect: wildcard call disconnects from destroyed signal of QFFmpeg::StreamDecoder::",
        "QObject::disconnect: wildcard call disconnects from destroyed signal of QFFmpeg::AudioRenderer::",
    )

    def _handler(_msg_type, _context, message):
        text = str(message)
        if any(marker in text for marker in suppressed_markers):
            return
        if getattr(sys, "stderr", None) is not None:
            sys.stderr.write(f"{text}\n")

    qInstallMessageHandler(_handler)


def main():
    _install_qt_message_filter()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
