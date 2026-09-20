"""gx 终端集成的真实 PTY 回归；不读取或修改用户配置。"""
import os
import pathlib
import pty
import select
import shlex
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
MODULE = REPO / "gx/config/terminal.zsh"
INSTALLER = REPO / "gx/install.sh"
# 安装器与 zsh 配置链会读取的宿主环境变量：隔离部署前一律剥离。
STRIP_ENV = ("ZSH", "ZSH_CUSTOM", "ZSH_CACHE_DIR", "ZSH_COMPDUMP", "GX_HOME", "GITSTATUS_CACHE_DIR",
             "GIT_DIR", "GIT_CEILING_DIRECTORIES", "FZF_DEFAULT_OPTS", "FZF_DEFAULT_COMMAND",
             "GX_TERMINAL_CWD_INSTALLED", "TERM_PROGRAM", "HERDR_ENV", "XDG_CACHE_HOME", "XDG_CONFIG_HOME")
# 模拟上游 lib/termsupport.zsh 在 xterm* 下无条件挂上的 OSC 7 钩子。
UPSTREAM_HOOK = "omz_termsupport_cwd() { :; }; autoload -Uz add-zsh-hook; add-zsh-hook precmd omz_termsupport_cwd; "



def isolated_env(home, **overrides):
    """以部署 HOME 为根的环境；值为 None 的键表示删除。"""
    env = {key: value for key, value in os.environ.items() if key not in STRIP_ENV}
    env.update(HOME=str(home), ZDOTDIR=str(home), TERM="xterm-256color")
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def deploy_gx_home(home):
    """用 gx/install.sh 把工作树真实部署到 mktemp HOME（不碰真实 $HOME）。"""
    if shutil.which("zsh") is None or shutil.which("sh") is None:
        raise AssertionError("真实链路测试需要 zsh 与 sh，缺失即失败（不 skip）")
    result = subprocess.run(
        ["sh", str(INSTALLER), "--home", str(home), "--zsh", str(home / ".oh-my-zsh"), "--skip-apt",
         "--skip-fonts", "--skip-wezterm", "--skip-chsh", "--unattended"],
        env=isolated_env(home), capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise AssertionError(f"gx/install.sh 部署失败 rc={result.returncode}\n{result.stdout}\n{result.stderr}")
    return home


def shadow_path(root, hide=(), shims=None):
    """构造 PATH：hide 中的命令从所有目录消失（目录整体以符号链接影子替代），
    shims 为 {命令名: 脚本正文} 的伪命令，放在 PATH 最前。"""
    parts = []
    shim_dir = root / "shim-bin"
    shim_dir.mkdir(exist_ok=True)
    for name, body in (shims or {}).items():
        shim = shim_dir / name
        shim.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        shim.chmod(0o755)
    parts.append(str(shim_dir))
    for index, entry in enumerate(os.environ.get("PATH", "").split(os.pathsep)):
        directory = pathlib.Path(entry)
        if not entry or not directory.is_dir():
            continue
        if not any((directory / name).exists() for name in hide):
            parts.append(entry)
            continue
        shadow = root / f"shadow-{index}"
        shadow.mkdir(exist_ok=True)
        for child in directory.iterdir():
            if child.name not in hide and not (shadow / child.name).exists():
                os.symlink(child, shadow / child.name)
        parts.append(str(shadow))
    return os.pathsep.join(parts)


class DeployedZshrc(unittest.TestCase):
    """部署形态（install.sh 落地的 .zshrc/.zshenv/omz/p10k）下的配置链断言。"""

    @classmethod
    def setUpClass(cls):
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="gx-deployed-"))
        cls.home = deploy_gx_home(cls.root / "home")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def run_login(self, script, **overrides):
        """在部署 HOME 中起 zsh -i -c（不加 -f，走真实 .zshenv/.zshrc 链）。"""
        result = subprocess.run(["zsh", "-i", "-c", script], env=isolated_env(self.home, **overrides),
                                capture_output=True, timeout=90, cwd=str(self.home))
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result.stdout, result.stderr

    def fzf_state(self, version_line=None, hide=(), extra_shims=None):
        shims = dict(extra_shims or {})
        if version_line is not None:
            shims["fzf"] = f'[ "$1" = --version ] && {{ printf \'%s\\n\' "{version_line}"; exit 0; }}; exit 2'
        # 每次调用独立的影子 PATH 根，避免上一用例的伪命令/影子目录残留。
        path_root = pathlib.Path(tempfile.mkdtemp(prefix="path-", dir=self.root))
        path = shadow_path(path_root, hide=set(hide) | ({"fzf"} if version_line is None else set()), shims=shims)
        out, err = self.run_login("print -r -- OPTS:${FZF_DEFAULT_OPTS-unset}:END; print -r -- CMD:${FZF_DEFAULT_COMMAND-unset}:END",
                                  PATH=path)
        text = out.decode(errors="replace")
        opts = text.split("OPTS:", 1)[1].split(":END", 1)[0]
        cmd = text.split("CMD:", 1)[1].split(":END", 1)[0]
        return opts, cmd, err.decode(errors="replace")

    def test_zshenv_skips_ubuntu_global_compinit(self):
        # Ubuntu 的 /etc/zsh/zshrc 先于 ~/.zshrc 执行并额外跑一次 compinit（多一份无
        # 后缀 .zcompdump）；开关只有放在 ~/.zshenv 里才来得及生效。
        out, _err = self.run_login("print -r -- SGC:${skip_global_compinit-unset}:END")
        self.assertIn(b"SGC:1:END", out)
        self.assertFalse((self.home / ".zcompdump").exists(), "全局 compinit 仍生成了无后缀 .zcompdump")
        self.assertTrue(list(self.home.glob(".zcompdump-*")), "omz 自身的 .zcompdump-<host>-<ver> 应存在")

    def test_fzf_020_gets_legacy_border_without_new_flags(self):
        # Ubuntu 20.04 的 fzf 0.20.0 不认识 --border=rounded/--pointer/--marker，
        # 任何 fzf 入口启动即退出。
        opts, _cmd, _err = self.fzf_state("0.20.0")
        self.assertNotIn("--pointer", opts)
        self.assertNotIn("--marker", opts)
        self.assertNotIn("--border=rounded", opts)
        self.assertIn("--border", opts)
        self.assertIn("--height=55%", opts)

    def test_fzf_024_plus_gets_rounded_border_pointer_marker(self):
        opts, _cmd, _err = self.fzf_state("0.44.1 (d0466fa)")
        for flag in ("--border=rounded", "--pointer=", "--marker="):
            self.assertIn(flag, opts)

    def test_missing_fzf_exports_nothing_and_stays_silent(self):
        opts, cmd, err = self.fzf_state(None, hide={"fd", "fdfind", "rg"})
        self.assertEqual(opts, "unset")
        self.assertEqual(cmd, "unset")
        self.assertNotIn("fzf", err)

    def test_default_command_prefers_fd_then_rg(self):
        with_fd = self.fzf_state("0.20.0", hide={"fd", "fdfind", "rg"}, extra_shims={"fd": "exit 0", "rg": "exit 0"})[1]
        self.assertTrue(with_fd.startswith("fd "), with_fd)
        only_rg = self.fzf_state("0.20.0", hide={"fd", "fdfind", "rg"}, extra_shims={"rg": "exit 0"})[1]
        self.assertTrue(only_rg.startswith("rg --files"), only_rg)
        neither = self.fzf_state("0.20.0", hide={"fd", "fdfind", "rg"})[1]
        self.assertEqual(neither, "unset")


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
