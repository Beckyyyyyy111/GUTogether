"""Web app: pick a gut-sound recording, click Play, and this records that
sound plus the live EmotiBit HR/EDA stream time-aligned to it (t=0 = the
instant playback starts). When playback ends, the three are saved together
under Final/<timestamp>_<sound>/ as a combined CSV + summary PNG.

Run with:
    uvicorn server:app --reload --port 8000
from this directory, then open http://localhost:8000/
"""
import asyncio
import csv
import json
import logging
import shutil
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import pylsl
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import plotting
from buffers import BufferStore
from lsl_receiver import LslParticipantReceiver
from session import SessionRecorder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COUNTDOWN_S = 3.0
STATUS_INTERVAL_S = 1.0
TICK_INTERVAL_S = 0.5

BACKEND_DIR = Path(__file__).resolve().parent
WEBSITE_DIR = BACKEND_DIR.parent
PROJECT_ROOT = WEBSITE_DIR.parent
FRONTEND_DIR = WEBSITE_DIR / "frontend"
FINAL_DIR = PROJECT_ROOT / "Final"
SOUNDS_DIR = Path(r"D:\AAAAAAAA\OpenGut\Participant_Gut_Sounds\Selected_Sounds")

FINAL_DIR.mkdir(parents=True, exist_ok=True)

buffer_store = BufferStore(max_age_s=3600.0)
session_recorder = SessionRecorder()
receiver = LslParticipantReceiver(buffer_store, on_sample=session_recorder.on_sample)

_session_active = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    receiver.start()
    try:
        yield
    finally:
        receiver.stop()


app = FastAPI(lifespan=lifespan)


def safe_sound_path(name: str) -> Path | None:
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    path = SOUNDS_DIR / name
    if path.is_file() and path.suffix.lower() == ".wav":
        return path
    return None


@app.get("/api/sounds")
def list_sounds():
    if not SOUNDS_DIR.is_dir():
        return {"sounds": []}
    paths = sorted(SOUNDS_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    sounds = []
    for p in paths:
        try:
            duration_s = plotting.get_wav_duration_s(p)
        except Exception:
            duration_s = None
        sounds.append({"name": p.name, "duration_s": duration_s})
    return {"sounds": sounds}


def save_session(
    sound_name: str,
    wav_path: Path,
    start_unix: float,
    start_lsl: float,
    duration_s: float,
    samples: list[tuple[float, str, float, float | None]],
    stage: int,
) -> dict:
    ts = datetime.fromtimestamp(start_unix).strftime("%Y%m%d_%H%M%S")
    stem = Path(sound_name).stem
    out_dir = FINAL_DIR / f"{ts}_{stem}_stage{stage}"
    out_dir.mkdir(parents=True, exist_ok=True)

    samples_sorted = sorted(samples, key=lambda row: row[0])

    csv_path = out_dir / "combined_long.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        f.write(f"# sound_file={sound_name}\n")
        f.write(f"# stage={stage}\n")
        f.write(f"# anchor_unix_time={start_unix:.6f}\n")
        f.write(f"# anchor_lsl_clock={start_lsl:.6f}\n")
        f.write(f"# duration_s={duration_s:.3f}\n")
        writer = csv.writer(f)
        writer.writerow(["relative_time_s", "signal", "raw_value", "cleaned_value"])
        for t_rel, signal, raw_value, cleaned_value in samples_sorted:
            writer.writerow([f"{t_rel:.6f}", signal, raw_value, "" if cleaned_value is None else cleaned_value])

    shutil.copyfile(wav_path, out_dir / "audio.wav")

    hr_samples = [(t, c) for t, sig, _r, c in samples_sorted if sig == "HR"]
    eda_samples = [(t, c) for t, sig, _r, c in samples_sorted if sig == "EDA"]

    png_path = out_dir / "combined_summary.png"
    plotting.make_summary_plot(
        png_path, wav_path,
        hr_samples=hr_samples,
        eda_samples=eda_samples,
        duration_s=duration_s,
        title=f"{sound_name}  ({ts})",
    )

    meta = {
        "sound_file": sound_name,
        "stage": stage,
        "start_unix_time": start_unix,
        "duration_s": duration_s,
        "hr_sample_count": len(hr_samples),
        "eda_sample_count": len(eda_samples),
        "output_dir": str(out_dir),
    }
    with open(out_dir / "session_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    rel_dir = out_dir.name
    return {
        "folder": rel_dir,
        "png_url": f"/final/{rel_dir}/combined_summary.png",
        "csv_url": f"/final/{rel_dir}/combined_long.csv",
        **meta,
    }


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    global _session_active
    await websocket.accept()
    finalize_task: asyncio.Task | None = None

    async def status_pusher():
        while True:
            statuses = receiver.get_statuses()
            await websocket.send_json({
                "event": "status",
                "streams": [
                    {
                        "signal": s.signal,
                        "connected": s.connected,
                        "last_sample_age_s": s.last_sample_age_s,
                        "source_id": s.source_id,
                    }
                    for s in statuses
                ],
            })
            await asyncio.sleep(STATUS_INTERVAL_S)

    async def tick_pusher():
        while True:
            hr = buffer_store.get("HR").latest()
            eda = buffer_store.get("EDA").latest()
            await websocket.send_json({
                "event": "tick",
                "hr": hr[1] if hr else None,
                "eda": eda[1] if eda else None,
            })
            await asyncio.sleep(TICK_INTERVAL_S)

    async def run_session(sound_name: str, stage: int):
        nonlocal finalize_task
        global _session_active

        wav_path = safe_sound_path(sound_name)
        if wav_path is None:
            await websocket.send_json({"event": "error", "message": f"Sound not found: {sound_name}"})
            _session_active = False
            return
        try:
            duration_s = plotting.get_wav_duration_s(wav_path)
        except Exception as exc:
            await websocket.send_json({"event": "error", "message": f"Could not read WAV file: {exc}"})
            _session_active = False
            return

        await websocket.send_json({"event": "countdown", "seconds": COUNTDOWN_S})
        await asyncio.sleep(COUNTDOWN_S)

        start_lsl = pylsl.local_clock()
        start_unix = time.time()
        session_recorder.begin(start_lsl)

        # Both stages play the sound in the browser; stage 2 additionally
        # renders a live amplitude visualization client-side (see app.js).
        await websocket.send_json({
            "event": "play",
            "stage": stage,
            "sound": sound_name,
            "sound_url": f"/sounds/{sound_name}",
            "duration_s": duration_s,
        })

        try:
            await asyncio.sleep(duration_s)
        except asyncio.CancelledError:
            session_recorder.end()
            _session_active = False
            await websocket.send_json({"event": "cancelled"})
            return

        samples = session_recorder.end()
        try:
            result = await asyncio.to_thread(
                save_session, sound_name, wav_path, start_unix, start_lsl, duration_s, samples, stage,
            )
            await websocket.send_json({"event": "done", **result})
        except Exception as exc:
            logger.exception("Failed to save session")
            await websocket.send_json({"event": "error", "message": f"Failed to save session: {exc}"})
        finally:
            _session_active = False

    status_task = asyncio.create_task(status_pusher())
    tick_task = asyncio.create_task(tick_pusher())
    try:
        while True:
            msg = await websocket.receive_json()
            action = msg.get("action")
            if action == "start":
                if _session_active:
                    await websocket.send_json({"event": "error", "message": "A session is already recording."})
                    continue
                stage = msg.get("stage", 1)
                if stage not in (1, 2):
                    await websocket.send_json({"event": "error", "message": f"Invalid stage: {stage}"})
                    continue
                _session_active = True
                finalize_task = asyncio.create_task(run_session(msg.get("sound", ""), stage))
            elif action == "cancel":
                if finalize_task is not None and not finalize_task.done():
                    finalize_task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        status_task.cancel()
        tick_task.cancel()
        if finalize_task is not None and not finalize_task.done():
            finalize_task.cancel()


if SOUNDS_DIR.is_dir():
    app.mount("/sounds", StaticFiles(directory=SOUNDS_DIR), name="sounds")
app.mount("/final", StaticFiles(directory=FINAL_DIR), name="final")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
