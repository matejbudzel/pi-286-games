import errno
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('disconnect_launcher', ROOT / 'launcher/launcher.py')
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)
import display_monitor


class DisplayTests(unittest.TestCase):
    def test_known_statuses_and_unknown_results(self):
        for text, expected in [('state 0x120002 [HDMI DMT (4) RGB full 4:3]', True),
                               ('state 0x1 [TV is off]', False), ('state 0x0 [unplugged]', False),
                               ('no device', None)]:
            self.assertIs(display_monitor.tvservice_status(text), expected)
        for text, expected in [('power status: on', True), ('power status: standby', False),
                               ('power status: in transition from on to standby', False),
                               ('power status: unknown', None), ('timeout', None)]:
            self.assertIs(display_monitor.cec_status(text), expected)

    def test_failed_probes_do_not_report_disconnection(self):
        monitor = display_monitor.DisplayMonitor()
        monitor.tvservice = 'tvservice'; monitor.cec_client = 'cec-client'
        with patch.object(monitor, 'command', return_value=''):
            self.assertIsNone(monitor.read_status())
        for failure in (FileNotFoundError(), subprocess.TimeoutExpired('tvservice', 3)):
            with patch.object(display_monitor.subprocess, 'run', side_effect=failure):
                self.assertEqual(monitor.command(['tvservice', '-s']), '')

    def test_cec_standby_overrides_forced_hotplug_without_sending_power_commands(self):
        monitor = display_monitor.DisplayMonitor()
        monitor.tvservice = 'tvservice'; monitor.cec_client = 'cec-client'
        with patch.object(monitor, 'command', side_effect=['state 0x1 [HDMI]', 'power status: standby']) as command:
            self.assertIs(monitor.read_status(), False)
            self.assertEqual(command.call_args.args, (['cec-client', '-s', '-d', '1'], 'pow 0\n'))

    def test_monitor_latches_disconnect_and_joins_before_handoff(self):
        monitor = display_monitor.DisplayMonitor()
        monitor.tvservice = 'tvservice'
        with patch.object(monitor, 'read_status', return_value=False):
            with monitor:
                self.assertTrue(monitor.disconnected.wait(1))
            self.assertFalse(monitor.thread.is_alive())

    def test_hdmi_loss_terminates_hung_presenter_and_restores_console(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired('presenter', 2), 0]
        monitor = Mock()
        monitor.__enter__ = Mock(return_value=monitor)
        monitor.__exit__ = Mock(return_value=False)
        monitor.disconnected.wait.return_value = True
        with patch.object(launcher, 'game_running_screen'), \
             patch.object(launcher.sys, 'stdin', Mock(fileno=Mock(return_value=0))), \
             patch.object(launcher.termios, 'tcgetattr', return_value=['raw']), \
             patch.object(launcher.termios, 'tcsetattr') as restore_tty, \
             patch.object(launcher.fcntl, 'ioctl', return_value=b'\x03\0\0\0'), \
             patch.object(launcher, 'restore_console_display') as restore, \
             patch.object(launcher, 'DisplayMonitor', return_value=monitor), \
             patch.object(launcher.subprocess, 'Popen', return_value=process), \
             patch.object(launcher.Path, 'open', unittest.mock.mock_open()):
            result = launcher.run_remote_presenter('Game', {'remote_dosbox_url': 'http://pi',
                'remote_dosbox_token_file': '/token'}, Mock(), '/presenter', 'session')
            self.assertEqual(result, 'panic')
            process.terminate.assert_called_once()
            process.kill.assert_called_once()
            restore.assert_called_once()
            self.assertEqual(restore_tty.call_args.args[2], ['raw'])

    def test_hdmi_return_deletes_remote_session(self):
        backend = Mock()
        backend.start_session.return_value = {'id': 'session'}
        with patch.object(launcher, 'remote_choice', return_value=(backend, '/presenter')), \
             patch.object(launcher, 'run_remote_presenter', return_value='panic'):
            launcher.run_remote_game(launcher.RemoteGame('Game', 'game', {}), {}, None)
            backend.stop_session.assert_called_once_with('session')


class InputTests(unittest.TestCase):
    def test_menu_pad_removal_eof_and_reconnect_initial_events(self):
        for failure in (b'', OSError(errno.ENODEV, 'unplugged')):
            pad = launcher.DancePad()
            pad.fds = [4]; pad.devices = {'/dev/input/js0': 4}; pad.next_scan = 0
            with patch.object(launcher.os, 'read', side_effect=[failure] if isinstance(failure, Exception) else None,
                              return_value=failure if isinstance(failure, bytes) else b''), \
                 patch.object(launcher.os, 'close') as close, patch.object(pad, 'scan') as scan:
                self.assertEqual(pad.buttons(), [])
                self.assertEqual(pad.fds, [])
                close.assert_called_once_with(4)
                scan.assert_called_once()
        pad.fds = [5]; pad.next_scan = float('inf')
        initial = launcher.JS_EVENT.pack(0, 1, 0x81, 8) + launcher.JS_EVENT.pack(0, 1, 0x81, 9)
        actual = launcher.JS_EVENT.pack(0, 1, 1, 2)
        with patch.object(launcher.os, 'read', return_value=initial + actual):
            self.assertEqual(pad.buttons(), [2])

    def test_keyboard_can_be_absent_at_launch_and_reconnected_for_panic(self):
        monitor = launcher.PanicKeyboard()
        with patch.object(monitor, 'scan'):
            monitor.__enter__()  # No physical keyboard is required to launch pi-dance.
        monitor.fds = {'/dev/input/event0': 4}; monitor.next_scan = float('inf')
        with patch.object(launcher.os, 'read', side_effect=OSError(errno.ENODEV, 'unplugged')), \
             patch.object(launcher.os, 'close'):
            self.assertFalse(monitor.pressed())
            self.assertEqual(monitor.fds, {})
        def reconnect(): monitor.fds['/dev/input/event1'] = 5
        monitor.next_scan = 0
        event = monitor.event.pack(0, 0, 1, 59, 1)
        with patch.object(monitor, 'scan', side_effect=reconnect), \
             patch.object(launcher.os, 'read', return_value=event):
            self.assertTrue(monitor.pressed())

    @unittest.skipUnless(shutil.which('cc'), 'C compiler required')
    def test_native_input_disconnect_and_reconnect(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'input-test'
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'streaming/client'),
                            str(ROOT / 'tests/input_devices_harness.c'),
                            str(ROOT / 'streaming/client/presenter_protocol.c'), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=5, capture_output=True)


if __name__ == '__main__': unittest.main()
