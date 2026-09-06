"""Live single-participant EmotiBit HR/EDA viewer with LSL-based time alignment."""
import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pylsl
import pyqtgraph as pg
from PyQt5 import QtCore, QtWidgets

from .buffers import BufferStore
from .lsl_receiver import LslParticipantReceiver
from .recorder import CsvRecorder

logger = logging.getLogger(__name__)

HR_COLOR = (214, 39, 40)   # red
EDA_COLOR = (31, 119, 180)  # blue

DEFAULT_WINDOW_S = 60.0


def _forward_fill(values: np.ndarray) -> np.ndarray:
    """Hold the last valid value forward across NaN gaps, for display only.

    cleaning.py rejects artifacts as NaN so the recording stays honest
    about what was and wasn't trusted, but a live line full of gaps reads
    as "broken" -- EmotiBit's own Oscilloscope always shows *something*
    (its HR channel is itself a step/hold display between updates). Holding
    the last good value through a rejected span keeps the plot continuous,
    e.g. an EDA contact-loss spike to 10000 just holds flat instead of
    either breaking the line or blowing out the axis.
    """
    if values.size == 0:
        return values
    out = values.copy()
    mask = np.isnan(out)
    if not mask.any():
        return out
    idx = np.where(~mask, np.arange(out.size), 0)
    np.maximum.accumulate(idx, out=idx)
    out = out[idx]
    out[idx == 0] = np.nan if np.isnan(values[0]) else values[0]
    return out


def _robust_y_range(values: np.ndarray) -> tuple[float, float] | None:
    """1st-99th percentile range with 10% padding, instead of raw min/max.

    A single extreme artifact (e.g. an EDA sensor rail-to-10000 glitch on
    electrode contact loss) would otherwise force the Y axis to stretch to
    fit it, squashing every normal-range sample into an unreadable flat
    line near zero for as long as that one sample stays in the window.
    """
    if values.size == 0:
        return None
    lo, hi = np.percentile(values, [1, 99])
    if lo == hi:
        pad = max(abs(lo) * 0.1, 0.5)
        return lo - pad, hi + pad
    pad = (hi - lo) * 0.1
    return lo - pad, hi + pad


class TimeAxisItem(pg.AxisItem):
    """Formats seconds-elapsed tick values as m:ss (e.g. 90 -> "1:30")."""

    def tickStrings(self, values, scale, spacing):
        strings = []
        for v in values:
            v = max(v, 0)
            minutes, seconds = divmod(int(round(v)), 60)
            strings.append(f"{minutes}:{seconds:02d}")
        return strings


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, data_dir: Path):
        super().__init__()
        self.setWindowTitle("EmotiBit HR / EDA Viewer (LSL, time-aligned)")
        self.resize(1000, 700)

        self._data_dir = data_dir
        self._buffers = BufferStore(max_age_s=DEFAULT_WINDOW_S + 30.0)
        self._recorder: CsvRecorder | None = None
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._window_s = DEFAULT_WINDOW_S
        self._session_start = pylsl.local_clock()

        self._build_ui()

        self._receiver = LslParticipantReceiver(self._buffers, on_sample=self._on_sample)
        self._receiver.start()

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(100)

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QHBoxLayout(central)

        plots_layout = QtWidgets.QVBoxLayout()
        outer.addLayout(plots_layout, stretch=4)

        pg.setConfigOptions(antialias=True, background="w", foreground="k")

        self.hr_plot = pg.PlotWidget(title="Heart Rate (HR, bpm)", axisItems={"bottom": TimeAxisItem(orientation="bottom")})
        self.hr_plot.showGrid(x=True, y=True, alpha=0.3)
        self.hr_plot.setLabel("bottom", "Elapsed time (m:ss)")
        plots_layout.addWidget(self.hr_plot)

        self.eda_plot = pg.PlotWidget(title="Electrodermal Activity (EDA, uS)", axisItems={"bottom": TimeAxisItem(orientation="bottom")})
        self.eda_plot.showGrid(x=True, y=True, alpha=0.3)
        self.eda_plot.setLabel("bottom", "Elapsed time (m:ss)")
        plots_layout.addWidget(self.eda_plot)

        side = QtWidgets.QVBoxLayout()
        outer.addLayout(side, stretch=1)

        side.addWidget(QtWidgets.QLabel("<b>EmotiBit</b>"))
        self.status_list = QtWidgets.QListWidget()
        side.addWidget(self.status_list, stretch=1)

        side.addWidget(QtWidgets.QLabel("Window (seconds)"))
        self.window_spin = QtWidgets.QSpinBox()
        self.window_spin.setRange(10, 600)
        self.window_spin.setValue(int(DEFAULT_WINDOW_S))
        self.window_spin.valueChanged.connect(self._on_window_changed)
        side.addWidget(self.window_spin)

        self.record_btn = QtWidgets.QPushButton("Start Recording")
        self.record_btn.setCheckable(True)
        self.record_btn.toggled.connect(self._on_record_toggled)
        side.addWidget(self.record_btn)

        self.record_label = QtWidgets.QLabel("")
        self.record_label.setWordWrap(True)
        side.addWidget(self.record_label)

        side.addStretch(1)

    def _on_window_changed(self, value: int) -> None:
        self._window_s = float(value)

    def _current_source_id(self) -> str:
        for s in self._receiver.get_statuses():
            if s.source_id:
                return s.source_id
        return ""

    def _on_record_toggled(self, checked: bool) -> None:
        if checked:
            out_path = self._data_dir / "recordings" / time.strftime("%Y-%m-%d_%H-%M-%S_aligned.csv")
            self._recorder = CsvRecorder(out_path)
            self._recorder.start(source_id=self._current_source_id())
            self.record_btn.setText("Stop Recording")
            self.record_label.setText(f"Recording to:\n{out_path}")
        else:
            if self._recorder is not None:
                self._recorder.stop()
            self.record_btn.setText("Start Recording")
            self.record_label.setText("Recording stopped.")

    def _on_sample(self, signal: str, t: float, raw_value: float, cleaned_value: float | None) -> None:
        if self._recorder is not None and self._recorder.is_recording:
            self._recorder.write(signal, t, raw_value, cleaned_value)

    def _curve_for(self, signal: str) -> pg.PlotDataItem:
        curve = self._curves.get(signal)
        if curve is None:
            plot = self.hr_plot if signal == "HR" else self.eda_plot
            color = HR_COLOR if signal == "HR" else EDA_COLOR
            kwargs = {}
            if signal == "HR":
                # HR arrives at ~1 Hz; if several consecutive samples get
                # rejected as artifacts, the surviving valid samples can end
                # up isolated (no valid neighbor to draw a connecting line
                # to) and connect="finite" then renders nothing at all for
                # them. Small markers make isolated points visible too.
                kwargs = dict(symbol="o", symbolSize=4, symbolBrush=color, symbolPen=None)
            # connect="finite": _forward_fill() below removes NaN gaps by
            # holding the last value, except before the very first valid
            # sample, which stays NaN and should render as nothing.
            curve = plot.plot(pen=pg.mkPen(color=color, width=2), connect="finite", **kwargs)
            self._curves[signal] = curve
        return curve

    def _refresh(self) -> None:
        # NB: buffered timestamps are in this process's pylsl local_clock()
        # frame (post time_correction), which is NOT the same epoch as
        # time.time() -- must compare against pylsl.local_clock() here too.
        now = pylsl.local_clock()
        elapsed_now = now - self._session_start
        for signal in self._buffers.keys():
            buf = self._buffers.get(signal)
            times, values = buf.snapshot()
            if times.size == 0:
                continue
            curve = self._curve_for(signal)
            elapsed = times - self._session_start
            # Forward-fill over the *full* buffered history (not just the
            # visible slice) before windowing, so a rejected run sitting at
            # the left edge of the window can still inherit the last good
            # value from just before that edge. Filling only the visible
            # slice would lose that seed the moment it scrolls out of view,
            # making an already-held span flip to a blank gap as time passes.
            filled = _forward_fill(values)
            mask = elapsed >= elapsed_now - self._window_s
            visible_values = values[mask]
            curve.setData(elapsed[mask], filled[mask])

            plot = self.hr_plot if signal == "HR" else self.eda_plot
            y_range = _robust_y_range(visible_values[np.isfinite(visible_values)])
            if y_range is not None:
                plot.setYRange(*y_range, padding=0)

        x_min = max(0.0, elapsed_now - self._window_s)
        self.hr_plot.setXRange(x_min, elapsed_now, padding=0.02)
        self.eda_plot.setXRange(x_min, elapsed_now, padding=0.02)

        self._refresh_status()

    def _refresh_status(self) -> None:
        self.status_list.clear()
        statuses = self._receiver.get_statuses()
        if not statuses:
            self.status_list.addItem("No EmotiBit LSL streams found yet...\n(Check Oscilloscope's 'Send data via' is set to LSL)")
            return
        for s in sorted(statuses, key=lambda s: s.signal):
            age = f"{s.last_sample_age_s:.1f}s ago" if s.last_sample_age_s is not None else "no data yet"
            state = "OK" if (s.last_sample_age_s is not None and s.last_sample_age_s < 5.0) else "STALE"
            text = f"[{s.signal}]  {state}  (last sample {age})\n  source_id={s.source_id}"
            self.status_list.addItem(text)

    def closeEvent(self, event) -> None:
        self._receiver.stop()
        if self._recorder is not None:
            self._recorder.stop()
        super().closeEvent(event)


def main() -> None:
    parser = argparse.ArgumentParser(description="Single-participant EmotiBit HR/EDA live viewer over LSL")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data",
        help="Directory for recordings (default: ./data)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow(args.data_dir)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
