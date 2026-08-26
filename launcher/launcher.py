#!/usr/bin/env python3
"""Minimal terminal UI and DOSBox supervisor for pi-286-games."""
import argparse, fcntl, glob, os, select, shlex, shutil, signal, socket, struct, subprocess, sys, tempfile, termios, time, tty, urllib.error, urllib.parse, urllib.request, zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENT = struct.Struct("llHHI")
# Linux input-event key codes for controls useful on a keyboard or dance mat.
KEY_CODES = {"F1": 59, "UP": 103, "DOWN": 108, "LEFT": 105, "RIGHT": 106,
             "SPACE": 57, "ENTER": 28}

class InstallationCancelled(Exception):
    pass

@dataclass(frozen=True)
class Game:
    name: str; data_dir: str; command: str; dosbox_conf: Path; mapper_file: Path; asset_archive: str = ""

def values(path):
    result = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1); result[key.strip()] = value.strip()
    return result

def enabled(value):
    return value.strip().lower() in ("1", "true", "yes", "on")

def stop_boot_splash():
    systemctl = shutil.which("systemctl")
    if systemctl:
        subprocess.run(["sudo", "-n", systemctl, "stop", "pi-286-games-splash.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

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
            games.append(Game(conf["name"], conf["data_dir"], conf["exe"], item / conf["dosbox_conf"], item / conf["mapper_file"], archive))
    return sorted(games, key=lambda g: g.name.casefold())

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
        return {b"\x03":"CTRL_C", b"\x1b":"ESC", b"\x1b[A":"UP", b"\x1bOA":"UP", b"\x1b[B":"DOWN", b"\x1bOB":"DOWN", b" ":"SPACE", b"\r":"ENTER", b"\x1bOP":"F1"}.get(data, data.decode("utf-8", "ignore").upper())
    @staticmethod
    def line(text, current, columns):
        prefix = ("> " if current else "  ") if columns >= 2 else ""
        available = max(0, columns - len(prefix))
        text = text[:available]
        return " " * max(0, (available - len(text)) // 2) + prefix + text
    @staticmethod
    def draw(lines, color="\x1b[96m", corner=""):
        try: size = os.get_terminal_size(sys.stdout.fileno())
        except OSError: size = shutil.get_terminal_size((80, 24))
        # Raw mode disables the terminal's normal NL-to-CRNL output conversion.
        # Use explicit CRLF so every menu row starts in column zero.
        out = ["\x1b[2J\x1b[H", "\r\n" * max(0, (size.lines-len(lines))//2)]
        for text, current in lines:
            out.append((color if current else "\x1b[37m") + Terminal.line(text, current, size.columns) + "\x1b[0m\r\n")
        if corner:
            out.append("\x1b[%d;%dH\x1b[90m%s\x1b[0m" % (size.lines, max(1, size.columns - len(corner) + 1), corner[:size.columns]))
        sys.stdout.write("".join(out)); sys.stdout.flush()

def error(term, game, detail, confirm):
    Terminal.draw([("Nepodarilo sa spustiť hru", False), (game.name, True), ("", False), (detail, False), ("", False), ("Stlač %s pre návrat" % confirm, False)], "\x1b[91m")
    while True:
        key = term.key()
        if key == "CTRL_C": return False
        if key == confirm: return True

def install_screen(term, game, title, detail, percent=None):
    lines = [(title, False), (game.name, True), ("", False), (detail, False)]
    if percent is not None:
        percent = max(0, min(100, percent))
        width = 24; filled = width * percent // 100
        lines.extend([("", False), ("[%s%s] %d%%" % ("#" * filled, "-" * (width - filled), percent), False)])
    Terminal.draw(lines, "\x1b[93m")

def wait_for_install_confirmation(term, game, confirm, title, detail):
    install_screen(term, game, title, detail)
    while True:
        key = term.key()
        if key in ("ESC", "CTRL_C"): raise InstallationCancelled()
        if key == confirm: return

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

def install_assets(game, data, term=None, confirm="SPACE"):
    """Install a ZIP or RAR archive only when the game directory is absent."""
    if data.is_dir(): return
    if not game.asset_archive: raise RuntimeError("Chýbajú herné dáta.")
    if term:
        wait_for_install_confirmation(term, game, confirm, "Chýbajú herné dáta", "Stlač %s pre inštaláciu, Esc pre návrat" % confirm)
        install_screen(term, game, "Inštalujem herné dáta", "Pripravujem archív...", 0)
    data.parent.mkdir(parents=True, exist_ok=True)
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
            extracted.rename(data)
            if term:
                install_screen(term, game, "Herné dáta sú pripravené", "Stlač %s pre spustenie hry" % confirm, 100)
                wait_for_install_confirmation(term, game, confirm, "Herné dáta sú pripravené", "Stlač %s pre spustenie hry" % confirm)
        except (OSError, subprocess.CalledProcessError, urllib.error.URLError, zipfile.BadZipFile) as exc:
            raise RuntimeError("Herné dáta sa nepodarilo nainštalovať: %s" % str(exc)) from exc

def validate(game, root, term=None, confirm="SPACE"):
    relative = Path(game.data_dir)
    if relative.is_absolute() or ".." in relative.parts: raise RuntimeError("Neplatný priečinok s dátami.")
    data = (root / relative).resolve()
    install_assets(game, data, term, confirm)
    parts = shlex.split(game.command)
    if not parts or Path(parts[0]).is_absolute() or ".." in Path(parts[0]).parts: raise RuntimeError("Neplatný príkaz hry.")
    return data, " ".join([parts[0].replace("/", "\\\\")] + parts[1:])

def run_game(game, config, term):
    try: data, command = validate(game, Path(config["game_data_root"]).expanduser(), term, config.get("confirm_key", "SPACE").upper())
    except InstallationCancelled: return "cancelled"
    if not game.dosbox_conf.is_file() or not game.mapper_file.is_file(): raise RuntimeError("Chýba nastavenie DOSBoxu.")
    dosbox = shutil.which(config.get("dosbox_command", "dosbox"))
    if not dosbox: raise RuntimeError("DOSBox nie je nainštalovaný.")
    generated = game.dosbox_conf.parent / ".launcher-autoexec.conf"
    generated.write_text("[sdl]\nmapperfile=%s\n\n[autoexec]\nmount c \"%s\"\nc:\n%s\nexit\n" % (game.mapper_file, data, command), encoding="utf-8")
    fds = []
    log = None
    log_path = Path("/tmp/pi-286-games-dosbox.log")
    try:
        # An explicit device keeps the deployment deterministic. On a VM the
        # empty default watches readable Linux keyboard event devices instead.
        configured = config.get("panic_device", "")
        devices = [configured] if configured else glob.glob("/dev/input/event*")
        for device in devices:
            try: fds.append(os.open(device, os.O_RDONLY | os.O_NONBLOCK))
            except OSError: pass
        try:
            log = log_path.open("wb")
            proc = subprocess.Popen([dosbox, "-conf", str(game.dosbox_conf), "-conf", str(generated)], preexec_fn=os.setsid, stdout=log, stderr=subprocess.STDOUT)
        except OSError as exc:
            raise RuntimeError("DOSBox sa nedá spustiť: %s" % exc.strerror) from exc
        wanted = KEY_CODES.get(config.get("panic_key", "F1").upper())
        while proc.poll() is None:
            for fd in fds:
                try: raw = os.read(fd, EVENT.size * 8)
                except BlockingIOError: continue
                for pos in range(0, len(raw) - EVENT.size + 1, EVENT.size):
                    _, _, typ, code, value = EVENT.unpack_from(raw, pos)
                    if typ == 1 and code == wanted and value == 1:
                        os.killpg(proc.pid, signal.SIGTERM)
                        try: proc.wait(timeout=3)
                        except subprocess.TimeoutExpired: os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                        return "panic"
            time.sleep(.05)
        if proc.returncode == 0:
            log_path.unlink(missing_ok=True)
            return "ok"
        return "failed"
    finally:
        for fd in fds: os.close(fd)
        if log: log.close()
        generated.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--host-conf", type=Path, default=ROOT / "config" / "host.conf")
    args = parser.parse_args(); config = values(ROOT / "config" / "host.conf.example"); config.update(values(args.host_conf))
    games = discover()
    if not games: print("No valid game definitions found.", file=sys.stderr); return 1
    selected = 0; confirm = config.get("confirm_key", "SPACE").upper(); corner = ""
    stop_boot_splash()
    with Terminal() as term:
        while True:
            lines = [(g.name, n == selected) for n, g in enumerate(games)] + [("", False), ("Bye bye!", selected == len(games))]
            Terminal.draw(lines, "\x1b[91m" if selected == len(games) else ("\x1b[92m", "\x1b[96m", "\x1b[93m")[sum(games[selected].name.encode()) % 3], corner)
            key = term.key()
            if key == "CTRL_C": return 0
            if key == config.get("panic_key", "F1").upper(): corner = network_address()
            elif key == config.get("up_key", "UP").upper(): selected = (selected - 1) % (len(games) + 1)
            elif key == config.get("down_key", "DOWN").upper(): selected = (selected + 1) % (len(games) + 1)
            elif key == confirm:
                if selected == len(games):
                    if not enabled(config.get("shutdown_on_bye_bye", "false")): return 0
                    try: subprocess.run(["sudo", "-n", "/sbin/shutdown", "-h", "now"], check=True)
                    except (OSError, subprocess.CalledProcessError):
                        if not error(term, Game("Systém", "", "", Path(), Path()), "Vypnutie systému zlyhalo.", confirm): return 0
                else:
                    try:
                        result = run_game(games[selected], config, term)
                        if result == "panic": corner = network_address()
                        if result == "failed" and not error(term, games[selected], "DOSBox skončil s chybou.", confirm): return 0
                    except RuntimeError as exc:
                        if not error(term, games[selected], str(exc), confirm): return 0
if __name__ == "__main__": raise SystemExit(main())
