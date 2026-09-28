import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("gx_tui_probe", ROOT / "scripts/gx_tui_probe.py")
tui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tui)


class TuiProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gx-tui-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_response_marker_must_be_a_complete_output_line(self):
        marker = "GX-RESULT-abc:中文"
        self.assertTrue(tui.response_line("prompt\n" + marker + "\nprompt", marker))
        self.assertFalse(tui.response_line("prompt> printf '" + marker + "'", marker))
        self.assertFalse(tui.response_line(marker + "suffix", marker))

    def test_cwd_normalization_and_report_extraction(self):
        report = {"result": {"foreground_processes": [{"cwd": "C:\\中文 目录"}], "unrelated": "C:\\bad"}}
        self.assertEqual(list(tui.cwd_values(report)), ["C:\\中文 目录"])
        self.assertEqual(tui.normalize_cwd("C:\\中文 目录", True), tui.normalize_cwd("/c/中文 目录", True))
        self.assertNotEqual(tui.normalize_cwd("/tmp/A"), tui.normalize_cwd("/tmp/a"))

    def test_pane_discovery_merges_duplicate_references(self):
        value = {"pane_id": "w1:p1", "cwd": "home", "children": [{"pane_id": "w1:p1", "focused": True}, {"pane_id": "w2:p1"}]}
        self.assertEqual(len(tui.collect_panes(value)), 2)
        first = tui.collect_panes(value)[0]
        self.assertEqual(first["cwd"], "home")
        self.assertTrue(first["focused"])

    def test_profile_cannot_escape_evidence(self):
        output = self.root / "output"
        output.mkdir()
        with self.assertRaises(tui.ProbeError):
            tui.safe_profile(self.root / "outside", output)
        self.assertFalse((self.root / "outside").exists())
        tui.safe_profile(output / "中文 profile", output)

    def test_existing_output_is_never_overwritten(self):
        with mock.patch.object(tui, "make_environment") as env, self.assertRaises(tui.ProbeError):
            tui.run_probe(Path(sys.executable), Path(sys.executable), self.root)
        env.assert_not_called()

    def test_environment_isolates_native_windows_home_and_secrets(self):
        with mock.patch.dict(os.environ, {"SYSTEMROOT": "C:\\Windows", "HOME": "real", "HERDR_SESSION": "user-session", "SSH_AUTH_SOCK": "private", "API_TOKEN": "never-copy"}, clear=True):
            env = tui.make_environment(self.root, self.root / "msys")
        for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            self.assertTrue(Path(env[key]).is_relative_to(self.root))
        for key in ("API_TOKEN", "SSH_AUTH_SOCK", "HERDR_SESSION"):
            self.assertNotIn(key, env)
        if os.name == "nt":
            self.assertEqual(env["HOME"], str(self.root / "用户 HOME"))
            self.assertEqual(env["HOME"], env["USERPROFILE"])

    def test_capture_is_bounded_and_input_preserved(self):
        terminal = tui.TerminalBuffer(self.root / "capture")
        terminal.received("中文".encode())
        terminal.note_input(b"\x02q", "detach")
        terminal.persist()
        self.assertEqual((self.root / "capture.raw").read_bytes(), "中文".encode())
        self.assertEqual(json.loads((self.root / "capture.input.json").read_text())[0]["hex"], "0271")
        with self.assertRaises(tui.ProbeError):
            terminal.received(b"x" * (32 * 1024 * 1024))

    def test_shell_quote_preserves_literal_text(self):
        self.assertEqual(tui.shell_quote("a'b $HOME"), "'a'\\''b $HOME'")

    def test_real_local_transport_has_tty_and_keyboard(self):
        env = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "OS"}}
        env.update(HOME=str(self.root), USERPROFILE=str(self.root), APPDATA=str(self.root), LOCALAPPDATA=str(self.root), TERM="xterm-256color", LANG="C.UTF-8", PATH=os.defpath)
        if os.name == "nt":
            argv = [os.environ["COMSPEC"], "/d", "/q"]
            terminal = tui.WindowsConPty(argv, env, self.root, self.root / "native")
            marker = b"GX-NATIVE-CONPTY-729"
            payload = b"set /a 700+29\r"
        else:
            argv = [sys.executable, "-u", "-c", "import os; print('TTY='+str(os.isatty(0) and os.isatty(1)),flush=True); s=input(); print('GX-PTY-'+str(int(s)+1),flush=True)"]
            terminal = tui.UnixPty(argv, env, self.root, self.root / "native")
            marker = b"GX-PTY-730"
            payload = b"729\r"
        try:
            deadline = time.monotonic() + 10
            if os.name != "nt":
                while b"TTY=True" not in terminal.read_bytes() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertIn(b"TTY=True", terminal.read_bytes())
            else:
                time.sleep(.2)
            terminal.send(payload, "unit-transport-keyboard")
            if os.name == "nt":
                terminal.send(b"echo GX-NATIVE-CONPTY-729\r", "unit-marker")
            while marker not in terminal.read_bytes() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertIn(marker, terminal.read_bytes())
            if os.name == "nt":
                terminal.resize(100, 30)
                terminal.send(b"exit\r", "unit-exit")
            self.assertEqual(terminal.wait(10), 0)
        finally:
            terminal.close()
        self.assertIsNone(terminal.error)
        self.assertTrue((self.root / "native.raw").stat().st_size > 0)


if __name__ == "__main__":
    unittest.main()
