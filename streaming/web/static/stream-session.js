export function createSession({input, textStatus, showGame, showList}) {
  const width = 320, height = 240, frame = new Uint8Array(width * height * 2);
  const canvas = document.querySelector("#screen"), ctx = canvas.getContext("2d"), source = document.createElement("canvas"), player = document.querySelector("#player"), hud = document.querySelector("#hud"), hudToggle = document.querySelector("#hud-toggle");
  source.width = width; source.height = height;
  const sourceCtx = source.getContext("2d"), image = sourceCtx.createImageData(width, height);
  let session = null, videoSeq = 0, audioOffset = 0, polling = false, audioContext = null, audioNext = 0, ws = null, starting = false, hudVisible = false, clientStats = null, statsReported = false;
  function active() { return Boolean(session); }
  function newMetric() { return {count: 0, total: 0, min: 0, max: 0}; }
  function addMetric(metric, value) { metric.count++; metric.total += value; metric.min = metric.count === 1 ? value : Math.min(metric.min, value); metric.max = Math.max(metric.max, value); }
  function metric(value) { return {count: value.count, avg: value.count ? Math.round(value.total / value.count) : 0, min: value.min, max: value.max}; }
  function browserStats() {
    if (!clientStats) return null;
    return {version: 1, transport: clientStats.transport, started_at: clientStats.startedAt, duration_ms: Math.round(performance.now() - clientStats.startedAtMs), frames: clientStats.frames, last_video_sequence: videoSeq, frame_interval_ms: metric(clientStats.frameIntervals), server_capture_ms: metric(clientStats.captureMs), decode_draw_ms: metric(clientStats.decodeDrawMs), video_bytes: metric(clientStats.videoBytes), audio_bytes: metric(clientStats.audioBytes), audio: {queued: 0, duplicate: 0, deferred: 0}};
  }
  async function reportBrowserStats(sessionId) {
    if (!clientStats || statsReported) return;
    const response = await fetch("/web/api/sessions/" + sessionId + "/stats", {method: "POST", keepalive: true, headers: {"Content-Type": "application/json"}, body: JSON.stringify(browserStats())});
    if (!response.ok) throw Error("nepodarilo sa uložiť štatistiky: " + response.status); statsReported = true;
  }
  window.copyStats = async () => { const stats = browserStats(); if (!stats) throw Error("nie je k dispozícii žiadna stream relácia"); await navigator.clipboard.writeText(JSON.stringify(stats, null, 2)); return stats; };
  function draw() {
    for (let i = 0, pixel = 0; i < frame.length; i += 2, pixel += 4) {
      const value = frame[i] | frame[i + 1] << 8;
      image.data[pixel] = (value >> 8 & 0xf8) | (value >> 13); image.data[pixel + 1] = (value >> 3 & 0xfc) | (value >> 9 & 3);
      image.data[pixel + 2] = (value << 3 & 0xf8) | (value >> 2 & 7); image.data[pixel + 3] = 255;
    }
    sourceCtx.putImageData(image, 0, 0); ctx.imageSmoothingEnabled = false; ctx.drawImage(source, 0, 0, 640, 480);
  }
  function updateHud() {
    const buffered = audioContext ? Math.max(0, audioNext - audioContext.currentTime) * 1000 : 0;
    hud.hidden = !hudVisible; hudToggle.setAttribute("aria-pressed", String(hudVisible));
    hud.textContent = "HUD  frame " + videoSeq + "  input rev. " + input.snapshot().revision + "\nvideo " + (frame.length / 1024).toFixed(0) + " KiB  audio buffer " + Math.round(buffered) + " ms";
  }
  function applyVideo(packet) {
    const view = new DataView(packet.buffer, packet.byteOffset, packet.byteLength);
    if (packet.length < 16 || String.fromCharCode(...packet.slice(0, 4)) !== "P2V1") throw Error("neplatný video paket");
    const type = packet[4], count = view.getUint16(6), sequence = view.getUint32(8), capture = view.getUint32(12); let at = 16;
    if (type === 1) frame.set(packet.slice(at));
    else if (type === 2) for (let tile = 0; tile < count; tile++) { const x = packet[at++], y = packet[at++]; for (let row = 0; row < 16; row++) { frame.set(packet.slice(at, at + 32), ((y * 16 + row) * width + x * 16) * 2); at += 32; } }
    else throw Error("neznámy video paket");
    videoSeq = sequence; draw(); return capture;
  }
  function queueAudio(packet) {
    if (!packet.length || !audioContext) return "empty";
    const now = audioContext.currentTime; if (audioNext > now + .35) return "deferred";
    const samples = packet.length / 2, audio = audioContext.createBuffer(1, samples, 22050), out = audio.getChannelData(0), view = new DataView(packet.buffer, packet.byteOffset, packet.byteLength);
    for (let i = 0; i < samples; i++) out[i] = view.getInt16(i * 2, true) / 32768;
    const node = audioContext.createBufferSource(); node.buffer = audio; node.connect(audioContext.destination); audioNext = Math.max(audioNext, now + .08); node.start(audioNext); audioNext += audio.duration; return "queued";
  }
  function controlBody() { const state = input.snapshot(); return {input_revision: state.revision, video_seq: videoSeq, audio_offset: audioOffset, keyboard_held: state.keyboardHeld, dance_pad_held: state.dancePadHeld}; }
  function sendControl() { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(controlBody())); }
  function consumePacket(bytes, started = performance.now()) {
    const view = new DataView(bytes.buffer);
    if (String.fromCharCode(...bytes.slice(0, 4)) !== "P2P1") throw Error("neplatný stream paket");
    const videoLength = view.getUint32(4), audioLength = view.getUint32(8), nextAudioOffset = view.getUint32(12);
    const capture = applyVideo(bytes.slice(16, 16 + videoLength));
    if (nextAudioOffset !== audioOffset && queueAudio(bytes.slice(16 + videoLength, 16 + videoLength + audioLength)) !== "deferred") audioOffset = nextAudioOffset;
    if (clientStats) { if (clientStats.lastFrameAt) addMetric(clientStats.frameIntervals, Math.round(started - clientStats.lastFrameAt)); clientStats.lastFrameAt = started; clientStats.frames++; addMetric(clientStats.captureMs, capture); addMetric(clientStats.decodeDrawMs, Math.round(performance.now() - started)); addMetric(clientStats.videoBytes, videoLength); addMetric(clientStats.audioBytes, audioLength); }
    updateHud();
  }
  async function poll() {
    if (!session || polling) return; polling = true;
    try { const started = performance.now(), response = await fetch("/web/api/sessions/" + session + "/poll", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(controlBody())}); if (response.status === 204) return; if (!response.ok) throw Error(await response.text()); consumePacket(new Uint8Array(await response.arrayBuffer()), started); }
    catch (error) { textStatus("Chyba streamu: " + error.message); await stop(); }
    finally { polling = false; if (session) setTimeout(poll, 0); }
  }
  function websocketStart() {
    const scheme = location.protocol === "https:" ? "wss" : "ws"; ws = new WebSocket(scheme + "://" + location.host + "/web/api/sessions/" + session + "/stream"); ws.binaryType = "arraybuffer"; ws.onopen = sendControl;
    ws.onmessage = event => { if (!(event.data instanceof ArrayBuffer)) return; try { consumePacket(new Uint8Array(event.data)); sendControl(); } catch (error) { textStatus("Chyba websocketu: " + error.message); stop(); } };
    ws.onclose = () => { if (session) { textStatus("WebSocket skončil; skús HTTP polling."); stop(); } };
  }
  async function start(gameId, options) {
    if (starting || session) return; starting = true; textStatus("Pripravujem hru…");
    try {
      audioContext = new AudioContext(); await audioContext.resume(); audioNext = audioContext.currentTime;
      const response = await fetch("/web/api/sessions", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({game_id: gameId, video_scaling: options.videoScaling, transport: options.transport})});
      if (!response.ok) { textStatus("Štart zlyhal: " + await response.text()); await audioContext.close(); audioContext = null; return; }
      session = (await response.json()).id; videoSeq = audioOffset = 0; statsReported = false; clientStats = {transport: options.transport, startedAt: new Date().toISOString(), startedAtMs: performance.now(), lastFrameAt: 0, frames: 0, frameIntervals: newMetric(), captureMs: newMetric(), decodeDrawMs: newMetric(), videoBytes: newMetric(), audioBytes: newMetric()}; frame.fill(0); draw(); updateHud(); player.hidden = false; showGame(options); if (options.transport === "websocket") websocketStart(); else poll();
    } finally { starting = false; }
  }
  async function stop() {
    const closing = session; if (!closing) return;
    try { await reportBrowserStats(closing); } catch (error) { console.warn(error); }
    session = null; if (ws) { ws.onclose = null; ws.close(); ws = null; } input.reset(); player.hidden = true; showList();
    if (audioContext) { await audioContext.close(); audioContext = null; } await fetch("/web/api/sessions/" + closing, {method: "DELETE"});
  }
  function toggleHud() { hudVisible = !hudVisible; updateHud(); }
  hudToggle.addEventListener("click", toggleHud);
  addEventListener("pagehide", () => { if (session && clientStats && !statsReported) navigator.sendBeacon("/web/api/sessions/" + session + "/stats", new Blob([JSON.stringify(browserStats())], {type: "application/json"})); });
  return {active, sendControl, start, stop, toggleHud};
}
