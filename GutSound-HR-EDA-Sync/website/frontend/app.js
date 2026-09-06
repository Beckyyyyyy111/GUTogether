const soundSelect = document.getElementById("sound-select");
const playBtn = document.getElementById("play-btn");
const cancelBtn = document.getElementById("cancel-btn");
const hrStatus = document.getElementById("hr-status");
const edaStatus = document.getElementById("eda-status");
const countdownEl = document.getElementById("countdown");
const recordingPanel = document.getElementById("recording-panel");
const recTime = document.getElementById("rec-time");
const recDuration = document.getElementById("rec-duration");
const progressBar = document.getElementById("progress-bar");
const amplitudeCanvas = document.getElementById("amplitude-canvas");
const amplitudeCtx = amplitudeCanvas.getContext("2d");
const stageInputs = document.querySelectorAll('input[name="stage"]');
// Live HR/EDA numeric readout disabled per user request (kept for reference).
// const liveHr = document.getElementById("live-hr");
// const liveEda = document.getElementById("live-eda");
const player = document.getElementById("player");
const messageEl = document.getElementById("message");
const resultPanel = document.getElementById("result-panel");
const resultMessage = document.getElementById("result-message");
// Detailed folder/CSV/PNG display disabled per user request.
// const resultFolder = document.getElementById("result-folder");
// const resultCsv = document.getElementById("result-csv");
// const resultPng = document.getElementById("result-png");

let ws = null;
let progressTimer = null;
let playbackDuration = 0;
let playbackStartedAt = 0;

let audioCtx = null;
let analyser = null;
let vizRunning = false;

// Web Audio graph can only be attached to the <audio> element once for its
// whole lifetime, so this is created lazily on the first Play click (a user
// gesture, which browsers require) and then reused for every session.
function ensureAudioGraph() {
  if (audioCtx) return;
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const source = audioCtx.createMediaElementSource(player);
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 2048;
  source.connect(analyser);
  analyser.connect(audioCtx.destination);
}

// The canvas is now sized to most of the screen (CSS: 100vw x 60vh) so it
// reads from across the room; this matches the actual drawing-surface
// resolution to that on-screen size (accounting for devicePixelRatio) so the
// line stays crisp instead of blurry/stretched.
function resizeCanvasToDisplaySize() {
  const dpr = window.devicePixelRatio || 1;
  amplitudeCanvas.width = Math.round(amplitudeCanvas.clientWidth * dpr);
  amplitudeCanvas.height = Math.round(amplitudeCanvas.clientHeight * dpr);
  amplitudeCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function drawAmplitude() {
  if (!vizRunning) return;
  requestAnimationFrame(drawAmplitude);

  const data = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(data);

  const width = amplitudeCanvas.clientWidth;
  const height = amplitudeCanvas.clientHeight;
  amplitudeCtx.fillStyle = "#0b0f14";
  amplitudeCtx.fillRect(0, 0, width, height);
  amplitudeCtx.lineWidth = 3;
  amplitudeCtx.strokeStyle = "#4ade80";
  amplitudeCtx.beginPath();

  const sliceWidth = width / data.length;
  const mid = height / 2;
  const gain = 4; // exaggerate quiet gut-sound audio so it reads clearly from across the room
  let x = 0;
  for (let i = 0; i < data.length; i++) {
    let y = mid + ((data[i] - 128) / 128) * mid * gain;
    if (y < 0) y = 0;
    else if (y > height) y = height;
    if (i === 0) amplitudeCtx.moveTo(x, y);
    else amplitudeCtx.lineTo(x, y);
    x += sliceWidth;
  }
  amplitudeCtx.stroke();
}

function startAmplitudeViz() {
  ensureAudioGraph();
  if (audioCtx.state === "suspended") audioCtx.resume();
  amplitudeCanvas.classList.remove("hidden");
  resizeCanvasToDisplaySize();
  vizRunning = true;
  drawAmplitude();
}

function stopAmplitudeViz() {
  vizRunning = false;
  amplitudeCanvas.classList.add("hidden");
}

function setBadge(el, label, cls) {
  el.textContent = label;
  el.className = `badge ${cls}`;
}

function showMessage(text) {
  messageEl.textContent = text;
  messageEl.classList.remove("hidden");
}

function clearMessage() {
  messageEl.classList.add("hidden");
}

function resetUiForIdle() {
  playBtn.disabled = false;
  cancelBtn.disabled = true;
  countdownEl.classList.add("hidden");
  recordingPanel.classList.add("hidden");
  stopAmplitudeViz();
  stageInputs.forEach((el) => (el.disabled = false));
  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
}

async function loadSounds() {
  const res = await fetch("/api/sounds");
  const data = await res.json();
  soundSelect.innerHTML = "";
  for (const sound of data.sounds) {
    const opt = document.createElement("option");
    opt.value = sound.name;
    opt.textContent = sound.duration_s != null
      ? `${sound.name} (${sound.duration_s.toFixed(1)}s)`
      : sound.name;
    soundSelect.appendChild(opt);
  }
  if (data.sounds.length === 0) {
    showMessage("No .wav files found in the Selected_Sounds folder.");
    playBtn.disabled = true;
  }
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws`);

  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    handleMessage(msg);
  };

  ws.onclose = () => {
    setTimeout(connectWs, 1000);
  };
}

function handleMessage(msg) {
  switch (msg.event) {
    case "status":
      updateStreamStatus(msg.streams);
      break;
    case "countdown":
      startCountdown(msg.seconds);
      break;
    case "play":
      startPlayback(msg);
      break;
    case "tick":
      // Live HR/EDA numeric readout disabled per user request (kept for reference).
      // liveHr.textContent = msg.hr != null ? msg.hr.toFixed(1) : "--";
      // liveEda.textContent = msg.eda != null ? msg.eda.toFixed(3) : "--";
      break;
    case "done":
      showResult(msg);
      resetUiForIdle();
      break;
    case "cancelled":
      clearMessage();
      resetUiForIdle();
      break;
    case "error":
      showMessage(msg.message);
      resetUiForIdle();
      break;
  }
}

function updateStreamStatus(streams) {
  const bySignal = Object.fromEntries(streams.map((s) => [s.signal, s]));
  for (const [signal, el] of [["HR", hrStatus], ["EDA", edaStatus]]) {
    const s = bySignal[signal];
    if (!s) {
      setBadge(el, `${signal}: not found`, "unknown");
    } else if (s.connected && s.last_sample_age_s != null && s.last_sample_age_s < 5) {
      setBadge(el, `${signal}: OK`, "ok");
    } else {
      const age = s.last_sample_age_s != null ? `${s.last_sample_age_s.toFixed(0)}s ago` : "no data";
      setBadge(el, `${signal}: stale (${age})`, "stale");
    }
  }
}

let countdownInterval = null;

function startCountdown(seconds) {
  clearMessage();
  resultPanel.classList.add("hidden");
  countdownEl.classList.remove("hidden");
  cancelBtn.disabled = false;
  stageInputs.forEach((el) => (el.disabled = true));
  let remaining = Math.ceil(seconds);
  countdownEl.textContent = remaining;
  countdownInterval = setInterval(() => {
    remaining -= 1;
    if (remaining > 0) {
      countdownEl.textContent = remaining;
    } else {
      clearInterval(countdownInterval);
    }
  }, 1000);
}

function startPlayback(msg) {
  countdownEl.classList.add("hidden");
  recordingPanel.classList.remove("hidden");
  playbackDuration = msg.duration_s;
  playbackStartedAt = performance.now();
  recDuration.textContent = `${playbackDuration.toFixed(1)}s`;

  player.src = msg.sound_url;
  player.currentTime = 0;
  player.play().catch((err) => showMessage(`Playback failed: ${err.message}`));

  if (msg.stage === 2) {
    startAmplitudeViz();
  }

  progressTimer = setInterval(() => {
    const elapsed = (performance.now() - playbackStartedAt) / 1000;
    recTime.textContent = `${Math.min(elapsed, playbackDuration).toFixed(1)}s`;
    progressBar.style.width = `${Math.min(100, (elapsed / playbackDuration) * 100)}%`;
  }, 100);
}

function showResult(msg) {
  // Detailed folder/CSV/PNG display disabled per user request; files are
  // still written to Final/<folder>/ automatically either way.
  // resultFolder.textContent = msg.folder;
  // resultCsv.href = msg.csv_url;
  // resultPng.src = `${msg.png_url}?t=${Date.now()}`;
  resultMessage.textContent = `Saved to Final folder: ${msg.folder}`;
  resultPanel.classList.remove("hidden");
}

playBtn.addEventListener("click", () => {
  const sound = soundSelect.value;
  if (!sound) return;
  const stage = Number(document.querySelector('input[name="stage"]:checked').value);
  ensureAudioGraph(); // must run inside this click's user gesture, not later
  clearMessage();
  resultPanel.classList.add("hidden");
  playBtn.disabled = true;
  ws.send(JSON.stringify({ action: "start", sound, stage }));
});

cancelBtn.addEventListener("click", () => {
  ws.send(JSON.stringify({ action: "cancel" }));
  player.pause();
  stopAmplitudeViz();
});

loadSounds();
connectWs();
