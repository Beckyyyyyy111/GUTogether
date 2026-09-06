"""Discovers a single participant's EmotiBit LSL outlets ("HR", "EDA") and
pulls samples into shared rolling buffers, with each sample's timestamp
corrected onto this machine's local LSL clock via
StreamInlet.time_correction().

EmotiBit Oscilloscope must have "Send data via" set to LSL (it defaults to
"None") for these streams to appear on the network at all.
"""
import logging
import math
import threading
import time
from dataclasses import dataclass

import pylsl

from buffers import BufferStore
from cleaning import make_cleaner

logger = logging.getLogger(__name__)

SIGNAL_STREAM_NAMES = ("HR", "EDA")
DISCOVERY_INTERVAL_S = 3.0
TIME_CORRECTION_INTERVAL_S = 5.0
TIME_CORRECTION_TIMEOUT_S = 2.0


@dataclass
class StreamStatus:
    signal: str
    source_id: str
    connected: bool
    last_sample_age_s: float | None
    time_correction_s: float | None


class LslParticipantReceiver:
    """Connects to one EmotiBit's HR/EDA LSL streams. If more than one
    device's streams are seen for the same signal (e.g. a second EmotiBit
    Oscilloscope left running), the first one discovered is used and a
    warning is logged -- this receiver is single-participant by design."""

    def __init__(self, buffer_store: BufferStore, on_sample=None):
        self._buffers = buffer_store
        self._on_sample = on_sample  # optional callback(signal, t, raw_value, cleaned_value_or_None)
        self._stop_event = threading.Event()
        self._discovery_thread: threading.Thread | None = None
        self._stream_threads: dict[str, threading.Thread] = {}  # keyed by signal name
        self._status_lock = threading.Lock()
        self._status: dict[str, StreamStatus] = {}  # keyed by signal name

    def start(self) -> None:
        self._stop_event.clear()
        self._discovery_thread = threading.Thread(target=self._discovery_loop, daemon=True)
        self._discovery_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._discovery_thread is not None:
            self._discovery_thread.join(timeout=2.0)
        for t in list(self._stream_threads.values()):
            t.join(timeout=2.0)

    def get_statuses(self) -> list[StreamStatus]:
        with self._status_lock:
            return list(self._status.values())

    def _discovery_loop(self) -> None:
        while not self._stop_event.is_set():
            for signal in SIGNAL_STREAM_NAMES:
                if signal in self._stream_threads:
                    continue
                try:
                    infos = pylsl.resolve_byprop("name", signal, timeout=1.0)
                except Exception:
                    logger.exception("LSL resolve failed for stream %s", signal)
                    continue
                if not infos:
                    continue
                if len(infos) > 1:
                    logger.warning(
                        "Found %d '%s' streams on the network; using the first "
                        "one (source_id=%s). This viewer is single-participant.",
                        len(infos), signal, infos[0].source_id(),
                    )
                t = threading.Thread(target=self._pull_loop, args=(infos[0], signal), daemon=True)
                self._stream_threads[signal] = t
                t.start()
            self._stop_event.wait(DISCOVERY_INTERVAL_S)

    def _pull_loop(self, info: pylsl.StreamInfo, signal: str) -> None:
        source_id = info.source_id() or "unknown-source"
        logger.info("Connected to %s stream (source_id=%s)", signal, source_id)

        inlet = pylsl.StreamInlet(info, max_buflen=360, recover=True)
        buf = self._buffers.get(signal)
        cleaner = make_cleaner(signal)

        correction = 0.0
        last_correction_at = 0.0
        last_sample_at = time.time()
        last_accepted_timestamp: float | None = None

        with self._status_lock:
            self._status[signal] = StreamStatus(signal, source_id, True, None, None)

        try:
            while not self._stop_event.is_set():
                now = time.time()
                if now - last_correction_at >= TIME_CORRECTION_INTERVAL_S:
                    try:
                        correction = inlet.time_correction(timeout=TIME_CORRECTION_TIMEOUT_S)
                    except Exception:
                        logger.warning("time_correction() timed out for %s", signal)
                    last_correction_at = now

                samples, timestamps = inlet.pull_chunk(timeout=0.2, max_samples=256)
                if timestamps:
                    last_sample_at = time.time()
                    # Reject non-increasing timestamps once, here, so both the
                    # live plot buffer and the recorder see the same filtered
                    # stream -- a brief WiFi hiccup can make an LSL inlet (with
                    # recover=True) re-send a backlog of already-seen samples,
                    # which would otherwise land out of order in both places.
                    accepted_t, cleaned_v = [], []
                    for ts, s in zip(timestamps, samples):
                        t = ts + correction
                        if last_accepted_timestamp is not None and t <= last_accepted_timestamp:
                            continue
                        last_accepted_timestamp = t
                        raw_value = s[0]

                        # Reject implausible-range/implausible-jump samples (contact
                        # loss, motion artifacts) and smooth what's left; rejected
                        # samples become a gap (NaN) in the plotted/buffered series
                        # rather than fabricated continuity. The raw value is still
                        # handed to on_sample so the recorder can keep it.
                        cleaned_value = cleaner.process(t, raw_value)
                        accepted_t.append(t)
                        cleaned_v.append(cleaned_value if cleaned_value is not None else math.nan)

                        if self._on_sample is not None:
                            self._on_sample(signal, t, raw_value, cleaned_value)

                    if accepted_t:
                        buf.extend(accepted_t, cleaned_v)

                with self._status_lock:
                    self._status[signal] = StreamStatus(
                        signal, source_id, True,
                        time.time() - last_sample_at, correction,
                    )
        finally:
            inlet.close_stream()
            with self._status_lock:
                if signal in self._status:
                    self._status[signal].connected = False
