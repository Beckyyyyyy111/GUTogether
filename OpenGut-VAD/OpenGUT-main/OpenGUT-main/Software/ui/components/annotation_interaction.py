"""Interactive annotation selection controller for AudioViewerWidget."""

from PyQt6.QtCore import QObject, QEvent, Qt, QPointF
from PyQt6.QtGui import QShortcut, QKeySequence, QCursor
from PyQt6.QtWidgets import QApplication
import pyqtgraph as pg


class AnnotationInteractionManager(QObject):
    """Owns key/mouse interaction for creating and selecting annotation regions."""

    def __init__(
        self,
        parent_widget,
        plot_left,
        plot_right,
        is_mono_getter,
        annotations_getter,
        on_annotation_created,
        on_annotation_block_clicked,
        on_pending_annotation,
    ):
        super().__init__(parent_widget)
        self.parent_widget = parent_widget
        self.plot_left = plot_left
        self.plot_right = plot_right
        self.is_mono_getter = is_mono_getter
        self.annotations_getter = annotations_getter
        self.on_annotation_created = on_annotation_created
        self.on_annotation_block_clicked = on_annotation_block_clicked
        self.on_pending_annotation = on_pending_annotation

        self.annotation_mode = None  # None, "single_channel", or "both_channels"
        self.selection_start = None
        self.selection_end = None
        self.is_selecting = False
        self._drag_region_left = None
        self._drag_region_right = None
        self._drag_source_plot = None
        self._last_annotation_channel = "mono"

        self._shortcut1 = QShortcut(QKeySequence("1"), parent_widget)
        self._shortcut1.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut1.activated.connect(lambda: self.enable_annotation_mode("single_channel"))

        self._shortcut2 = QShortcut(QKeySequence("2"), parent_widget)
        self._shortcut2.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut2.activated.connect(lambda: self.enable_annotation_mode("both_channels"))

        self._shortcut3 = QShortcut(QKeySequence("3"), parent_widget)
        self._shortcut3.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut3.activated.connect(lambda: self.enable_annotation_mode("right_channel"))

        self.plot_left.viewport().installEventFilter(self)
        self.plot_right.viewport().installEventFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def cleanup(self):
        """Detach event filters and remove transient visuals."""
        try:
            self.plot_left.viewport().removeEventFilter(self)
        except Exception:
            pass
        try:
            self.plot_right.viewport().removeEventFilter(self)
        except Exception:
            pass
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
        self._remove_drag_regions()
        if QApplication.overrideCursor() is not None:
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass

    def enable_annotation_mode(self, mode):
        if mode not in ("single_channel", "both_channels", "right_channel"):
            return
        self.annotation_mode = mode
        if self.is_mono_getter():
            self._last_annotation_channel = "mono"
        elif mode == "both_channels":
            self._last_annotation_channel = "both"
        elif mode == "right_channel":
            self._last_annotation_channel = "right"
        else:
            self._last_annotation_channel = "left"
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.CrossCursor))

    def cancel_annotation_mode(self):
        self.annotation_mode = None
        self.is_selecting = False
        self.selection_start = None
        self.selection_end = None
        self._drag_source_plot = None
        self._remove_drag_regions()
        if QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()

    def handle_key_press(self, event):
        if event.key() == Qt.Key.Key_Escape and self.annotation_mode is not None:
            self.cancel_annotation_mode()
            return True
        return False

    def _drag_region_color(self):
        return pg.mkBrush(255, 165, 0, 128), pg.mkPen(255, 140, 0, width=2)

    def _create_drag_regions(self, x0):
        brush, pen = self._drag_region_color()
        if self.is_mono_getter() or self._last_annotation_channel in ("mono", "left", "both"):
            self._drag_region_left = pg.LinearRegionItem([x0, x0], orientation="vertical", movable=False, pen=pen, brush=brush)
            self.plot_left.addItem(self._drag_region_left)

        if (not self.is_mono_getter()) and self._last_annotation_channel in ("right", "both"):
            self._drag_region_right = pg.LinearRegionItem([x0, x0], orientation="vertical", movable=False, pen=pen, brush=brush)
            self.plot_right.addItem(self._drag_region_right)

    def _update_drag_regions(self, x1):
        if self._drag_region_left is not None and self.selection_start is not None:
            self._drag_region_left.setRegion([self.selection_start, x1])
        if self._drag_region_right is not None and self.selection_start is not None:
            self._drag_region_right.setRegion([self.selection_start, x1])

    def _remove_drag_regions(self):
        if self._drag_region_left is not None:
            try:
                self.plot_left.removeItem(self._drag_region_left)
            except Exception:
                pass
            self._drag_region_left = None
        if self._drag_region_right is not None:
            try:
                self.plot_right.removeItem(self._drag_region_right)
            except Exception:
                pass
            self._drag_region_right = None

    def _annotation_matches_plot(self, annotation_channel, plot):
        channel = (annotation_channel or "mono").lower()
        if self.is_mono_getter():
            return channel in ["mono", "left", "right", "both"]
        if plot is self.plot_left:
            return channel in ["mono", "left", "both"]
        return channel in ["right", "both"]

    def _find_annotation_index_at(self, plot, x_value):
        candidates = []
        annotations = self.annotations_getter() or []
        for idx, ann in enumerate(annotations):
            start_time = ann.start if hasattr(ann, "start") else ann.get("start", 0)
            stop_time = ann.stop if hasattr(ann, "stop") else ann.get("stop", 0)
            channel = ann.channel if hasattr(ann, "channel") else ann.get("channel", "mono")
            if start_time <= x_value <= stop_time and self._annotation_matches_plot(channel, plot):
                candidates.append((stop_time - start_time, idx))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyRelease and getattr(event, "key", None) is not None:
            if event.key() in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3) and self.annotation_mode is not None and not self.is_selecting:
                self.cancel_annotation_mode()
            return False

        is_left_vp = watched is self.plot_left.viewport()
        is_right_vp = watched is self.plot_right.viewport()
        if not (is_left_vp or is_right_vp):
            return False

        plot = self.plot_left if is_left_vp else self.plot_right

        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if self.annotation_mode is not None:
                vp_pos = event.position()
                scene_pt = plot.mapToScene(vp_pos.toPoint())
                data_pt = plot.getViewBox().mapSceneToView(QPointF(scene_pt))
                self.is_selecting = True
                self._drag_source_plot = plot
                self.selection_start = data_pt.x()
                self._create_drag_regions(self.selection_start)
                return True

            vp_pos = event.position()
            scene_pt = plot.mapToScene(vp_pos.toPoint())
            data_pt = plot.getViewBox().mapSceneToView(QPointF(scene_pt))
            clicked_index = self._find_annotation_index_at(plot, data_pt.x())
            if clicked_index is not None:
                self.on_annotation_block_clicked(clicked_index)
                return True

        elif event.type() == QEvent.Type.MouseMove:
            if self.annotation_mode is not None and self.is_selecting and self.selection_start is not None:
                src = self._drag_source_plot or plot
                vp_pos = event.position()
                global_pt = watched.mapToGlobal(vp_pos.toPoint())
                src_local = src.mapFromGlobal(global_pt)
                scene_pt = src.mapToScene(src_local)
                data_pt = src.getViewBox().mapSceneToView(QPointF(scene_pt))
                self.selection_end = data_pt.x()
                self._update_drag_regions(self.selection_end)
                return True

        elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if self.annotation_mode is not None and self.is_selecting:
                start = self.selection_start
                end = self.selection_end
                channel = self._last_annotation_channel

                if start is not None and end is not None:
                    t0, t1 = min(start, end), max(start, end)
                    if t1 - t0 > 0.01:
                        self.on_pending_annotation(t0, t1, "#FFA500", channel)

                self.cancel_annotation_mode()

                if start is not None and end is not None:
                    t0, t1 = min(start, end), max(start, end)
                    if t1 - t0 > 0.01:
                        self.on_annotation_created(t0, t1, channel)
                return True

        return False
