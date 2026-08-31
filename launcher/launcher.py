#!/usr/bin/env python3
"""Minimal terminal UI and DOSBox supervisor for pi-286-games."""
import argparse, fcntl, glob, os, re, select, shlex, shutil, signal, socket, struct, subprocess, sys, tempfile, termios, time, traceback, tty, urllib.error, urllib.parse, urllib.request, zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from streaming.client.remote_api import RemoteBackend, RemoteProtocolError, RemoteUnavailable
EVENT = struct.Struct("llHHI")
JS_EVENT = struct.Struct("IhBB")
PAD_DEVICE_NAME = "WiseGroup.,Ltd X-PAD, Extreme Dance Pad"
JSIOCGNAME = 0x80806A13  # _IOR('j', 0x13, 128), Linux joystick device name
JSIOCGAXES = 0x80016A11
JSIOCGBUTTONS = 0x80016A12
KDSETMODE = 0x4B3A
KD_TEXT = 0x00
# Linux input-event key codes for controls useful on a keyboard or dance mat.
KEY_CODES = {"F1": 59, "UP": 103, "DOWN": 108, "LEFT": 105, "RIGHT": 106,
             "SPACE": 57, "ENTER": 28}
PANIC_KEY = "F1"
# Keep the verified HDMI hardware target, but let ALSA adapt legacy SDL's
# requested sample format/rate instead of requiring an exact hardware match.
HDMI_PCM = "plughw:0,0"
AUDIO_VOLUME_KEY = "audio_volume_percent"
RAINBOW_CAT_LABEL = "Dúhová mačka"
VIDEO_SCALING_MODES = ("nearest", "linear-v", "crt-lite")
LAUNCHER_SPLASH_SECONDS = 4.0
SPLASH_ART = (
    "                                                                       ▄█╗",
    "                                                                       ╚═╝",
    "██╗  ██╗ ██████╗  ██████╗██╗  ██╗ ██████╗ ██╗   ██╗ █████╗ ███╗   ██╗███████╗",
    "██║ ██╔╝██╔═══██╗██╔════╝██║ ██╔╝██╔═══██╗██║   ██║██╔══██╗████╗  ██║██╔════╝",
    "█████╔╝ ██║   ██║██║     █████╔╝ ██║   ██║██║   ██║███████║██╔██╗ ██║█████╗  ",
    "██╔═██╗ ██║   ██║██║     ██╔═██╗ ██║   ██║╚██╗ ██╔╝██╔══██║██║╚██╗██║██╔══╝  ",
    "██║  ██╗╚██████╔╝╚██████╗██║  ██╗╚██████╔╝ ╚████╔╝ ██║  ██║██║ ╚████║███████╗",
    "╚═╝  ╚═╝ ╚═════╝  ╚═════╝╚═╝  ╚═╝ ╚═════╝   ╚═══╝  ╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝",
    "",
    "",
    "██╗  ██╗██████╗ ██╗   ██╗",
    "██║  ██║██╔══██╗╚██╗ ██╔╝",
    "███████║██████╔╝ ╚████╔╝ ",
    "██╔══██║██╔══██╗  ╚██╔╝  ",
    "██║  ██║██║  ██║   ██║   ",
    "╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ",
)
SPLASH_COLORS = ("\x1b[91m", "\x1b[93m", "\x1b[92m", "\x1b[96m", "\x1b[94m", "\x1b[95m")
PAD_ACTIONS = {2: "UP", 1: "DOWN", 0: "LEFT", 3: "RIGHT", 8: "START", 9: "SELECT"}
PAD_LAYOUT = ((6, "HORE-L"), (2, "HORE"), (7, "HORE-P"), (0, "VĽAVO"), (3, "VPRAVO"), (4, "DOLE-L"), (1, "DOLE"), (5, "DOLE-P"))
DOSBOX_KEY_ACTIONS = {"UP": "key_up", "DOWN": "key_down", "LEFT": "key_left", "RIGHT": "key_right", "SPACE": "key_space", "ENTER": "key_enter", "ESC": "key_esc", "LSHIFT": "key_lshift", "LCTRL": "key_lctrl", "A": "key_a", "Z": "key_z"}
KEY_NAMES = {"UP": "ŠÍPKA HORE", "DOWN": "ŠÍPKA DOLE", "LEFT": "ŠÍPKA VĽAVO", "RIGHT": "ŠÍPKA VPRAVO", "SPACE": "MEDZERNÍK", "ENTER": "ENTER", "ESC": "ESC", "LSHIFT": "ĽAVÝ SHIFT", "LCTRL": "ĽAVÝ CTRL", "A": "A", "Z": "Z"}

class InstallationCancelled(Exception):
    pass

class LauncherExit(Exception):
    pass

@dataclass(frozen=True)
class Game:
    name: str; data_dir: str; command: str; dosbox_conf: Path; mapper_file: Path; asset_archive: str = ""; ddr_conf: Path = Path()

def values(path):
    result = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1); result[key.strip()] = value.strip()
    return result

def save_value(path, key, value):
    """Replace one simple host setting while preserving all other lines."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    replacement = "%s=%s" % (key, value)
    for index, line in enumerate(lines):
        if line.strip().startswith(key + "="):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def volume_percent(value):
    try: return max(0, min(100, int(value)))
    except (TypeError, ValueError): return 96

def video_scaling(config):
    """Return the shared display-scaling preference, safely defaulting to nearest."""
    value = config.get("video_scaling", "nearest").lower()
    return value if value in VIDEO_SCALING_MODES else "nearest"

def set_audio_volume(percent):
    """Set the one verified bcm2835 HDMI PCM mixer control."""
    try:
        return subprocess.run(["amixer", "-c", "0", "sset", "PCM", "%d%%" % percent], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0
    except OSError:
        return False

def volume_status(percent):
    filled = max(0, min(10, (percent + 5) // 10))
    return "Zvuk: [%s%s]" % ("#" * filled, "." * (10 - filled))

def is_raspberry_pi(model_path=Path("/proc/device-tree/model")):
    """Return true for a physical Raspberry Pi, where Bye bye powers off."""
    try:
        return model_path.read_text(encoding="utf-8").rstrip("\0").startswith("Raspberry Pi")
    except OSError:
        return False

def network_address():
    """Return the first IPv4 address on Ethernet or Wi-Fi, if available."""
    names = [name for _, name in socket.if_nameindex()]
    names.sort(key=lambda name: (not name.startswith(("eth", "en")), name))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        for name in names:
            if not name.startswith(("eth", "en", "wlan", "wl")): continue
            try:
                reply = fcntl.ioctl(probe.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))
                return socket.inet_ntoa(reply[20:24])
            except OSError:
                pass
    return "offline"

def discover(directory=ROOT / "games"):
    games = []
    for item in directory.iterdir():
        if not item.is_dir() or item.name.startswith("_"): continue
        conf = values(item / "game.conf")
        if all(conf.get(k) for k in ("name", "data_dir", "exe", "dosbox_conf", "mapper_file")):
            archive = conf.get("asset_archive", conf.get("asset_zip", ""))
            games.append(Game(conf["name"], conf["data_dir"], conf["exe"], item / conf["dosbox_conf"], item / conf["mapper_file"], archive, item / conf.get("ddr_file", "ddr.conf")))
    return sorted(games, key=lambda g: g.name.casefold())

def known_dance_pad(name, axes, buttons):
    """Recognise the exact X-PAD, including kernels that alter its USB name."""
    return name == PAD_DEVICE_NAME or (axes == 2 and buttons == 10)

class DancePad:
    """Read only the known DDR pad's Linux joystick button numbers; axes are ignored."""
    def __init__(self): self.fds = []
    def __enter__(self):
        for device in glob.glob("/dev/input/js*"):
            fd = None
            try:
                fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
                name = fcntl.ioctl(fd, JSIOCGNAME, b"\0" * 128).split(b"\0", 1)[0].decode("utf-8", "replace")
                axes = fcntl.ioctl(fd, JSIOCGAXES, b"\0")[0]
                buttons = fcntl.ioctl(fd, JSIOCGBUTTONS, b"\0")[0]
                if known_dance_pad(name, axes, buttons):
                    self.fds.append(fd); fd = None
            except OSError:
                pass
            finally:
                if fd is not None: os.close(fd)
        return self
    def __exit__(self, *_):
        for fd in self.fds: os.close(fd)
    @property
    def available(self): return bool(self.fds)
    def buttons(self):
        pressed = []
        for fd in self.fds:
            try: raw = os.read(fd, JS_EVENT.size * 32)
            except BlockingIOError: continue
            for pos in range(0, len(raw) - JS_EVENT.size + 1, JS_EVENT.size):
                _, value, typ, number = JS_EVENT.unpack_from(raw, pos)
                if typ & 0x7f == 1 and value == 1: pressed.append(number)
        return pressed

def load_ddr_mapping(game):
    """Load one game's fixed physical-pad-to-DOS-key mapping and Slovak labels."""
    if not game.ddr_conf.is_file(): raise RuntimeError("Chýba nastavenie DDR ovládača.")
    raw = values(game.ddr_conf); keys = {}; labels = {}
    for button in range(9):
        key = raw.get("button%d_key" % button, "").upper()
        label = raw.get("button%d_label" % button, "nepoužité")
        if key in ("", "-"): key = ""
        elif key not in DOSBOX_KEY_ACTIONS: raise RuntimeError("Neplatné DDR tlačidlo %d." % button)
        if key and not label: raise RuntimeError("Chýba popis DDR tlačidla %d." % button)
        keys[button], labels[button] = key, label or "nepoužité"
    if "button9_key" in raw: raise RuntimeError("SELECT sa nesmie mapovať do hry.")
    return keys, labels

def ddr_mapper_content(mapper_file, keys):
    content = mapper_file.read_text(encoding="utf-8")
    for button, key in keys.items():
        if not key: continue
        action = DOSBOX_KEY_ACTIONS[key]
        lines = content.splitlines()
        for index, line in enumerate(lines):
            if line.startswith(action + " "):
                lines[index] = line + ' "stick_0 button %d"' % button
                break
        else: raise RuntimeError("DDR kláves %s nie je v DOSBox mapovaní." % key)
        content = "\n".join(lines) + "\n"
    return content

def pad_panic(buttons):
    """SELECT is never handed to DOSBox: it always returns to the launcher."""
    return 9 in buttons

def keyboard_available(devices_path=Path("/proc/bus/input/devices")):
    """Detect a Linux keyboard from input handlers; unknown means keyboard fallback."""
    try:
        return any("Handlers=" in block and "kbd" in block for block in devices_path.read_text(encoding="utf-8").split("\n\n"))
    except OSError:
        return True

class Terminal:
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        if not os.isatty(self.fd): raise RuntimeError("Launcher needs an interactive Linux console.")
        self.old = termios.tcgetattr(self.fd); tty.setraw(self.fd)
        sys.stdout.write("\x1b[?1049h\x1b[?25l"); sys.stdout.flush(); return self
    def __exit__(self, *_):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
        sys.stdout.write("\x1b[?25h\x1b[?1049l"); sys.stdout.flush()
    def key(self, timeout=None):
        if not select.select([self.fd], [], [], timeout)[0]: return None
        data = os.read(self.fd, 8)
        return self.decode_key(data)
    @staticmethod
    def decode_key(data):
        """Normalise the Linux console's cursor-key escape sequences."""
        return {b"\x03":"CTRL_C", b"\x1b":"ESC", b"\x1b[A":"UP", b"\x1bOA":"UP", b"\x1b[B":"DOWN", b"\x1bOB":"DOWN", b"\x1b[C":"RIGHT", b"\x1bOC":"RIGHT", b"\x1b[D":"LEFT", b"\x1bOD":"LEFT", b" ":"SPACE", b"\r":"ENTER", b"\x1bOP":"F1"}.get(data, data.decode("utf-8", "ignore").upper())
    @staticmethod
    def line(text, current, columns):
        prefix, suffix = ("> ", " <") if current and columns >= 4 else ("", "")
        available = max(0, columns - len(prefix) - len(suffix))
        text = text[:available]
        return " " * max(0, (columns - len(prefix) - len(text) - len(suffix)) // 2) + prefix + text + suffix
    @staticmethod
    def draw(lines, color="\x1b[96m", corner="", top_corner=""):
        try: size = os.get_terminal_size(sys.stdout.fileno())
        except OSError: size = shutil.get_terminal_size((80, 24))
        # Raw mode disables the terminal's normal NL-to-CRNL output conversion.
        # Use explicit CRLF so every menu row starts in column zero.
        out = ["\x1b[2J\x1b[H", "\r\n" * max(0, (size.lines-len(lines))//2)]
        for text, current in lines:
            out.append((color if current else "\x1b[37m") + Terminal.line(text, current, size.columns) + "\x1b[0m\r\n")
        if corner:
            out.append("\x1b[%d;%dH\x1b[90m%s\x1b[0m" % (size.lines, max(1, size.columns - len(corner) + 1), corner[:size.columns]))
        if top_corner:
            out.append("\x1b[1;%dH\x1b[90m%s\x1b[0m" % (max(1, size.columns - len(top_corner) + 1), top_corner[:size.columns]))
        sys.stdout.write("".join(out)); sys.stdout.flush()
    @staticmethod
    def splash_lines(columns):
        """Use the full block logo only when it fits a normal 80-column console."""
        return SPLASH_ART if columns >= 80 else ("KOCKOVANÉ HRY",)
    @staticmethod
    def rainbow(text, columns, row):
        left = " " * max(0, (columns - len(text)) // 2)
        if not text: return "\r\n"
        return left + "".join(SPLASH_COLORS[((index + row * 4) * len(SPLASH_COLORS) // max(1, columns)) % len(SPLASH_COLORS)] + character
                               for index, character in enumerate(text)) + "\x1b[0m\r\n"
    def splash(self, seconds=LAUNCHER_SPLASH_SECONDS):
        try: size = os.get_terminal_size(sys.stdout.fileno())
        except OSError: size = shutil.get_terminal_size((80, 24))
        lines = self.splash_lines(size.columns)
        out = ["\x1b[2J\x1b[H", "\r\n" * max(0, (size.lines - len(lines)) // 2)]
        out.extend(self.rainbow(line, size.columns, row) for row, line in enumerate(lines))
        sys.stdout.write("".join(out)); sys.stdout.flush()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            # Discard accidental boot-time input instead of selecting a game.
            self.key(min(.1, deadline - time.monotonic()))

def sound_status(percent=None):
    """Return the appliance audio state without treating it as a video failure."""
    try:
        module_loaded = any(line.startswith("snd_bcm2835 ") for line in Path("/proc/modules").read_text().splitlines())
        devices = list(Path("/dev/snd").glob("*"))
        usable = any(os.access(device, os.R_OK | os.W_OK) for device in devices)
    except OSError:
        return "Zvuk: nejde"
    if not module_loaded or not usable: return "Zvuk: nejde"
    return volume_status(percent) if percent is not None else "Zvuk: ide"

def next_input(term, pad, timeout=.1):
    key = term.key(timeout)
    if key: return key
    for button in pad.buttons():
        action = PAD_ACTIONS.get(button)
        if action: return action
    return None

def error(term, pad, game, detail, confirm):
    Terminal.draw([("Nepodarilo sa spustiť hru", False), (game.name, True), ("", False), (detail, False), ("", False), ("Stlač %s pre návrat" % confirm, False)], "\x1b[91m")
    while True:
        key = next_input(term, pad)
        if key == "CTRL_C": return False
        if key in (confirm, "START"): return True
        if key in ("SELECT", "ESC"): return False

def confirm_shutdown(term, pad, confirm):
    """Require an explicit second action before powering off physical hardware."""
    Terminal.draw([("Naozaj vypnúť Raspberry Pi?", True), ("", False),
                   ("%s / START - vypnúť" % confirm, False),
                   ("ESC / SELECT - späť do menu", False)], "\x1b[91m")
    while True:
        key = next_input(term, pad)
        if key in (confirm, "START"): return True
        if key in ("SELECT", "ESC", "CTRL_C"): return False

def game_running_screen(game, panic):
    """Keep a meaningful console screen visible until DOSBox takes it over."""
    Terminal.draw([("Je spustená hra", False), (game.name, True), ("", False),
                   ("Ukončiť: SELECT alebo %s." % panic, False)], "\x1b[92m")

def pre_game_lines(game, labels, keys=None, has_pad=True, has_keyboard=True):
    by_button = dict(PAD_LAYOUT)
    def panel(button): return "%s: %s" % (by_button[button], labels[button])
    lines = [(game.name, True), ("", False)]
    if has_pad:
        lines.extend([("[ %s ]  [ %s ]  [ %s ]" % (panel(6), panel(2), panel(7)), False),
                      ("", False), ("[ %s ]      TY      [ %s ]" % (panel(0), panel(3)), False),
                      ("", False), ("[ %s ]  [ %s ]  [ %s ]" % (panel(4), panel(1), panel(5)), False),
                      ("", False), ("SELECT: späť do menu", False), ("START: %s" % labels[8], False)])
    if has_keyboard:
        if has_pad: lines.append(("", False))
        lines.append(("Klávesnica:", False))
        for button in range(9):
            key = (keys or {}).get(button, "")
            if key: lines.append(("%s: %s" % (KEY_NAMES[key], labels[button]), False))
        lines.append(("ESC: späť do menu", False))
    lines.extend([("", False), (("SPACE / START - spustiť hru" if has_pad and has_keyboard else "START - spustiť hru" if has_pad else "SPACE - spustiť hru"), True)])
    return lines

def wait_for_game_start(term, pad, game, labels, keys=None, volume=None):
    has_pad = pad.available
    has_keyboard = keyboard_available()
    # A console may not expose /proc input metadata. In that unusual case the
    # launcher still presents its safe keyboard instructions rather than blank UI.
    if not has_pad and not has_keyboard: has_keyboard = True
    Terminal.draw(pre_game_lines(game, labels, keys, has_pad, has_keyboard), "\x1b[93m", top_corner=sound_status(volume))
    while True:
        key = next_input(term, pad)
        if key in ("SPACE", "START", "ENTER"): return True
        if key == "CTRL_C": return "exit"
        if key in ("SELECT", "ESC"): return False

def restore_console_display():
    """Return fbcon to text mode before redrawing the tty launcher UI."""
    try:
        fcntl.ioctl(sys.stdout.fileno(), KDSETMODE, KD_TEXT)
    except OSError:
        pass
    sys.stdout.write("\x1bc")
    sys.stdout.flush()

def install_screen(term, game, title, detail, percent=None):
    lines = [(title, False), (game.name, True), ("", False), (detail, False)]
    if percent is not None:
        percent = max(0, min(100, percent))
        width = 24; filled = width * percent // 100
        lines.extend([("", False), ("[%s%s] %d%%" % ("#" * filled, "-" * (width - filled), percent), False)])
    Terminal.draw(lines, "\x1b[93m")

def wait_for_install_confirmation(term, game, confirm, title, detail, pad=None):
    install_screen(term, game, title, detail)
    while True:
        key = next_input(term, pad) if pad else term.key()
        if key == "CTRL_C": raise LauncherExit()
        if key in ("ESC", "SELECT"): raise InstallationCancelled()
        if key in (confirm, "START"): return

def copy_archive(source, archive, game, term):
    if source.startswith(("http://", "https://")):
        response = urllib.request.urlopen(source, timeout=30)
        total = int(response.headers.get("Content-Length", "0"))
    else:
        path = Path(source).expanduser()
        response = path.open("rb")
        total = path.stat().st_size
    with response, archive.open("wb") as output:
        copied = 0
        while True:
            block = response.read(65536)
            if not block: break
            output.write(block); copied += len(block)
            if term and total: install_screen(term, game, "Inštalujem herné dáta", "Kopírujem archív...", copied * 50 // total)

def install_assets(game, data, term=None, confirm="SPACE", pad=None):
    """Install a ZIP or RAR archive only when the game directory is absent."""
    if data.is_dir(): return
    if not game.asset_archive: raise RuntimeError("Chýbajú herné dáta.")
    if term:
        wait_for_install_confirmation(term, game, confirm, "Chýbajú herné dáta", "Stlač %s pre inštaláciu, Esc pre návrat" % confirm, pad)
        install_screen(term, game, "Inštalujem herné dáta", "Pripravujem archív...", 0)
    try:
        data.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError("Priečinok s hernými dátami sa nedá vytvoriť: %s" % str(exc)) from exc
    with tempfile.TemporaryDirectory(prefix="pi-286-games-", dir=data.parent) as temporary:
        source = game.asset_archive
        source_path = urllib.parse.urlparse(source).path if source.startswith(("http://", "https://")) else source
        archive = Path(temporary) / ("game" + Path(source_path).suffix.lower())
        try:
            copy_archive(source, archive, game, term)
            extracted = Path(temporary) / "extracted"
            if term: install_screen(term, game, "Inštalujem herné dáta", "Rozbaľujem archív...", 55)
            if archive.suffix == ".rar":
                unrar = shutil.which("unrar")
                if not unrar: raise RuntimeError("Pre RAR archív nainštalujte balík unrar.")
                listing = subprocess.run([unrar, "lb", str(archive)], check=True, capture_output=True, text=True).stdout.splitlines()
                if any(Path(name).is_absolute() or ".." in Path(name).parts for name in listing):
                    raise RuntimeError("Archív obsahuje nebezpečnú cestu.")
                extracted.mkdir()
                subprocess.run([unrar, "x", "-idq", "-o-", str(archive), str(extracted)], check=True, capture_output=True)
            else:
                with zipfile.ZipFile(archive) as bundle:
                    for member in bundle.infolist():
                        path = Path(member.filename)
                        if path.is_absolute() or ".." in path.parts or (member.external_attr >> 16) & 0o170000 == 0o120000:
                            raise RuntimeError("Archív obsahuje nebezpečnú cestu.")
                    bundle.extractall(extracted)
            entries = list(extracted.iterdir())
            payload = entries[0] if len(entries) == 1 and entries[0].is_dir() else extracted
            payload.rename(data)
            if term:
                install_screen(term, game, "Herné dáta sú pripravené", "Stlač %s pre spustenie hry" % confirm, 100)
                wait_for_install_confirmation(term, game, confirm, "Herné dáta sú pripravené", "Stlač %s pre spustenie hry" % confirm, pad)
        except (OSError, subprocess.CalledProcessError, urllib.error.URLError, zipfile.BadZipFile) as exc:
            raise RuntimeError("Herné dáta sa nepodarilo nainštalovať: %s" % str(exc)) from exc

def validate(game, root, term=None, confirm="SPACE", pad=None):
    relative = Path(game.data_dir)
    if relative.is_absolute() or ".." in relative.parts: raise RuntimeError("Neplatný priečinok s dátami.")
    data = (root / relative).resolve()
    install_assets(game, data, term, confirm, pad)
    parts = shlex.split(game.command)
    if not parts or Path(parts[0]).is_absolute() or ".." in Path(parts[0]).parts: raise RuntimeError("Neplatný príkaz hry.")
    return data, " ".join([parts[0].replace("/", "\\\\")] + parts[1:])

def dosbox_environment(config, no_sound=False):
    """Build DOSBox's environment from optional host-specific SDL settings."""
    environment = os.environ.copy()
    variables = {
        "dosbox_ld_library_path": "LD_LIBRARY_PATH",
        "dosbox_sdl_videodriver": "SDL_VIDEODRIVER",
        "dosbox_sdl_fbdev": "SDL_FBDEV",
        "dosbox_sdl_fb_broken_modes": "SDL_FB_BROKEN_MODES",
        "dosbox_sdl_fb_pillarbox": "PI286_SDL_FB_PILLARBOX",
        "dosbox_sdl_fb_canvas_color": "PI286_SDL_FB_CANVAS_COLOR",
    }
    for setting, variable in variables.items():
        value = config.get(setting, "")
        if value: environment[variable] = value
    # Canvas colour is an SDL framebuffer self-test diagnostic.  A normal
    # DOSBox launch must create a black physical canvas, which also clears any
    # test pattern left behind by a preceding standalone SDL test.
    environment.pop("PI286_SDL_FB_CANVAS_COLOR", None)
    # This appliance has one physically verified HDMI PCM. SDL 1.2 checks
    # SDL_PATH_DSP before AUDIODEV in some audio paths, so pin both explicitly.
    environment["SDL_AUDIODRIVER"] = "dummy" if no_sound else "alsa"
    environment["AUDIODEV"] = HDMI_PCM
    environment["SDL_PATH_DSP"] = HDMI_PCM
    # On the Pi 1, SDL's timed ALSA wait is less prone to mixer underruns than
    # the select()-based path. The dummy driver used by --no-sound ignores it.
    environment["SDL_DSP_NOSELECT"] = "1"
    return environment

# This is the appliance base config. It is loaded first, so a deliberate
# value in a game's dosbox.conf may override it.
APPLIANCE_DOSBOX_BASE_CONFIG = """[sdl]
fullscreen=true
fulldouble=false
fullfixed=true
fullresolution=640x480
output=surface
usescancodes=false

[render]
frameskip=0
aspect=true
scaler=normal2x

[mixer]
# The Pi 1 is a PC-speaker appliance. Keeping only this low-rate mixer path
# avoids the emulation cost of FM, Sound Blaster, MIDI, and other sound cards.
rate=22050
blocksize=2048
prebuffer=100

[sblaster]
sbtype=none

[speaker]
pcspeaker=true
pcrate=22050
tandy=off
disney=false

[midi]
mpu401=none
mididevice=none
"""

def generated_dosbox_config(mapper_file, data, command, no_sound=False):
    """Compose the final launch config; the appliance base is a separate -conf."""
    sound_config = "\n[mixer]\nnosound=true\n\n[midi]\nmpu401=none\nmididevice=none\n" if no_sound else ""
    return "[sdl]\nmapperfile=%s\n%s\n[autoexec]\nmount c \"%s\"\nc:\n%s\nexit\n" % (mapper_file, sound_config, data, command)

def remote_choice(config):
    mode = config.get("dosbox_backend", "local").lower()
    if mode not in ("local", "auto", "remote"): raise RuntimeError("Neplatné nastavenie DOSBox backendu.")
    if mode == "local": return None
    try:
        presenter = Path(config.get("remote_dosbox_presenter", "/opt/pi286/stream/bin/pi286-stream-presenter"))
        backend = RemoteBackend.from_token_file(config["remote_dosbox_url"], Path(config["remote_dosbox_token_file"]).expanduser())
        backend.status()
        if not presenter.is_file() or not os.access(presenter, os.X_OK): raise RemoteUnavailable("Pi stream klient nie je nainštalovaný")
        return backend, presenter
    except (KeyError, OSError, ValueError, RemoteUnavailable, RemoteProtocolError) as exc:
        if mode == "auto": return None
        raise RuntimeError("Vzdialený DOSBox nie je dostupný: %s" % exc) from exc

def remote_pad_map(keys):
    translate = {"LCTRL": "CTRL", "LSHIFT": "SHIFT"}
    return ",".join(translate.get(keys.get(button, ""), keys.get(button, "")) for button in range(9))

def remote_transport(config):
    transport = config.get("remote_dosbox_transport", "poll").lower()
    if transport not in ("poll", "websocket"):
        raise RuntimeError("Neplatný transport vzdialeného DOSBoxu.")
    return transport

def run_remote_presenter(title, config, backend, presenter, session_id, ddr_keys=None, transport="poll"):
    """Show one remote session through the Pi's isolated SDL fbcon client."""
    parsed = urllib.parse.urlparse(config["remote_dosbox_url"])
    if not parsed.hostname or parsed.scheme != "http":
        raise RuntimeError("Neplatná adresa vzdialeného DOSBoxu.")
    game_running_screen(Game(title, "", "", Path(), Path()), PANIC_KEY)
    environment = os.environ.copy()
    environment.update(dosbox_environment(config))
    log_path = Path("/tmp/pi286-stream-presenter.log")
    with log_path.open("wb") as log:
        token_file = str(Path(config["remote_dosbox_token_file"]).expanduser())
        result = subprocess.run([str(presenter), parsed.hostname, str(parsed.port or 80), token_file, session_id,
                                 remote_pad_map(ddr_keys or {}), transport], stdout=log, stderr=subprocess.STDOUT, env=environment, check=False)
        log.write(("presenter exit status: %d\n" % result.returncode).encode())
    restore_console_display()
    return "panic" if result.returncode == 0 else "failed"

def run_remote_game(game, config, term, data, ddr_keys):
    selected = remote_choice(config)
    if not selected: return None
    backend, presenter = selected
    transport = remote_transport(config)
    def progress(done, total, name):
        percent = 100 if not total else done * 100 // total
        install_screen(term, game, "Pripravujem vzdialenú hru", "Nahrávam herné dáta " + name, percent)
    install_screen(term, game, "Pripravujem vzdialenú hru", "Kontrolujem herné dáta...", 0)
    files, _ = backend.sync_directory(data, progress)
    executable = backend.executable_in_manifest(shlex.split(game.command)[0], files)
    session = backend.start_session(re.sub(r"[^a-z0-9_-]", "-", game.data_dir.lower()), executable, files,
                                    video_scaling(config), transport)
    try:
        return run_remote_presenter(game.name, config, backend, presenter, session["id"], ddr_keys, transport)
    finally:
        try: backend.stop_session(session["id"])
        except (RemoteUnavailable, RemoteProtocolError): pass

def run_rainbow_cat(config):
    """Run the remote-only asset-free transport diagnostic from the menu."""
    selected = remote_choice(config)
    if not selected:
        raise RuntimeError("Vzdialené spojenie nie je dostupné.")
    backend, presenter = selected
    transport = remote_transport(config)
    session = backend.start_rainbow_cat(video_scaling(config), transport)
    try:
        return run_remote_presenter(RAINBOW_CAT_LABEL, config, backend, presenter, session["id"], transport=transport)
    finally:
        try: backend.stop_session(session["id"])
        except (RemoteUnavailable, RemoteProtocolError): pass

def effective_dosbox_config(game_config, mapper_file, data, command, no_sound=False):
    """Return the ordered config text DOSBox receives for diagnostics/tests."""
    return "%s\n%s\n%s" % (APPLIANCE_DOSBOX_BASE_CONFIG, game_config.read_text(encoding="utf-8"), generated_dosbox_config(mapper_file, data, command, no_sound))

def write_dosbox_replay(dosbox, base_conf, game_conf, generated_conf, environment):
    """Keep a runnable copy of the precise appliance launch beside the log."""
    replay = Path("/tmp/pi-286-games-dosbox-command.sh")
    variables = ("LD_LIBRARY_PATH", "SDL_VIDEODRIVER", "SDL_FBDEV", "SDL_FB_BROKEN_MODES", "PI286_SDL_FB_PILLARBOX", "PI286_SDL_FB_CANVAS_COLOR", "SDL_AUDIODRIVER", "AUDIODEV", "SDL_PATH_DSP", "SDL_DSP_NOSELECT")
    command = ["env"] + ["%s=%s" % (name, environment[name]) for name in variables if name in environment]
    command += [dosbox, "-conf", str(base_conf), "-conf", str(game_conf), "-conf", str(generated_conf)]
    replay.write_text("#!/bin/sh\n# Generated by pi-286-games; replays the last DOSBox launch.\nexec %s > /tmp/pi-286-games-dosbox.log 2>&1\n" % shlex.join(command), encoding="utf-8")
    replay.chmod(0o700)
    return replay

def run_game(game, config, term, pad, ddr_keys, no_sound=False):
    try: data, command = validate(game, Path(config["game_data_root"]).expanduser(), term, config.get("confirm_key", "SPACE").upper(), pad)
    except InstallationCancelled: return "cancelled"
    except LauncherExit: return "exit"
    remote = run_remote_game(game, config, term, data, ddr_keys)
    if remote is not None: return remote
    if not game.dosbox_conf.is_file() or not game.mapper_file.is_file(): raise RuntimeError("Chýba nastavenie DOSBoxu.")
    dosbox = shutil.which(config.get("dosbox_command", "dosbox"))
    if not dosbox: raise RuntimeError("DOSBox nie je nainštalovaný.")
    generated = game.dosbox_conf.parent / ".launcher-autoexec.conf"
    base_copy = Path("/tmp/pi-286-games-dosbox-base.conf")
    generated_mapper = Path("/tmp/pi-286-games-dosbox-mapper.txt")
    generated_mapper.write_text(ddr_mapper_content(game.mapper_file, ddr_keys), encoding="utf-8")
    generated_content = generated_dosbox_config(generated_mapper, data, command, no_sound)
    base_copy.write_text(APPLIANCE_DOSBOX_BASE_CONFIG, encoding="utf-8")
    generated.write_text(generated_content, encoding="utf-8")
    generated_copy = Path("/tmp/pi-286-games-dosbox.conf")
    generated_copy.write_text(generated_content, encoding="utf-8")
    fds = []
    log = None
    log_path = Path("/tmp/pi-286-games-dosbox.log")
    try:
        # F1 is always available alongside dance-pad SELECT while DOSBox owns
        # the display. Watch readable keyboard event devices without host setup.
        for device in glob.glob("/dev/input/event*"):
            try: fds.append(os.open(device, os.O_RDONLY | os.O_NONBLOCK))
            except OSError: pass
        try:
            log = log_path.open("wb")
            environment = dosbox_environment(config, no_sound)
            write_dosbox_replay(dosbox, base_copy, game.dosbox_conf, generated_copy, environment)
            game_running_screen(game, PANIC_KEY)
            # Classic SDL fbcon requires DOSBox to remain in tty1's foreground
            # process group. DOSBox does not need a separate session/group.
            proc = subprocess.Popen([dosbox, "-conf", str(base_copy), "-conf", str(game.dosbox_conf), "-conf", str(generated)], stdout=log, stderr=subprocess.STDOUT, env=environment)
        except OSError as exc:
            raise RuntimeError("DOSBox sa nedá spustiť: %s" % exc.strerror) from exc
        wanted = KEY_CODES[PANIC_KEY]
        panicked = False
        while proc.poll() is None:
            if pad_panic(pad.buttons()):
                proc.terminate()
                try: proc.wait(timeout=3)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                panicked = True
                break
            for fd in fds:
                try: raw = os.read(fd, EVENT.size * 8)
                except BlockingIOError: continue
                for pos in range(0, len(raw) - EVENT.size + 1, EVENT.size):
                    _, _, typ, code, value = EVENT.unpack_from(raw, pos)
                    if typ == 1 and code == wanted and value == 1:
                        proc.terminate()
                        try: proc.wait(timeout=3)
                        except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                        panicked = True
                        break
            if panicked: break
            time.sleep(.05)
        restore_console_display()
        if panicked: return "panic"
        return "ok" if proc.returncode == 0 else "failed"
    finally:
        for fd in fds: os.close(fd)
        if log: log.close()
        generated.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--host-conf", type=Path, default=ROOT / "config" / "host.conf"); parser.add_argument("--no-sound", action="store_true", help="disable DOSBox and SDL audio")
    args = parser.parse_args(); config = values(ROOT / "config" / "host.conf.example"); config.update(values(args.host_conf))
    games = discover()
    if not games: print("No valid game definitions found.", file=sys.stderr); return 1
    selected = 0; confirm = config.get("confirm_key", "SPACE").upper(); corner = ""; redraw = True
    diagnostic_index = len(games); bye_index = diagnostic_index + 1
    volume = volume_percent(config.get(AUDIO_VOLUME_KEY, "96")); set_audio_volume(volume)
    restart_hint = False
    with Terminal() as term, DancePad() as pad:
        term.splash()
        while True:
            if redraw:
                lines = [(g.name, n == selected) for n, g in enumerate(games)] + [("", False), (RAINBOW_CAT_LABEL, selected == diagnostic_index), ("", False), ("Bye bye!", selected == bye_index)]
                color = "\x1b[91m" if selected == bye_index else "\x1b[95m" if selected == diagnostic_index else ("\x1b[92m", "\x1b[96m", "\x1b[93m")[sum(games[selected].name.encode()) % 3]
                Terminal.draw(lines, color, corner, sound_status(volume))
                redraw = False
            key = next_input(term, pad)
            if key is None: continue
            if key == "CTRL_C": return 0
            redraw = True
            if key == PANIC_KEY: corner = network_address()
            elif key == "SELECT": continue
            elif key == config.get("up_key", "UP").upper(): selected = (selected - 1) % (len(games) + 2)
            elif key == config.get("down_key", "DOWN").upper(): selected = (selected + 1) % (len(games) + 2)
            elif key in ("LEFT", "RIGHT"):
                changed = max(0, min(100, volume + (10 if key == "RIGHT" else -10)))
                if changed != volume and set_audio_volume(changed):
                    volume = changed; config[AUDIO_VOLUME_KEY] = str(volume); save_value(args.host_conf, AUDIO_VOLUME_KEY, volume)
            elif key in (confirm, "START"):
                if selected == bye_index:
                    if not is_raspberry_pi():
                        restart_hint = True
                        break
                    if not confirm_shutdown(term, pad, confirm):
                        redraw = True
                        continue
                    try: subprocess.run(["sudo", "-n", "/sbin/shutdown", "-h", "now"], check=True)
                    except (OSError, subprocess.CalledProcessError):
                        if not error(term, pad, Game("Systém", "", "", Path(), Path()), "Vypnutie systému zlyhalo.", confirm): return 0
                elif selected == diagnostic_index:
                    try:
                        result = run_rainbow_cat(config)
                        if result == "panic": corner = network_address()
                        if result == "failed" and not error(term, pad, Game(RAINBOW_CAT_LABEL, "", "", Path(), Path()), "Vzdialený prehrávač skončil s chybou.", confirm): return 0
                    except RuntimeError as exc:
                        if not error(term, pad, Game(RAINBOW_CAT_LABEL, "", "", Path(), Path()), str(exc), confirm): return 0
                    except Exception:
                        Path("/tmp/pi286-stream-launcher-error.log").write_text(traceback.format_exc(), encoding="utf-8")
                        if not error(term, pad, Game(RAINBOW_CAT_LABEL, "", "", Path(), Path()), "Vzdialený test zlyhal. Detaily sú v /tmp/pi286-stream-launcher-error.log.", confirm): return 0
                else:
                    try:
                        ddr_keys, ddr_labels = load_ddr_mapping(games[selected])
                        ready = wait_for_game_start(term, pad, games[selected], ddr_labels, ddr_keys, volume)
                        if ready == "exit": return 0
                        if not ready: continue
                        result = run_game(games[selected], config, term, pad, ddr_keys, args.no_sound)
                        if result == "exit": return 0
                        if result == "panic": corner = network_address()
                        if result == "failed" and not error(term, pad, games[selected], "DOSBox skončil s chybou.", confirm): return 0
                    except RuntimeError as exc:
                        if not error(term, pad, games[selected], str(exc), confirm): return 0
    if restart_hint:
        print("\nLauncher skončil. Znova ho spustíš príkazom:\n  pg-start\n")
    return 0
if __name__ == "__main__": raise SystemExit(main())
