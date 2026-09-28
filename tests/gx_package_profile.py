"""GX 包 profile 的隔离回归；须在有真实 Zsh/PTY 的 POSIX 环境运行（Windows 使用 WSL）。"""
import hashlib
import os
import pathlib
import select
import shutil
import subprocess
import tempfile
import time
import unittest


REPO = pathlib.Path(__file__).resolve().parents[1]
PLUGINS = ("git", "sudo", "extract", "colored-man-pages", "nvm", "herdr")


def make_writable(root):
    for path in [root, *root.rglob("*")]:
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() else 0o644)


def tree_snapshot(root):
    result = {}
    for path in root.rglob("*"):
        info = path.stat()
        digest = None
        if path.is_file():
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except PermissionError:
                digest = ("unreadable", info.st_size, info.st_mtime_ns)
        result[str(path.relative_to(root))] = (info.st_mode, digest)
    return result


class PackageProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != "posix":
            raise AssertionError("需要真实 POSIX Zsh/PTY；Windows 请在 WSL 运行，不支持整族 skip")
        selected = os.environ.get("GX_TEST_ZSH")
        if selected is not None:
            if not pathlib.Path(selected).is_absolute() or not pathlib.Path(selected).is_file() or not os.access(selected, os.X_OK):
                raise AssertionError("GX_TEST_ZSH 必须是存在且可执行的绝对 Zsh/runtime wrapper 路径")
            cls.zsh = selected
        else:
            cls.zsh = shutil.which("zsh")
            if cls.zsh is None:
                raise AssertionError("缺少真实 Zsh；安装运行时或显式指定 GX_TEST_ZSH，不支持整族 skip")
        print(f"GX profile tests runtime: {cls.zsh} ({'GX_TEST_ZSH' if selected is not None else 'system PATH'})", flush=True)
        cls.sandbox = pathlib.Path(tempfile.mkdtemp(prefix="gx-package-profile-"))
        cls.addClassCleanup(cls.cleanup_sandbox)
        cls.resources = cls.sandbox / "资源 root ' $(touch injected) [x]"
        cls.resources.mkdir()
        shutil.copy2(REPO / "oh-my-zsh.sh", cls.resources)
        for name in ("lib", "tools"):
            shutil.copytree(REPO / name, cls.resources / name)
        for name in PLUGINS:
            shutil.copytree(REPO / "plugins" / name, cls.resources / "plugins" / name)
        (cls.resources / "custom").mkdir()
        (cls.resources / "gx/config").mkdir(parents=True)
        for name in ("zshrc", "zshenv", "package.zsh", "p10k.zsh", "terminal.zsh"):
            shutil.copy2(REPO / "gx/config" / name, cls.resources / "gx/config" / name)
        shutil.copy2(REPO / "gx/install.sh", cls.resources / "gx/install.sh")
        shutil.copytree(
            REPO / "gx/omz-custom/themes/powerlevel10k",
            cls.resources / "gx/omz-custom/themes/powerlevel10k",
            ignore=shutil.ignore_patterns("*.zwc", "*.tmp.*", ".git"),
        )
        (cls.resources / "gx/bin").mkdir()
        for name in ("gitstatusd-linux-x86_64", "zoxide-linux-x86_64"):
            shutil.copy2(REPO / "gx/bin" / name, cls.resources / "gx/bin" / name)
        for path in [*cls.resources.rglob("*"), cls.resources]:
            if path.is_file() and path.parent != cls.resources / "gx/bin":
                data = path.read_bytes()
                if b"\0" not in data and b"\r\n" in data:
                    path.write_bytes(data.replace(b"\r\n", b"\n"))
            path.chmod(0o755 if path.is_dir() else 0o644)
        cls.source_snapshot = tree_snapshot(cls.resources)
        cls.theme_id = hashlib.sha256((repr(tree_snapshot(cls.resources / "gx/omz-custom/themes/powerlevel10k"))
                                       + cls.zsh).encode("utf-8")).hexdigest()
        cls.system_path = cls.sandbox / "system-bin"
        cls.system_path.mkdir()
        hidden = {"herdr", "fzf", "zoxide", "atuin", "fd", "fdfind", "rg", "zsh"}
        for directory in (pathlib.Path("/usr/bin"), pathlib.Path("/bin")):
            for binary in directory.iterdir():
                target = cls.system_path / binary.name
                if binary.name not in hidden and not target.exists() and not target.is_symlink():
                    target.symlink_to(binary)
        shell = cls.system_path / "zsh"
        shell.write_text('#!/bin/sh\nexec "$GX_TEST_SELECTED_ZSH" "$@"\n')
        shell.chmod(0o755)

    @classmethod
    def cleanup_sandbox(cls):
        make_writable(cls.sandbox)
        shutil.rmtree(cls.sandbox)

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="case-", dir=self.sandbox))
        self.home = self.root / "宿主 HOME"
        self.profile = self.root / "配置 profile ' $(touch injected) [x]"
        self.bin = self.root / "bin"
        self.tmp = self.root / "tmp"
        for directory in (self.home, self.profile, self.bin, self.tmp):
            directory.mkdir()
        shutil.copyfile(self.resources / "gx/config/zshrc", self.profile / ".zshrc")
        (self.profile / ".zshenv").write_text("skip_global_compinit=1\n", encoding="utf-8")
        self.runtime = self.prepare_p10k_runtime(self.profile)
        self.env = {
            "PATH": f"{self.bin}:{self.system_path}",
            "HOME": str(self.home), "ZDOTDIR": str(self.profile), "TMPDIR": str(self.tmp),
            "TERM": "xterm-256color", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "GX_PACKAGE_ROOT": str(self.resources), "GX_PROFILE_DIR": str(self.profile),
            "GX_P10K_RUNTIME_DIR": str(self.runtime), "GX_TEST_SELECTED_ZSH": self.zsh,
        }

    def prepare_p10k_runtime(self, profile, cache_id=None):
        destination = profile / ".cache/themes" / (cache_id or self.theme_id) / "powerlevel10k"
        if not destination.exists():
            shutil.copytree(self.resources / "gx/omz-custom/themes/powerlevel10k", destination,
                            ignore=shutil.ignore_patterns("*.zwc", "*.tmp.*"))
        return destination

    def tearDown(self):
        self.assertEqual(tree_snapshot(self.resources), self.source_snapshot, "资源树发生运行时写入")
        self.assertFalse((self.home / "injected").exists(), "路径被当成了 shell 代码")
        make_writable(self.root)
        shutil.rmtree(self.root)

    def run_zsh(self, script, *, env=None, interactive=True):
        result = subprocess.run(
            [self.zsh, "-i" if interactive else "-f", "-c", script],
            env=self.env if env is None else env, cwd=self.home,
            capture_output=True, text=True, encoding="utf-8", errors="backslashreplace",
            start_new_session=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "", result.stdout + result.stderr)
        return result.stdout

    def run_tty_command(self, script, *, zle=True, env=None):
        import fcntl
        import pty
        import struct
        import termios

        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        environment = dict(self.env if env is None else env, POWERLEVEL9K_DISABLE_GITSTATUS="true")
        child = subprocess.Popen(
            [self.zsh, "-i", *([] if zle else ["+Z"]), "-c", script],
            env=environment, cwd=environment["HOME"],
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
            preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
        )
        os.close(slave)
        output = bytearray()
        deadline = time.monotonic() + 30
        try:
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        break
                    if not data:
                        break
                    output.extend(data)
                elif child.poll() is not None:
                    break
            self.assertEqual(child.wait(timeout=5), 0, bytes(output))
        finally:
            os.close(master)
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
        text = output.decode("utf-8", errors="backslashreplace").replace("\r\n", "\n")
        self.assertNotIn("can't change option", text)
        return text

    def shim(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_module_without_package_variables_is_noop(self):
        env = {key: value for key, value in self.env.items() if not key.startswith("GX_")}
        env.update(MODULE=str(self.resources / "gx/config/package.zsh"), ZSH="legacy-root", HISTFILE="legacy-history")
        out = self.run_zsh('source "$MODULE"; print -r -- "$ZSH|$HISTFILE|${XDG_CACHE_HOME-unset}"',
                           env=env, interactive=False)
        self.assertEqual(out, "legacy-root|legacy-history|unset\n")
        self.assertEqual(list(self.home.iterdir()), [])

    def msys_zoxide_env(self):
        self.shim("zoxide", "exit 0")
        self.shim("uname", "printf 'MSYS_NT-10.0-26100\\n'")
        return dict(self.env, GX_PACKAGE_BIN=str(self.bin), MODULE=str(self.resources / "gx/config/package.zsh"))

    def test_msys_zoxide_default_uses_native_profile_directory(self):
        env = self.msys_zoxide_env()
        self.shim("cygpath", 'printf "%s\\n" "$@" > "$GX_PROFILE_DIR/cygpath-args"\n'
                            'printf "%s\\n" \'C:\\profile 中文\\.local\\share\\zoxide\'')
        out = self.run_zsh('OSTYPE=cygwin; source "$MODULE" || exit; print -r -- "$_ZO_DATA_DIR"',
                           env=env, interactive=False)
        self.assertEqual(out, "C:\\profile 中文\\.local\\share\\zoxide\n")
        data = self.profile / ".local/share/zoxide"
        self.assertTrue(data.is_dir())
        self.assertEqual((self.profile / "cygpath-args").read_text().splitlines(), ["-w", "--", str(data)])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_msys_zoxide_explicit_directory_is_preserved(self):
        env = self.msys_zoxide_env()
        explicit = "C:\\user data\\中文 $(touch injected)"
        env["_ZO_DATA_DIR"] = explicit
        out = self.run_zsh('OSTYPE=cygwin; source "$MODULE" || exit; print -r -- "$_ZO_DATA_DIR"',
                           env=env, interactive=False)
        self.assertEqual(out, explicit + "\n")
        self.assertFalse((self.profile / ".local").exists())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_msys_zoxide_refuses_path_escape_and_failed_conversion(self):
        env = self.msys_zoxide_env()
        self.shim("cygpath", "exit 7")
        result = subprocess.run([self.zsh, "-f", "-c", 'OSTYPE=cygwin; source "$MODULE"'],
                                env=env, cwd=self.home, capture_output=True, text=True, start_new_session=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("native zoxide data directory", result.stderr)
        self.assertFalse((self.profile / ".local").exists())
        (self.profile / ".local").symlink_to(self.home, target_is_directory=True)
        result = subprocess.run([self.zsh, "-f", "-c", 'OSTYPE=cygwin; source "$MODULE"'],
                                env=env, cwd=self.home, capture_output=True, text=True, start_new_session=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stay inside GX_PROFILE_DIR", result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_non_msys_zoxide_keeps_standard_data_directory_semantics(self):
        self.shim("zoxide", "exit 0")
        for ostype, kernel in (("linux-gnu", "Linux"), ("cygwin", "CYGWIN_NT-10.0")):
            self.shim("uname", f"printf '{kernel}\\n'")
            for value in (None, "", "/explicit/用户 database"):
                with self.subTest(ostype=ostype, value=value):
                    env = dict(self.env, MODULE=str(self.resources / "gx/config/package.zsh"), GX_TEST_OSTYPE=ostype)
                    if value is not None:
                        env["_ZO_DATA_DIR"] = value
                    out = self.run_zsh('OSTYPE=$GX_TEST_OSTYPE; source "$MODULE" || exit; '
                                       'print -r -- "${_ZO_DATA_DIR-unset}"', env=env, interactive=False)
                    self.assertEqual(out, ("unset" if value is None else value) + "\n")
                    self.assertFalse((self.profile / ".local").exists())

    def test_host_xdg_locations_and_home_are_preserved(self):
        locations = {
            "XDG_CONFIG_HOME": self.home / "existing config",
            "XDG_DATA_HOME": self.home / "existing data",
            "XDG_STATE_HOME": self.home / "existing state",
        }
        for directory in locations.values():
            directory.mkdir()
            (directory / "sentinel").write_text("unchanged\n")
        before = tree_snapshot(self.home)
        for mode in ("set", "unset", "empty"):
            with self.subTest(mode=mode):
                env = dict(self.env, HERDR_CONFIG_PATH=str(self.profile / "herdr/config.toml"),
                           HERDR_SESSION="ohmyzsh-gx")
                if mode != "unset":
                    env.update({key: str(value) if mode == "set" else "" for key, value in locations.items()})
                out = self.run_zsh('print -rl -- "${XDG_CONFIG_HOME-unset}" "${XDG_DATA_HOME-unset}" '
                                   '"${XDG_STATE_HOME-unset}" "$HOME" "$HERDR_CONFIG_PATH" "$HERDR_SESSION"',
                                   env=env)
                expected = [str(value) for value in locations.values()] if mode == "set" else [mode if mode == "unset" else ""] * 3
                self.assertEqual(out.splitlines(), [*expected, str(self.home),
                                                    str(self.profile / "herdr/config.toml"), "ohmyzsh-gx"])
                self.assertEqual(tree_snapshot(self.home), before)
                for directory in (".config", ".local/share", ".local/state"):
                    self.assertFalse((self.profile / directory).exists())

    def test_launcher_bootstrap_zdotdir_is_preserved(self):
        bootstrap = self.root / "ascii-bootstrap"
        bootstrap.mkdir()
        (bootstrap / ".zshenv").write_text("skip_global_compinit=1\n")
        (bootstrap / ".zshrc").write_text('source "$GX_PACKAGE_ROOT/gx/config/zshrc"\n')
        out = self.run_zsh('print -rl -- "$ZDOTDIR" "$GX_PROFILE_DIR" "$HOME" "${+functions[omz]}"',
                           env=dict(self.env, ZDOTDIR=str(bootstrap)))
        self.assertEqual(out.splitlines(), [str(bootstrap), str(self.profile), str(self.home), "1"])
        self.assertFalse(list(bootstrap.glob(".zcompdump*")))
        self.assertTrue(list(self.profile.glob(".zcompdump-*")))
        env = dict(self.env, MODULE=str(self.resources / "gx/config/package.zsh"))
        env.pop("ZDOTDIR")
        out = self.run_zsh('source "$MODULE" || exit; print -r -- "${ZDOTDIR-unset}"', env=env, interactive=False)
        self.assertEqual(out, "unset\n")

    def test_package_bin_is_available_before_mkdir(self):
        package_bin = self.root / "工具 bin ' $(touch injected) [x]"
        package_bin.mkdir()
        mkdir = package_bin / "mkdir"
        mkdir.write_text('#!/bin/sh\nprintf "called\\n" > "$GX_PROFILE_DIR/package-mkdir.log"\nexec /bin/mkdir "$@"\n')
        mkdir.chmod(0o755)
        agent = package_bin / "gx-package-agent"
        agent.write_text('#!/bin/sh\nprintf "agent:%s\\n" "$1"\n')
        agent.chmod(0o755)
        env = dict(self.env, GX_PACKAGE_BIN=str(package_bin),
                   MODULE=str(self.resources / "gx/config/package.zsh"))
        out = self.run_zsh('path=(/no/inherited/tools); source "$MODULE" || exit; print -r -- "$path[1]"; '
                           'command gx-package-agent ready', env=env, interactive=False)
        self.assertEqual(out, f"{package_bin}\nagent:ready\n")
        self.assertEqual((self.profile / "package-mkdir.log").read_text(), "called\n")
        self.assertTrue((self.profile / ".cache/oh-my-zsh/completions").is_dir())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_missing_or_invalid_optional_package_bin_is_not_added(self):
        not_directory = self.root / "bin-file"
        not_directory.write_text("not a directory\n")
        colon_bin = self.root / "colon:bin"
        newline_bin = self.root / "newline\nbin"
        for directory in (colon_bin, newline_bin):
            directory.mkdir()
        for value in (None, "", "relative", str(self.root / "missing-bin"), str(not_directory),
                      str(colon_bin), str(newline_bin)):
            with self.subTest(value=value):
                env = dict(self.env, MODULE=str(self.resources / "gx/config/package.zsh"))
                if value is not None:
                    env["GX_PACKAGE_BIN"] = value
                out = self.run_zsh('source "$MODULE" || exit; print -r -- "$PATH"', env=env, interactive=False)
                self.assertEqual(out, self.env["PATH"] + "\n")

    def test_cygwin_and_msys_restore_existing_posix_tool_directories(self):
        expected = [directory for directory in ("/usr/bin", "/ucrt64/bin") if pathlib.Path(directory).is_dir()]
        for ostype in ("cygwin", "msys"):
            with self.subTest(ostype=ostype):
                env = dict(self.env, MODULE=str(self.resources / "gx/config/package.zsh"),
                           GX_PACKAGE_BIN=str(self.bin), GX_TEST_OSTYPE=ostype)
                out = self.run_zsh('path=(/no/inherited/tools); OSTYPE=$GX_TEST_OSTYPE; source "$MODULE" || exit; '
                                   'print -rl -- "${path[@]}"', env=env, interactive=False)
                self.assertEqual(out.splitlines(), [str(self.bin), *expected, "/no/inherited/tools"])
                self.assertTrue((self.profile / ".cache/oh-my-zsh/completions").is_dir())

    def test_package_keeps_existing_user_tools_without_loading_machine_config(self):
        directories = [self.home / name for name in (".local/bin", ".kimi-code/bin", ".local/go/bin", "go/bin", ".cargo/bin", ".bun/bin")]
        for directory in directories:
            directory.mkdir(parents=True)
        agent = directories[0] / "gx-user-agent"
        agent.write_text('#!/bin/sh\nprintf "user-agent:%s\\n" "$1"\n')
        agent.chmod(0o755)
        for name in (".zshrc.local", ".p10k.zsh", ".bun/_bun"):
            (self.home / name).write_text('print host-machine-layer-loaded\nprint bad > "$HOME/host-write"\n')
        before = tree_snapshot(self.home)
        env = dict(self.env, GX_PACKAGE_BIN=str(self.bin), PATH=self.env["PATH"] + ":" + str(directories[0]))
        out = self.run_zsh('print -rl -- "${path[@]}"; command gx-user-agent ready', env=env)
        values = out.splitlines()
        self.assertEqual(values[0], str(self.bin))
        self.assertEqual(values[-1], "user-agent:ready")
        for directory in directories:
            self.assertEqual(values.count(str(directory)), 1)
        self.assertNotIn(str(self.home / ".opencode/bin"), values)
        self.assertEqual(tree_snapshot(self.home), before)

    def test_package_bin_restores_herdr_after_inherited_path_reset(self):
        profile = self.profile
        self.shim("herdr", 'if [ "$1 $2" = "completion zsh" ]; then printf "#compdef herdr\\n_herdr() { :; }\\n"; fi')
        env = dict(self.env, GX_PACKAGE_BIN=str(self.bin), PATH=str(self.system_path),
                   XDG_CONFIG_HOME=str(self.home / "existing config"))
        out = self.run_zsh('repeat 100; do [[ -s "$ZSH_CACHE_DIR/completions/_herdr" ]] && break; sleep 0.01; done; '
                           'print -rl -- "$commands[herdr]" "${aliases[hrdr]}" "$XDG_CONFIG_HOME"', env=env)
        self.assertEqual(out.splitlines(), [str(self.bin / "herdr"), "herdr", str(self.home / "existing config")])
        self.assertIn("#compdef herdr", (profile / ".cache/oh-my-zsh/completions/_herdr").read_text())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_non_tty_fixture_disables_gitstatus(self):
        out = self.run_zsh('print -r -- "${TTY:-none}|${POWERLEVEL9K_DISABLE_GITSTATUS:-unset}|'
                           '${GITSTATUS_DAEMON_PID_POWERLEVEL9K:-none}"')
        self.assertEqual(out, "none|true|none\n")

    def test_command_environment_skips_theme_but_keeps_omz_and_p10k_config(self):
        username = self.run_zsh('print -r -- "${(%):-%n}"', interactive=False).strip()
        instant = self.profile / ".cache" / f"p10k-instant-prompt-{username}.zsh"
        instant.write_text("typeset -g GX_TEST_INSTANT_SOURCED=1\n")
        instant_before = instant.read_bytes()
        runtime_before = tree_snapshot(self.runtime)
        out = self.run_zsh('print -rl -- "${TTY:-none}|${ZSH_THEME:-empty}|${+functions[omz]}|'
                           '${+functions[p10k]}|${+parameters[__p9k_root_dir]}|${GX_TEST_INSTANT_SOURCED:-0}" '
                           '"$POWERLEVEL9K_MODE" "${aliases[gco]}" "${widgets[up-line-or-beginning-search]}"')
        values = out.splitlines()
        self.assertEqual(values[:3], ["none|empty|1|0|0|0", "nerdfont-v3", "git checkout"])
        self.assertIn("up-line-or-beginning-search", values[3])
        cli = subprocess.run([self.zsh, "-i", "-c", "omz help"], env=self.env, cwd=self.home,
                             capture_output=True, text=True, start_new_session=True, timeout=30)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertEqual(cli.stdout, "")
        self.assertTrue(cli.stderr.startswith("Usage: omz <command> [options]\n"), cli.stderr)
        self.assertIn("Manage plugins", cli.stderr)
        self.assertNotIn("gitstatus", cli.stderr)
        self.assertEqual(instant.read_bytes(), instant_before)
        self.assertEqual(tree_snapshot(self.runtime), runtime_before)
        self.assertEqual(list(self.runtime.rglob("*.zwc")), [])
        self.assertEqual(list(self.home.iterdir()), [])

    def test_invalid_package_parameters_fail_before_home_or_profile_writes(self):
        bad_root = self.root / "incomplete"
        bad_root.mkdir()
        cases = (
            {"GX_PACKAGE_ROOT": None}, {"GX_PROFILE_DIR": None},
            {"GX_PACKAGE_ROOT": ""}, {"GX_PROFILE_DIR": ""},
            {"GX_PACKAGE_ROOT": "relative"}, {"GX_PROFILE_DIR": "relative"},
            {"GX_PACKAGE_ROOT": str(bad_root)},
            {"GX_PROFILE_DIR": str(self.root / "missing")},
            {"GX_PROFILE_DIR": str(self.home)},
            {"GX_PROFILE_DIR": str(self.resources)},
            {"GX_PROFILE_DIR": str(self.resources / "gx")},
            {"GX_PROFILE_DIR": str(self.sandbox)},
            {"GX_PROFILE_DIR": str(self.profile) + "\n"},
        )
        before = tree_snapshot(self.profile)
        for overrides in cases:
            with self.subTest(overrides=overrides):
                env = dict(self.env, CONFIG=str(self.resources / "gx/config/zshrc"))
                for key, value in overrides.items():
                    if value is None:
                        env.pop(key, None)
                    else:
                        env[key] = value
                result = subprocess.run([self.zsh, "-f", "-c", 'source "$CONFIG"'],
                                        env=env, cwd=self.home, capture_output=True, text=True, start_new_session=True, timeout=15)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("gx package:", result.stderr)
                self.assertEqual(list(self.home.iterdir()), [])
                self.assertEqual(tree_snapshot(self.profile), before)

    def test_symlink_cache_escape_fails_without_writing_home(self):
        (self.profile / ".cache").rename(self.root / "original-cache")
        (self.profile / ".cache").symlink_to(self.home, target_is_directory=True)
        env = dict(self.env, CONFIG=str(self.resources / "gx/config/zshrc"))
        result = subprocess.run([self.zsh, "-f", "-c", 'source "$CONFIG"'], env=env,
                                cwd=self.home, capture_output=True, text=True, start_new_session=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime paths", result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])

    def assert_runtime_rejected(self, value):
        env = dict(self.env, CONFIG=str(self.resources / "gx/config/zshrc"))
        if value is None:
            env.pop("GX_P10K_RUNTIME_DIR")
        else:
            env["GX_P10K_RUNTIME_DIR"] = str(value)
        before = tree_snapshot(self.profile)
        result = subprocess.run([self.zsh, "-f", "-c", 'source "$CONFIG"'], env=env, cwd=self.home,
                                capture_output=True, text=True, start_new_session=True, timeout=15)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GX_P10K_RUNTIME_DIR", result.stderr)
        self.assertEqual(tree_snapshot(self.profile), before)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_vendored_theme_requires_valid_runtime_before_omz(self):
        malformed = self.profile / ".cache/themes/not-a-digest/powerlevel10k"
        shutil.copytree(self.runtime, malformed)
        absent = self.profile / ".cache/themes" / ("e" * 64) / "powerlevel10k"
        for value in (None, "", "relative", self.resources / "gx/omz-custom/themes/powerlevel10k",
                      malformed, absent, self.runtime.parent, str(self.runtime) + "\n"):
            with self.subTest(value=value):
                self.assert_runtime_rejected(value)

    def test_runtime_escaping_symlink_is_rejected(self):
        outside = self.root / "outside-theme"
        shutil.copytree(self.runtime, outside)
        escaped = self.profile / ".cache/themes" / ("d" * 64) / "powerlevel10k"
        escaped.parent.mkdir()
        escaped.symlink_to(outside, target_is_directory=True)
        self.assert_runtime_rejected(escaped)

    def test_runtime_requires_readable_contained_entry_files(self):
        for name in ("powerlevel10k.zsh-theme", "internal/p10k.zsh", "gitstatus/gitstatus.plugin.zsh"):
            with self.subTest(name=name):
                target = self.runtime / name
                saved = target.with_name(target.name + ".saved")
                target.rename(saved)
                try:
                    self.assert_runtime_rejected(self.runtime)
                    target.symlink_to(self.resources / "gx/omz-custom/themes/powerlevel10k" / name)
                    self.assert_runtime_rejected(self.runtime)
                    target.unlink()
                    saved.rename(target)
                    target.chmod(0)
                    self.assert_runtime_rejected(self.runtime)
                finally:
                    if saved.exists():
                        if target.is_symlink():
                            target.unlink()
                        saved.rename(target)
                    target.chmod(0o644)

    def test_writable_resource_tree_uses_only_profile_theme_cache(self):
        self.assertTrue(os.access(self.resources / "gx/omz-custom/themes/powerlevel10k", os.W_OK))
        self.assertEqual(list(self.runtime.rglob("*.zwc")), [])
        out = self.run_tty_command('print -rl -- "$__p9k_root_dir" "$POWERLEVEL9K_INSTALLATION_DIR" "$ZSH_CUSTOM"')
        self.assertEqual(out.splitlines(), [str(self.runtime), str(self.runtime), str(self.resources / "gx/omz-custom")])
        self.assertEqual(len(list(self.runtime.rglob("*.zwc"))), 9)
        before = tree_snapshot(self.runtime)
        compiled_times = {p: p.stat().st_mtime_ns for p in self.runtime.rglob("*.zwc")}
        self.run_tty_command('[[ $+functions[p10k] == 1 ]]')
        self.assertEqual(tree_snapshot(self.runtime), before)
        self.assertEqual({p: p.stat().st_mtime_ns for p in self.runtime.rglob("*.zwc")}, compiled_times)
        self.assertFalse(list(self.resources.rglob("*.zwc")))

    def test_new_runtime_fingerprint_preserves_old_cache_and_rolls_back(self):
        self.run_tty_command('[[ $+functions[p10k] == 1 ]]')
        old = tree_snapshot(self.runtime)
        new_id = hashlib.sha256((self.theme_id + "upgrade").encode()).hexdigest()
        upgraded = self.prepare_p10k_runtime(self.profile, new_id)
        out = self.run_tty_command('print -r -- "$__p9k_root_dir"', env=dict(self.env, GX_P10K_RUNTIME_DIR=str(upgraded)))
        self.assertEqual(out.strip(), str(upgraded))
        self.assertEqual(len(list(upgraded.rglob("*.zwc"))), 9)
        self.assertEqual(tree_snapshot(self.runtime), old)
        out = self.run_tty_command('print -r -- "$__p9k_root_dir"')
        self.assertEqual(out.strip(), str(self.runtime))
        self.assertEqual(tree_snapshot(self.runtime), old)

    def test_vendored_symlink_custom_uses_runtime_and_preserves_custom_files(self):
        custom = self.root / "用户 custom"
        custom.mkdir()
        (custom / "themes").symlink_to(self.resources / "gx/omz-custom/themes", target_is_directory=True)
        (custom / "local.zsh").write_text("typeset -g GX_USER_CUSTOM=preserved\n")
        before = tree_snapshot(custom)
        out = self.run_tty_command('print -rl -- "$ZSH_CUSTOM" "$GX_USER_CUSTOM" "$__p9k_root_dir"',
                                   env=dict(self.env, ZSH_CUSTOM=str(custom)))
        self.assertEqual(out.splitlines(), [str(custom), "preserved", str(self.runtime)])
        self.assertEqual(tree_snapshot(custom), before)

    def test_independent_custom_theme_needs_no_vendored_runtime(self):
        custom = self.root / "独立 custom"
        theme = custom / "themes/powerlevel10k"
        shutil.copytree(self.resources / "gx/omz-custom/themes/powerlevel10k", theme)
        (custom / "local.zsh").write_text("typeset -g GX_USER_CUSTOM=independent\n")
        source_before = tree_snapshot(custom)
        cache_before = tree_snapshot(self.runtime)
        for with_runtime in (False, True):
            with self.subTest(with_runtime=with_runtime):
                env = dict(self.env, ZSH_CUSTOM=str(custom))
                if not with_runtime:
                    env.pop("GX_P10K_RUNTIME_DIR")
                out = self.run_tty_command('print -rl -- "$ZSH_CUSTOM" "$__p9k_root_dir" "$GX_USER_CUSTOM" '
                                           '"${POWERLEVEL9K_INSTALLATION_DIR-unset}"', env=env)
                self.assertEqual(out.splitlines(), [str(custom), str(theme), "independent", "unset"])
                self.assertEqual({key: value for key, value in tree_snapshot(custom).items() if not key.endswith(".zwc")},
                                 source_before)
                self.assertEqual(tree_snapshot(self.runtime), cache_before)

    def test_explicit_independent_installation_dir_is_respected(self):
        independent = self.root / "用户 P10k"
        shutil.copytree(self.resources / "gx/omz-custom/themes/powerlevel10k", independent)
        cache_before = tree_snapshot(self.runtime)
        for with_runtime in (False, True):
            with self.subTest(with_runtime=with_runtime):
                env = dict(self.env, POWERLEVEL9K_INSTALLATION_DIR=str(independent))
                if not with_runtime:
                    env.pop("GX_P10K_RUNTIME_DIR")
                out = self.run_tty_command('print -rl -- "$POWERLEVEL9K_INSTALLATION_DIR" "$__p9k_root_dir"', env=env)
                self.assertEqual(out.splitlines(), [str(independent), str(independent)])
                self.assertEqual(tree_snapshot(self.runtime), cache_before)

    def test_explicit_vendored_installation_dir_still_requires_runtime(self):
        env = dict(self.env, POWERLEVEL9K_INSTALLATION_DIR=str(self.resources / "gx/omz-custom/themes/powerlevel10k"))
        out = self.run_tty_command('print -r -- "$__p9k_root_dir"', env=env)
        self.assertEqual(out.strip(), str(self.runtime))
        env.pop("GX_P10K_RUNTIME_DIR")
        env["CONFIG"] = str(self.resources / "gx/config/zshrc")
        result = subprocess.run([self.zsh, "-f", "-c", 'source "$CONFIG"'], env=env, cwd=self.home,
                                capture_output=True, text=True, start_new_session=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GX_P10K_RUNTIME_DIR", result.stderr)

    def test_interactive_package_uses_readonly_resources_and_profile_state(self):
        inherited = self.root / "inherited-cache"
        inherited.mkdir()
        env = dict(self.env, XDG_CACHE_HOME=str(inherited), ZSH_CACHE_DIR=str(inherited),
                   ZSH_COMPDUMP=str(self.home / "bad-dump"), HISTFILE=str(self.home / "bad-history"),
                   GITSTATUS_CACHE_DIR=str(self.root / "launcher-gitstatus"))
        out = self.run_zsh('print -rl -- "$ZSH" "$ZSH_CUSTOM" "$ZDOTDIR" "$ZSH_CACHE_DIR" '
                           '"$ZSH_COMPDUMP" "$HISTFILE" "$XDG_CACHE_HOME" "$GITSTATUS_CACHE_DIR" '
                           '"$GITSTATUS_AUTO_INSTALL" "${+functions[omz]}:${+functions[p10k]}" '
                           '"$POWERLEVEL9K_MODE"; print -r -- "${(j:,:)plugins}"; '
                           'print -s -- GX_PACKAGE_HISTORY; fc -AI', env=env)
        values = out.splitlines()
        self.assertEqual(values[:4], [str(self.resources), str(self.resources / "gx/omz-custom"),
                                      str(self.profile), str(self.profile / ".cache/oh-my-zsh")])
        self.assertTrue(values[4].startswith(str(self.profile / ".zcompdump-")))
        self.assertEqual(values[5:11], [str(self.profile / ".zsh_history"), str(self.profile / ".cache"),
                                       str(self.root / "launcher-gitstatus"), "0", "1:0", "nerdfont-v3"])
        self.assertEqual(values[11], ",".join(PLUGINS))
        self.assertTrue(pathlib.Path(values[4]).is_file())
        self.assertTrue((self.profile / ".cache/oh-my-zsh/completions").is_dir())
        self.assertIn("GX_PACKAGE_HISTORY", (self.profile / ".zsh_history").read_text())
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(list(inherited.iterdir()), [])

    def test_profile_config_precedence_and_no_host_machine_layer(self):
        for name in (".p10k.zsh", ".zshrc.local"):
            (self.home / name).write_text('print host-config-loaded\nprint bad > "$HOME/host-write"\n')
        (self.home / ".bun").mkdir()
        (self.home / ".bun/_bun").write_text('print host-bun-loaded\n')
        (self.profile / ".p10k.zsh").write_text("typeset -g GX_TEST_CONFIG=profile\n")
        (self.profile / ".zshrc.local").write_text("typeset -g GX_TEST_LOCAL=profile\n")
        before = tree_snapshot(self.home)
        out = self.run_zsh('print -r -- "$GX_TEST_CONFIG|$GX_TEST_LOCAL|$POWERLEVEL9K_CONFIG_FILE"; '
                           'print -r -- "$PATH|$NVM_DIR"')
        self.assertEqual(out.splitlines()[0], f"profile|profile|{self.profile}/.p10k.zsh")
        self.assertNotIn(str(self.home), out)
        self.assertEqual(tree_snapshot(self.home), before)

    def test_explicit_custom_directory_is_respected(self):
        custom = self.root / "custom 中文"
        custom.mkdir()
        (custom / "themes").symlink_to(self.resources / "gx/omz-custom/themes", target_is_directory=True)
        (custom / "local.zsh").write_text("typeset -g GX_TEST_CUSTOM=loaded\n")
        out = self.run_tty_command('print -r -- "$ZSH_CUSTOM|$GX_TEST_CUSTOM|${+functions[p10k]}"',
                                   env=dict(self.env, ZSH_CUSTOM=str(custom)))
        self.assertEqual(out, f"{custom}|loaded|1\n")

    def test_missing_herdr_and_fzf_are_silent(self):
        out = self.run_zsh('print -r -- "${+functions[herdr_prompt_info]}:${+aliases[hrdr]}:${+functions[hrdrs]}"; '
                           'print -r -- "${FZF_DEFAULT_OPTS-unset}|${FZF_DEFAULT_COMMAND-unset}"')
        self.assertEqual(out, "1:0:0\nunset|unset\n")
        self.assertFalse((self.profile / ".cache/oh-my-zsh/completions/_herdr").exists())

    def test_herdr_aliases_and_completion_use_profile_cache(self):
        self.shim("herdr", 'if [ "$1 $2" = "completion zsh" ]; then printf "#compdef herdr\\n_herdr() { :; }\\n"; fi')
        out = self.run_zsh('repeat 100; do [[ -s "$ZSH_CACHE_DIR/completions/_herdr" ]] && break; sleep 0.01; done; '
                           'print -r -- "${aliases[hrdr]}|${+functions[hrdrs]}|${_comps[herdr]}"')
        self.assertEqual(out, "herdr|1|_herdr\n")
        self.assertIn("#compdef herdr", (self.profile / ".cache/oh-my-zsh/completions/_herdr").read_text())
        self.assertEqual(list(self.home.iterdir()), [])

    def embedded_fzf_shim(self):
        calls = self.root / "fzf-zsh.calls"
        self.env["GX_TEST_FZF_CALLS"] = str(calls)
        self.shim("fzf", '''case "$1" in
  --version) printf '0.74.4 (official-shape)\\n' ;;
  --zsh)
    printf 'called\\n' >> "$GX_TEST_FZF_CALLS"
    /bin/cat <<'ZSH'
__fzf_key_bindings_options="options=(${(j: :)${(kv)options[@]}})"
typeset -g GX_TEST_FZF=embedded
fzf-history-widget() { :; }
zle -N fzf-history-widget
bindkey '^R' fzf-history-widget
eval "$__fzf_key_bindings_options"
unset __fzf_key_bindings_options
ZSH
    ;;
  *) exit 2 ;;
esac''')
        return calls

    def test_fzf_074_embedded_zsh_integration(self):
        calls = self.embedded_fzf_shim()
        out = self.run_tty_command('print -r -- "$GX_TEST_FZF|$FZF_DEFAULT_OPTS|$options[zle]"; '
                                   'bindkey -M emacs "^R"')
        self.assertTrue(out.startswith("embedded|"), out)
        self.assertIn("--border=rounded", out)
        self.assertIn('|on\n"^R" fzf-history-widget\n', out)
        self.assertEqual(calls.read_text(), "called\n")

    def test_fzf_without_tty_keeps_options_and_static_completion(self):
        calls = self.embedded_fzf_shim()
        self.shim("fd", "exit 0")
        custom = self.root / "completion-custom"
        (custom / "completions").mkdir(parents=True)
        (custom / "themes").symlink_to(self.resources / "gx/omz-custom/themes", target_is_directory=True)
        (custom / "completions/_fzf").write_text("#compdef fzf\n_arguments '--version[show version]'\n")
        out = self.run_zsh('print -rl -- "${TTY:-none}|${GX_TEST_FZF-unset}" '
                           '"${+widgets[fzf-history-widget]}|${+widgets[fzf-completion]}|${_comps[fzf]}" '
                           '"$FZF_DEFAULT_COMMAND" "$FZF_DEFAULT_OPTS"', env=dict(self.env, ZSH_CUSTOM=str(custom)))
        values = out.splitlines()
        self.assertEqual(values[:3], ["none|unset", "0|0|_fzf", "fd --type f"])
        self.assertIn("--border=rounded", values[3])
        self.assertFalse(calls.exists(), "无 TTY 时不应请求含 ZLE 初始化的 --zsh")

    def test_fzf_without_zle_on_tty_keeps_options(self):
        self.shim("rg", "exit 0")
        for version in ("0.20.0", "0.74.4"):
            with self.subTest(version=version):
                calls = None
                if version == "0.74.4":
                    calls = self.embedded_fzf_shim()
                else:
                    self.shim("fzf", '[ "$1" = --version ] && { printf "0.20.0\\n"; exit 0; }; exit 2')
                out = self.run_tty_command('print -rl -- "${TTY:-none}|$options[zle]" '
                                           '"${+widgets[fzf-history-widget]}|${+widgets[fzf-completion]}" '
                                           '"$FZF_DEFAULT_COMMAND" "$FZF_DEFAULT_OPTS"', zle=False)
                values = out.splitlines()
                self.assertRegex(values[0], r"^/dev/.+\|off$")
                self.assertEqual(values[1:3], ["0|0", "rg --files"])
                self.assertEqual("--border=rounded" in values[3], version == "0.74.4")
                if calls is not None:
                    self.assertFalse(calls.exists())

    def test_old_fzf_option_contract_and_doc_integration(self):
        for version in ("0.20.0", "0.44.1 (d0466fa)", "fzf 0.20.0", "unknown"):
            with self.subTest(version=version):
                self.shim("fzf", f'[ "$1" = --version ] && {{ printf "%s\\n" "{version}"; exit 0; }}; exit 2')
                out = self.run_zsh('print -rl -- "$FZF_DEFAULT_OPTS" '
                                   '"${+widgets[fzf-history-widget]}|${+widgets[fzf-completion]}"')
                values = out.splitlines()
                self.assertEqual("--border=rounded" in values[0], version.startswith("0.44."))
                self.assertIn("--height=55%", values[0])
                self.assertIn("--border", values[0])
                self.assertEqual(values[1], "0|0")

    def test_old_fzf_doc_widgets_are_loaded_on_real_pty(self):
        for name in ("completion.zsh", "key-bindings.zsh"):
            self.assertTrue((pathlib.Path("/usr/share/doc/fzf/examples") / name).is_file(),
                            "本用例需要系统 fzf doc 脚本验证真实旧版集成")
        self.shim("fzf", '[ "$1" = --version ] && { printf "0.20.0\\n"; exit 0; }; exit 2')
        out = self.run_tty_command('print -r -- "$options[zle]|${+widgets[fzf-completion]}"; '
                                   'bindkey -M emacs "^R"; bindkey -M emacs "^I"')
        self.assertEqual(out, 'on|1\n"^R" fzf-history-widget\n"^I" fzf-completion\n')

    def test_fzf_default_command_priority_without_tty(self):
        self.shim("fzf", '[ "$1" = --version ] && { printf "0.20.0\\n"; exit 0; }; exit 2')
        cases = ((("fd", "fdfind", "rg"), "fd --type f"), (("fdfind", "rg"), "fdfind --type f"),
                 (("rg",), "rg --files"), ((), "unset"))
        for commands, expected in cases:
            with self.subTest(commands=commands):
                for name in ("fd", "fdfind", "rg"):
                    (self.bin / name).unlink(missing_ok=True)
                for name in commands:
                    self.shim(name, "exit 0")
                out = self.run_zsh('print -rl -- "${FZF_DEFAULT_COMMAND-unset}" "$FZF_DEFAULT_OPTS" '
                                   '"${+widgets[fzf-history-widget]}"')
                values = out.splitlines()
                self.assertEqual(values[0], expected)
                self.assertIn("--border", values[1])
                self.assertNotIn("--border=rounded", values[1])
                self.assertEqual(values[2], "0")

    def test_cursor_block_position_contract_is_preserved(self):
        text = (self.resources / "gx/config/zshrc").read_text(encoding="utf-8")
        positions = [text.index(value) for value in (
            "fzf/examples/key-bindings.zsh", "autoload -Uz up-line-or-beginning-search",
            "zsh-autosuggestions/zsh-autosuggestions.zsh", "zsh-syntax-highlighting/zsh-syntax-highlighting.zsh")]
        self.assertEqual(positions, sorted(positions))

    def test_installer_legacy_default_and_custom_zsh_paths(self):
        source = self.root / "legacy-source"
        shutil.copytree(self.resources, source)
        make_writable(source)
        for binary in (source / "gx/bin").iterdir():
            binary.chmod(0o755)
        for custom in (False, True):
            with self.subTest(custom=custom):
                home = self.root / ("legacy custom HOME" if custom else "legacy HOME")
                home.mkdir()
                (home / ".zshrc.local").write_text("typeset -g GX_TEST_LOCAL=legacy\n")
                target = home / ("定制 OMZ" if custom else ".oh-my-zsh")
                env = {key: value for key, value in self.env.items() if not key.startswith("GX_")}
                env.update(HOME=str(home), ZDOTDIR=str(home), GITSTATUS_CACHE_DIR=str(home / ".cache/gitstatus"),
                           GX_TEST_SELECTED_ZSH=self.zsh)
                argv = ["sh", str(source / "gx/install.sh"), "--home", str(home), "--skip-apt", "--skip-fonts",
                        "--skip-wezterm", "--skip-chsh", "--unattended"]
                if custom:
                    argv += ["--zsh", str(target)]
                result = subprocess.run(argv, env=env, cwd=home, capture_output=True, text=True, start_new_session=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                script = ('print -rl -- "$ZSH" "$ZSH_CUSTOM" "$HISTFILE" '
                          '"$GX_TEST_LOCAL" "${+functions[omz]}:${+functions[p10k]}"')
                out = self.run_zsh(script, env=env)
                self.assertEqual(out.splitlines(), [str(target), str(target / "custom"),
                                                    str(home / ".zsh_history"), "legacy", "1:0"])
                out = self.run_tty_command(script, env=env)
                self.assertEqual(out.splitlines(), [str(target), str(target / "custom"),
                                                    str(home / ".zsh_history"), "legacy", "1:1"])
                self.assertNotIn("GX_PACKAGE_ROOT=", (home / ".zshrc").read_text())

    def pty_session(self):
        import fcntl
        import pty
        import struct
        import termios

        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        child = subprocess.Popen(
            [self.zsh, "-i"], env=self.env, cwd=self.home,
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
            preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0),
        )
        os.close(slave)
        output = bytearray()
        marker = b"\r\nGX_READY:71391\r\n"
        deadline = time.monotonic() + 40
        prompt_at = ready_at = None
        sent_command = sent_exit = False
        try:
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        break
                    if not data:
                        break
                    output.extend(data)
                if b"\x1b[?2004h" in output and prompt_at is None:
                    prompt_at = time.monotonic()
                if prompt_at is not None and time.monotonic() - prompt_at > 0.5 and not sent_command:
                    os.write(master, b'print -r -- "GX_TTY:$TTY"; '
                                     b'print -r -- "GX_PROMPT:$ZSH_THEME|${+functions[p10k]}|'
                                     b'${POWERLEVEL9K_DISABLE_GITSTATUS:-unset}|${GITSTATUS_DAEMON_PID_POWERLEVEL9K:-none}"; '
                                     b'print -r -- GX_READY:$((71390+1))\n')
                    sent_command = True
                if marker in output and ready_at is None:
                    ready_at = time.monotonic()
                if ready_at is not None and time.monotonic() - ready_at > 0.5 and not sent_exit:
                    os.write(master, b"exit\n")
                    sent_exit = True
                if child.poll() is not None:
                    break
            self.assertIn(marker, output, bytes(output[-4000:]))
            self.assertEqual(child.wait(timeout=10), 0, bytes(output[-4000:]))
        finally:
            os.close(master)
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
        return bytes(output)

    def prepare_gitstatus(self):
        cache = self.profile / ".cache/gitstatus"
        cache.mkdir(parents=True)
        daemon = cache / "gitstatusd-linux-x86_64"
        shutil.copyfile(self.resources / "gx/bin/gitstatusd-linux-x86_64", daemon)
        daemon.chmod(0o755)
        self.env["GITSTATUS_CACHE_DIR"] = str(cache)

    def test_real_pty_instant_prompt_and_history_stay_in_profile(self):
        self.prepare_gitstatus()
        (self.profile / ".zshrc.local").write_text(
            'print -r -- "${__p9k_instant_prompt_active:-0}" > "$GX_PROFILE_DIR/instant-observed"\n')
        first = self.pty_session()
        self.assertTrue(list((self.profile / ".cache").glob("p10k-instant-prompt-*.zsh")), first[-4000:])
        self.assertEqual(len(list(self.runtime.rglob("*.zwc"))), 9)
        second = self.pty_session()
        for data in (first, second):
            self.assertIn(b"GX_TTY:/dev/", data)
            self.assertRegex(data, rb"GX_PROMPT:powerlevel10k/powerlevel10k\|1\|unset\|[0-9]+\r?\n")
            self.assertNotIn(b"failed to initialize", data)
            self.assertNotIn(b"permission denied", data.lower())
        self.assertEqual((self.profile / "instant-observed").read_text().strip(), "1")
        self.assertIn("GX_READY", (self.profile / ".zsh_history").read_text())
        self.assertEqual(list(self.home.iterdir()), [])
        print("PTY verified: Chinese HOME/profile, p10k=1, gitstatus PID present, 9 runtime .zwc files, warm instant prompt active")

    def test_warm_instant_prompt_is_silent_without_tty(self):
        self.prepare_gitstatus()
        self.pty_session()
        self.assertTrue(list((self.profile / ".cache").glob("p10k-instant-prompt-*.zsh")))
        cache_before = tree_snapshot(self.profile / ".cache")
        out = self.run_zsh('print -r -- "${TTY:-none}|${ZSH_THEME:-empty}|${+functions[p10k]}|'
                           '${POWERLEVEL9K_DISABLE_GITSTATUS:-unset}|${GITSTATUS_DAEMON_PID_POWERLEVEL9K:-none}"')
        self.assertEqual(out, "none|empty|0|true|none\n")
        self.assertEqual(tree_snapshot(self.profile / ".cache"), cache_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
