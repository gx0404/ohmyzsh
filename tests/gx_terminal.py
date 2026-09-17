"""gx 终端集成的真实 PTY 回归；不读取或修改用户配置。"""
import os
import pathlib
import pty
import select
import shlex
import subprocess
import tempfile
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "gx/config/terminal.zsh"

class TerminalIntegration(unittest.TestCase):
    def run_shell(self, script, interactive=True):
        with tempfile.TemporaryDirectory(prefix="gx-terminal-") as root:
            cwd = pathlib.Path(root) / "中文 space"
            cwd.mkdir()
            env = dict(os.environ, TERM_PROGRAM="WezTerm", TERM="xterm-256color", HOME=root, ZDOTDIR=root)
            env.pop("GX_TERMINAL_CWD_INSTALLED", None)
            script = script.replace("MODULE", shlex.quote(str(MODULE))).replace("DIRECTORY", shlex.quote(str(cwd)))
            if not interactive:
                return subprocess.check_output(["zsh", "-f", "-c", script], env=env)
            master, slave = pty.openpty()
            try:
                child = subprocess.Popen(["zsh", "-f", "-i", "-c", script], env=env, stdin=slave, stdout=slave, stderr=slave)
                os.close(slave)
                data = bytearray()
                while child.poll() is None or select.select([master], [], [], 0)[0]:
                    if select.select([master], [], [], 2)[0]:
                        try:
                            chunk = os.read(master, 65536)
                            if not chunk: break
                            data.extend(chunk)
                        except OSError: break
                self.assertEqual(child.wait(timeout=5), 0)
                return bytes(data)
            finally:
                os.close(master)

    def test_cwd_is_encoded_cached_and_hook_installed_once(self):
        data = self.run_shell("source MODULE; source MODULE; cd DIRECTORY; _gx_terminal_report_cwd; _gx_terminal_report_cwd; print -r -- ${(j:,:)precmd_functions}")
        self.assertEqual(data.count(b"\x1b]7;"), 1)
        self.assertIn(b"%E4%B8%AD%E6%96%87%20space", data)
        self.assertEqual(data.count(b"_gx_terminal_report_cwd"), 1)

    def test_existing_wezterm_integration_remains_owner(self):
        data = self.run_shell("__wezterm_osc7() { :; }; source MODULE; print -r -- INSTALLED:${GX_TERMINAL_CWD_INSTALLED:-no}")
        self.assertIn(b"INSTALLED:no", data)
        self.assertNotIn(b"\x1b]7;", data)

    def test_noninteractive_shell_does_not_emit_control_sequences(self):
        data = self.run_shell("source MODULE; print -r -- INSTALLED:${GX_TERMINAL_CWD_INSTALLED:-no}", interactive=False)
        self.assertEqual(data, b"INSTALLED:no\n")

if __name__ == "__main__":
    unittest.main()
