export function createVirtualControls({keyName, active, stop, toggleHud, changed}) {
  const entry = document.querySelector("#text-entry"), held = new Set(), padHeld = new Set(), heldSources = new Map(), textTapQueue = [];
  let revision = 0, textTapRunning = false;
  function snapshot() { return {revision, keyboardHeld: [...held], dancePadHeld: [...padHeld]}; }
  function notify() { revision++; changed(); }
  function setHeldSource(source, keys) {
    if (keys.length) heldSources.set(source, new Set(keys)); else heldSources.delete(source);
    const next = new Set(); for (const sourceKeys of heldSources.values()) for (const key of sourceKeys) next.add(key);
    if (next.size === held.size && [...next].every(key => held.has(key))) return;
    held.clear(); for (const key of next) held.add(key); notify();
  }
  function tapTextKey(key) {
    textTapQueue.push(key);
    if (textTapRunning) return;
    textTapRunning = true;
    const next = () => {
      const value = textTapQueue.shift();
      if (!value || !active()) { textTapRunning = false; return; }
      const source = `text:${value}`;
      setHeldSource(source, [value]);
      setTimeout(() => { setHeldSource(source, []); setTimeout(next, 35); }, 80);
    };
    next();
  }
  function virtualKey(button) {
    const key = button.dataset.virtualKey;
    if (!active() || !key) return;
    if (button.dataset.modifier === "true") {
      const pressed = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", String(pressed)); setHeldSource(`virtual:${key}`, pressed ? [key] : []);
    } else tapTextKey(key);
  }
  function setPadButton(button, pressed, element) {
    const changed = pressed ? !padHeld.has(button) : padHeld.has(button);
    if (pressed) padHeld.add(button); else padHeld.delete(button);
    if (changed) notify(); element.classList.toggle("active", pressed);
  }
  function reset() {
    held.clear(); padHeld.clear(); heldSources.clear(); textTapQueue.length = 0; textTapRunning = false;
    for (const button of document.querySelectorAll("[data-modifier]")) button.setAttribute("aria-pressed", "false");
    for (const button of document.querySelectorAll("[data-pad-button]")) button.classList.remove("active");
  }
  function show(caps) { document.querySelector("#virtual-keys").hidden = !caps.keyboard; document.querySelector("#virtual-pad").hidden = !caps.dancePad; }
  addEventListener("keydown", event => { if (!active() || event.target === entry) return; if (event.key === "F1") { event.preventDefault(); stop(); return; } if (event.key === "F8") { event.preventDefault(); toggleHud(); return; } const key = keyName(event); if (key) { setHeldSource(`keyboard:${key}`, [key]); event.preventDefault(); } });
  addEventListener("keyup", event => { if (event.target === entry) return; const key = keyName(event); if (key) { setHeldSource(`keyboard:${key}`, []); event.preventDefault(); } });
  document.querySelector("#panic").addEventListener("click", stop);
  document.querySelector("#pad-select").addEventListener("click", stop);
  for (const button of document.querySelectorAll("[data-virtual-key]")) button.addEventListener("click", () => virtualKey(button));
  document.querySelector("#virtual-keyboard").addEventListener("click", () => entry.focus({preventScroll: true}));
  entry.addEventListener("beforeinput", event => {
    if (!active()) return;
    let keys = [];
    if (event.inputType === "deleteContentBackward") keys = ["BACKSPACE"];
    else if (event.inputType === "deleteContentForward") keys = ["DELETE"];
    else if (event.inputType === "insertLineBreak") keys = ["ENTER"];
    else if (event.inputType === "insertText" && event.data) keys = [...event.data].map(textKey).filter(Boolean);
    if (!keys.length) return;
    event.preventDefault(); entry.value = "";
    for (const key of keys) virtualKey({dataset: {virtualKey: key}});
  });
  for (const button of document.querySelectorAll("[data-pad-button]")) {
    const release = () => setPadButton(Number(button.dataset.padButton), false, button);
    button.addEventListener("pointerdown", event => { if (!active()) return; event.preventDefault(); button.setPointerCapture(event.pointerId); setPadButton(Number(button.dataset.padButton), true, button); });
    button.addEventListener("pointerup", release); button.addEventListener("pointercancel", release); button.addEventListener("lostpointercapture", release);
  }
  return {reset, show, snapshot};
}

function textKey(character) {
  const punctuation = {" ": "SPACE", "-": "MINUS", "=": "EQUALS", "[": "LEFTBRACKET", "]": "RIGHTBRACKET", "\\": "BACKSLASH", ";": "SEMICOLON", "'": "QUOTE", "`": "BACKQUOTE", ",": "COMMA", ".": "PERIOD", "/": "SLASH"};
  return punctuation[character] || (/^[a-z0-9]$/i.test(character) ? character.toUpperCase() : null);
}
