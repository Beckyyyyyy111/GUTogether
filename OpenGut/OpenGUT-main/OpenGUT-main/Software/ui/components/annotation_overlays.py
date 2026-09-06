"""Annotation overlay rendering helpers for the audio viewer."""

from PyQt6.QtGui import QColor
import pyqtgraph as pg


class AnnotationOverlayManager:
    """Render saved and draft annotation overlays on one or two plots."""

    def __init__(self, plot_left, plot_right, is_mono_getter):
        self.plot_left = plot_left
        self.plot_right = plot_right
        self.is_mono_getter = is_mono_getter
        self.annotations = []
        self.annotation_blocks = {"left": [], "right": []}
        self._pending_region_left = None
        self._pending_region_right = None
        self._pending_annotation = None

    def set_annotations(self, annotations):
        self.annotations = list(annotations or [])

    def redraw_annotations(self, audio_duration_sec):
        """Redraw saved annotations and the current pending overlay."""
        for item in self.annotation_blocks.get("left", []):
            try:
                self.plot_left.removeItem(item)
            except Exception:
                pass
        for item in self.annotation_blocks.get("right", []):
            try:
                self.plot_right.removeItem(item)
            except Exception:
                pass
        self.annotation_blocks = {"left": [], "right": []}

        if audio_duration_sec == 0:
            return

        is_mono = bool(self.is_mono_getter())
        for ann in self.annotations:
            color_name = ann.color if hasattr(ann, "color") else ann.get("color", "#FF6B6B")
            fill_color = QColor(color_name)
            fill_color.setAlpha(128)
            channel = ann.channel.lower() if hasattr(ann, "channel") else ann.get("channel", "mono")
            start_time = ann.start if hasattr(ann, "start") else ann.get("start", 0)
            stop_time = ann.stop if hasattr(ann, "stop") else ann.get("stop", 0)
            name = ann.name if hasattr(ann, "name") else ann.get("name", "")

            if is_mono or channel in ["mono", "left", "both"]:
                region = pg.LinearRegionItem(
                    [start_time, stop_time],
                    orientation="vertical",
                    movable=False,
                    pen=pg.mkPen(color_name, width=2),
                    brush=pg.mkBrush(fill_color),
                )
                self.plot_left.addItem(region)
                self.annotation_blocks["left"].append(region)
                label = self._make_annotation_label(self.plot_left, start_time, name)
                if label is not None:
                    self.plot_left.addItem(label)
                    self.annotation_blocks["left"].append(label)

            if (not is_mono) and channel in ["right", "both"]:
                region = pg.LinearRegionItem(
                    [start_time, stop_time],
                    orientation="vertical",
                    movable=False,
                    pen=pg.mkPen(color_name, width=2),
                    brush=pg.mkBrush(fill_color),
                )
                self.plot_right.addItem(region)
                self.annotation_blocks["right"].append(region)
                label = self._make_annotation_label(self.plot_right, start_time, name)
                if label is not None:
                    self.plot_right.addItem(label)
                    self.annotation_blocks["right"].append(label)

        self._redraw_pending_annotation()

    def set_pending_annotation(self, start_time, stop_time, color, channel):
        """Show a persistent draft annotation overlay while the user edits details."""
        if stop_time <= start_time:
            self.clear_pending_annotation()
            return
        self._pending_annotation = {
            "start": float(start_time),
            "stop": float(stop_time),
            "color": str(color),
            "channel": str(channel).strip().lower() or "mono",
        }
        self._redraw_pending_annotation()

    def clear_pending_annotation(self):
        """Remove the persistent draft annotation overlay."""
        if self._pending_region_left is not None:
            try:
                self.plot_left.removeItem(self._pending_region_left)
            except Exception:
                pass
            self._pending_region_left = None
        if self._pending_region_right is not None:
            try:
                self.plot_right.removeItem(self._pending_region_right)
            except Exception:
                pass
            self._pending_region_right = None
        self._pending_annotation = None

    def _redraw_pending_annotation(self):
        current = self._pending_annotation
        self.clear_pending_annotation()
        if current is None:
            return
        self._pending_annotation = current

        fill_color = QColor(current["color"])
        fill_color.setAlpha(128)
        brush = pg.mkBrush(fill_color)
        pen = pg.mkPen(current["color"], width=2)
        region = [current["start"], current["stop"]]
        channel = current["channel"]
        is_mono = bool(self.is_mono_getter())

        if is_mono or channel in ["mono", "left", "both"]:
            self._pending_region_left = pg.LinearRegionItem(
                region,
                orientation="vertical",
                movable=False,
                pen=pen,
                brush=brush,
            )
            self.plot_left.addItem(self._pending_region_left)

        if (not is_mono) and channel in ["right", "both"]:
            self._pending_region_right = pg.LinearRegionItem(
                region,
                orientation="vertical",
                movable=False,
                pen=pen,
                brush=brush,
            )
            self.plot_right.addItem(self._pending_region_right)

    def _make_annotation_label(self, plot, start_time, text):
        label_text = (text or "").strip()
        if not label_text:
            return None
        y_range = plot.getViewBox().viewRange()[1]
        y_top = y_range[1]
        y_bottom = y_range[0]
        y_pos = y_top - (y_top - y_bottom) * 0.06
        label = pg.TextItem(text=label_text, anchor=(0, 1), color="w")
        label.setPos(float(start_time), float(y_pos))
        return label