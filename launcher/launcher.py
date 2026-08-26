#!/usr/bin/env python3
"""Minimal terminal UI and DOSBox supervisor for pi-286-games."""
import argparse, glob, os, select, shlex, shutil, signal, struct, subprocess, sys, termios, time, tty
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENT = struct.Struct("llHHI")
# Linux input-event key codes for controls useful on a keyboard or dance mat.
KEY_CODES = {"F1": 59, "UP": 103, "DOWN": 108, "LEFT": 105, "RIGHT": 106,
             "SPACE": 57, "ENTER": 28}

@dataclass(frozen=True)
class Game:
    name: str; data_dir: str; command: str; dosbox_conf: Path; mapper_file: Path

def values(path):
    result = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1); result[key.strip()] = value.strip()
    return result

def discover(directory=ROOT / "games"):
    games = []
    for item in directory.iterdir():
        if not item.is_dir() or item.name.startswith("_"): continue
        conf = values(item / "game.conf")
        if all(conf.get(k) for k in ("name", "data_dir", "exe", "dosbox_conf", "mapper_file")):
            games.append(Game(conf["name"], conf["data_dir"], conf["exe"], item / conf["dosbox_conf"], item / conf["mapper_file"]))
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
        return {b"\x03":"CTRL_C", b"\x1b[A":"UP", b"\x1bOA":"UP", b"\x1b[B":"DOWN", b"\x1bOB":"DOWN", b" ":"SPACE", b"\r":"ENTER", b"\x1bOP":"F1"}.get(data, data.decode("utf-8", "ignore").upper())
    @staticmethod
    def draw(lines, color="\x1b[96m"):
        size = shutil.get_terminal_size((80, 24)); out = ["\x1b[2J\x1b[H", "\n" * max(0, (size.lines-len(lines))//2)]
        for text, current in lines:
            out.append((color if current else "\x1b[37m") + " " * max(0, (size.columns-len(text))//2) + ("> " if current else "  ") + text + "\x1b[0m\n")
        sys.stdout.write("".join(out)); sys.stdout.flush()

def error(term, game, detail, confirm):
    Terminal.draw([("Nepodarilo sa spustiť hru", False), (game.name, True), ("", False), (detail, False), ("", False), ("Stlač %s pre návrat" % confirm, False)], "\x1b[91m")
    while True:
        key = term.key()
        if key == "CTRL_C": return False
        if key == confirm: return True

def validate(game, root):
    relative = Path(game.data_dir)
    if relative.is_absolute() or ".." in relative.parts: raise RuntimeError("Neplatný priečinok s dátami.")
    data = (root / relative).resolve()
    if not data.is_dir(): raise RuntimeError("Chýbajú herné dáta.")
    parts = shlex.split(game.command)
    if not parts or Path(parts[0]).is_absolute() or ".." in Path(parts[0]).parts or not (data / parts[0]).is_file(): raise RuntimeError("Chýba spúšťací súbor hry.")
    return data, " ".join([parts[0].replace("/", "\\\\")] + parts[1:])

def run_game(game, config):
    data, command = validate(game, Path(config["game_data_root"]).expanduser())
    if not game.dosbox_conf.is_file() or not game.mapper_file.is_file(): raise RuntimeError("Chýba nastavenie DOSBoxu.")
    dosbox = shutil.which(config.get("dosbox_command", "dosbox"))
    if not dosbox: raise RuntimeError("DOSBox nie je nainštalovaný.")
    generated = game.dosbox_conf.parent / ".launcher-autoexec.conf"
    generated.write_text("[sdl]\nmapperfile=%s\n\n[autoexec]\nmount c \"%s\"\nc:\n%s\nexit\n" % (game.mapper_file, data, command), encoding="utf-8")
    fds = []
    try:
        # An explicit device keeps the deployment deterministic. On a VM the
        # empty default watches readable Linux keyboard event devices instead.
        configured = config.get("panic_device", "")
        devices = [configured] if configured else glob.glob("/dev/input/event*")
        for device in devices:
            try: fds.append(os.open(device, os.O_RDONLY | os.O_NONBLOCK))
            except OSError: pass
        try:
            proc = subprocess.Popen([dosbox, "-conf", str(game.dosbox_conf), "-conf", str(generated)], preexec_fn=os.setsid)
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
        return "ok" if proc.returncode == 0 else "failed"
    finally:
        for fd in fds: os.close(fd)
        generated.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--host-conf", type=Path, default=ROOT / "config" / "host.conf")
    args = parser.parse_args(); config = values(ROOT / "config" / "host.conf.example"); config.update(values(args.host_conf))
    games = discover()
    if not games: print("No valid game definitions found.", file=sys.stderr); return 1
    selected = 0; confirm = config.get("confirm_key", "SPACE").upper()
    with Terminal() as term:
        while True:
            lines = [(g.name, n == selected) for n, g in enumerate(games)] + [("", False), ("Bye bye!", selected == len(games))]
            Terminal.draw(lines, "\x1b[91m" if selected == len(games) else ("\x1b[92m", "\x1b[96m", "\x1b[93m")[sum(games[selected].name.encode()) % 3])
            key = term.key()
            if key == "CTRL_C": return 0
            if key == config.get("up_key", "UP").upper(): selected = (selected - 1) % (len(games) + 1)
            elif key == config.get("down_key", "DOWN").upper(): selected = (selected + 1) % (len(games) + 1)
            elif key == confirm:
                if selected == len(games):
                    try: subprocess.run(["sudo", "-n", "/sbin/shutdown", "-h", "now"], check=True)
                    except (OSError, subprocess.CalledProcessError):
                        if not error(term, Game("Systém", "", "", Path(), Path()), "Vypnutie systému zlyhalo.", confirm): return 0
                else:
                    try:
                        if run_game(games[selected], config) == "failed" and not error(term, games[selected], "DOSBox skončil s chybou.", confirm): return 0
                    except RuntimeError as exc:
                        if not error(term, games[selected], str(exc), confirm): return 0
if __name__ == "__main__": raise SystemExit(main())
