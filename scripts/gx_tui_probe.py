#!/usr/bin/env python3
"""在自有隔离会话中驱动真实 Herdr TUI；API 仅观察，键盘输入经 PTY/ConPTY。"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

CORE_CHECKS = {"herdr-tui", "zsh-pane", "ctrl-c", "resize", "detach-attach", "cwd", "completion", "unicode-input", "space-paths"}


class ProbeError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeError(message)


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            result.update(block)
    return result.hexdigest()


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def response_line(text: str, marker: str) -> bool:
    return marker in text.splitlines()


def cwd_values(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"cwd", "foreground_cwd"} and isinstance(child, str):
                yield child
            yield from cwd_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from cwd_values(child)


def normalize_cwd(value: str, windows=False) -> str:
    result = value.replace("\\", "/").rstrip("/")
    if windows:
        if re.match(r"^/[a-zA-Z]/", result):
            result = result[1] + ":" + result[2:]
        result = result.casefold()
    return result


class TerminalBuffer:
    def __init__(self, prefix: Path):
        self.prefix = prefix
        self.data = bytearray()
        self.condition = threading.Condition()
        self.input_events = []
        self.error = None
        self.closed = False
        self.reader = None

    def received(self, data: bytes) -> None:
        with self.condition:
            require(len(self.data) + len(data) <= 32 * 1024 * 1024, "terminal capture exceeded 32 MiB safety limit")
            self.data.extend(data)
            self.condition.notify_all()

    def read_bytes(self) -> bytes:
        with self.condition:
            return bytes(self.data)

    def note_input(self, data: bytes, purpose: str) -> None:
        self.input_events.append({"monotonic": time.monotonic(), "purpose": purpose, "hex": data.hex(), "utf8": data.decode("utf-8", "backslashreplace")})

    def persist(self):
        raw = self.read_bytes()
        self.prefix.with_suffix(".raw").write_bytes(raw)
        text = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", raw)
        self.prefix.with_suffix(".text.log").write_text(text.decode("utf-8", "backslashreplace"), encoding="utf-8")
        write_json(self.prefix.with_suffix(".input.json"), self.input_events)


class UnixPty(TerminalBuffer):
    transport = "unix-controlling-pty"

    def __init__(self, argv: list[str], env: dict, cwd: Path, prefix: Path, cols=140, rows=38):
        super().__init__(prefix)
        import fcntl
        import pty
        import struct
        import termios
        self._fcntl, self._struct, self._termios = fcntl, struct, termios
        self.exit_code = None
        self.pid, self.master = pty.fork()
        if self.pid == 0:
            try:
                fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
                os.chdir(cwd)
                os.execve(argv[0], argv, env)
            except BaseException as error:
                os.write(2, str(error).encode("utf-8", "replace"))
                os._exit(127)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while not self.closed:
                try:
                    data = os.read(self.master, 65536)
                except OSError as error:
                    if error.errno in (errno.EIO, errno.EBADF):
                        break
                    raise
                if not data:
                    break
                self.received(data)
        except BaseException as error:
            self.error = repr(error)

    def send(self, data: bytes, purpose="keyboard"):
        require(not self.closed and self.poll() is None, "PTY client is not running")
        self.note_input(data, purpose)
        view = memoryview(data)
        while view:
            size = os.write(self.master, view)
            view = view[size:]

    def resize(self, cols: int, rows: int):
        require(20 <= cols <= 500 and 10 <= rows <= 200, "invalid terminal dimensions")
        self._fcntl.ioctl(self.master, self._termios.TIOCSWINSZ, self._struct.pack("HHHH", rows, cols, 0, 0))

    def poll(self):
        if self.exit_code is None:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.exit_code = os.waitstatus_to_exitcode(status)
        return self.exit_code

    def wait(self, timeout=15):
        deadline = time.monotonic() + timeout
        while self.poll() is None:
            if time.monotonic() >= deadline:
                raise TimeoutError("owned PTY client did not exit")
            time.sleep(0.05)
        return self.exit_code

    def close(self):
        if self.closed:
            return
        if self.poll() is None:
            os.kill(self.pid, signal.SIGTERM)
            try:
                self.wait(5)
            except TimeoutError:
                os.kill(self.pid, signal.SIGKILL)
                self.wait(5)
        self.closed = True
        os.close(self.master)
        self.reader.join(timeout=2)
        self.persist()


class WindowsConPty(TerminalBuffer):
    transport = "windows-system-conpty"

    def __init__(self, argv: list[str], env: dict, cwd: Path, prefix: Path, cols=140, rows=38):
        super().__init__(prefix)
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        class Coord(c.Structure):
            _fields_ = [("X", c.c_short), ("Y", c.c_short)]
        class Startup(c.Structure):
            _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR), ("lpDesktop", w.LPWSTR), ("lpTitle", w.LPWSTR),
                        ("dwX", w.DWORD), ("dwY", w.DWORD), ("dwXSize", w.DWORD), ("dwYSize", w.DWORD),
                        ("dwXCountChars", w.DWORD), ("dwYCountChars", w.DWORD), ("dwFillAttribute", w.DWORD),
                        ("dwFlags", w.DWORD), ("wShowWindow", w.WORD), ("cbReserved2", w.WORD),
                        ("lpReserved2", c.POINTER(c.c_byte)), ("hStdInput", w.HANDLE), ("hStdOutput", w.HANDLE), ("hStdError", w.HANDLE)]
        class StartupEx(c.Structure):
            _fields_ = [("StartupInfo", Startup), ("lpAttributeList", c.c_void_p)]
        class ProcessInfo(c.Structure):
            _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE), ("dwProcessId", w.DWORD), ("dwThreadId", w.DWORD)]
        self.Coord = Coord
        self.exit_code = None
        self.k = c.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreatePipe": ([c.POINTER(w.HANDLE), c.POINTER(w.HANDLE), c.c_void_p, w.DWORD], w.BOOL),
            "CreatePseudoConsole": ([Coord, w.HANDLE, w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)], c.c_long),
            "ResizePseudoConsole": ([w.HANDLE, Coord], c.c_long),
            "ClosePseudoConsole": ([w.HANDLE], None),
            "InitializeProcThreadAttributeList": ([c.c_void_p, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)], w.BOOL),
            "UpdateProcThreadAttribute": ([c.c_void_p, w.DWORD, c.c_size_t, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p], w.BOOL),
            "DeleteProcThreadAttributeList": ([c.c_void_p], None),
            "CreateProcessW": ([w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL, w.DWORD, c.c_void_p, w.LPCWSTR, c.c_void_p, c.POINTER(ProcessInfo)], w.BOOL),
            "ReadFile": ([w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p], w.BOOL),
            "WriteFile": ([w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "GetExitCodeProcess": ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
            "TerminateProcess": ([w.HANDLE, w.UINT], w.BOOL),
            "CancelIoEx": ([w.HANDLE, c.c_void_p], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.k, name)
            function.argtypes, function.restype = arguments, result
        self.input_read, self.input_write, self.output_read, self.output_write, self.hpc = [w.HANDLE() for _ in range(5)]
        self.process = ProcessInfo()
        self.attributes = None
        try:
            self._check(self.k.CreatePipe(c.byref(self.input_read), c.byref(self.input_write), None, 0))
            self._check(self.k.CreatePipe(c.byref(self.output_read), c.byref(self.output_write), None, 0))
            self._hr(self.k.CreatePseudoConsole(Coord(cols, rows), self.input_read, self.output_write, 0, c.byref(self.hpc)))
            self.k.CloseHandle(self.input_read); self.input_read = w.HANDLE()
            self.k.CloseHandle(self.output_write); self.output_write = w.HANDLE()
            size = c.c_size_t()
            self.k.InitializeProcThreadAttributeList(None, 1, 0, c.byref(size))
            self.attributes = c.create_string_buffer(size.value)
            self._check(self.k.InitializeProcThreadAttributeList(self.attributes, 1, 0, c.byref(size)))
            self._check(self.k.UpdateProcThreadAttribute(self.attributes, 0, 0x00020016, self.hpc, c.sizeof(w.HANDLE), None, None))
            startup = StartupEx()
            startup.StartupInfo.cb = c.sizeof(startup)
            # 父进程输出被重定向时，显式空标准句柄避免 Win32 复制父管道而绕过 ConPTY。
            startup.StartupInfo.dwFlags = 0x00000100
            startup.lpAttributeList = c.cast(self.attributes, c.c_void_p)
            command = c.create_unicode_buffer(subprocess.list2cmdline(argv))
            block = c.create_unicode_buffer("\0".join(key + "=" + value for key, value in sorted(env.items(), key=lambda pair: pair[0].upper())) + "\0\0")
            self._check(self.k.CreateProcessW(argv[0], command, None, None, False, 0x00080000 | 0x00000400, block, str(cwd), c.byref(startup), c.byref(self.process)))
            self.pid = self.process.dwProcessId
            self.k.CloseHandle(self.process.hThread); self.process.hThread = None
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
        except BaseException:
            self.close()
            raise

    def _check(self, value):
        if not value:
            raise self.c.WinError(self.c.get_last_error())

    def _hr(self, value):
        if value != 0:
            raise ProbeError(f"ConPTY HRESULT 0x{value & 0xffffffff:08x}")

    def _read(self):
        try:
            while not self.closed:
                data = self.c.create_string_buffer(65536)
                size = self.w.DWORD()
                if not self.k.ReadFile(self.output_read, data, len(data), self.c.byref(size), None):
                    error = self.c.get_last_error()
                    if error not in (6, 109, 995):
                        raise self.c.WinError(error)
                    break
                if not size.value:
                    break
                self.received(data.raw[:size.value])
        except BaseException as error:
            self.error = repr(error)

    def send(self, data: bytes, purpose="keyboard"):
        require(not self.closed and self.poll() is None, "ConPTY client is not running")
        self.note_input(data, purpose)
        require(len(data) <= 16384, "keyboard event exceeds bounded write size")
        errors = []
        def write():
            try:
                written = self.w.DWORD()
                self._check(self.k.WriteFile(self.input_write, data, len(data), self.c.byref(written), None))
                require(written.value == len(data), "partial ConPTY write")
            except BaseException as error:
                errors.append(error)
        writer = threading.Thread(target=write, daemon=True)
        writer.start()
        writer.join(timeout=5)
        require(not writer.is_alive(), "ConPTY keyboard write exceeded 5 seconds")
        if errors:
            raise errors[0]

    def resize(self, cols: int, rows: int):
        require(20 <= cols <= 500 and 10 <= rows <= 200, "invalid terminal dimensions")
        self._hr(self.k.ResizePseudoConsole(self.hpc, self.Coord(cols, rows)))

    def poll(self):
        if self.exit_code is not None:
            return self.exit_code
        if not self.process.hProcess:
            return 127
        status = self.k.WaitForSingleObject(self.process.hProcess, 0)
        if status == 258:
            return None
        self._check(status != 0xffffffff)
        code = self.w.DWORD()
        self._check(self.k.GetExitCodeProcess(self.process.hProcess, self.c.byref(code)))
        self.exit_code = code.value
        return self.exit_code

    def wait(self, timeout=15):
        deadline = time.monotonic() + timeout
        while self.poll() is None:
            if time.monotonic() >= deadline:
                raise TimeoutError("owned ConPTY client did not exit")
            time.sleep(0.05)
        return self.poll()

    def close(self):
        if self.closed:
            return
        if self.process.hProcess and self.poll() is None:
            self.k.TerminateProcess(self.process.hProcess, 99)
            self.wait(5)
        if self.hpc:
            # ClosePseudoConsole 会等待输出消费；读线程必须先保持运行。
            handle = self.hpc
            closer = threading.Thread(target=self.k.ClosePseudoConsole, args=(handle,), daemon=True)
            closer.start()
            closer.join(timeout=8)
            if closer.is_alive():
                self.error = "ClosePseudoConsole did not finish within 8 seconds"
            self.hpc = self.w.HANDLE()
        self.closed = True
        if self.reader:
            self.k.CancelIoEx(self.output_read, None)
            self.reader.join(timeout=2)
        for handle in (self.input_read, self.input_write, self.output_read, self.output_write, self.process.hProcess, self.process.hThread):
            if handle:
                self.k.CloseHandle(handle)
        if self.attributes is not None:
            self.k.DeleteProcThreadAttributeList(self.attributes)
        self.persist()


def make_environment(output: Path, msys_root: Path | None) -> dict:
    env = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "OS"}}
    for name, relative in {"HOME": "用户 HOME", "USERPROFILE": "用户 HOME", "APPDATA": "APPDATA 独立", "LOCALAPPDATA": "LOCALAPPDATA 独立", "XDG_CONFIG_HOME": "config 中文", "XDG_CACHE_HOME": "cache", "XDG_DATA_HOME": "data", "XDG_STATE_HOME": "state", "TMP": "tmp", "TEMP": "tmp", "TMPDIR": "tmp"}.items():
        path = output / relative
        path.mkdir(exist_ok=True)
        env[name] = str(path)
    env.update(TERM="xterm-256color", COLORTERM="truecolor", LANG="C.UTF-8", LC_ALL="C.UTF-8", HERDR_LANG="en", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    if os.name == "nt":
        require(msys_root is not None, "Windows requires --msys-root")
        env["PATH"] = os.pathsep.join((str(msys_root / "usr/bin"), str(msys_root / "ucrt64/bin"), str(Path(env["SYSTEMROOT"]) / "System32")))
        env.update(MSYSTEM="MSYS", MSYS2_PATH_TYPE="inherit", CHERE_INVOKING="1")
    return env


def posix_path(path: Path, env: dict, msys_root: Path | None) -> str:
    if os.name != "nt":
        return str(path)
    result = subprocess.run([str(msys_root / "usr/bin/cygpath.exe"), "-u", "--", str(path)], env=env, capture_output=True, check=True, timeout=15)
    return result.stdout.decode("utf-8").strip()


def safe_profile(profile: Path, output: Path):
    require(profile.resolve().is_relative_to(output.resolve()), "profile must be inside the caller's new isolated evidence directory")
    profile.mkdir(parents=True, exist_ok=True)
    require(not profile.is_symlink(), "symlinked profile refused")


def collect_panes(value):
    found = []
    if isinstance(value, dict):
        if isinstance(value.get("pane_id"), str):
            found.append(value)
        for child in value.values():
            found.extend(collect_panes(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(collect_panes(child))
    unique = {}
    for item in found:
        previous = unique.get(item["pane_id"], {})
        unique[item["pane_id"]] = {**previous, **item}
    return list(unique.values())


def run_probe(herdr: Path, zsh: Path, output: Path, msys_root: Path | None = None, *, fixture=True, profile_source: Path | None = None, gx_root: Path | None = None, gx_bin: Path | None = None, client_entry: Path | None = None, timeout=30) -> dict:
    herdr = herdr.resolve(strict=True)
    zsh = zsh.resolve(strict=True)
    client_entry = client_entry.resolve(strict=True) if client_entry else herdr
    if msys_root:
        msys_root = msys_root.resolve(strict=True)
    require(output.is_absolute() and not output.exists(), "output must be a new absolute isolated directory")
    require(5 <= timeout <= 120, "timeout must be between 5 and 120 seconds")
    output.mkdir(parents=True)
    env = make_environment(output, msys_root)
    home = Path(env["USERPROFILE"])
    profile = (output / "profile 独立 中文") if fixture else Path(env["LOCALAPPDATA" if os.name == "nt" else "XDG_CONFIG_HOME"]) / "ohmyzsh-gx/profile"
    safe_profile(profile, output)
    env["HOME"] = str(home) if os.name == "nt" else posix_path(home, env, msys_root)
    env["ZDOTDIR"] = posix_path(profile, env, msys_root)
    env["GX_PROFILE_DIR"] = env["ZDOTDIR"]
    env["GX_TUI_DIR"] = posix_path(output, env, msys_root)
    env["TMPDIR"] = posix_path(output / "tmp", env, msys_root)
    env["TMPPREFIX"] = env["TMPDIR"] + "/zsh"
    if gx_root:
        env["GX_PACKAGE_ROOT"] = posix_path(gx_root.resolve(strict=True), env, msys_root)
    if gx_bin:
        env["GX_PACKAGE_BIN"] = posix_path(gx_bin.resolve(strict=True), env, msys_root)
        gitstatus = gx_bin.resolve().parent / "lib/gitstatus"
        if gitstatus.is_dir():
            env["GITSTATUS_CACHE_DIR"] = posix_path(gitstatus, env, msys_root)
    if msys_root and (msys_root / "share/zsh/functions").is_dir():
        function_root = msys_root / "share/zsh/functions"
        function_dirs = sorted({function_root, *(path.parent for path in function_root.rglob("*") if path.is_file())})
        site_functions = msys_root / "share/zsh/site-functions"
        if site_functions.is_dir():
            function_dirs.insert(0, site_functions)
        env["FPATH"] = ":".join(posix_path(path, env, msys_root) for path in function_dirs)
    if profile_source:
        require(not fixture and profile_source.is_file(), "--profile-source requires --installed-profile and a real startup file")
        source = posix_path(profile_source.resolve(), env, msys_root)
        (profile / ".zshenv").write_text("skip_global_compinit=1\n", encoding="utf-8")
        (profile / ".zshrc").write_text("source " + shell_quote(source) + "\n", encoding="utf-8")
    else:
        require(fixture, "installed profile needs --profile-source")
        (profile / ".zshenv").write_text("skip_global_compinit=1\n", encoding="utf-8")
        (profile / ".zshrc").write_text('export PATH=/usr/bin:/ucrt64/bin:$PATH\nbindkey -e\nHISTFILE="$GX_PROFILE_DIR/.zsh_history"\nHISTSIZE=100\nSAVEHIST=100\nPROMPT="GX-TUI> "\n', encoding="utf-8")
    session = "gx-tui-" + uuid.uuid4().hex[:18]
    env["HERDR_SESSION"] = session
    socket = output / "herdr.sock"
    socket_directory = None
    if os.name != "nt" and len(os.fsencode(socket)) >= 100:
        socket_directory = Path(tempfile.mkdtemp(prefix="gx-tui-sock-", dir="/tmp"))
        socket = socket_directory / "herdr.sock"
    env["HERDR_SOCKET_PATH"] = str(socket)
    env["HERDR_CONFIG_PATH"] = str(output / "herdr.toml")
    config = 'onboarding = false\n[terminal]\ndefault_shell = ' + json.dumps(str(zsh), ensure_ascii=False) + '\nshell_mode = "login"\n[update]\nversion_check = false\nmanifest_check = false\n[ui]\nanimations = false\n'
    (output / "herdr.toml").write_text(config, encoding="utf-8")
    work = home / "中文 工作 空格"
    work.mkdir()
    completion = work / ("completion-" + uuid.uuid4().hex[:12] + ".txt")
    completion.write_text("completion fixture\n", encoding="utf-8")
    transcript = []
    input_steps = []
    state = {"schema_version": 1, "status": "failed", "scope": "real Herdr client keyboard/PTY; prototype profile" if fixture else "real Herdr client with explicitly supplied packaged profile",
             "session": session, "fixture_profile": fixture, "platform": "windows-x64" if os.name == "nt" else "ubuntu-amd64",
             "herdr": str(herdr), "herdr_sha256": digest(herdr), "zsh": str(zsh), "home": str(home), "profile": str(profile), "checks": {},
             "environment": env, "transport": WindowsConPty.transport if os.name == "nt" else UnixPty.transport}
    server = None
    client = None
    clients = []
    pane = None
    overall_deadline = time.monotonic() + 240
    def cli(*arguments, check=True):
        # 除自有 server 的启动/停止外，驱动只调用只读 API，绝不绕过键盘发送输入。
        require(arguments[0] in {"status", "pane", "workspace", "--version", "server", "config"}, "unexpected API family")
        if arguments[0] == "pane":
            require(arguments[1] in {"list", "get", "read", "process-info", "layout"}, "mutating pane API forbidden")
        if arguments[0] == "workspace":
            require(arguments[1] == "list", "mutating workspace API forbidden")
        if arguments[0] == "server":
            require(arguments[1:] == ("stop",) and server is not None, "may only stop the owned server")
        result = subprocess.run([str(herdr), *arguments], env=env, cwd=home, capture_output=True, timeout=timeout)
        record = {"argv": [str(herdr), *arguments], "exit_code": result.returncode, "stdout": result.stdout.decode("utf-8", "replace"), "stderr": result.stderr.decode("utf-8", "replace")}
        transcript.append(record)
        write_json(output / "api.json", transcript)
        if check:
            require(result.returncode == 0, f"read API failed: {arguments}: {record['stderr']}")
        return record
    def wait_until(predicate, label):
        deadline = min(time.monotonic() + timeout, overall_deadline)
        while True:
            require(time.monotonic() < deadline, "timeout: " + label)
            if client is not None:
                require(client.error is None, "terminal transport failed: " + str(client.error))
            value = predicate()
            if value:
                return value
            if client is not None:
                require(client.poll() is None, f"client exited during {label}: {client.poll()}")
            require(time.monotonic() < deadline, "timeout: " + label)
            time.sleep(0.12)
    def screen():
        record = cli("pane", "read", pane, "--source", "recent-unwrapped", "--lines", "250", "--format", "text")
        return record["stdout"]
    def observed(marker, label):
        text = wait_until(lambda: (lambda text: text if marker in text.splitlines() else None)(screen()), label)
        (output / (label + ".pane.txt")).write_text(text, encoding="utf-8")
        return text
    def settled_terminal(label):
        previous = None
        stable_since = time.monotonic()
        def settled():
            nonlocal previous, stable_since
            current = client.read_bytes()
            if current != previous:
                previous = current
                stable_since = time.monotonic()
            return bool(current) and time.monotonic() - stable_since >= 0.4
        wait_until(settled, label)
    def keyboard(data, label):
        payload = data.encode("utf-8") if isinstance(data, str) else data
        require(client is not None, "no attached TUI client")
        client.send(payload, label)
        input_steps.append({"label": label, "payload_hex": payload.hex(), "transport": client.transport})
        write_json(output / "keyboard.json", input_steps)
    def command(text, label):
        keyboard(text + "\r", label)
    def passed(name, evidence):
        state["checks"][name] = {"status": "passed", "evidence": evidence}
        write_json(output / "result.json", state)
    try:
        if not fixture:
            require(gx_root is not None and gx_bin is not None, "installed profile requires package resources and launchers")
            initializer = gx_bin / ("gx-zsh.exe" if os.name == "nt" else "gx-zsh")
            initialized = subprocess.run([str(initializer), "--gx-initialize-only"], env=env, cwd=home, capture_output=True, timeout=60)
            (output / "initialize.stdout").write_bytes(initialized.stdout)
            (output / "initialize.stderr").write_bytes(initialized.stderr)
            require(initialized.returncode == 0, "packaged launcher failed profile initialization")
            identity = (gx_root / "p10k-runtime-id").read_text(encoding="ascii").strip()
            require(re.fullmatch(r"[0-9a-f]{64}", identity) is not None, "invalid packaged theme identity")
            env["GX_P10K_RUNTIME_DIR"] = posix_path(profile / ".cache/themes" / identity / "powerlevel10k", env, msys_root)
        state["version"] = cli("--version")["stdout"].strip()
        cli("config", "check")
        existing = cli("status", "--json")
        require(json.loads(existing["stdout"])["server"]["running"] is False, "unique session unexpectedly already exists")
        with (output / "server.log").open("wb") as log:
            server = subprocess.Popen([str(herdr), "server"], env=env, cwd=home, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        state["server_pid"] = server.pid
        def server_ready():
            require(server.poll() is None, "owned server exited before becoming ready")
            record = cli("pane", "list", check=False)
            return record["exit_code"] == 0 and "pane_list" in record["stdout"]
        wait_until(server_ready, "owned server ready")
        terminal = WindowsConPty if os.name == "nt" else UnixPty
        state["client_argv"] = [str(client_entry)]
        state["launch_scope"] = "user-facing real client attached to probe-owned server; daemon auto-spawn is not covered"
        client = terminal(state["client_argv"], env, home, output / "client-1")
        clients.append(client)
        def find_pane():
            record = cli("pane", "list", check=False)
            if record["exit_code"] != 0:
                return None
            return next(iter(collect_panes(json.loads(record["stdout"]))), None)
        item = wait_until(find_pane, "client creates a pane")
        pane = item["pane_id"]
        state["pane"] = pane
        wait_until(lambda: b"GX-TUI>" in re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", client.read_bytes()) if fixture else "❯" in screen(), "client renders startup")
        if not fixture:
            settled_terminal("packaged prompt settles before initial keyboard input")
        token = uuid.uuid4().hex[:10]
        if fixture:
            command('autoload -Uz compinit; compinit -d "$GX_PROFILE_DIR/.zcompdump"; printf \'%s%s\\n\' GX-COMPINIT- ' + token, "prototype-compinit-keyboard")
            observed("GX-COMPINIT-" + token, "prototype-compinit")
            state["prototype_compinit"] = "executed through keyboard after startup; not evidence that packaged Unicode startup is fixed"
        command("[[ -t 0 && -t 1 ]] && GX_TUI_TTY=yes; printf '%s%s:%s:%s\\n' GX-BOOT- " + token + ' "$ZSH_VERSION" "$GX_TUI_TTY"', "zsh-keyboard")
        text = wait_until(lambda: (lambda text: text if re.search(r"^GX-BOOT-" + token + r":5\.[^\r\n]+:yes$", text, re.M) else None)(screen()), "Zsh tty response")
        (output / "zsh-keyboard.pane.txt").write_text(text, encoding="utf-8")
        passed("herdr-tui", ["client-1.raw", "keyboard.json", "zsh-keyboard.pane.txt"])
        passed("zsh-pane", ["zsh-keyboard.pane.txt"])
        command("printf '%s%s:%s\\n' GX-UNICODE- " + token + " '中文 键盘输入'", "unicode-keyboard")
        observed("GX-UNICODE-" + token + ":中文 键盘输入", "unicode-keyboard")
        passed("unicode-input", ["keyboard.json", "unicode-keyboard.pane.txt"])
        command('cd "$HOME/中文 工作 空格"; printf \'%s%s:%s\\n\' GX-CWD- ' + token + ' "${PWD:t}"', "cwd-keyboard")
        observed("GX-CWD-" + token + ":中文 工作 空格", "cwd-keyboard")
        def cwd_observed():
            process_info = cli("pane", "process-info", "--pane", pane)
            record = json.loads(process_info["stdout"])
            locations = list(cwd_values(record))
            if normalize_cwd(str(work), os.name == "nt") in {normalize_cwd(item, os.name == "nt") for item in locations}:
                return {"api": process_info, "expected": str(work), "reported": locations}
            return None
        write_json(output / "cwd-process.json", wait_until(cwd_observed, "server-observed foreground cwd"))
        keyboard("printf '%s%s:%s\\n' GX-TAB- " + token + " completion-", "completion-text")
        keyboard(b"\t", "completion-tab")
        time.sleep(0.3)
        keyboard(b"\r", "completion-enter")
        observed("GX-TAB-" + token + ":" + completion.name, "completion")
        passed("completion", ["keyboard.json", "completion.pane.txt"])
        passed("cwd", ["cwd-keyboard.pane.txt", "cwd-process.json"])
        passed("space-paths", ["cwd-keyboard.pane.txt", "completion.pane.txt"])
        command("printf '%s%s\\n' GX-SLEEP- " + token + "; sleep 60", "interrupt-start")
        observed("GX-SLEEP-" + token, "interrupt-ready")
        keyboard(b"\x03", "ctrl-c-keyboard")
        if fixture:
            wait_until(lambda: screen().rstrip().endswith("GX-TUI>"), "prompt returns after interrupt")
        settled_terminal("terminal settles after interrupt")
        command("printf '%s%s:%s\\n' GX-INT- " + token + ' "$?"', "interrupt-result")
        observed("GX-INT-" + token + ":130", "interrupt")
        passed("ctrl-c", ["keyboard.json", "interrupt.pane.txt"])
        def dimensions(label):
            command("printf '%s%s:%s\\n' GX-SIZE- " + label + ' "$(stty size)"', "size-" + label)
            text = wait_until(lambda: (lambda text: text if re.search(r"^GX-SIZE-" + label + r":\d+ \d+$", text, re.M) else None)(screen()), "size response")
            (output / ("size-" + label + ".pane.txt")).write_text(text, encoding="utf-8")
            match = re.search(r"^GX-SIZE-" + label + r":(\d+) (\d+)$", text, re.M)
            return tuple(map(int, match.groups()))
        before = dimensions(token + "a")
        client.resize(180, 48)
        time.sleep(0.4)
        after = dimensions(token + "b")
        require(after[0] > before[0] and after[1] > before[1], f"resize did not reach inner shell: {before} -> {after}")
        write_json(output / "resize.json", {"outer_before": [140, 38], "outer_after": [180, 48], "inner_before": before, "inner_after": after})
        passed("resize", ["resize.json", "keyboard.json", "size-" + token + "b.pane.txt"])
        command("GX_PERSIST=" + shell_quote(token) + "; printf '%s%s\\n' GX-PERSIST- " + token, "persist-before-detach")
        observed("GX-PERSIST-" + token, "persist")
        keyboard(b"\x02", "detach-prefix")
        time.sleep(0.1)
        keyboard(b"q", "detach-key")
        require(client.wait(timeout) == 0, "TUI detach did not exit cleanly")
        client.close()
        client = None
        require(server.poll() is None and cli("pane", "list")["exit_code"] == 0, "detach stopped persistent server")
        client = terminal(state["client_argv"], env, home, output / "client-2", cols=180, rows=48)
        clients.append(client)
        wait_until(lambda: ("GX-PERSIST-" + token).encode() in re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", client.read_bytes()), "reattached client renders the persistent shell state")
        if os.name != "nt":
            keyboard(b"\x1b[I", "reattach-terminal-focus-in")
        settled_terminal("reattached terminal settles before keyboard input")
        command("printf '%s%s:%s\\n' GX-ATTACH- " + token + ' "$GX_PERSIST"', "reattach-keyboard")
        observed("GX-ATTACH-" + token + ":" + token, "reattach")
        require(any(p["pane_id"] == pane for p in collect_panes(json.loads(cli("pane", "list")["stdout"]))), "reattach changed the persistent pane")
        passed("detach-attach", ["client-1.raw", "client-2.raw", "keyboard.json", "reattach.pane.txt"])
        if os.name == "nt":
            powershell = Path(env["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            statement = '[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); (Get-Process -Id ' + str(server.pid) + ').Modules | Where-Object {$_.ModuleName -ieq "conpty.dll"} | ForEach-Object {$_.FileName}'
            result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", statement], env=env, capture_output=True, timeout=20)
            loaded = [str(Path(line).resolve()) for line in result.stdout.decode("utf-8").splitlines() if line.strip()]
            expected = str((herdr.parent / "conpty/conpty.dll").resolve())
            require(result.returncode == 0 and expected.lower() in {name.lower() for name in loaded}, "inner shell app-local ConPTY module was not proven")
            state["inner_conpty"] = expected
            state["outer_conpty"] = str(Path(env["SYSTEMROOT"]) / "System32/kernel32.dll")
            write_json(output / "conpty-modules.json", {"server_pid": server.pid, "loaded": loaded, "expected_inner": expected, "outer_api": state["outer_conpty"]})
        if not fixture:
            theme_prefix = "GX-THEME-" + token + "|"
            command("printf '%s%s|%s|%s|%s\\n' GX-THEME- " + token
                    + ' "${+functions[p10k]}" "${GITSTATUS_DAEMON_PID_POWERLEVEL9K:-0}" "${__p9k_root_dir:-}"', "packaged-theme-keyboard")
            text = wait_until(lambda: (lambda value: value if any(line.startswith(theme_prefix) for line in value.splitlines()) else None)(screen()), "packaged theme response")
            (output / "packaged-theme.pane.txt").write_text(text, encoding="utf-8")
            line = next(line for line in text.splitlines() if line.startswith(theme_prefix))
            fields = line.split("|")
            require(len(fields) == 4 and fields[1] == "1" and re.fullmatch(r"[1-9][0-9]*", fields[2]) is not None, "packaged P10k function or numeric gitstatus group identifier missing")
            require(fields[3] == env["GX_P10K_RUNTIME_DIR"] and "/.cache/themes/" in fields[3], "theme is not loaded from the independent profile cache")
            observation = {"status": "passed", "scope": "keyboard-observed theme function, numeric gitstatus group identifier and cached root; no daemon-liveness or cold/warm claim", "p10k_function": 1,
                           "gitstatus_pid_parameter": int(fields[2]), "theme_root": fields[3], "evidence": ["keyboard.json", "packaged-theme.pane.txt"]}
            write_json(output / "packaged-theme.json", observation)
            state["theme_observation"] = observation
            zoxide_work = work / "中文 项目.demo"
            zoxide_work.mkdir()
            command('cd "$HOME/中文 工作 空格/中文 项目.demo"; zoxide add "$PWD"; '
                    + "printf '%s%s:%s\\n' GX-ZOADD- " + token + ' "$?"', "zoxide-add-keyboard")
            observed("GX-ZOADD-" + token + ":0", "zoxide-add")
            query_prefix = "GX-ZOQUERY-" + token + "|"
            command("GX_ZO_QUERY=$(zoxide query .); printf '%s%s|%s|%s\\n' GX-ZOQUERY- " + token + ' "$?" "$GX_ZO_QUERY"', "zoxide-query-keyboard")
            text = wait_until(lambda: (lambda value: value if any(line.startswith(query_prefix) for line in value.splitlines()) else None)(screen()), "zoxide query response")
            (output / "zoxide-query.pane.txt").write_text(text, encoding="utf-8")
            query_fields = next(line for line in text.splitlines() if line.startswith(query_prefix)).split("|", 2)
            require(len(query_fields) == 3 and query_fields[1] == "0" and normalize_cwd(query_fields[2], os.name == "nt") == normalize_cwd(str(zoxide_work), os.name == "nt"), "zoxide query does not round-trip the actual Chinese cwd")
            data_prefix = "GX-ZODATA-" + token + "|"
            command("printf '%s%s|%s\\n' GX-ZODATA- " + token + ' "${_ZO_DATA_DIR:-}"', "zoxide-data-keyboard")
            text = wait_until(lambda: (lambda value: value if any(line.startswith(data_prefix) for line in value.splitlines()) else None)(screen()), "zoxide data directory response")
            (output / "zoxide-data.pane.txt").write_text(text, encoding="utf-8")
            data_dir = next(line for line in text.splitlines() if line.startswith(data_prefix))[len(data_prefix):]
            if os.name == "nt":
                require(normalize_cwd(data_dir, True) == normalize_cwd(str(profile / ".local/share/zoxide"), True), "native zoxide data is not in the independent profile")
            require(not any("could not find data directory" in (entry["stdout"] + entry["stderr"]).lower() for entry in transcript), "zoxide data-directory failure appeared in the actual pane")
            zoxide_observation = {"status": "passed", "scope": "real keyboard add/query plus active cd hook; no final installer claim", "query_result": query_fields[2],
                                  "expected_cwd": str(zoxide_work), "query_keyword": ".", "query_semantics": "literal final-directory keyword, not current-directory shorthand",
                                  "data_directory": data_dir, "data_directory_error_observed": False,
                                  "evidence": ["keyboard.json", "zoxide-add.pane.txt", "zoxide-query.pane.txt", "zoxide-data.pane.txt"]}
            write_json(output / "zoxide-observation.json", zoxide_observation)
            state["zoxide_observation"] = zoxide_observation
        keyboard(b"\x02", "final-detach-prefix")
        time.sleep(0.1)
        keyboard(b"q", "final-detach-key")
        require(client.wait(timeout) == 0, "final detach failed")
        client.close()
        client = None
        state["status"] = "passed"
    except BaseException as error:
        state["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        cleanup = []
        for owned in clients:
            try:
                owned.close()
                cleanup.append({"pid": owned.pid, "exit_code": owned.poll(), "transport": owned.transport, "reader_error": owned.error})
                if owned.error:
                    state["status"] = "failed"
                    state["cleanup_error"] = owned.error
            except BaseException as error:
                cleanup.append({"error": repr(error)})
                state["status"] = "failed"
        if server is not None:
            try:
                stop = cli("server", "stop", check=False)
                server.wait(timeout=15)
                if stop["exit_code"] != 0:
                    state["status"] = "failed"
                    state["cleanup_error"] = "owned server stop failed"
            except BaseException as error:
                if server.poll() is None:
                    server.terminate()
                    try:
                        server.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=5)
                state["status"] = "failed"
                state["cleanup_error"] = repr(error)
        if socket_directory is not None:
            try:
                socket_directory.rmdir()
                state["owned_socket_directory_removed"] = str(socket_directory)
            except OSError as error:
                state["status"] = "failed"
                state["cleanup_error"] = f"Owned socket directory retained for inspection: {error}"
        state["cleanup"] = cleanup
        write_json(output / "api.json", transcript)
        write_json(output / "result.json", state)
    require(state["status"] == "passed", state.get("cleanup_error", "probe failed"))
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--herdr", type=Path, required=True)
    parser.add_argument("--zsh", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--msys-root", type=Path)
    parser.add_argument("--installed-profile", action="store_true")
    parser.add_argument("--profile-source", type=Path)
    parser.add_argument("--gx-root", type=Path)
    parser.add_argument("--gx-bin", type=Path)
    parser.add_argument("--client-entry", type=Path, help="installed herdr launcher; API/server still use the explicitly selected raw binary")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args(argv)
    output_existed = args.output.exists()
    try:
        result = run_probe(args.herdr, args.zsh, args.output.absolute(), args.msys_root, fixture=not args.installed_profile,
                           profile_source=args.profile_source, gx_root=args.gx_root, gx_bin=args.gx_bin, client_entry=args.client_entry, timeout=args.timeout)
        print(json.dumps({"status": result["status"], "output": str(args.output), "checks": list(result["checks"]), "fixture_profile": result["fixture_profile"]}))
        return 0
    except (OSError, ValueError, KeyError, ProbeError, subprocess.SubprocessError) as error:
        if not output_existed and args.output.is_dir() and not (args.output / "result.json").exists():
            write_json(args.output / "result.json", {"schema_version": 1, "status": "failed", "phase": "setup", "error": str(error), "checks": {}})
        print(f"gx-tui-probe: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
