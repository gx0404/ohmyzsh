"""gx 终端集成的真实 PTY 回归；不读取或修改用户配置。"""
import fcntl
import os
import pathlib
import pty
import re
import select
import shlex
import shutil
import statistics
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
STRIP_ENV = ("ZSH", "ZSH_CUSTOM", "ZSH_CACHE_DIR", "ZSH_COMPDUMP", "GX_HOME", "GX_KEEP_BACKUPS",
             "GITSTATUS_CACHE_DIR",
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

    def test_zshrc_local_not_deployed_fresh(self):
        # GX-14：机器差异层（CUDA/SDK 路径等）不随安装器部署，换机不带本机路径；
        # zshrc 用 [[ -r ... ]] 守卫，缺失静默跳过（上面全部用例在该形态下通过）。
        self.assertFalse((self.home / ".zshrc.local").exists(),
                         ".zshrc.local 属机器差异层，不应被安装器部署")

    def test_cursor_block_sits_after_bindkeys_before_plugin_sources(self):
        # cursor-mode 块（承接历史 wezterm-gx 标记块）的位置约束：全部 zle -N/bindkey
        # （含 fzf 源内绑定）之后、autosuggestions 与 syntax-highlighting 的 source 之前。
        text = (self.home / ".zshrc").read_text(encoding="utf-8")
        i_fzf = text.index("fzf/examples/key-bindings.zsh")
        i_block = text.index("autoload -Uz up-line-or-beginning-search")
        i_suggest = text.index("zsh-autosuggestions/zsh-autosuggestions.zsh")
        i_highlight = text.index("zsh-syntax-highlighting/zsh-syntax-highlighting.zsh")
        self.assertLess(i_fzf, i_block, "cursor-mode 块须在 fzf 键位源之后")
        self.assertLess(i_block, i_suggest, "cursor-mode 块须在 autosuggestions source 之前")
        self.assertLess(i_suggest, i_highlight, "autosuggestions 须在 syntax-highlighting 之前")

    def test_cursor_mode_zstyles_and_widgets(self):
        out, _err = self.run_login(
            "zstyle -L ':zle:up-line-or-beginning-search' leave-cursor; "
            "zstyle -L ':zle:down-line-or-beginning-search' leave-cursor; "
            "print -r -- W:${widgets[up-line-or-beginning-search]}")
        # zstyle -L 的引号形态随 zsh 版本不同（5.8 不加引号），只钉语义部分。
        self.assertRegex(out, rb":zle:up-line-or-beginning-search'? leave-cursor yes")
        self.assertRegex(out, rb":zle:down-line-or-beginning-search'? leave-cursor yes")
        # widget 经 z-sy-h/autosuggestions 包裹改名后仍以原名为尾缀。
        self.assertRegex(out, rb"W:user:\S*up-line-or-beginning-search")

    def test_non_tty_disables_gitstatus_and_stays_silent(self):
        # GX-15：非 tty 的 zsh -i -c（agent 工具调用形态）画不出提示符——不拉起
        # gitstatusd，stderr 不含初始化横幅；真 PTY 形态不受影响（对面用例覆盖）。
        out, err = self.run_login(
            "print -r -- GS:${POWERLEVEL9K_DISABLE_GITSTATUS-unset} PID:${GITSTATUS_DAEMON_PID_POWERLEVEL9K:-none}")
        self.assertIn(b"GS:true PID:none", out)
        self.assertEqual(err, b"", err)

    def test_atuin_alignment_with_reality(self):
        # GX-16：本机未装 atuin——配置不再往 path 加不存在的 ~/.atuin/bin，Ctrl+R 现实
        # 归属 fzf-history-widget；atuin 段保留存在性守卫，装了的机器仍由 atuin 接管。
        text = (self.home / ".zshrc").read_text(encoding="utf-8")
        self.assertNotIn('"$HOME/.atuin/bin"', text, "path 列表仍含不存在的 .atuin/bin 条目")
        self.assertIn("$+commands[atuin]", text)
        out, _err = self.run_login("bindkey -M emacs '^R'")
        self.assertIn(b"fzf-history-widget", out)
        # 宿主 PATH 里可能带着旧世代配置留下的 .atuin/bin（继承不证明 gx 添加），
        # 用洗干净的 PATH 重跑才能钉住「gx 自己不加」。
        clean, _err = self.run_login("print -r -- ${(j:|:)path}", PATH="/usr/local/bin:/usr/bin:/bin")
        self.assertNotIn(b".atuin", clean)



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

    def test_long_command_line_stays_editable(self):
        # GX-09：syntax-highlighting 每击键重新解析整个 buffer、autosuggestions 每击键按整个
        # buffer 查历史。4401 字符粘贴行 20 键中位的四种组合实测（部署 HOME 真 PTY）：
        # 都不设 25.5 ms、只设 BUFFER_MAX_SIZE 24.5 ms（≈无效）、只设 MAXLENGTH 1.0 ms、
        # 两者同设 0.65 ms —— MAXLENGTH 是主因，BUFFER_MAX_SIZE 是补足项。
        # 改后实测 0.65 ms/击键；阈值取其数倍以上，避免机器差异 flaky。
        tokens = []
        while sum(len(token) + 1 for token in tokens) < 4401:
            tokens.append(f"--flag{len(tokens)}=value_{len(tokens)}")
        line = ("echo " + " ".join(tokens))[:4401]
        shell = PtySession(self.home, rows=50, cols=200, timeout=90, TERM_PROGRAM="WezTerm")
        try:
            shell.settle()
            shell.command(*marked("print -r -- HL:${ZSH_HIGHLIGHT_MAXLENGTH-unset}", 13))
            shell.command(*marked("print -r -- AS:${ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE-unset}", 14))
            started = time.monotonic()
            shell.send(b"\x1b[200~" + line.encode() + b"\x1b[201~")
            arrival, hung = shell.settle(cap=10)
            paste_ms = ((arrival or time.monotonic()) - started) * 1000
            latencies = []
            for _ in range(20):
                started = time.monotonic()
                shell.send(b"x")
                arrival, key_hung = shell.settle(cap=10)
                hung = hung or key_hung
                latencies.append(((arrival or time.monotonic()) - started) * 1000)
            shell.send(b"\x03")
            shell.settle()
        finally:
            data = shell.close()
        for tag, index in (("HL", 13), ("AS", 14)):
            value = captured(data, tag, index)
            self.assertRegex(value, rb"^\d+$", f"{tag} 未在部署形态下设置: {value!r}")
        median = statistics.median(latencies)
        self.assertFalse(hung, f"粘贴/击键后 10 s 内输出仍未静默；粘贴 {paste_ms:.0f} ms，击键 {latencies}")
        # 粘贴首帧在 zsh 5.8 PTY 里约 0.35 ms/字符（bracketed-paste 逐字节回显；只设
        # MAXLENGTH 与两者同设实测同为 1.5 s，与 BUFFER_MAX_SIZE 无关）；这里只守住
        # 「不再撞 20 s 上限」。
        self.assertLess(paste_ms, 5000, f"粘贴后首次渲染 {paste_ms:.0f} ms")
        self.assertLess(median, 5.0, f"每击键中位 {median:.1f} ms: {latencies}")

    def test_highlight_freezes_beyond_maxlength_instead_of_clearing(self):
        # GX-09 的真实降级形态：z-sy-h 的 `_zsh_highlight` 在 `region_highlight=()` **之前**
        # 就因 ZSH_HIGHLIGHT_MAXLENGTH 返回，于是越界前那一帧的高亮区间原样留下并随编辑被
        # ZLE 平移——不是「失去颜色」，而是颜色可能与实际语法不符。三段对照（widget 把
        # region_highlight 落盘，避免干扰 ZLE 重绘）：
        #   1) 未越界的 `echo hello` → `0 4 fg=green`（有效命令）
        #   2) 补到 >512 后在行首插入 x（echo → 不存在的 xecho）→ 仍是平移后的 fg=green，
        #      既没被清空也没重新解析
        #   3) 同一形态下 unset ZSH_HIGHLIGHT_MAXLENGTH → 重新解析，首词变 fg=red,bold
        # 若将来改成「越界真正清空 region_highlight」，本用例会红；那时 gx/config/zshrc、
        # gx/README.md 与 CHANGELOG 条目 19 的措辞必须一起改。
        pad = b"a" * 600            # 与 "echo hello" 相加后 > MAXLENGTH=512
        log = self.home / "rh.log"
        if log.exists():
            log.unlink()
        shell = PtySession(self.home, rows=50, cols=200, timeout=180, TERM_PROGRAM="WezTerm")
        try:
            shell.settle()
            shell.command(*marked(
                "_gxrh() { print -r -- \"RH:${(j:|:)region_highlight}:END\" >> ~/rh.log }; "
                "zle -N _gxrh; bindkey '^G' _gxrh; print -r -- RHREADY", 20))
            for keys in (b"echo hello", b"\x07", pad, b"\x01x", b"\x07", b"\x03"):
                shell.send(keys)
                shell.settle()
            shell.command(*marked("unset ZSH_HIGHLIGHT_MAXLENGTH; print -r -- NOLIMIT", 21))
            for keys in (b"xecho hello" + pad, b"\x07", b"\x03"):
                shell.send(keys)
                shell.settle()
        finally:
            shell.close()
        dumps = [line for line in log.read_text(errors="replace").splitlines() if line.startswith("RH:")]
        self.assertEqual(len(dumps), 3, f"region_highlight 落盘条数不对: {dumps}")
        short, over_limit, no_limit = dumps
        self.assertIn("fg=green", short, f"未越界时有效命令应是 fg=green: {short}")
        self.assertNotEqual(over_limit, "RH::END", f"越界后 region_highlight 被清空（与文档措辞不符）: {over_limit}")
        self.assertNotIn("fg=red", over_limit, f"越界后仍重新解析了整个 buffer: {over_limit}")
        self.assertIn("fg=red", no_limit, f"去掉 MAXLENGTH 后应重新解析并标出不存在的命令: {no_limit}")

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

    def test_real_tty_keeps_gitstatusd(self):
        # GX-15 的对照面：真 PTY 里 gitstatus 照常拉起（非 tty 关闭不影响交互体验）。
        data = self.session([
            marked("print -r -- GS:${POWERLEVEL9K_DISABLE_GITSTATUS:-unset} PID:${GITSTATUS_DAEMON_PID_POWERLEVEL9K:-none}", 60),
        ], TERM_PROGRAM="WezTerm")
        value = captured(data, "GS", 60)
        self.assertTrue(value.startswith(b"unset PID:"), value)
        self.assertNotIn(b"none", value, "真 PTY 里 gitstatusd 未拉起")


class WeztermLegacyBlock(unittest.TestCase):
    """~/.zshrc 归属 gx 层：wezterm 安装器历史追加的「# >>> wezterm-gx >>>」cursor-mode
    键位块已由 gx/config/zshrc 承接；部署（备份 + 整体替换）后标记块被剥离、备份原样
    保留，双光标模式键位在真 PTY 里生效。"""

    MARKER_BLOCK = """\
# >>> wezterm-gx >>>
# WezTerm 在普通/应用光标模式下会发送两组不同序列，两组都显式覆盖。
autoload -Uz up-line-or-beginning-search down-line-or-beginning-search
zle -N up-line-or-beginning-search
zle -N down-line-or-beginning-search
zstyle ':zle:up-line-or-beginning-search' leave-cursor yes
zstyle ':zle:down-line-or-beginning-search' leave-cursor yes
for keymap in emacs viins; do
  bindkey -M "$keymap" '^[[A' up-line-or-beginning-search
  bindkey -M "$keymap" '^[OA' up-line-or-beginning-search
  bindkey -M "$keymap" '^[[B' down-line-or-beginning-search
  bindkey -M "$keymap" '^[OB' down-line-or-beginning-search
done
# <<< wezterm-gx <<<
"""

    @classmethod
    def setUpClass(cls):
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="gx-wezblock-"))
        cls.home = cls.root / "home"
        cls.home.mkdir()
        (cls.home / ".zshrc").write_text("# legacy user zshrc\n" + cls.MARKER_BLOCK, encoding="utf-8")
        result = run_installer(cls.home, "--zsh", str(cls.home / ".oh-my-zsh"))
        if result.returncode != 0:
            raise AssertionError(f"gx/install.sh 部署失败 rc={result.returncode}\n{result.stdout}\n{result.stderr}")
        cls.install_out = result.stdout

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_marker_block_stripped_and_backup_faithful(self):
        text = (self.home / ".zshrc").read_text(encoding="utf-8")
        # 钉行首锚定：gx/config/zshrc 的承接注释会提及标记字面量，但真实标记块
        # 的边界行必须整行就是标记本身。
        self.assertNotRegex(text, r"(?m)^# >>> wezterm-gx >>>$", "部署后的 .zshrc 仍含 wezterm-gx 起始标记行")
        self.assertNotRegex(text, r"(?m)^# <<< wezterm-gx <<<$", "部署后的 .zshrc 仍含 wezterm-gx 结束标记行")
        self.assertIn("up-line-or-beginning-search", text, "承接后的 cursor-mode 键位不在 .zshrc")
        self.assertIn("wezterm-gx", self.install_out, "安装器未打印剥离提示")
        backups = sorted(self.home.glob(".zshrc.pre-gx-*"))
        self.assertTrue(backups, "历史 .zshrc 没有产生备份")
        self.assertRegex(backups[-1].read_text(encoding="utf-8"), r"(?m)^# >>> wezterm-gx >>>$",
                         "备份未原样保留历史标记块")

    def test_cursor_keys_live_in_real_pty(self):
        shell = PtySession(self.home, TERM_PROGRAM="WezTerm")
        try:
            shell.settle()
            shell.command(*marked("print -r -- S40", 40))
            shell.send(b"bindkey -M emacs '^[[A'\n")   # 普通光标模式 Up
            shell.settle()
            shell.command(*marked("print -r -- S41", 41))
            shell.send(b"bindkey -M viins '^[OB'\n")   # 应用光标模式 Down
            shell.settle()
            shell.command(*marked("print -r -- S42", 42))
            shell.send(b"bindkey -M emacs '^P'\n")     # emacs 前缀历史
            shell.settle()
            shell.command(*marked("print -r -- S43", 43))
        finally:
            data = shell.close()
        for lo, hi, want in ((1040, 1041, b"up-line-or-beginning-search"),
                             (1041, 1042, b"down-line-or-beginning-search"),
                             (1042, 1043, b"up-line-or-beginning-search")):
            body = segment(data, f":M{lo}".encode(), f":M{hi}".encode())
            self.assertEqual(body.count(want), 1, f"bindkey 输出 {want!r} 出现次数不对: {body!r}")


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
