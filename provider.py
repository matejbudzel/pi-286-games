"""DOS streaming provider CLI consumed by pi-games-launcher."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse

from streaming.client.remote_api import RemoteBackend, RemoteProtocolError, RemoteUnavailable

ROOT = Path(__file__).resolve().parent

def values(path):
    result = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1); result[key.strip()] = value.strip()
    return result

def backend(config):
    return RemoteBackend.from_token_file(config["remote_dosbox_url"], Path(config["remote_dosbox_token_file"]).expanduser())

def manifest(config):
    """Fetch and normalize the server catalogue for pi-games-launcher."""
    catalog = backend(config).games(True, True)
    command_prefix = [sys.executable, str(ROOT / "provider.py"), "--config", str(config["_path"]), "run"]
    return {"version": 1, "games": [{"id": item["id"], "title": item["name"], "command": command_prefix + [item["id"]]} for item in catalog["games"]]}

def run(game_id, config):
    remote = backend(config)
    presenter = Path(config.get("remote_dosbox_presenter", "/opt/pi286/stream/bin/pi286-stream-presenter"))
    if not presenter.is_file() or not os.access(str(presenter), os.X_OK): raise RuntimeError("Pi stream klient nie je nainštalovaný")
    transport = config.get("remote_dosbox_transport", "poll").lower()
    if transport not in ("poll", "websocket"): raise RuntimeError("Neplatný transport vzdialeného DOSBoxu.")
    parsed = urllib.parse.urlparse(config["remote_dosbox_url"])
    if parsed.scheme != "http" or not parsed.hostname: raise RuntimeError("Neplatná adresa vzdialeného DOSBoxu.")
    session = remote.start_session(game_id, config.get("video_scaling", "nearest"), transport)
    try:
        # The launcher service supplies the appliance SDL/fbcon and ALSA setup.
        # This provider only owns the DOS stream session and its input protocol.
        return subprocess.call([str(presenter), parsed.hostname, str(parsed.port or 80), str(Path(config["remote_dosbox_token_file"]).expanduser()), session["id"], transport])
    finally:
        try: remote.stop_session(session["id"])
        except (RemoteUnavailable, RemoteProtocolError): pass

def main(argv=None):
    parser = argparse.ArgumentParser(description="pi-286-games launcher provider")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "provider.conf")
    parser.add_argument("action", choices=("manifest", "run")); parser.add_argument("game_id", nargs="?")
    args = parser.parse_args(argv); config = values(ROOT / "config" / "provider.conf.example"); config.update(values(args.config)); config["_path"] = args.config.resolve()
    try:
        if args.action == "manifest": print(json.dumps(manifest(config), ensure_ascii=False)); return 0
        if not args.game_id: parser.error("run requires game_id")
        return run(args.game_id, config)
    except (KeyError, OSError, ValueError, RuntimeError, RemoteUnavailable, RemoteProtocolError) as exc:
        print("pi-286-games: %s" % exc, file=sys.stderr); return 1

if __name__ == "__main__": raise SystemExit(main())
