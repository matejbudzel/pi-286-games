"use strict";
const width = 320, height = 240, frame = new Uint8Array(width * height * 2);
const audioBufferTarget = .35, audioStartLead = .08;
const canvas = document.querySelector("#screen"), ctx = canvas.getContext("2d"), source = document.createElement("canvas");
source.width = width; source.height = height;
const sourceCtx = source.getContext("2d"), image = sourceCtx.createImageData(width, height);
const menu = document.querySelector("#menu"), player = document.querySelector("#player"), games = document.querySelector("#games"), status = document.querySelector("#status"), hud = document.querySelector("#hud"), hudToggle = document.querySelector("#hud-toggle");
let session = null, videoSeq = 0, audioOffset = 0, revision = 0, polling = false, audioContext = null, audioNext = 0, ws = null, selectedGame = null;
const held = new Set(), padHeld = new Set();
const heldSources = new Map();
let hudVisible = false, hudWindow = performance.now(), hudPolls = 0, hudFrames = 0, hudPollHz = 0, hudFrameHz = 0, hudPollMs = 0, hudBackendMs = 0, hudServerMs = 0, hudDecodeMs = 0, hudCaptureMs = 0, hudVideoBytes = 0, hudAudioBytes = 0, hudAudioQueued = 0, hudAudioDuplicate = 0, hudAudioDeferred = 0;

function textStatus(value) { status.textContent = value; }
function draw() {
  for (let i = 0, pixel = 0; i < frame.length; i += 2, pixel += 4) {
    const value = frame[i] | frame[i + 1] << 8;
    image.data[pixel] = (value >> 8 & 0xf8) | (value >> 13);
    image.data[pixel + 1] = (value >> 3 & 0xfc) | (value >> 9 & 0x03);
    image.data[pixel + 2] = (value << 3 & 0xf8) | (value >> 2 & 0x07);
    image.data[pixel + 3] = 255;
  }
  sourceCtx.putImageData(image, 0, 0); ctx.imageSmoothingEnabled = false;
  ctx.drawImage(source, 0, 0, 640, 480);
}
function updateHud() {
  const now = performance.now();
  if (now - hudWindow >= 1000) {
    const seconds = (now - hudWindow) / 1000;
    hudPollHz = hudPolls / seconds; hudFrameHz = hudFrames / seconds;
    hudPolls = 0; hudFrames = 0; hudWindow = now;
  }
  const buffered = audioContext ? Math.max(0, audioNext - audioContext.currentTime) * 1000 : 0;
  hud.hidden = !hudVisible;
  hudToggle.setAttribute("aria-pressed", String(hudVisible));
  hud.textContent = `HUD  poll ${hudPollHz.toFixed(1)}/s  obraz ${hudFrameHz.toFixed(1)}/s\n` +
    `browser RTT ${hudPollMs} ms  web→LXC ${hudBackendMs} ms  LXC ${hudServerMs} ms\n` +
    `decode/kreslenie ${hudDecodeMs} ms  server obraz ${hudCaptureMs} ms\n` +
    `video ${(hudVideoBytes / 1024).toFixed(1)} KiB  audio ${(hudAudioBytes / 1024).toFixed(1)} KiB  buffer ${Math.round(buffered)} ms\n` +
    `audio: zaradené ${hudAudioQueued}  duplicitné ${hudAudioDuplicate}  odložené ${hudAudioDeferred}\n` +
    `frame ${videoSeq}  input rev. ${revision}`;
}
function applyVideo(packet) {
  const view = new DataView(packet.buffer, packet.byteOffset, packet.byteLength);
  if (packet.length < 16 || String.fromCharCode(...packet.slice(0, 4)) !== "P2V1") throw Error("neplatný video paket");
  const type = packet[4], count = view.getUint16(6), sequence = view.getUint32(8), capture = view.getUint32(12);
  let at = 16;
  if (type === 1) frame.set(packet.slice(at));
  else if (type === 2) for (let tile = 0; tile < count; tile++) {
    const x = packet[at++], y = packet[at++];
    for (let row = 0; row < 16; row++) { frame.set(packet.slice(at, at + 32), ((y * 16 + row) * width + x * 16) * 2); at += 32; }
  } else throw Error("neznámy video paket");
  videoSeq = sequence; hudFrames++; draw(); return capture;
}
function queueAudio(packet) {
  if (!packet.length || !audioContext) return "empty";
  const now = audioContext.currentTime;
  // Do not acknowledge data that did not enter Web Audio's queue. The server
  // will repeat it on the next packet instead of silently creating a PCM gap.
  if (audioNext > now + audioBufferTarget) return "deferred";
  const samples = packet.length / 2, audio = audioContext.createBuffer(1, samples, 22050), out = audio.getChannelData(0), view = new DataView(packet.buffer, packet.byteOffset, packet.byteLength);
  for (let i = 0; i < samples; i++) out[i] = view.getInt16(i * 2, true) / 32768;
  const node = audioContext.createBufferSource(); node.buffer = audio; node.connect(audioContext.destination);
  audioNext = Math.max(audioNext, now + audioStartLead); node.start(audioNext); audioNext += audio.duration;
  return "queued";
}
function acceptAudio(packet, nextAudioOffset) {
  if (nextAudioOffset === audioOffset) { hudAudioDuplicate++; return; }
  const result = queueAudio(packet);
  if (result === "deferred") { hudAudioDeferred++; return; }
  if (result === "queued") hudAudioQueued++;
  audioOffset = nextAudioOffset;
}
async function poll() {
  if (!session || polling) return; polling = true;
  try {
    const started = performance.now();
    const response = await fetch(`/web/api/sessions/${session}/poll`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({input_revision: revision, video_seq: videoSeq, audio_offset: audioOffset, keyboard_held: [...held], dance_pad_held: [...padHeld]})});
    if (response.status === 204) return;
    if (!response.ok) throw Error(await response.text());
    const backendMs = Number(response.headers.get("X-Pi286-Web-Backend-Ms")), serverMs = Number(response.headers.get("X-Pi286-Server-Poll-Ms"));
    const bytes = new Uint8Array(await response.arrayBuffer()), view = new DataView(bytes.buffer), decodeStarted = performance.now();
    if (String.fromCharCode(...bytes.slice(0, 4)) !== "P2P1") throw Error("neplatný poll paket");
    const videoLength = view.getUint32(4), audioLength = view.getUint32(8), nextAudioOffset = view.getUint32(12);
    hudPollMs = Math.round(performance.now() - started); hudBackendMs = Number.isFinite(backendMs) && backendMs >= 0 ? backendMs : 0; hudServerMs = Number.isFinite(serverMs) && serverMs >= 0 ? serverMs : 0; hudVideoBytes = videoLength; hudAudioBytes = audioLength; hudPolls++;
    hudCaptureMs = applyVideo(bytes.slice(16, 16 + videoLength)); acceptAudio(bytes.slice(16 + videoLength, 16 + videoLength + audioLength), nextAudioOffset); hudDecodeMs = Math.round(performance.now() - decodeStarted); updateHud();
  } catch (error) { textStatus(`Chyba streamu: ${error.message}`); await stop(); }
  finally { polling = false; if (session) setTimeout(poll, 0); }
}
function websocketControl() {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({input_revision: revision, video_seq: videoSeq, audio_offset: audioOffset, keyboard_held: [...held], dance_pad_held: [...padHeld]}));
}
function websocketStart() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${scheme}://${location.host}/web/api/sessions/${session}/stream`); ws.binaryType = "arraybuffer";
  ws.onopen = websocketControl;
  ws.onmessage = event => {
    if (!(event.data instanceof ArrayBuffer)) { textStatus(`Chyba websocketu: ${event.data}`); return; }
    try {
      const bytes = new Uint8Array(event.data), view = new DataView(bytes.buffer), started = performance.now();
      if (String.fromCharCode(...bytes.slice(0, 4)) !== "P2P1") throw Error("neplatný websocket paket");
      const videoLength = view.getUint32(4), audioLength = view.getUint32(8), nextAudioOffset = view.getUint32(12);
      hudPollMs = hudBackendMs = hudServerMs = 0; hudVideoBytes = videoLength; hudAudioBytes = audioLength; hudPolls++;
      // The LXC may send once more before it sees this browser's offset ACK.
      // TCP already guarantees the first copy arrived, so never queue that PCM
      // range twice; duplicated speaker samples sound like a false second voice.
      hudCaptureMs = applyVideo(bytes.slice(16, 16 + videoLength)); acceptAudio(bytes.slice(16 + videoLength, 16 + videoLength + audioLength), nextAudioOffset); hudDecodeMs = Math.round(performance.now() - started); updateHud(); websocketControl();
    } catch (error) { textStatus(`Chyba websocketu: ${error.message}`); stop(); }
  };
  ws.onclose = () => { if (session) { textStatus("WebSocket skončil; skús HTTP polling."); stop(); } };
}
async function start(gameId) {
  textStatus("Pripravujem hru…");
  audioContext = new AudioContext(); await audioContext.resume(); audioNext = audioContext.currentTime;
  const transport = document.querySelector("#transport").value;
  const response = await fetch("/web/api/sessions", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({game_id: gameId, video_scaling: document.querySelector("#scaling").value, transport})});
  if (!response.ok) { textStatus(`Štart zlyhal: ${await response.text()}`); return; }
  const started = await response.json(); session = started.id; videoSeq = 0; audioOffset = 0; hudWindow = performance.now(); hudPolls = hudFrames = hudPollHz = hudFrameHz = hudPollMs = hudBackendMs = hudServerMs = hudDecodeMs = hudCaptureMs = hudVideoBytes = hudAudioBytes = hudAudioQueued = hudAudioDuplicate = hudAudioDeferred = 0; frame.fill(0); draw(); updateHud(); menu.hidden = true; player.hidden = false; if (transport === "websocket") websocketStart(); else poll();
}
async function stop() {
  const closing = session; session = null; if (ws) { ws.onclose = null; ws.close(); ws = null; } held.clear(); padHeld.clear(); heldSources.clear(); player.hidden = true; menu.hidden = false;
  if (audioContext) { await audioContext.close(); audioContext = null; }
  if (closing) await fetch(`/web/api/sessions/${closing}`, {method: "DELETE"});
}
function keyName(event) {
  const names = {ArrowUp: "UP", ArrowDown: "DOWN", ArrowLeft: "LEFT", ArrowRight: "RIGHT", Enter: "ENTER", Escape: "ESC", " ": "SPACE", Tab: "TAB", Backspace: "BACKSPACE", Control: "CTRL", Alt: "ALT", Shift: "SHIFT", CapsLock: "CAPSLOCK", NumLock: "NUMLOCK", ScrollLock: "SCROLLLOCK", Pause: "PAUSE", PrintScreen: "PRINT", Insert: "INSERT", Delete: "DELETE", Home: "HOME", End: "END", PageUp: "PAGEUP", PageDown: "PAGEDOWN"};
  if (names[event.key]) return names[event.key];
  const codes = {Minus: "MINUS", Equal: "EQUALS", BracketLeft: "LEFTBRACKET", BracketRight: "RIGHTBRACKET", Backslash: "BACKSLASH", Semicolon: "SEMICOLON", Quote: "QUOTE", Backquote: "BACKQUOTE", Comma: "COMMA", Period: "PERIOD", Slash: "SLASH", Numpad0: "KP0", Numpad1: "KP1", Numpad2: "KP2", Numpad3: "KP3", Numpad4: "KP4", Numpad5: "KP5", Numpad6: "KP6", Numpad7: "KP7", Numpad8: "KP8", Numpad9: "KP9", NumpadDecimal: "KP_PERIOD", NumpadDivide: "KP_DIVIDE", NumpadMultiply: "KP_MULTIPLY", NumpadSubtract: "KP_MINUS", NumpadAdd: "KP_PLUS", NumpadEnter: "KP_ENTER", NumpadEqual: "KP_EQUALS"};
  if (codes[event.code]) return codes[event.code];
  if (/^[a-z0-9]$/i.test(event.key)) return event.key.toUpperCase();
  if (/^F(?:[2-9]|1[0-2])$/.test(event.key)) return event.key;
  return null;
}
function setHeldSource(source, keys) {
  if (keys.length) heldSources.set(source, new Set(keys)); else heldSources.delete(source);
  const next = new Set(); for (const sourceKeys of heldSources.values()) for (const key of sourceKeys) next.add(key);
  if (next.size === held.size && [...next].every(key => held.has(key))) return;
  held.clear(); for (const key of next) held.add(key); revision++; websocketControl();
}
function toggleHud() { hudVisible = !hudVisible; updateHud(); }
function showPadMap(game) {
  const labels = game.pre_game.pad_labels, keys = game.pre_game.pad_keys;
  const legend = document.querySelector("#pre-game-pad"); legend.replaceChildren();
  for (const button of [6, 2, 7, 0, 8, 3, 4, 1, 5]) {
    const entry = document.createElement("span");
    entry.textContent = button === 8 ? "START" : document.querySelector(`[data-pad-button="${button}"]`).textContent;
    const detail = document.createElement("small"); detail.textContent = keys[button] ? labels[button] : "nepoužité";
    entry.append(detail); legend.append(entry);
  }
}
addEventListener("keydown", event => { if (!session) return; if (event.key === "F1") { event.preventDefault(); stop(); return; } if (event.key === "F8") { event.preventDefault(); toggleHud(); return; } const key = keyName(event); if (key) { setHeldSource(`keyboard:${key}`, [key]); event.preventDefault(); } });
addEventListener("keyup", event => { const key = keyName(event); if (key) { setHeldSource(`keyboard:${key}`, []); event.preventDefault(); } });
document.querySelector("#panic").addEventListener("click", () => stop());
hudToggle.addEventListener("click", toggleHud);
document.querySelector("#pad-select").addEventListener("click", () => stop());
for (const button of document.querySelectorAll("[data-pad-button]")) {
  const release = event => { padHeld.delete(Number(button.dataset.padButton)); revision++; websocketControl(); button.classList.remove("active"); };
  button.addEventListener("pointerdown", event => { if (!session) return; event.preventDefault(); button.setPointerCapture(event.pointerId); padHeld.add(Number(button.dataset.padButton)); revision++; websocketControl(); button.classList.add("active"); });
  button.addEventListener("pointerup", release);
  button.addEventListener("pointercancel", release);
  button.addEventListener("lostpointercapture", release);
}
async function initialise() {
  try {
    const response = await fetch("/web/api/games"), payload = await response.json();
    for (const game of payload.games) { const button = document.createElement("button"); button.textContent = game.name; button.onclick = () => { selectedGame = game; document.querySelector("#pre-game-title").textContent = game.name; document.querySelector("#pre-game-hint").textContent = game.pre_game.launch_hint; showPadMap(game); document.querySelector("#pre-game").hidden = false; games.hidden = true; }; games.append(button); }
    textStatus("Vyber hru. Tento runtime je určený iba pre dôveryhodnú lokálnu sieť.");
  } catch (error) { textStatus(`Nedá sa načítať launcher: ${error.message}`); }
}
document.querySelector("#pre-game-start").onclick = () => { if (selectedGame) start(selectedGame.id); };
document.querySelector("#pre-game-back").onclick = () => { document.querySelector("#pre-game").hidden = true; games.hidden = false; };
initialise();
