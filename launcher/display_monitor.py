"""Best-effort legacy Pi HDMI checks, owned only by a remote game session."""
import logging
from pathlib import Path
import re
import shutil
import subprocess
from threading import Event, Thread

LOG = logging.getLogger(__name__)


def tvservice_status(output):
    match = re.search(r"state 0x[0-9a-f]+ \[([^]]+)\]", output, re.I)
    if not match: return None
    mode = match.group(1).upper()
    if "HDMI" in mode or "DVI" in mode: return True
    if "OFF" in mode or "UNPLUGGED" in mode: return False
    return None


def cec_status(output):
    match = re.search(r"power status:\s*([^\r\n]+)", output, re.I)
    if not match: return None
    status = match.group(1).strip().lower()
    if status == "on": return True
    if status in ("standby", "in transition from on to standby"): return False
    return None


class DisplayMonitor:
    def __init__(self, cec=False):
        self.tvservice = shutil.which("tvservice")
        if not self.tvservice and Path("/opt/vc/bin/tvservice").is_file():
            self.tvservice = "/opt/vc/bin/tvservice"
        self.cec_client = shutil.which("cec-client") if cec else None
        self.disconnected = Event()
        self.stop = Event()
        self.thread = None

    @staticmethod
    def command(arguments, input_text=None):
        try:
            result = subprocess.run(arguments, input=input_text, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, timeout=3, check=False)
            return result.stdout if result.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def read_status(self):
        connected = tvservice_status(self.command([self.tvservice, "-s"])) if self.tvservice else None
        if self.cec_client and not self.stop.is_set():
            power = cec_status(self.command([self.cec_client, "-s", "-d", "1"], "pow 0\n"))
            if power is False: return False
            if connected is None: connected = power
        return connected

    def watch(self):
        while not self.stop.is_set():
            try:
                if self.read_status() is False:
                    LOG.info("HDMI disconnected or TV in standby; stopping remote session")
                    self.disconnected.set()
                    return
            except Exception:
                LOG.exception("HDMI status check failed")
            self.stop.wait(2)

    def __enter__(self):
        if self.tvservice or self.cec_client:
            self.thread = Thread(target=self.watch, name="hdmi-status", daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        # Finish any bounded command before a local app can start its own monitor.
        if self.thread: self.thread.join()
