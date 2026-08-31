"use strict";
const width = 320, height = 240, frame = new Uint8Array(width * height * 2);
const canvas = document.querySelector("#screen"), ctx = canvas.getContext("2d"), source = document.createElement("canvas");
source.width = width; source.height = height;
const sourceCtx = source.getContext("2d"), image = sourceCtx.createImageData(width, height);
const menu = document.querySelector("#menu"), player = document.querySelector("#player"), games = document.querySelector("#games"), status = document.querySelector("#status"), hud = document.querySelector("#hud");
let session = null, videoSeq = 0, audioOffset = 0, revision = 0, polling = false, audioContext = null, audioNext = 0, ws = null;
const held = new Set();
let hudVisible = true, hudWindow = performance.now(), hudPolls = 0, hudFrames = 0, hudPollHz = 0, hudFrameHz = 0, hudPollMs = 0, hudBackendMs = 0, hudServerMs = 0, hudDecodeMs = 0, hudCaptureMs = 0, hudVideoBytes = 0, hudAudioBytes = 0;

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
  hud.textContent = `HUD  poll ${hudPollHz.toFixed(1)}/s  obraz ${hudFrameHz.toFixed(1)}/s\n` +
    `browser RTT ${hudPollMs} ms  web→LXC ${hudBackendMs} ms  LXC ${hudServerMs} ms\n` +
    `decode/kreslenie ${hudDecodeMs} ms  server obraz ${hudCaptureMs} ms\n` +
    `video ${(hudVideoBytes / 1024).toFixed(1)} KiB  audio ${(hudAudioBytes / 1024).toFixed(1)} KiB  buffer ${Math.round(buffered)} ms\n` +
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
  if (!packet.length || !audioContext) return;
  const now = audioContext.currentTime;
  if (audioNext > now + .35) return;
  const samples = packet.length / 2, audio = audioContext.createBuffer(1, samples, 22050), out = audio.getChannelData(0), view = new DataView(packet.buffer, packet.byteOffset, packet.byteLength);
  for (let i = 0; i < samples; i++) out[i] = view.getInt16(i * 2, true) / 32768;
  const node = audioContext.createBufferSource(); node.buffer = audio; node.connect(audioContext.destination);
  audioNext = Math.max(audioNext, now + .05); node.start(audioNext); audioNext += audio.duration;
}
async function poll() {
  if (!session || polling) return; polling = true;
  try {
    const started = performance.now();
    const response = await fetch(`/api/sessions/${session}/poll`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({input_revision: revision, video_seq: videoSeq, audio_offset: audioOffset, held_keys: [...held]})});
    if (response.status === 204) return;
    if (!response.ok) throw Error(await response.text());
    const backendMs = Number(response.headers.get("X-Pi286-Web-Backend-Ms")), serverMs = Number(response.headers.get("X-Pi286-Server-Poll-Ms"));
    const bytes = new Uint8Array(await response.arrayBuffer()), view = new DataView(bytes.buffer), decodeStarted = performance.now();
    if (String.fromCharCode(...bytes.slice(0, 4)) !== "P2P1") throw Error("neplatný poll paket");
    const videoLength = view.getUint32(4), audioLength = view.getUint32(8); audioOffset = view.getUint32(12);
    hudPollMs = Math.round(performance.now() - started); hudBackendMs = Number.isFinite(backendMs) && backendMs >= 0 ? backendMs : 0; hudServerMs = Number.isFinite(serverMs) && serverMs >= 0 ? serverMs : 0; hudVideoBytes = videoLength; hudAudioBytes = audioLength; hudPolls++;
    hudCaptureMs = applyVideo(bytes.slice(16, 16 + videoLength)); queueAudio(bytes.slice(16 + videoLength, 16 + videoLength + audioLength)); hudDecodeMs = Math.round(performance.now() - decodeStarted); updateHud();
  } catch (error) { textStatus(`Chyba streamu: ${error.message}`); await stop(); }
  finally { polling = false; if (session) setTimeout(poll, 0); }
}
function websocketControl() {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({input_revision: revision, video_seq: videoSeq, audio_offset: audioOffset, held_keys: [...held]}));
}
function websocketStart() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${scheme}://${location.host}/api/sessions/${session}/stream`); ws.binaryType = "arraybuffer";
  ws.onopen = websocketControl;
  ws.onmessage = event => {
    if (!(event.data instanceof ArrayBuffer)) return;
    try {
      const bytes = new Uint8Array(event.data), view = new DataView(bytes.buffer), started = performance.now();
      if (String.fromCharCode(...bytes.slice(0, 4)) !== "P2P1") throw Error("neplatný websocket paket");
      const videoLength = view.getUint32(4), audioLength = view.getUint32(8); audioOffset = view.getUint32(12);
      hudPollMs = hudBackendMs = hudServerMs = 0; hudVideoBytes = videoLength; hudAudioBytes = audioLength; hudPolls++;
      hudCaptureMs = applyVideo(bytes.slice(16, 16 + videoLength)); queueAudio(bytes.slice(16 + videoLength, 16 + videoLength + audioLength)); hudDecodeMs = Math.round(performance.now() - started); updateHud(); websocketControl();
    } catch (error) { textStatus(`Chyba websocketu: ${error.message}`); stop(); }
  };
  ws.onclose = () => { if (session) { textStatus("WebSocket skončil; skús HTTP polling."); stop(); } };
}
async function start(gameId) {
  textStatus("Pripravujem hru…");
  audioContext = new AudioContext(); await audioContext.resume(); audioNext = audioContext.currentTime;
  const transport = document.querySelector("#transport").value;
  const response = await fetch("/api/sessions", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({game_id: gameId, video_scaling: document.querySelector("#scaling").value, transport})});
  if (!response.ok) { textStatus(`Štart zlyhal: ${await response.text()}`); return; }
  session = (await response.json()).id; videoSeq = 0; audioOffset = 0; hudWindow = performance.now(); hudPolls = hudFrames = hudPollHz = hudFrameHz = hudPollMs = hudBackendMs = hudServerMs = hudDecodeMs = hudCaptureMs = hudVideoBytes = hudAudioBytes = 0; frame.fill(0); draw(); updateHud(); menu.hidden = true; player.hidden = false; if (transport === "websocket") websocketStart(); else poll();
}
async function stop() {
  const closing = session; session = null; if (ws) { ws.onclose = null; ws.close(); ws = null; } held.clear(); player.hidden = true; menu.hidden = false;
  if (audioContext) { await audioContext.close(); audioContext = null; }
  if (closing) await fetch(`/api/sessions/${closing}`, {method: "DELETE"});
}
function keyName(event) {
  const names = {ArrowUp: "UP", ArrowDown: "DOWN", ArrowLeft: "LEFT", ArrowRight: "RIGHT", Enter: "ENTER", Escape: "ESC", " ": "SPACE", Tab: "TAB", Backspace: "BACKSPACE"};
  if (names[event.key]) return names[event.key];
  if (/^[a-z0-9]$/i.test(event.key)) return event.key.toUpperCase();
  if (/^F(?:[2-9]|1[0-2])$/.test(event.key)) return event.key;
  return null;
}
addEventListener("keydown", event => { if (!session) return; if (event.key === "F1") { event.preventDefault(); stop(); return; } if (event.key === "F8") { event.preventDefault(); hudVisible = !hudVisible; updateHud(); return; } const key = keyName(event); if (key && !held.has(key)) { held.add(key); revision++; websocketControl(); event.preventDefault(); } });
addEventListener("keyup", event => { const key = keyName(event); if (key && held.delete(key)) { revision++; websocketControl(); event.preventDefault(); } });
async function initialise() {
  try {
    const response = await fetch("/api/games"), payload = await response.json();
    for (const game of payload.games) { const button = document.createElement("button"); button.textContent = game.name; button.onclick = () => start(game.id); games.append(button); }
    const diagnostic = document.createElement("button"); diagnostic.textContent = "Dúhová mačka"; diagnostic.onclick = () => start("rainbow-cat"); games.append(diagnostic);
    textStatus("Vyber hru. Tento runtime je určený iba pre dôveryhodnú lokálnu sieť.");
  } catch (error) { textStatus(`Nedá sa načítať launcher: ${error.message}`); }
}
initialise();
