"""Configuration, protocol constants, and game-definition loading."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import os
import re

ROOT = Path(__file__).resolve().parents[2]


WEB_STATIC = ROOT / "streaming" / "web" / "static"
WEB_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
             "/app.js": ("app.js", "text/javascript; charset=utf-8"),
             "/input.js": ("input.js", "text/javascript; charset=utf-8"),
             "/style.css": ("style.css", "text/css; charset=utf-8")}

SESSION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DEFAULTS = {
    "bind": "0.0.0.0",
    "port": "28680",
    "state_root": "/srv/pi286-stream",
    "token_file": "/etc/pi286-stream.token",
    "dosbox": "/usr/bin/dosbox",
    "xvfb": "/usr/bin/Xvfb",
    "xvfb_fbdir": "xvfb-fb",
    "capture_helper": "/opt/pi286-stream/repo/streaming/backend/bin/pi286-xvfb-capture",
    "xwd": "/usr/bin/xwd",
    "xdotool": "/usr/bin/xdotool",
    "arecord": "/usr/bin/arecord",
    "audio_capture": "file",
    "audio_playback_device": "plughw:Loopback,0,0",
    "audio_capture_device": "hw:Loopback,1,0",
    "audio_rate": "22050",
    # A lost browser/Pi must not leave its headless DOSBox process alive.
    # WebSockets additionally stop immediately when their TCP connection closes.
    "session_idle_seconds": "8",
    "game_definitions_root": "/opt/pi286-stream/repo/games",
    "game_data_root": "/srv/pi286-games",
}

KEYS = {
    "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
    "ENTER": "Return", "ESC": "Escape", "SPACE": "space", "BACKSPACE": "BackSpace", "TAB": "Tab",
    "CAPSLOCK": "Caps_Lock", "NUMLOCK": "Num_Lock", "SCROLLLOCK": "Scroll_Lock", "PAUSE": "Pause",
    "PRINT": "Print", "INSERT": "Insert", "DELETE": "Delete", "HOME": "Home", "END": "End",
    "PAGEUP": "Prior", "PAGEDOWN": "Next",
    "CTRL": "Control_L", "ALT": "Alt_L", "SHIFT": "Shift_L", "META": "Super_L",
    "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4", "F5": "F5",
    "F6": "F6", "F7": "F7", "F8": "F8", "F9": "F9", "F10": "F10", "F11": "F11", "F12": "F12",
    "MINUS": "minus", "EQUALS": "equal", "LEFTBRACKET": "bracketleft", "RIGHTBRACKET": "bracketright",
    "BACKSLASH": "backslash", "SEMICOLON": "semicolon", "QUOTE": "apostrophe", "BACKQUOTE": "grave",
    "COMMA": "comma", "PERIOD": "period", "SLASH": "slash",
    "KP0": "KP_0", "KP1": "KP_1", "KP2": "KP_2", "KP3": "KP_3", "KP4": "KP_4",
    "KP5": "KP_5", "KP6": "KP_6", "KP7": "KP_7", "KP8": "KP_8", "KP9": "KP_9",
    "KP_PERIOD": "KP_Decimal", "KP_DIVIDE": "KP_Divide", "KP_MULTIPLY": "KP_Multiply",
    "KP_MINUS": "KP_Subtract", "KP_PLUS": "KP_Add", "KP_ENTER": "KP_Enter", "KP_EQUALS": "KP_Equal",
    **{character.upper(): character for character in "abcdefghijklmnopqrstuvwxyz0123456789"},
}
RAINBOW_CAT_COM = bytes.fromhex("b0b6e643b8a904e64288e0e642e4610c03e661b81300cd10b800a08ec031ffb003b900faf3aab401cd1674fab400cd1680fc4875f131ffb004b900faf3aaebe6")
VIDEO_WIDTH = 320
VIDEO_HEIGHT = 240
VIDEO_BYTES = VIDEO_WIDTH * VIDEO_HEIGHT * 2
VIDEO_TILE = 16
VIDEO_PACKET_HEADER = 16
VIDEO_KEYFRAME_INTERVAL = 2.0
POLL_HEADER = 16
PCM_CHUNK_BYTES = 4096
VIDEO_SCALING_MODES = ("nearest", "linear-v", "crt-lite")


class GameDefinition:
    def __init__(self, game_id: str, name: str, data_dir: str, executable: str,
                 dosbox_conf: Path, pad_keys: tuple[str, ...],
                 pad_labels: tuple[str, ...], startup_keys: tuple[tuple[float, str], ...] = (),
                 input_profile: str = "", keyboard_actions: dict[str, str] | None = None,
                 pad_actions: tuple[tuple[str, str], ...] = (), pregame: dict[str, list[str]] | None = None):
        self.game_id = game_id
        self.name = name
        self.data_dir = data_dir
        self.executable = executable
        self.dosbox_conf = dosbox_conf
        self.pad_keys = pad_keys
        self.pad_labels = pad_labels
        self.startup_keys = startup_keys
        self.input_profile = input_profile
        self.keyboard_actions = keyboard_actions or {}
        self.pad_actions = pad_actions
        self.pregame = pregame or {}


def ini_values(path: Path) -> dict[str, str]:
    result = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def load_games(root: Path) -> dict[str, GameDefinition]:
    games = {}
    for directory in sorted(root.iterdir() if root.is_dir() else (), key=lambda item: item.name):
        if not directory.is_dir() or directory.name.startswith("_"):
            continue
        values = ini_values(directory / "game.conf")
        if not all(values.get(key) for key in ("name", "data_dir", "exe")):
            continue
        ddr = ini_values(directory / values.get("ddr_file", "ddr.conf"))
        keys, labels = [], []
        for button in range(9):
            key = ddr.get(f"button{button}_key", "").upper()
            key = {"LSHIFT": "SHIFT", "RSHIFT": "SHIFT", "LCTRL": "CTRL", "RCTRL": "CTRL",
                   "LALT": "ALT", "RALT": "ALT"}.get(key, key)
            if key == "-": key = ""
            if key and key not in KEYS: raise ValueError(f"invalid DDR key in {directory.name}")
            keys.append(key); labels.append(ddr.get(f"button{button}_label", "nepoužité"))
        startup_keys = []
        for action in filter(None, values.get("startup_key_sequence", "").split(",")):
            try:
                delay_text, startup_key = action.split(":", 1)
                startup_delay = float(delay_text)
            except ValueError as error:
                raise ValueError(f"invalid startup key sequence in {directory.name}") from error
            startup_key = startup_key.upper()
            if startup_delay < 0 or startup_key not in KEYS:
                raise ValueError(f"invalid startup key sequence in {directory.name}")
            if startup_keys and startup_delay < startup_keys[-1][0]:
                raise ValueError(f"startup key sequence must be ordered in {directory.name}")
            startup_keys.append((startup_delay, startup_key))
        input_profile = ddr.get("input_profile", "")
        keyboard_actions = {key[9:-7]: value for key, value in ddr.items()
                            if key.startswith("keyboard_") and key.endswith("_action") and key[9:-7] in KEYS}
        pad_actions = tuple((ddr.get(f"button{button}_primary_action", ""),
                             ddr.get(f"button{button}_secondary_action", "")) for button in range(9))
        pregame = {name: [line for line in ddr.get("pregame_" + name, "").split("|") if line]
                   for name in ("keyboard", "pad", "both")}
        game_id = directory.name
        games[game_id] = GameDefinition(game_id, values["name"], values["data_dir"], values["exe"],
                                        directory / "dosbox.conf", tuple(keys), tuple(labels),
                                        tuple(startup_keys), input_profile, keyboard_actions, pad_actions, pregame)
    return games


def read_config(path: Path) -> dict[str, str]:
    config = dict(DEFAULTS)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid configuration line: {line!r}")
        key, value = (item.strip() for item in line.split("=", 1))
        if key not in DEFAULTS:
            raise ValueError(f"unknown configuration key: {key}")
        config[key] = value
    return config


def safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or str(path) == ".":
        raise ValueError("file paths must be non-empty, relative POSIX paths")
    return path
