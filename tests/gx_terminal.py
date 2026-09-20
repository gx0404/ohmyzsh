"""gx 终端集成的真实 PTY 回归；不读取或修改用户配置。"""
import fcntl
import os
import pathlib
import pty
import re
import select
import shlex
import shutil
import struct
import subprocess
import tempfile
import termios
import time
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
MODULE = REPO / "gx/config/terminal.zsh"
INSTALLER = REPO / "gx/install.sh"
# 远端会话标记：模块在这些变量存在时不接管（与上游 termsupport 一致）；宿主若经 ssh
# 跑本测试会继承它们，所以隔离环境一律剥离，专门的用例再显式注入。
REMOTE_ENV = ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY", "INSIDE_EMACS")
# 安装器与 zsh 配置链会读取的宿主环境变量：隔离部署前一律剥离。
STRIP_ENV = ("ZSH", "ZSH_CUSTOM", "ZSH_CACHE_DIR", "ZSH_COMPDUMP", "GX_HOME", "GITSTATUS_CACHE_DIR",
             "GIT_DIR", "GIT_CEILING_DIRECTORIES", "FZF_DEFAULT_OPTS", "FZF_DEFAULT_COMMAND",
             "GX_TERMINAL_CWD_INSTALLED", "TERM_PROGRAM", "HERDR_ENV", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
             "TMPDIR") + REMOTE_ENV
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


def run_installer(home, *args, **overrides):
    """在隔离环境里跑 gx/install.sh：TMPDIR 指进沙箱，安装器的 tar 中转文件不落共享 /tmp。"""
    if shutil.which("zsh") is None or shutil.which("sh") is None:
        raise AssertionError("真实链路测试需要 zsh 与 sh，缺失即失败（不 skip）")
    overrides.setdefault("TMPDIR", str(pathlib.Path(home).parent))
    return subprocess.run(
        ["sh", str(INSTALLER), "--home", str(home), *args, "--skip-apt", "--skip-fonts", "--skip-wezterm",
         "--skip-chsh", "--unattended"],
        env=isolated_env(home, **overrides), capture_output=True, text=True, timeout=120)


def deploy_gx_home(home):
    """用 gx/install.sh 把工作树真实部署到 mktemp HOME（不碰真实 $HOME）。"""
    result = run_installer(home, "--zsh", str(home / ".oh-my-zsh"))
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

    def test_fzf_unparseable_version_falls_back_to_legacy_flags(self):
        # 包装脚本/补丁构建会打印 "fzf 0.20.0" 或 "v0.44.1"：首字段不是 <数字>.<数字>
        # 时 is-at-least 会把它当成新版；解析不出必须退化到老选项（安全一侧）。
        for version_line in ("fzf 0.20.0", "v0.44.1", "unknown"):
            opts, _cmd, _err = self.fzf_state(version_line)
            self.assertNotIn("--pointer", opts, version_line)
            self.assertNotIn("--marker", opts, version_line)
            self.assertNotIn("--border=rounded", opts, version_line)
            self.assertIn("--border", opts, version_line)

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



class InstallerZshInterlock(unittest.TestCase):
    """--home 与继承的环境 ZSH 互锁：gx 会话里 export 的 ZSH=~/.oh-my-zsh 不得让隔离
    演练把重装路径打到真实目录上。用 mktemp 里的假树代替真实 ~/.oh-my-zsh。"""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="gx-interlock-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.foreign = self.root / "foreign-zsh"
        (self.foreign / "custom" / "plugins").mkdir(parents=True)
        (self.foreign / ".gx-managed").write_text("foreign marker\n")
        (self.foreign / "custom" / "plugins" / "keep.zsh").write_text("# keep\n")
        self.snapshot = sorted(str(p.relative_to(self.foreign)) for p in self.foreign.rglob("*"))

    def foreign_unchanged(self):
        self.assertEqual(sorted(str(p.relative_to(self.foreign)) for p in self.foreign.rglob("*")), self.snapshot)
        self.assertEqual((self.foreign / "custom" / "plugins" / "keep.zsh").read_text(), "# keep\n")

    def test_home_flag_ignores_inherited_zsh_env(self):
        home = self.root / "home"
        result = run_installer(home, ZSH=str(self.foreign))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((home / ".oh-my-zsh" / ".gx-managed").exists(), result.stdout)
        self.assertIn(f"忽略环境 ZSH={self.foreign}", result.stdout)
        self.foreign_unchanged()

    def test_env_zsh_outside_home_is_refused_unattended(self):
        home = self.root / "home"
        home.mkdir()
        result = subprocess.run(
            ["sh", str(INSTALLER), "--skip-apt", "--skip-fonts", "--skip-wezterm", "--skip-chsh", "--unattended"],
            env=isolated_env(home, GX_HOME=str(home), ZSH=str(self.foreign), TMPDIR=str(self.root)),
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("--zsh", result.stderr)
        self.assertFalse((home / ".oh-my-zsh").exists())
        self.assertFalse((home / ".zshrc").exists())
        self.foreign_unchanged()


def fzf_version():
    """宿主真实 fzf 的 (major, minor) 版本；未安装返回 None。探测时清空 FZF_DEFAULT_OPTS。"""
    if shutil.which("fzf") is None:
        return None
    out = subprocess.run(["fzf", "--version"], env=dict(os.environ, FZF_DEFAULT_OPTS=""),
                         capture_output=True, text=True, timeout=10).stdout
    match = re.match(r"(\d+)\.(\d+)", out)
    if not match:
        raise AssertionError(f"无法解析 fzf --version 输出: {out!r}")
    return int(match.group(1)), int(match.group(2))


def osc7_payloads(data):
    """按出现顺序返回每条 OSC 7 的 URI（到 ST 为止）。"""
    return [m.group(1) for m in re.finditer(rb"\x1b\]7;([^\x07\x1b]*)(?:\x07|\x1b\\)", data)]


def segment(data, start, end=None):
    begin = data.index(start) + len(start)
    return data[begin:] if end is None else data[begin:data.index(end, begin)]


def marked(text, index):
    """打标记的命令：标记用算术展开生成，输入回显里不出现字面值，等待时不会被回显骚扰。"""
    return f"{text}:M$(({index}+1000))", f":M{index + 1000}".encode()


class PtySession:
    """真 PTY 里的交互 zsh（不加 -f，走部署 HOME 的 .zshenv/.zshrc 链）：按步发送字节、
    等标记或输出静默，close 时发 exit 并回收；全部输出字节留在 out。"""

    def __init__(self, home, timeout=60, rows=40, cols=120, **overrides):
        try:
            self.master, slave = pty.openpty()
        except OSError as error:
            raise AssertionError(f"无法分配 PTY: {error}")
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.child = subprocess.Popen(
            ["zsh", "-i"], env=isolated_env(home, **overrides), cwd=str(home),
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
            preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
        os.close(slave)
        self.out = bytearray()
        self.deadline = time.monotonic() + timeout

    def pump(self, wait):
        if select.select([self.master], [], [], wait)[0]:
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                return False
            if not chunk:
                return False
            self.out.extend(chunk)
        return True

    def settle(self, quiet=0.3, cap=None):
        """等输出静默 quiet 秒。返回 (最后一个字节的到达时刻或 None, 是否在 cap 秒内未静默)。"""
        start = time.monotonic()
        last = start
        arrival = None
        while time.monotonic() - last < quiet:
            if time.monotonic() > self.deadline:
                raise AssertionError(f"PTY 会话超时；尾部输出: {bytes(self.out[-600:])!r}")
            if cap is not None and time.monotonic() - start > cap:
                return arrival, True
            before = len(self.out)
            if not self.pump(0.02):
                break
            if len(self.out) != before:
                last = time.monotonic()
                arrival = last
        return arrival, False

    def send(self, data):
        os.write(self.master, data)

    def wait_for(self, marker):
        while marker not in self.out:
            if time.monotonic() > self.deadline:
                raise AssertionError(f"等待标记 {marker!r} 超时；尾部输出: {bytes(self.out[-600:])!r}")
            if not self.pump(0.5):
                raise AssertionError(f"shell 在标记 {marker!r} 之前退出；输出: {bytes(self.out[-600:])!r}")

    def command(self, text, marker):
        """发送一行命令，等其标记出现且输出静默。"""
        self.send((text + "\n").encode())
        self.wait_for(marker)
        self.settle()

    def close(self):
        try:
            self.send(b"exit\n")
            while self.child.poll() is None:
                if time.monotonic() > self.deadline:
                    self.child.kill()
                    raise AssertionError("shell 未在 exit 后退出")
                self.pump(0.2)
            while self.pump(0.05):
                pass
        finally:
            os.close(self.master)
            if self.child.poll() is None:
                self.child.kill()
            self.child.wait(timeout=10)
        return bytes(self.out)


def captured(data, tag, index):
    """取 `print -r -- TAG:<值>` 打标记命令的输出值；`[^$]` 排除含 `${` 的输入回显。"""
    match = re.search(rb"%s:([^$\r\n]*):M%d" % (tag.encode(), index + 1000), data)
    if match is None:
        raise AssertionError(f"没有捕获到 {tag} 的输出；尾部: {data[-800:]!r}")
    return match.group(1)

class DeployedInteractive(unittest.TestCase):
    """真实链路：install.sh 部署 + 真 PTY 起 zsh -i（不加 -f），覆盖 p10k instant prompt
    生效的第二次及之后启动形态；缺 zsh/sh/pty 直接失败而非 skip。"""

    @classmethod
    def setUpClass(cls):
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="gx-pty-"))
        cls.home = deploy_gx_home(cls.root / "home")
        cls.workdir = cls.home / "中文 dir"
        cls.workdir.mkdir()
        # 首个会话让 p10k 写出 instant prompt 缓存；之后的会话才处于"fd 1 被重定向"形态。
        cls.session([marked("print -r -- warmup", 0)], TERM_PROGRAM="WezTerm")
        if not list((cls.home / ".cache").glob("p10k-instant-prompt-*.zsh")):
            raise AssertionError("预热会话未生成 p10k instant prompt 缓存，无法覆盖部署形态")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    @classmethod
    def session(cls, commands, timeout=60, **overrides):
        """逐条发送命令，等到其标记出现且输出空闲后再发下一条，最后 exit；返回全部字节。"""
        shell = PtySession(cls.home, timeout=timeout, **overrides)
        try:
            shell.settle()
            for command, marker in commands:
                shell.command(command, marker)
        finally:
            data = shell.close()
        return data

    def probe(self, **overrides):
        commands = [
            marked("print -r -- ready", 1),
            marked(f"cd {shlex.quote(str(self.workdir))}; print -r -- moved", 2),
            marked("print -r -- idle", 3),
            marked("print -r -- PF:${(j:,:)precmd_functions}", 4),
            marked("print -r -- INST:${GX_TERMINAL_CWD_INSTALLED:-no}", 5),
        ]
        data = self.session(commands, **overrides)
        hooks = re.search(rb"PF:([^$\r\n]*):M1004", data)
        installed = re.search(rb"INST:([^$\r\n]*):M1005", data)
        self.assertIsNotNone(hooks, data[-800:])
        self.assertIsNotNone(installed, data[-800:])
        return data, hooks.group(1).split(b","), installed.group(1)

    def test_instant_prompt_session_reports_cwd_once_without_host(self):
        data, hooks, installed = self.probe(TERM_PROGRAM="WezTerm")
        self.assertEqual(installed, b"1")
        self.assertIn(b"_gx_terminal_report_cwd", hooks)
        self.assertNotIn(b"omz_termsupport_cwd", hooks)
        payloads = osc7_payloads(data)
        self.assertTrue(payloads, "整个会话没有任何 OSC 7")
        for uri in payloads:
            self.assertTrue(uri.startswith(b"file:///"), uri)
        # 首个提示符一条（当前目录）、cd 后一条（编码后的新目录）；未变目录的提示符不发。
        self.assertEqual(len(osc7_payloads(data[:data.index(b":M1001")])), 1)
        self.assertEqual(osc7_payloads(segment(data, b":M1001", b":M1002")), [])
        after_cd = osc7_payloads(segment(data, b":M1002", b":M1003"))
        self.assertEqual(len(after_cd), 1, after_cd)
        self.assertTrue(after_cd[0].endswith(b"/%E4%B8%AD%E6%96%87%20dir"), after_cd[0])
        self.assertEqual(osc7_payloads(segment(data, b":M1003")), [])

    def test_herdr_env_without_term_program_installs_hook(self):
        data, hooks, installed = self.probe(TERM_PROGRAM=None, HERDR_ENV="1")
        self.assertEqual(installed, b"1")
        self.assertIn(b"_gx_terminal_report_cwd", hooks)
        self.assertNotIn(b"omz_termsupport_cwd", hooks)
        self.assertTrue(all(uri.startswith(b"file:///") for uri in osc7_payloads(data)))

    def test_unknown_terminal_keeps_upstream_cwd_hook(self):
        _data, hooks, installed = self.probe(TERM_PROGRAM=None, HERDR_ENV=None)
        self.assertEqual(installed, b"no")
        self.assertNotIn(b"_gx_terminal_report_cwd", hooks)
        self.assertIn(b"omz_termsupport_cwd", hooks)

    def test_autosuggest_binds_once_and_wraps_late_widgets(self):
        # GX-07：插件在首个 precmd 统一包裹 widget，此时整份 .zshrc（含后半段的 zle -N）
        # 已执行完；ZSH_AUTOSUGGEST_MANUAL_REBIND 只让它绑完一次后自删，去掉此后每提示符
        # 的重绑（真 PTY 原位实测 5.5 ms → 0.05 ms）。两条一起断言才同时覆盖「省了重绑」
        # 与「后定义的 widget 没绑漏」；灰色建议仍要出现。
        shell = PtySession(self.home, TERM_PROGRAM="WezTerm")
        try:
            shell.settle()
            shell.command(*marked("print -r -- PF:${(j:,:)precmd_functions}", 8))
            shell.command(*marked("print -r -- WUP:${widgets[up-line-or-beginning-search]}", 9))
            shell.command(*marked("print -r -- WDEL:${widgets[ubuntu_delete_char_or_eof]}", 10))
            shell.command(*marked("print -r -- WKILL:${widgets[backward-kill-space-word]}", 11))
            shell.command(*marked("print -r -- READY", 12))
            # 预热会话执行过 `print -r -- warmup…`，只敲前缀应弹出灰色历史建议（不回车）。
            shell.send(b"print -r -- w")
            shell.settle()
            typed = len(shell.out)
            shell.send(b"\x03")
            shell.settle()
        finally:
            data = shell.close()
        hooks = captured(data, "PF", 8).split(b",")
        self.assertNotIn(b"_zsh_autosuggest_start", hooks, hooks)
        for tag, index in (("WUP", 9), ("WDEL", 10), ("WKILL", 11)):
            self.assertTrue(captured(data, tag, index).startswith(b"user:_zsh_autosuggest_bound_"),
                            f"{tag} 未被 autosuggestions 包裹: {captured(data, tag, index)!r}")
        ready = data.index(b":M1012")
        self.assertIn(b"armup", data[ready:typed], "输入前缀后没有出现历史建议")

    def test_fzf_default_opts_match_installed_fzf(self):
        data = self.session([
            marked("print -r -- FZF:${FZF_DEFAULT_OPTS-unset}", 6),
            marked("print a | fzf --filter=a >/dev/null 2>&1; print -r -- FZFRC:$?", 7),
        ], TERM_PROGRAM="WezTerm")
        opts = re.search(rb"FZF:([^$\r\n]*):M1006", data)
        self.assertIsNotNone(opts, data[-800:])
        opts = opts.group(1).decode()
        version = fzf_version()
        if version is None:
            self.assertEqual(opts, "unset")
            return
        rc = re.search(rb"FZFRC:(\d+):M1007", data)
        self.assertIsNotNone(rc, data[-800:])
        self.assertEqual(rc.group(1), b"0", f"fzf {version} 拒绝了导出的选项: {opts}")
        if version < (0, 24):
            self.assertNotIn("--pointer", opts)
            self.assertNotIn("--marker", opts)
            self.assertNotIn("--border=rounded", opts)
            self.assertIn("--border", opts)
        else:
            for flag in ("--border=rounded", "--pointer=", "--marker="):
                self.assertIn(flag, opts)


class TerminalIntegration(unittest.TestCase):
    def run_shell(self, script, interactive=True, env_overrides=None):
        with tempfile.TemporaryDirectory(prefix="gx-terminal-") as root:
            cwd = pathlib.Path(root) / "中文 space"
            cwd.mkdir()
            env = dict(os.environ, TERM_PROGRAM="WezTerm", TERM="xterm-256color", HOME=root, ZDOTDIR=root)
            for key in ("GX_TERMINAL_CWD_INSTALLED", "HERDR_ENV") + REMOTE_ENV:
                env.pop(key, None)
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

    def test_resourcing_zshrc_after_upstream_rehooks_keeps_single_reporter(self):
        # `source ~/.zshrc` 会让 lib/termsupport.zsh 重新挂 omz_termsupport_cwd，而模块
        # 已安装；摘钩子必须在 INSTALLED 早退之前执行，否则双发当场回归。
        data = self.run_shell("source MODULE; " + UPSTREAM_HOOK + "source MODULE; print -r -- PF:${(j:,:)precmd_functions}:END")
        hooks = data.split(b"PF:", 1)[1].split(b":END", 1)[0].split(b",")
        self.assertEqual(hooks.count(b"_gx_terminal_report_cwd"), 1, hooks)
        self.assertNotIn(b"omz_termsupport_cwd", hooks)

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

    def test_remote_sessions_keep_upstream_behaviour(self):
        # ssh / emacs 里的 cwd 对本地终端没有意义：即使 TERM_PROGRAM/HERDR_ENV 被
        # SendEnv 带过去，模块也不接管、不摘上游钩子、不发 file:///。
        for marker in ({"SSH_TTY": "/dev/pts/9"}, {"SSH_CLIENT": "10.0.0.2 51000 22"},
                       {"SSH_CONNECTION": "10.0.0.2 51000 10.0.0.1 22"}, {"INSIDE_EMACS": "1"}):
            data = self.run_shell(UPSTREAM_HOOK + "source MODULE; cd DIRECTORY; print -r -- INSTALLED:${GX_TERMINAL_CWD_INSTALLED:-no} PF:${(j:,:)precmd_functions}:END",
                                  env_overrides=dict(marker, HERDR_ENV="1"))
            self.assertIn(b"INSTALLED:no", data, marker)
            hooks = data.split(b"PF:", 1)[1].split(b":END", 1)[0].split(b",")
            self.assertIn(b"omz_termsupport_cwd", hooks, marker)
            self.assertNotIn(b"_gx_terminal_report_cwd", hooks, marker)
            self.assertNotIn(b"\x1b]7;file:///", data, marker)

    def test_existing_wezterm_integration_remains_owner(self):
        data = self.run_shell("__wezterm_osc7() { :; }; source MODULE; print -r -- INSTALLED:${GX_TERMINAL_CWD_INSTALLED:-no}")
        self.assertIn(b"INSTALLED:no", data)
        self.assertNotIn(b"\x1b]7;", data)

    def test_noninteractive_shell_does_not_emit_control_sequences(self):
        data = self.run_shell("source MODULE; print -r -- INSTALLED:${GX_TERMINAL_CWD_INSTALLED:-no}", interactive=False)
        self.assertEqual(data, b"INSTALLED:no\n")

if __name__ == "__main__":
    unittest.main()
