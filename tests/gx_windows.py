"""gx/config/windows.zsh 与 terminal.zsh Windows 分支的隔离回归。

Linux 上模块不生效；强制 OSTYPE=msys/cygwin 后用 pwsh.exe、powershell.exe、cygpath 等 shim 验证
PowerShell 桥接的参数、临时脚本、退出码、PATH 刷新与缺失命令提示，从不运行真实 PowerShell。
须在有真实 Zsh 的 POSIX 环境运行（Linux/WSL，或 MSYS2 的 python）；Windows 原生 python 下失败而不是 skip。
"""
import os
import pathlib
import select
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest


REPO = pathlib.Path(__file__).resolve().parents[1]
MODULE = REPO / "gx/config/windows.zsh"
TERMINAL = REPO / "gx/config/terminal.zsh"
BOM = b"\xef\xbb\xbf"
# gx-pwsh 交给 PowerShell 的 -Command：设好输出编码、关掉进度条后调用原样写出的临时脚本；退出码与 -File 相同
# （exit N 为 N，正常结束为 0，throw 为 1）。
WRAPPER = ("& {{ Remove-Item Env:MSYS2_ARG_CONV_EXCL -ErrorAction SilentlyContinue; "
           "[Console]::OutputEncoding = $OutputEncoding = [Text.UTF8Encoding]::new($false); "
           "$ProgressPreference = 'SilentlyContinue'; & {script}; "
           "if ($?) {{ exit 0 }}; if ($LASTEXITCODE) {{ exit $LASTEXITCODE }}; exit 1 }}")
# irm/iwr 生成的脚本末尾追加的状态行：请求失败时返回 1。
WEB_STATUS = b"if (-not $?) { exit 1 }\n"
BRIDGED = ("gx-pwsh", "iex", "Invoke-Expression", "irm", "Invoke-RestMethod", "iwr", "Invoke-WebRequest")
SHIMS = ("unzip", "vi", "open", "xdg-open", "pbcopy", "pbpaste")
SYSTEM_TOOLS = ("mktemp", "cat", "sed", "tr", "cp", "sleep")
# 与 zoxide 0.9.9 原生 Windows 版 `zoxide init zsh` 相同形态的 PWD 助手与 cd 钩子。
ZOXIDE_INIT = r'''function __zoxide_pwd() { \command cygpath -w "$(\builtin pwd -P)"; }
function __zoxide_hook() { \command zoxide add -- "$(__zoxide_pwd)"; }
\builtin typeset -ga chpwd_functions
chpwd_functions+=(__zoxide_hook)'''

# cygpath 替身：-w 把 /a/b 写成 C:\a\b，-u 反过来；每次调用记一行参数。
CYGPATH = r'''printf '%s\n' "$*" >> "$GX_TEST_LOG/cygpath.calls"
mode=$1; shift; [ "$1" = -- ] && shift
for p in "$@"; do
  case $mode in
    -w) printf 'C:%s\n' "$p" | tr / '\\' ;;
    -u) printf '%s\n' "$p" | sed 's/^[A-Za-z]://; s#\\#/#g' ;;
    *) exit 2 ;;
  esac
done'''

# PowerShell 替身：记录参数、MSYS2_ARG_CONV_EXCL、运行次数、-Command 调用的脚本副本与标准输入来源，
# 再执行用例给的动作。脚本路径取自包装里的 `& '<路径>'; if`，先把单引号字面量里的 '' 还原成 '。
POWERSHELL = r'''name=${0##*/}
log=$GX_TEST_LOG/$name
{ printf 'conv=%s\n' "${MSYS2_ARG_CONV_EXCL-unset}"; for a in "$@"; do printf 'arg=%s\n' "$a"; done; } > "$log.call"
printf '%s\n' "$PATH" > "$log.env"
printf 'run\n' >> "$log.runs"
wrapper=
while [ $# -gt 0 ]; do if [ "$1" = -Command ]; then wrapper=$2; break; fi; shift; done
native=$(printf '%s\n' "$wrapper" | sed -n "s/.*& '\(.*\)'; if .*/\1/p" | sed "s/''/'/g")
script=$(printf '%s' "$native" | sed 's/^[A-Za-z]://; s#\\#/#g')
cp "$script" "$log.ps1"
printf '%s\n' "$script" > "$log.path"
if [ -t 0 ]; then printf 'tty\n' > "$log.stdin"; else cat > "$log.stdin"; fi
eval "${GX_TEST_PS_ACTION:-exit 0}"'''


class WindowsModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != "posix":
            raise AssertionError("需要真实 POSIX Zsh；Windows 请在 WSL 或 MSYS2 python 下运行，不支持整族 skip")
        selected = os.environ.get("GX_TEST_ZSH")
        cls.zsh = selected if selected is not None else shutil.which("zsh")
        if cls.zsh is None or not os.path.isabs(cls.zsh) or not os.access(cls.zsh, os.X_OK):
            raise AssertionError("缺少真实 Zsh；安装后重试或用 GX_TEST_ZSH 指定绝对路径，不支持整族 skip")
        cls.sandbox = pathlib.Path(tempfile.mkdtemp(prefix="gx-windows-"))
        cls.addClassCleanup(shutil.rmtree, cls.sandbox, True)
        # 只放模块与 shim 需要的系统工具，宿主上已有的 unzip/open 等不会遮住被测的定义。
        # 用 exec 包装而不是符号链接：MSYS2 的符号链接是复制，复制出的 exe 找不到自己的 DLL。
        cls.system = cls.sandbox / "system-bin"
        cls.system.mkdir()
        for name in SYSTEM_TOOLS:
            tool = shutil.which(name)
            if tool is None:
                raise AssertionError(f"缺少测试依赖 {name}")
            wrapper = cls.system / name
            wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(tool)} "$@"\n', encoding="utf-8")
            wrapper.chmod(0o755)

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="case-", dir=self.sandbox))
        self.bin = self.root / "bin"
        self.tmp = self.root / "临时 tmp ' $(touch injected)"
        self.log = self.root / "log"
        self.home = self.root / "home"
        for directory in (self.bin, self.tmp, self.log, self.home):
            directory.mkdir()
        self.shim("cygpath", CYGPATH)
        self.env = {
            "PATH": f"{self.bin}:{self.system}", "HOME": str(self.home), "TMPDIR": str(self.tmp),
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "xterm-256color",
            "MODULE": str(MODULE), "TERMINAL": str(TERMINAL), "GX_TEST_LOG": str(self.log),
        }

    def tearDown(self):
        self.assertFalse((self.home / "injected").exists(), "路径被当成了 shell 代码")

    def shim(self, name, body, directory=None):
        path = (directory or self.bin) / name
        path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def run_zsh(self, script, *, ostype="msys", env=None, stdin=b""):
        return subprocess.run(
            [self.zsh, "-f", "-c", f'OSTYPE={ostype}; source "$MODULE" || exit 99\n{script}'],
            env=dict(self.env, **(env or {})), cwd=self.home, input=stdin, capture_output=True,
            start_new_session=True, timeout=60,
        )

    def run_pty(self, script, *, env=None):
        import fcntl
        import pty
        import termios

        master, slave = pty.openpty()

        def acquire_terminal():
            request = getattr(termios, "TIOCSCTTY", None)
            if request is not None:
                fcntl.ioctl(0, request, 0)
            else:
                os.close(os.open(os.ttyname(0), os.O_RDWR))

        # 退出前稍等，让最后的输出在从端关闭前被读走（Cygwin 的 pty 会丢掉未读数据）。
        child = subprocess.Popen(
            [self.zsh, "-f", "-i", "-c", f'OSTYPE=msys; source "$MODULE" || exit 99\n{script}\nsleep 0.5; exit 0'],
            env=dict(self.env, **(env or {})), cwd=self.home, stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True, preexec_fn=acquire_terminal,
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
        return bytes(output).replace(b"\r\n", b"\n")

    def powershell_shims(self, *names):
        for name in names:
            self.shim(name, POWERSHELL)

    def call(self, name):
        lines = (self.log / f"{name}.call").read_text(encoding="utf-8").splitlines()
        return lines[0][len("conv="):], [line[len("arg="):] for line in lines[1:]]

    def cygpath_calls(self, mode):
        calls = self.log / "cygpath.calls"
        lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
        return [line for line in lines if line.startswith(mode + " ")]

    def assert_script_invocation(self, name):
        conv, args = self.call(name)
        self.assertEqual(conv, "*")
        self.assertEqual(args[:5], ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"])
        self.assertEqual(len(args), 6, args)
        script = (self.log / f"{name}.path").read_text(encoding="utf-8").strip()
        # 临时目录名带 '：包装里的 Windows 路径是单引号字面量，' 必须写成 ''。
        native = "C:" + script.replace("/", "\\")
        self.assertEqual(args[5], WRAPPER.format(script="'" + native.replace("'", "''") + "'"))
        self.assertEqual(pathlib.Path(script).parent, self.tmp)
        self.assertTrue(pathlib.Path(script).name.startswith("gx-pwsh."), script)
        self.assertTrue(script.endswith(".ps1"), script)
        return (self.log / f"{name}.ps1").read_bytes()

    def assert_tmp_empty(self):
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_module_is_noop_off_windows(self):
        names = (*BRIDGED, "command_not_found_handler", *SHIMS, "_gx_pwsh_run", "_gx_windows_refresh_path",
                 "_gx_zoxide_pwd", "_gx_windows_pwd")
        result = self.run_zsh(f'{ZOXIDE_INIT}\nsource "$MODULE" || exit 99\n'
                              f'for f in {" ".join(names)}; do (( $+functions[$f] )) && print -r -- defined:$f; done; '
                              'print -r -- keys:${+_gx_registry_path_keys}', ostype="linux-gnu")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode(), "keys:0\n")

    def test_bridge_and_shims_are_defined_on_msys_and_cygwin(self):
        self.shim("bsdunzip", 'printf "bsdunzip:%s\\n" "$*"')
        self.shim("vim", 'printf "vim:%s\\n" "$*"')
        names = (*BRIDGED, "command_not_found_handler", *SHIMS)
        for ostype in ("msys", "cygwin"):
            with self.subTest(ostype=ostype):
                result = self.run_zsh(
                    f'for f in {" ".join(names)}; do print -rn -- "${{+functions[$f]}}"; done; print; '
                    'print -r -- ${+functions[_gx_windows_free]}; '
                    'open_command() { print -r -- "open_command:$*"; }; open "a b"; xdg-open c; unzip -l x.zip; '
                    'vi "a b.txt"; '
                    '[[ ${functions[pbcopy]} == *"> /dev/clipboard"* && ${functions[pbpaste]} == *" /dev/clipboard"* ]] && '
                    'print -r -- clipboard', ostype=ostype)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.decode().splitlines(),
                                 ["1" * len(names), "0", "open_command:a b", "open_command:c", "bsdunzip:-l x.zip",
                                  "vim:a b.txt", "clipboard"])

    def test_shims_stay_undefined_when_the_runtime_ships_the_tool(self):
        # 运行时已带 unzip/vi（或缺 bsdunzip/vim）时不定义对应 shim，直接用真实命令。
        self.shim("unzip", 'printf "real unzip\\n"')
        self.shim("vi", 'printf "real vi\\n"')
        result = self.run_zsh('print -r -- ${+functions[unzip]}${+functions[vi]}; unzip; vi')
        self.assertEqual(result.stdout.decode().splitlines(), ["00", "real unzip", "real vi"], result.stderr)
        (self.bin / "unzip").unlink()
        (self.bin / "vi").unlink()
        result = self.run_zsh('print -r -- ${+functions[unzip]}${+functions[vi]}')
        self.assertEqual(result.stdout.decode(), "00\n", "没有 bsdunzip/vim 可转交时不定义 shim")

    def test_existing_definitions_are_kept(self):
        self.shim("iwr", 'printf "real iwr\\n"')
        self.shim("unzip", 'printf "real unzip\\n"')
        self.shim("bsdunzip", "exit 0")
        # -c 的整段脚本先解析后执行，别名要经 eval 才会在运行时展开。
        script = "\n".join((
            "OSTYPE=msys", "iex() { print mine; }", 'alias irm="print alias"',
            "command_not_found_handler() { print theirs; return 127; }", "open() { print own-open; }",
            'source "$MODULE"', "iex", "eval irm", "iwr", "unzip", "open", "missing-tool",
            "print -r -- ${+functions[unzip]}"))
        result = subprocess.run([self.zsh, "-f", "-c", script], env=self.env, cwd=self.home, input=b"",
                                capture_output=True, start_new_session=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode().splitlines(),
                         ["mine", "alias", "real iwr", "real unzip", "own-open", "theirs", "0"])

    def test_stdin_script_is_written_unchanged_with_bom_and_exit_code(self):
        self.powershell_shims("pwsh.exe", "powershell.exe")
        result = self.run_zsh("print -r -- 'Write-Output \"中文 & ok\"' | iex; print -r -- rc=$?",
                              env={"GX_TEST_PS_ACTION": "printf 'ran\\n'; exit 7"})
        self.assertEqual(result.stdout.decode().splitlines(), ["ran", "rc=7"], result.stderr)
        data = self.assert_script_invocation("pwsh.exe")
        self.assertEqual(data, BOM + 'Write-Output "中文 & ok"\n'.encode())
        self.assertEqual((self.log / "pwsh.exe.stdin").read_bytes(), b"", "无终端时 PowerShell 的标准输入应为 /dev/null")
        self.assertFalse((self.log / "powershell.exe.call").exists())
        self.assert_tmp_empty()

    def test_script_header_statements_stay_first(self):
        # param()、[CmdletBinding()] 与 using 只能写在脚本开头：临时脚本除 BOM 外不得加任何内容。
        self.powershell_shims("pwsh.exe")
        scripts = ('param([string]$Dir = "x") Write-Output "p=$Dir"; exit 4',
                   "[CmdletBinding()]\nparam()\nWrite-Output ok",
                   "using namespace System.Text\n[StringBuilder]::new('ok').ToString()")
        for script in scripts:
            for command in ('print -r -- "$GX_TEST_SCRIPT" | iex', 'gx-pwsh "$GX_TEST_SCRIPT"'):
                with self.subTest(script=script, command=command):
                    result = self.run_zsh(f"{command}; print -r -- rc=$?",
                                          env={"GX_TEST_SCRIPT": script, "GX_TEST_PS_ACTION": "exit 4"})
                    self.assertEqual(result.stdout.decode(), "rc=4\n", result.stderr)
                    self.assertEqual(self.assert_script_invocation("pwsh.exe"), BOM + script.encode() + b"\n")
                    self.assert_tmp_empty()

    def test_argument_script_keeps_caller_stdin(self):
        self.powershell_shims("powershell.exe")
        result = self.run_zsh("gx-pwsh 'Write-Output hi' extra; print -r -- rc=$?", stdin=b"piped data\n")
        self.assertEqual(result.stdout.decode(), "rc=0\n", result.stderr)
        data = self.assert_script_invocation("powershell.exe")
        self.assertEqual(data, BOM + b"Write-Output hi extra\n")
        self.assertEqual((self.log / "powershell.exe.stdin").read_bytes(), b"piped data\n")
        self.assert_tmp_empty()

    def test_powershell_path_lists_the_private_runtime_last(self):
        # 安装脚本里的 tar、find、sort、curl 应解析到 Windows 自带版本：运行时目录按原顺序排到最后。
        self.powershell_shims("pwsh.exe")
        path = f"/usr/bin:{self.bin}:/ucrt64/bin/:{self.system}:/bin"
        result = self.run_zsh("print -r -- 'exit 0' | iex; print -r -- rc=$?", env={"PATH": path})
        self.assertEqual(result.stdout.decode(), "rc=0\n", result.stderr)
        self.assertEqual((self.log / "pwsh.exe.env").read_text(encoding="utf-8").strip(),
                         f"{self.bin}:{self.system}:/usr/bin:/ucrt64/bin/:/bin")

    def test_empty_script_is_refused_without_running_powershell(self):
        # `irm <坏地址> | iex` 里 irm 失败时 iex 只收到空输入：不启动 PowerShell，返回 1 并说明原因。
        self.powershell_shims("pwsh.exe")
        for command in ("print -rn -- '' | iex", "print -r -- ' ' $'\\t' | iex", "false | iex", "gx-pwsh ''",
                        "gx-pwsh ' ' ''", "Invoke-Expression < /dev/null"):
            with self.subTest(command=command):
                result = self.run_zsh(f"{command}; print -r -- rc=$?")
                self.assertEqual(result.stdout.decode(), "rc=1\n", result.stderr)
                self.assertIn("没有收到要执行的 PowerShell 脚本", result.stderr.decode())
                self.assertFalse((self.log / "pwsh.exe.runs").exists(), "空脚本不得交给 PowerShell")
                self.assert_tmp_empty()
        result = self.run_zsh("irm https://bad.invalid/x | iex; print -r -- rc=$?",
                              env={"GX_TEST_PS_ACTION": "printf 'irm failed\\n' >&2; exit 1"})
        self.assertEqual(result.stdout.decode(), "rc=1\n", result.stderr)
        self.assertIn("没有收到要执行的 PowerShell 脚本", result.stderr.decode())
        self.assertEqual((self.log / "pwsh.exe.runs").read_text(), "run\n", "只运行了 irm，空脚本没有交给 PowerShell")
        self.assertEqual(self.assert_script_invocation("pwsh.exe"),
                         BOM + b"Invoke-RestMethod 'https://bad.invalid/x'\n" + WEB_STATUS)
        self.assert_tmp_empty()

    def test_temp_script_is_removed_on_failure_and_interrupt(self):
        self.powershell_shims("pwsh.exe")
        for action, expected in (("exit 3", "rc=3"), ("kill -INT $PPID; sleep 1; exit 0", "rc=130")):
            with self.subTest(action=action):
                result = self.run_zsh("gx-pwsh 'Write-Output x'; print -r -- rc=$?", env={"GX_TEST_PS_ACTION": action})
                self.assertEqual(result.stdout.decode(), expected + "\n", result.stderr)
                self.assertTrue((self.log / "pwsh.exe.ps1").is_file())
                self.assert_tmp_empty()

    def test_web_cmdlets_quote_arguments_in_one_command_line(self):
        self.powershell_shims("pwsh.exe")
        utf8, c_locale = {}, {"LANG": "C", "LC_ALL": "C"}
        cases = (
            ("irm 'https://example.com/i.ps1?a=1&b=2' -UseBasicParsing \"it's\"",
             b"Invoke-RestMethod 'https://example.com/i.ps1?a=1&b=2' -UseBasicParsing 'it''s'\n", utf8),
            ("Invoke-RestMethod -Uri https://example.com -Method Get",
             b"Invoke-RestMethod -Uri 'https://example.com' -Method 'Get'\n", utf8),
            ("iwr -useb 'https://example.com/$(x)' -OutFile 'a b.txt'",
             b"(Invoke-WebRequest -useb 'https://example.com/$(x)' -OutFile 'a b.txt').Content\n", utf8),
            # iwr 没写 -UseBasicParsing（任意大小写的 -useb… 前缀）时补上，Windows PowerShell 5.1 不走 IE 引擎。
            ("iwr https://example.com -OutFile x",
             b"(Invoke-WebRequest 'https://example.com' -OutFile 'x' -UseBasicParsing).Content\n", utf8),
            ("Invoke-WebRequest -USEBASICPARSING https://example.com",
             b"(Invoke-WebRequest -USEBASICPARSING 'https://example.com').Content\n", utf8),
            # ’ ‘ ‚ ‛ 在 PowerShell 里同样结束单引号字符串；只有 -Name 形式原样传，-x;… 与 --% 都是字面量。
            ("irm 'https://example.com/it’s' '-x;calc' --% -UseBasicParsing",
             "Invoke-RestMethod 'https://example.com/it’’s' '-x;calc' '--%' -UseBasicParsing\n".encode(), utf8),
            ("irm \"q‘u‚o‛t'e’\"", "Invoke-RestMethod 'q‘‘u‚‚o‛‛t''e’’'\n".encode(), utf8),
            ("irm \"q‘u‚o‛t'e’\"", "Invoke-RestMethod 'q‘‘u‚‚o‛‛t''e’’'\n".encode(), c_locale),
        )
        for command, body, env in cases:
            with self.subTest(command=command, env=env):
                result = self.run_zsh(f"{command}; print -r -- rc=$?", env=env)
                self.assertEqual(result.stdout.decode(), "rc=0\n", result.stderr)
                self.assertEqual(self.assert_script_invocation("pwsh.exe"), BOM + body + WEB_STATUS)
                self.assert_tmp_empty()
        self.assertEqual(self.cygpath_calls("-u"), [], "irm/iwr 不应刷新 PATH")

    def test_terminal_stdin_and_iwr_output_on_real_pty(self):
        self.powershell_shims("pwsh.exe")
        output = self.run_pty("print -r -- 'Write-Output tty' | iex; print -r -- IEX:$?; "
                              "iwr https://example.com >/dev/tty; print -r -- IWR:$?")
        self.assertIn(b"IEX:0\n", output)
        self.assertIn(b"IWR:0\n", output)
        self.assertEqual((self.log / "pwsh.exe.stdin").read_text(), "tty\n")
        self.assertEqual((self.log / "pwsh.exe.ps1").read_bytes(),
                         BOM + b"Invoke-WebRequest 'https://example.com' -UseBasicParsing\n" + WEB_STATUS)
        self.assert_tmp_empty()

    def test_powershell_selection_and_missing_powershell(self):
        custom = self.root / "custom ps"
        custom.mkdir()
        self.shim("my-ps", POWERSHELL, custom)
        cases = (
            (("powershell.exe",), {}, "powershell.exe"),
            (("pwsh.exe", "powershell.exe"), {}, "pwsh.exe"),
            (("pwsh.exe", "powershell.exe"), {"GX_POWERSHELL": "powershell.exe"}, "powershell.exe"),
            (("pwsh.exe",), {"GX_POWERSHELL": str(custom / "my-ps")}, "my-ps"),
        )
        for shims, env, expected in cases:
            with self.subTest(shims=shims, env=env):
                for name in ("pwsh.exe", "powershell.exe"):
                    (self.bin / name).unlink(missing_ok=True)
                for path in self.log.iterdir():
                    path.unlink()
                self.powershell_shims(*shims)
                result = self.run_zsh("gx-pwsh 'Write-Output x'; print -r -- rc=$?", env=env)
                self.assertEqual(result.stdout.decode(), "rc=0\n", result.stderr)
                self.assertEqual(sorted(path.name for path in self.log.glob("*.call")), [expected + ".call"])
        for name in ("pwsh.exe", "powershell.exe"):
            (self.bin / name).unlink(missing_ok=True)
        for env, message in (({}, "找不到 PowerShell"), ({"GX_POWERSHELL": str(self.root / "missing.exe")}, "GX_POWERSHELL")):
            with self.subTest(env=env):
                result = self.run_zsh("print -r -- 'Write-Output x' | iex; print -r -- rc=$?", env=env)
                self.assertEqual(result.stdout.decode(), "rc=127\n")
                self.assertIn(message, result.stderr.decode())
                self.assert_tmp_empty()

    def test_not_found_handler_only_prints_hints(self):
        self.powershell_shims("pwsh.exe", "powershell.exe")
        self.shim("winget", 'printf "winget ran\\n" > "$GX_TEST_LOG/winget.ran"')
        result = self.run_zsh(
            "Get-ChildItem -Path 'C:\\x y'; print -r -- rc=$?; ConvertTo-Json x; print -r -- rc=$?; "
            "Write-Host 'it’s $HOME' 'a\"b' \"it's\"; print -r -- rc=$?; "
            "rg pattern; print -r -- rc=$?; frobnicate --now; print -r -- rc=$?; man ls; print -r -- rc=$?; "
            "tmux new; print -r -- rc=$?; jq .; print -r -- rc=$?")
        self.assertEqual(result.stdout.decode().splitlines(), ["rc=127"] * 8)
        errors = result.stderr.decode()
        self.assertIn("zsh: command not found: Get-ChildItem", errors)
        # 每个参数按 PowerShell 规则单独加引号，整行再按 zsh 规则加引号：复制提示即可原样运行。
        self.assertIn("gx-pwsh 'Get-ChildItem -Path \"C:\\x y\"'\n", errors)
        self.assertIn("gx-pwsh 'ConvertTo-Json x'\n", errors)
        self.assertIn("gx-pwsh 'Write-Host '\\''it’’s $HOME'\\'' '\\''a\"b'\\'' \"it'\\''s\"'\n", errors)
        self.assertIn("winget install --id BurntSushi.ripgrep.MSVC -e", errors)
        self.assertIn("zsh: command not found: frobnicate", errors)
        self.assertNotIn("frobnicate --now", errors)
        self.assertIn("ls --help", errors)
        self.assertIn("herdr", errors)
        self.assertIn("zsh: command not found: jq", errors)
        self.assertNotIn("jqlang", errors, "jq 已随运行时附带，不再给 winget 提示")
        self.assertEqual(sorted(path.name for path in self.log.iterdir()), [], "提示处理器不得执行任何命令")
        self.assert_tmp_empty()

    def run_with_zoxide(self, script, init=ZOXIDE_INIT):
        return subprocess.run([self.zsh, "-f", "-c", f'OSTYPE=msys\n{init}\nsource "$MODULE" || exit 99\n{script}'],
                              env=self.env, cwd=self.home, input=b"", capture_output=True, start_new_session=True,
                              timeout=60)

    def test_zoxide_hook_converts_drive_paths_in_zsh_and_records_in_background(self):
        # zoxide 替身先睡 1 秒：同步执行的钩子会让 cd 等满这 1 秒。
        self.shim("zoxide", 'sleep 1; printf "%s\\n" "$*" >> "$GX_TEST_LOG/zoxide.calls"')
        work = self.root / "非盘符 目录"
        work.mkdir()
        self.env["GX_TEST_WORK"] = str(work)
        result = self.run_with_zoxide(
            'zmodload zsh/datetime; print -r -- override:${+functions[_gx_zoxide_pwd]}; '
            'for dir in "/c/Users/中文 dir" /cygdrive/d/x /c; do PWD=$dir; print -r -- "pwd:$(__zoxide_pwd)"; done; '
            'PWD=/c/Users/x; t=$EPOCHREALTIME; __zoxide_hook; print -r -- hook-ms:$(( (EPOCHREALTIME - t) * 1000 )); '
            't=$EPOCHREALTIME; cd "$GX_TEST_WORK"; print -r -- cd-ms:$(( (EPOCHREALTIME - t) * 1000 )); '
            'print -r -- "fallback:$(__zoxide_pwd)"')
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.decode("utf-8").splitlines()
        native_work = "C:" + str(work).replace("/", "\\")
        self.assertEqual(lines[:4], ["override:1", "pwd:C:\\Users\\中文 dir", "pwd:D:\\x", "pwd:C:\\"])
        self.assertLess(float(lines[4].split(":")[1]), 800, "钩子应在后台记录，不等 zoxide 退出")
        self.assertLess(float(lines[5].split(":")[1]), 800, "cd 不应等 zoxide 退出")
        self.assertEqual(lines[6], "fallback:" + native_work)
        calls = self.log / "zoxide.calls"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and len(calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []) < 2:
            time.sleep(0.1)
        self.assertEqual(sorted(calls.read_text(encoding="utf-8").splitlines()),
                         sorted(["add -- C:\\Users\\x", "add -- " + native_work]))
        self.assertEqual(len(self.cygpath_calls("-w")), 2, "只有非盘符目录才调用 cygpath")

    def test_zoxide_without_cygpath_helper_is_left_alone(self):
        init = 'function __zoxide_pwd() { \\builtin pwd -P; }\nfunction __zoxide_hook() { :; }'
        result = self.run_with_zoxide('print -r -- ${+functions[_gx_zoxide_pwd]}; print -r -- "${functions[__zoxide_pwd]}"',
                                      init=init)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.decode().splitlines()
        self.assertEqual(lines[0], "0")
        self.assertIn("pwd -P", lines[1])

    def test_refresh_merges_user_bins_and_registry_path(self):
        self.powershell_shims("pwsh.exe")
        new_bin = self.root / "new bin"
        second = self.root / "user bin2"
        user_bin = self.root / "user-bin"
        for directory in (new_bin, second, user_bin):
            directory.mkdir()
        self.shim("newtool", "exit 0", new_bin)
        windows_root = "C:" + str(self.root).replace("/", "\\")
        (self.root / "hkcu").write_bytes(
            f"%GXTESTROOT%\\new bin;C:\\missing;%NOPE%\\x;relative;%gxtestroot%\\user bin2\0".encode())
        (self.root / "hklm").write_bytes(("C:" + str(self.bin).replace("/", "\\") + "\\;%GXTESTROOT%\\new bin").encode())
        result = self.run_zsh(
            'typeset -U path; _gx_registry_path_keys=("$GX_TEST_LOG/../hkcu" "$GX_TEST_LOG/../hklm" "$GX_TEST_LOG/../none"); '
            '_gx_add_user_bins() { path+=("$GX_TEST_USER_BIN"); }; '
            'print -r -- before:${+commands[newtool]}; gx-pwsh "Write-Output x"; print -r -- rc=$?; '
            'print -rl -- $path; print -r -- after:${+commands[newtool]}',
            env={"GXTESTROOT": windows_root, "GX_TEST_USER_BIN": str(user_bin)})
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.decode().splitlines()
        self.assertEqual(lines, ["before:0", "rc=0", str(self.bin), str(self.system), str(user_bin), str(new_bin),
                                 str(second), "after:1"])
        self.assertEqual(len(self.cygpath_calls("-u")), 1, "注册表 PATH 应一次 cygpath 批量转换")


class TerminalCwd(unittest.TestCase):
    """terminal.zsh 在 MSYS/Cygwin 上把盘符目录报成 file://localhost/C:/…，非盘符目录不上报。"""

    @classmethod
    def setUpClass(cls):
        if os.name != "posix":
            raise AssertionError("需要真实 POSIX Zsh；Windows 请在 WSL 或 MSYS2 python 下运行，不支持整族 skip")
        cls.zsh = os.environ.get("GX_TEST_ZSH") or shutil.which("zsh")
        if cls.zsh is None:
            raise AssertionError("缺少真实 Zsh，不支持整族 skip")

    def report(self, ostype, directories):
        script = ('TTY=/dev/gx-test; TERM_PROGRAM=ghostty; unset SSH_CONNECTION SSH_CLIENT SSH_TTY INSIDE_EMACS; '
                  'source "$TERMINAL" || exit 99; OSTYPE=$GX_TEST_OSTYPE; '
                  'for dir in "${(@f)GX_TEST_DIRS}"; do PWD=$dir; _GX_TERMINAL_LAST_CWD=; '
                  'print -rn -- "<"; _gx_terminal_report_cwd; print -r -- ">"; done')
        env = {key: value for key, value in os.environ.items() if not key.startswith(("SSH_", "GX_", "HERDR_"))}
        env.update(TERMINAL=str(TERMINAL), TERM="xterm-256color", GX_TEST_OSTYPE=ostype,
                   GX_TEST_DIRS="\n".join(directories))
        result = subprocess.run([self.zsh, "-f", "-i", "-c", script], env=env, capture_output=True,
                                start_new_session=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.decode("utf-8").splitlines()

    def test_drive_paths_become_windows_file_uris(self):
        directories = ["/c/Users/中文 dir", "/cygdrive/d/a%b", "/c", "/cygdrive/e", "/usr/bin", "/", "/cygdrive",
                       "/cygdriveX/y", "/tmp"]
        expected = ["<\x1b]7;file://localhost/C:/Users/%E4%B8%AD%E6%96%87%20dir\x1b\\>",
                    "<\x1b]7;file://localhost/D:/a%25b\x1b\\>", "<\x1b]7;file://localhost/C:/\x1b\\>",
                    "<\x1b]7;file://localhost/E:/\x1b\\>", "<>", "<>", "<>", "<>", "<>"]
        for ostype in ("msys", "cygwin"):
            with self.subTest(ostype=ostype):
                self.assertEqual(self.report(ostype, directories), expected)

    def test_linux_paths_are_reported_verbatim(self):
        self.assertEqual(self.report("linux-gnu", ["/c/Users", "/usr/bin"]),
                         ["<\x1b]7;file://localhost/c/Users\x1b\\>", "<\x1b]7;file://localhost/usr/bin\x1b\\>"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
