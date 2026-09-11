import importlib.util
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("pi286_provider", ROOT / "provider.py")
provider = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provider)


class ProviderTests(unittest.TestCase):
    def test_manifest_fetches_the_remote_catalogue_and_emits_launcher_schema(self):
        config = {"remote_dosbox_url": "http://stream.test", "remote_dosbox_token_file": "token", "_path": ROOT / "config/provider.conf"}
        remote = type("Remote", (), {"games": lambda self, keyboard, dance_pad: {"games": [{"id": "pop", "name": "Prince of Persia"}]}})()
        with patch.object(provider, "backend", return_value=remote):
            document = provider.manifest(config)
        self.assertEqual(document["version"], 1)
        self.assertEqual(document["games"][0]["id"], "pop")
        self.assertEqual(document["games"][0]["title"], "Prince of Persia")
        self.assertEqual(document["games"][0]["command"][-2:], ["run", "pop"])

    def test_manifest_cli_prints_only_json(self):
        with patch.object(provider, "manifest", return_value={"version": 1, "games": []}):
            with patch.object(provider, "values", return_value={}):
                from io import StringIO
                with patch("sys.stdout", new_callable=StringIO) as output:
                    self.assertEqual(provider.main(["manifest"]), 0)
        self.assertEqual(json.loads(output.getvalue()), {"version": 1, "games": []})

    def test_run_inherits_the_launchers_appliance_environment(self):
        config = {"remote_dosbox_url": "http://stream.test", "remote_dosbox_token_file": "/tmp/token", "remote_dosbox_presenter": str(ROOT / "bin/pi-286-games"), "remote_dosbox_transport": "websocket"}
        remote = type("Remote", (), {"start_session": lambda *args: {"id": "session"}, "stop_session": lambda *args: None})()
        with patch.object(provider, "backend", return_value=remote), patch.object(provider.os, "access", return_value=True), patch.object(provider.subprocess, "call", return_value=0) as call:
            self.assertEqual(provider.run("pop", config), 0)
        self.assertNotIn("env", call.call_args.kwargs)

    def test_command_resolves_an_installed_symlink(self):
        with TemporaryDirectory() as directory:
            command = Path(directory) / "pi-286-games"
            command.symlink_to(ROOT / "bin/pi-286-games")
            result = subprocess.run([str(command), "--help"], text=True, stdout=subprocess.PIPE, check=True)
        self.assertIn("pi-286-games launcher provider", result.stdout)
