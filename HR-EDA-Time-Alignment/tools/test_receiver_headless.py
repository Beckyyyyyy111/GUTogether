"""Headless smoke test: run the LSL receiver against whatever streams are on
the network (e.g. tools/mock_emotibit_lsl.py) and print buffer contents after
a few seconds. No GUI involved -- validates discovery and time-correction
end to end.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dual_emotibit_viewer.buffers import BufferStore
from dual_emotibit_viewer.lsl_receiver import LslParticipantReceiver

buffers = BufferStore(max_age_s=60.0)

samples_seen = []
receiver = LslParticipantReceiver(buffers, on_sample=lambda *args: samples_seen.append(args))
receiver.start()

print("Waiting 10s for discovery + samples...")
time.sleep(10)

print("\n--- Stream statuses ---")
for s in receiver.get_statuses():
    print(s)

print("\n--- Buffer snapshots ---")
for signal in buffers.keys():
    times, values = buffers.get(signal).snapshot()
    print(f"{signal}: {len(times)} samples, "
          f"last value={values[-1] if len(values) else None}, "
          f"span={(times[-1]-times[0]) if len(times) else 0:.2f}s")

print(f"\nTotal samples seen via callback: {len(samples_seen)}")
receiver.stop()
