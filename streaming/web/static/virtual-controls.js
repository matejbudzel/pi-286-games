export function installVirtualControls({active, keyName, setHeldSource, tapKey, stop, toggleHud, setPadButton}) {
  const entry = document.querySelector("#text-entry");
  addEventListener("keydown", event => { if (!active() || event.target === entry) return; if (event.key === "F1") { event.preventDefault(); stop(); return; } if (event.key === "F8") { event.preventDefault(); toggleHud(); return; } const key = keyName(event); if (key) { setHeldSource(`keyboard:${key}`, [key]); event.preventDefault(); } });
  addEventListener("keyup", event => { if (event.target === entry) return; const key = keyName(event); if (key) { setHeldSource(`keyboard:${key}`, []); event.preventDefault(); } });
  document.querySelector("#panic").addEventListener("click", stop);
  document.querySelector("#pad-select").addEventListener("click", stop);
  for (const button of document.querySelectorAll("[data-virtual-key]")) button.addEventListener("click", () => tapKey(button));
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
    for (const key of keys) tapKey({dataset: {virtualKey: key}});
  });
  for (const button of document.querySelectorAll("[data-pad-button]")) {
    const release = () => setPadButton(Number(button.dataset.padButton), false, button);
    button.addEventListener("pointerdown", event => { if (!active()) return; event.preventDefault(); button.setPointerCapture(event.pointerId); setPadButton(Number(button.dataset.padButton), true, button); });
    button.addEventListener("pointerup", release);
    button.addEventListener("pointercancel", release);
    button.addEventListener("lostpointercapture", release);
  }
}

function textKey(character) {
  const punctuation = {" ": "SPACE", "-": "MINUS", "=": "EQUALS", "[": "LEFTBRACKET", "]": "RIGHTBRACKET", "\\": "BACKSLASH", ";": "SEMICOLON", "'": "QUOTE", "`": "BACKQUOTE", ",": "COMMA", ".": "PERIOD", "/": "SLASH"};
  return punctuation[character] || (/^[a-z0-9]$/i.test(character) ? character.toUpperCase() : null);
}
