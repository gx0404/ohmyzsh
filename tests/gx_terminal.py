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
# 模拟上游 lib/termsupport.zsh 在 xterm* 下无条件挂上的 OSC 7 钩子。
UPSTREAM_HOOK = "omz_termsupport_cwd() { :; }; autoload -Uz add-zsh-hook; add-zsh-hook precmd omz_termsupport_cwd; "


class TerminalIntegration(unittest.TestCase):
    def run_shell(self, script, interactive=True, env_overrides=None):
        with tempfile.TemporaryDirectory(prefix="gx-terminal-") as root:
            cwd = pathlib.Path(root) / "中文 space"
            cwd.mkdir()
            env = dict(os.environ, TERM_PROGRAM="WezTerm", TERM="xterm-256color", HOME=root, ZDOTDIR=root)
            env.pop("GX_TERMINAL_CWD_INSTALLED", None)
            env.pop("HERDR_ENV", None)
            for key, value in (env_overrides or {}).items():
                if value is None:
                    env.pop(key, None)
                else:
                    env[key] = value
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

    def test_osc7_host_field_is_empty(self):
        # herdr 的 parse_file_uri_cwd 只接受空或 localhost 主机；wezterm 同样接受空主机。
        data = self.run_shell("source MODULE; cd DIRECTORY; _gx_terminal_report_cwd")
        self.assertEqual(data.count(b"\x1b]7;"), 1)
        self.assertIn(b"\x1b]7;file:///", data)
        self.assertNotIn(("file://" + os.uname().nodename).encode(), data)

    def test_guard_survives_instant_prompt_fd_redirect(self):
        # p10k instant prompt 在 zshrc 早期把 fd 1 重定向到临时文件，`-t 1` 恒假；
        # 模块必须改以 $TTY 判定，否则部署形态下从未安装。
        data = self.run_shell("exec {fd}>&1 1>/dev/null; source MODULE; exec 1>&$fd {fd}>&-; print -r -- INSTALLED:${GX_TERMINAL_CWD_INSTALLED:-no}")
        self.assertIn(b"INSTALLED:1", data)

    def test_upstream_cwd_hook_is_replaced_when_module_owns_osc7(self):
        data = self.run_shell(UPSTREAM_HOOK + "source MODULE; print -r -- PF:${(j:,:)precmd_functions}:END")
        hooks = data.split(b"PF:", 1)[1].split(b":END", 1)[0].split(b",")
        self.assertIn(b"_gx_terminal_report_cwd", hooks)
        self.assertNotIn(b"omz_termsupport_cwd", hooks)

    def test_upstream_cwd_hook_is_kept_when_guard_declines(self):
        data = self.run_shell(UPSTREAM_HOOK + "source MODULE; print -r -- INSTALLED:${GX_TERMINAL_CWD_INSTALLED:-no} PF:${(j:,:)precmd_functions}:END", env_overrides={"TERM_PROGRAM": None})
        self.assertIn(b"INSTALLED:no", data)
        hooks = data.split(b"PF:", 1)[1].split(b":END", 1)[0].split(b",")
        self.assertIn(b"omz_termsupport_cwd", hooks)
        self.assertNotIn(b"_gx_terminal_report_cwd", hooks)

    def test_herdr_env_without_term_program_installs_hook(self):
        data = self.run_shell("source MODULE; print -r -- INSTALLED:${GX_TERMINAL_CWD_INSTALLED:-no}", env_overrides={"TERM_PROGRAM": None, "HERDR_ENV": "1"})
        self.assertIn(b"INSTALLED:1", data)

    def test_existing_wezterm_integration_remains_owner(self):
        data = self.run_shell("__wezterm_osc7() { :; }; source MODULE; print -r -- INSTALLED:${GX_TERMINAL_CWD_INSTALLED:-no}")
        self.assertIn(b"INSTALLED:no", data)
        self.assertNotIn(b"\x1b]7;", data)

    def test_noninteractive_shell_does_not_emit_control_sequences(self):
        data = self.run_shell("source MODULE; print -r -- INSTALLED:${GX_TERMINAL_CWD_INSTALLED:-no}", interactive=False)
        self.assertEqual(data, b"INSTALLED:no\n")

if __name__ == "__main__":
    unittest.main()
