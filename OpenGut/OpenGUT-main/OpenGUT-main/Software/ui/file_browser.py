"""
Legacy file browser widget (currently unused).

This module is kept for possible future reuse but is intentionally commented out
because the current app flow uses the Welcome/Post Processing tab design with
an explicit file-open button instead of a tree pane.
"""

# from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QPushButton
# from PyQt6.QtCore import pyqtSignal, Qt
# from pathlib import Path
#
#
# class FileBrowserWidget(QWidget):
#     file_selected = pyqtSignal(str)  # Emits file path
#
#     def __init__(self):
#         super().__init__()
#         self.audio_extensions = {'.wav', '.wave', '.mp3'}
#         self.expanded_dirs = set()  # Track which dirs have been loaded
#         self.current_root_dir = str(Path.home())
#         self.init_ui()
#
#     def init_ui(self):
#         layout = QVBoxLayout()
#
#         self.refresh_btn = QPushButton('Refresh File List')
#         self.refresh_btn.clicked.connect(self.refresh_directory)
#         layout.addWidget(self.refresh_btn)
#
#         self.tree = QTreeWidget()
#         self.tree.setHeaderLabels(['Files & Folders'])
#         self.tree.itemClicked.connect(self.on_item_clicked)
#         self.tree.itemExpanded.connect(self.on_item_expanded)
#
#         layout.addWidget(self.tree)
#         self.setLayout(layout)
#
#         # Load Documents directory as starting point
#         self.load_directory(self.current_root_dir)
#
#     def load_directory(self, dir_path):
#         """Load directory tree starting from given path."""
#         self.current_root_dir = dir_path
#         self.tree.clear()
#         self.expanded_dirs.clear()
#         root_path = Path(dir_path)
#         root_item = QTreeWidgetItem(self.tree)
#         root_item.setText(0, root_path.name or str(root_path))
#         root_item.setData(0, Qt.ItemDataRole.UserRole, str(root_path))
#
#         self.populate_tree_shallow(root_item, root_path)
#         self.expanded_dirs.add(str(root_path))
#
#     def refresh_directory(self):
#         """Refresh tree to include files/folders created after app launch."""
#         self.load_directory(self.current_root_dir)
#
#     def populate_tree_shallow(self, parent_item, path):
#         """Populate tree with one level of directories and audio files."""
#         try:
#             items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
#         except (PermissionError, OSError):
#             return
#
#         for item_path in items:
#             try:
#                 if item_path.is_dir() and not item_path.name.startswith('.'):
#                     child = QTreeWidgetItem(parent_item)
#                     child.setText(0, item_path.name)
#                     child.setData(0, Qt.ItemDataRole.UserRole, str(item_path))
#                     # Add a dummy child to make it expandable
#                     QTreeWidgetItem(child)
#                 elif item_path.is_file() and item_path.suffix.lower() in self.audio_extensions:
#                     child = QTreeWidgetItem(parent_item)
#                     child.setText(0, item_path.name)
#                     child.setData(0, Qt.ItemDataRole.UserRole, str(item_path))
#             except (PermissionError, OSError):
#                 continue
#
#     def on_item_expanded(self, item):
#         """Load subdirectories when an item is expanded."""
#         dir_path = item.data(0, Qt.ItemDataRole.UserRole)
#         if dir_path and dir_path not in self.expanded_dirs:
#             self.expanded_dirs.add(dir_path)
#             # Clear dummy children
#             item.takeChildren()
#             # Load real children
#             self.populate_tree_shallow(item, Path(dir_path))
#
#     def on_item_clicked(self, item, column):
#         """Handle tree item click."""
#         file_path = item.data(0, Qt.ItemDataRole.UserRole)
#         if file_path and Path(file_path).is_file():
#             self.file_selected.emit(file_path)
