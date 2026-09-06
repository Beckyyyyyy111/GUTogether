"""Reusable widgets for labeled path settings rows."""

from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit


class LabeledBrowseField:
    """Build a reusable label + line edit + browse button row."""

    def __init__(self, label_text, initial_text="", button_text="Browse"):
        self.label = QLabel(label_text)
        self.line_edit = QLineEdit(initial_text)
        self.button = QPushButton(button_text)
        self.button.setMaximumWidth(90)

    def build_layout(self):
        root = QVBoxLayout()
        root.setSpacing(3)
        root.addWidget(self.label)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.line_edit, 1)
        row.addWidget(self.button)

        root.addLayout(row)
        return root
