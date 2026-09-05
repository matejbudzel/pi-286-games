import importlib.util
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('local_launcher', Path(__file__).parents[1] / 'launcher/launcher.py')
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class LocalAppsTests(unittest.TestCase):
    def test_mixed_catalog_and_offline_local_entries(self):
        with tempfile.TemporaryDirectory() as root:
            host = Path(root) / 'host.conf'
            folder = Path(root) / 'local-apps'
            folder.mkdir()
            (folder / 'dance.conf').write_text('name=Dance\ncommand=./dance "two words"\nworking_dir=../dance\n')
            backend = Mock()
            backend.games.return_value = {'games': [{'name': 'Alpha', 'id': 'server-id', 'pre_game': {}}]}
            config = {'remote_dosbox_url': 'http://server', 'remote_dosbox_token_file': '/token'}
            with patch.object(launcher.RemoteBackend, 'from_token_file', return_value=backend):
                games, warning = launcher.menu_games(config, host, True, False)
                self.assertEqual([g.name for g in games], ['Alpha', 'Dance'])
                self.assertEqual(games[0].game_id, 'server-id')
                self.assertEqual(games[1].working_dir, Path(root) / 'dance')
                self.assertEqual(warning, '')
                backend.games.assert_called_once_with(True, False)
                backend.games.side_effect = launcher.RemoteUnavailable('offline')
                games, warning = launcher.menu_games(config, host, True, False)
                self.assertEqual([g.name for g in games], ['Dance'])
                self.assertTrue(warning)

    def test_invalid_entry_is_reported_and_missing_directory_is_empty(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(launcher.discover_local(Path(root) / 'absent'), [])
            (Path(root) / 'invalid.conf').write_text('name=No command\n')
            with self.assertRaisesRegex(RuntimeError, 'príkaz'):
                launcher.discover_local(Path(root))

    def test_panic_monitor_only_recognizes_f1_press(self):
        monitor = launcher.PanicKeyboard()
        monitor.fds = {'keyboard': 5}
        monitor.next_scan = float('inf')
        for kind, code, value, expected in ((1, 59, 1, True), (1, 59, 0, False),
                                           (1, 59, 2, False), (1, 1, 1, False), (3, 59, 1, False)):
            raw = monitor.event.pack(0, 0, kind, code, value)
            with patch.object(launcher.os, 'read', return_value=raw):
                self.assertEqual(monitor.pressed(), expected)

    def test_exit_crash_panic_and_spawn_failure_restore_console(self):
        for outcome in ('exit', 'crash', 'panic', 'spawn-failure'):
            with self.subTest(outcome=outcome):
                term, pad, process = Mock(fd=0, old=['cooked']), Mock(), Mock(pid=123)
                process.poll.return_value = None if outcome == 'panic' else 0
                process.returncode = 1 if outcome == 'crash' else 0
                panic = Mock()
                panic.__enter__ = Mock(return_value=Mock(pressed=Mock(return_value=True)))
                panic.__exit__ = Mock(return_value=False)
                pad.__enter__ = Mock()
                pad.__exit__ = Mock()
                with patch.object(launcher, 'PanicKeyboard', return_value=panic), \
                     patch.object(launcher.termios, 'tcgetattr', return_value=['raw']), \
                     patch.object(launcher.termios, 'tcsetattr') as attributes, \
                     patch.object(launcher.os, 'tcgetpgrp', return_value=42), \
                     patch.object(launcher.fcntl, 'ioctl', return_value=struct.pack('i', 3)), \
                     patch.object(launcher, 'foreground') as foreground, \
                     patch.object(launcher, 'stop_local_process') as stop, \
                     patch.object(launcher, 'restore_console_display') as restore, \
                     patch.object(launcher.subprocess, 'Popen', return_value=process) as spawn:
                    if outcome == 'spawn-failure': spawn.side_effect = FileNotFoundError('missing')
                    app = launcher.LocalApp('Dance', './dance "two words"', Path('/apps'))
                    if outcome == 'spawn-failure':
                        with self.assertRaisesRegex(RuntimeError, 'nepodarilo'):
                            launcher.run_local_app(app, term, pad)
                        stop.assert_not_called()
                    else:
                        self.assertEqual(launcher.run_local_app(app, term, pad), 'failed' if outcome == 'crash' else 'panic')
                        stop.assert_called_once_with(process)
                    self.assertEqual(spawn.call_args.args[0], ['./dance', 'two words'])
                    term.key.assert_not_called()
                    pad.buttons.assert_not_called()
                    foreground.assert_called_once_with(0, 42)
                    self.assertEqual(attributes.call_args.args[2], ['raw'])
                    restore.assert_called_once()

    def test_process_ignoring_term_is_killed_and_reaped(self):
        with tempfile.TemporaryDirectory() as root:
            ready = Path(root) / 'ready'
            child = subprocess.Popen([sys.executable, '-c',
                'import signal,time,pathlib; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                'pathlib.Path(%r).touch(); time.sleep(30)' % str(ready)], start_new_session=True)
            try:
                import time
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline: time.sleep(.01)
                self.assertTrue(ready.exists())
                launcher.stop_local_process(child)
                self.assertEqual(child.returncode, -signal.SIGKILL)
            finally:
                if child.poll() is None: child.kill(); child.wait()

    def test_app_owns_foreground_terminal_and_receives_input(self):
        import pty
        import time
        import termios
        import tty
        with tempfile.TemporaryDirectory() as root:
            result = Path(root) / 'result'
            script = Path(root) / 'app.py'
            script.write_text('import os,sys,pathlib\n'
                              'assert os.tcgetpgrp(0) == os.getpgrp()\n'
                              'pathlib.Path(sys.argv[1]).write_text(input())\n')
            pid, master = pty.fork()
            if pid == 0:
                try:
                    term = Mock(fd=0, old=termios.tcgetattr(0))
                    tty.setraw(0)
                    pad = launcher.DancePad()
                    # PTYs have job control but no Linux-console keyboard mode.
                    with patch.object(launcher.fcntl, 'ioctl', return_value=struct.pack('i', 3)), \
                         patch.object(launcher, 'PanicKeyboard') as monitor:
                        monitor.return_value.__enter__.return_value.pressed.return_value = False
                        app = launcher.LocalApp('Input', '%s %s %s' % (sys.executable, script, result), Path(root))
                        status = launcher.run_local_app(app, term, pad)
                        os._exit(0 if status == 'panic' else 1)
                except BaseException:
                    os._exit(2)
            try:
                deadline = time.monotonic() + 5
                # Resend until the child's startup input flush has completed.
                while not result.exists() and time.monotonic() < deadline:
                    os.write(master, b'hello\n')
                    time.sleep(.05)
                self.assertTrue(result.exists())
                self.assertEqual(result.read_text(), 'hello')
                _, status = os.waitpid(pid, 0)
                pid = None
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
            finally:
                os.close(master)
                if pid is not None:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)

    def test_remote_start_uses_catalog_id_and_stops_session(self):
        backend = Mock()
        backend.start_session.return_value = {'id': 'session'}
        with patch.object(launcher, 'remote_choice', return_value=(backend, Path('/presenter'))), \
             patch.object(launcher, 'run_remote_presenter', return_value='panic'):
            game = launcher.RemoteGame('Title', 'catalog-id', {})
            self.assertEqual(launcher.run_game(game, {}, None, None, None), 'panic')
            backend.start_session.assert_called_once_with('catalog-id', 'nearest', 'poll')
            backend.stop_session.assert_called_once_with('session')


if __name__ == '__main__': unittest.main()
