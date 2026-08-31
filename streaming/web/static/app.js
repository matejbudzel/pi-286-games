"use strict";
const width = 320, height = 240, frame = new Uint8Array(width * height * 2);
const canvas = document.querySelector("#screen"), ctx = canvas.getContext("2d"), source = document.createElement("canvas");
source.width = width; source.height = height;
const sourceCtx = source.getContext("2d"), image = sourceCtx.createImageData(width, height);
const menu = document.querySelector("#menu"), player = document.querySelector("#player"), games = document.querySelector("#games"), status = document.querySelector("#status");
let session = null, videoSeq = 0, audioOffset = 0, revision = 0, polling = false, audioContext = null, audioNext = 0;
const held = new Set();

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
  videoSeq = sequence; draw(); return capture;
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
    const response = await fetch(`/api/sessions/${session}/poll`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({input_revision: revision, video_seq: videoSeq, audio_offset: audioOffset, held_keys: [...held]})});
    if (response.status === 204) return;
    if (!response.ok) throw Error(await response.text());
    const bytes = new Uint8Array(await response.arrayBuffer()), view = new DataView(bytes.buffer);
    if (String.fromCharCode(...bytes.slice(0, 4)) !== "P2P1") throw Error("neplatný poll paket");
    const videoLength = view.getUint32(4), audioLength = view.getUint32(8); audioOffset = view.getUint32(12);
    applyVideo(bytes.slice(16, 16 + videoLength)); queueAudio(bytes.slice(16 + videoLength, 16 + videoLength + audioLength));
  } catch (error) { textStatus(`Chyba streamu: ${error.message}`); await stop(); }
  finally { polling = false; if (session) setTimeout(poll, 0); }
}
async function start(gameId) {
  textStatus("Pripravujem hru…");
  audioContext = new AudioContext(); await audioContext.resume(); audioNext = audioContext.currentTime;
  const response = await fetch("/api/sessions", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({game_id: gameId, video_scaling: document.querySelector("#scaling").value})});
  if (!response.ok) { textStatus(`Štart zlyhal: ${await response.text()}`); return; }
  session = (await response.json()).id; videoSeq = 0; audioOffset = 0; frame.fill(0); draw(); menu.hidden = true; player.hidden = false; poll();
}
async function stop() {
  const closing = session; session = null; held.clear(); player.hidden = true; menu.hidden = false;
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
addEventListener("keydown", event => { if (!session) return; if (event.key === "F1") { event.preventDefault(); stop(); return; } const key = keyName(event); if (key && !held.has(key)) { held.add(key); revision++; event.preventDefault(); } });
addEventListener("keyup", event => { const key = keyName(event); if (key && held.delete(key)) { revision++; event.preventDefault(); } });
async function initialise() {
  try {
    const response = await fetch("/api/games"), payload = await response.json();
    for (const game of payload.games) { const button = document.createElement("button"); button.textContent = game.name; button.onclick = () => start(game.id); games.append(button); }
    const diagnostic = document.createElement("button"); diagnostic.textContent = "Dúhová mačka"; diagnostic.onclick = () => start("rainbow-cat"); games.append(diagnostic);
    textStatus("Vyber hru. Tento runtime je určený iba pre dôveryhodnú lokálnu sieť.");
  } catch (error) { textStatus(`Nedá sa načítať launcher: ${error.message}`); }
}
initialise();
