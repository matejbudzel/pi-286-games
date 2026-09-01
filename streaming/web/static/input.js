export function keyName(event) {
  const names = {ArrowUp: "UP", ArrowDown: "DOWN", ArrowLeft: "LEFT", ArrowRight: "RIGHT", Enter: "ENTER", Escape: "ESC", " ": "SPACE", Tab: "TAB", Backspace: "BACKSPACE", Control: "CTRL", Alt: "ALT", Shift: "SHIFT", Meta: "META", OS: "META", CapsLock: "CAPSLOCK", NumLock: "NUMLOCK", ScrollLock: "SCROLLLOCK", Pause: "PAUSE", PrintScreen: "PRINT", Insert: "INSERT", Delete: "DELETE", Home: "HOME", End: "END", PageUp: "PAGEUP", PageDown: "PAGEDOWN"};
  if (names[event.key]) return names[event.key];
  const codes = {Minus: "MINUS", Equal: "EQUALS", BracketLeft: "LEFTBRACKET", BracketRight: "RIGHTBRACKET", Backslash: "BACKSLASH", Semicolon: "SEMICOLON", Quote: "QUOTE", Backquote: "BACKQUOTE", Comma: "COMMA", Period: "PERIOD", Slash: "SLASH", Numpad0: "KP0", Numpad1: "KP1", Numpad2: "KP2", Numpad3: "KP3", Numpad4: "KP4", Numpad5: "KP5", Numpad6: "KP6", Numpad7: "KP7", Numpad8: "KP8", Numpad9: "KP9", NumpadDecimal: "KP_PERIOD", NumpadDivide: "KP_DIVIDE", NumpadMultiply: "KP_MULTIPLY", NumpadSubtract: "KP_MINUS", NumpadAdd: "KP_PLUS", NumpadEnter: "KP_ENTER", NumpadEqual: "KP_EQUALS"};
  if (codes[event.code]) return codes[event.code];
  if (/^[a-z0-9]$/i.test(event.key)) return event.key.toUpperCase();
  return /^F(?:[2-9]|1[0-2])$/.test(event.key) ? event.key : null;
}
