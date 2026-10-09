import contextlib
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("gx_probe_herdr", Path(__file__).resolve().parents[1] / "scripts/gx_probe_herdr.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def host_os(name):
    """让探针走 name 对应的分支，但不改全局 os.name（pathlib/shutil 仍按宿主平台工作）。"""
    return types.SimpleNamespace(**{**vars(os), "name": name})


class FakeClock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


RUNNING = json.dumps({"running": True})


class FakeZshPane:
    """herdr CLI 与 Zsh 窗格替身：server 要问几次才就绪；Ctrl+C 后要再读几次屏提示符才回来，期间的键入被丢弃（同 MSYS2 Zsh）；
    原生 ping 要再读几次屏才打印目标地址，在那之前到达的 Ctrl+C 记为过早。"""

    def __init__(self, reads_until_prompt, not_ready=0, reads_until_ping=0):
        self.reads_until_prompt, self.countdown, self.not_ready = reads_until_prompt, None, not_ready
        self.reads_until_ping, self.ping = reads_until_ping, None
        self.lines, self.typed, self.status, self.busy, self.dropped = ["gx-probe>"], "", 0, False, []
        self.commands, self.interrupts, self.early = [], [], []

    def __call__(self, argv, **kwargs):
        args, stdout = argv[1:], "herdr fixture"
        if Path(argv[0]).name == "cygpath.exe":
            stdout = "".join("/c/Windows/System32/PING.EXE\n" if Path(path).name == "PING.EXE" else "/home\n" for path in args[2:])
        elif args == ["status", "server", "--json"]:
            self.not_ready -= 1
            stdout = json.dumps({"running": self.not_ready < 0})
        elif args[:2] == ["workspace", "create"]:
            if self.not_ready >= 0:
                return subprocess.CompletedProcess(argv, 1, "", "server_not_running")
            stdout = json.dumps({"result": {"root_pane": {"pane_id": "w1:p1"}}})
        elif args[:2] == ["pane", "read"]:
            if self.ping is not None:
                self.ping -= 1
                if self.ping <= 0:
                    self.ping = None
                    self.lines.append("Pinging 127.0.0.1 with 32 bytes of data:")
            if self.countdown is not None:
                self.countdown -= 1
                if self.countdown == 0:
                    self.countdown, self.busy, self.status, self.ping = None, False, 130, None
                    self.lines += ["", "gx-probe>"]
            stdout = "\n".join(self.lines)
        elif (args[:2], args[3:4]) in ((["pane", "send-keys"], ["ctrl+c"]), (["pane", "send-text"], [probe.WIN32_CTRL_C])):
            self.interrupts.append(args[1])
            if self.ping is not None:
                self.early.append(args[1])
            if self.busy:
                self.countdown = self.reads_until_prompt
        elif args[:2] in (["pane", "send-text"], ["pane", "send-keys"]):
            if self.busy:
                self.dropped.append(args[3])
            elif args[1] == "send-text":
                self.typed += args[3]
            else:
                self.run()
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    def run(self):
        command, self.typed = self.typed, ""
        self.commands.append(command)
        self.lines[-1] = "gx-probe> " + command
        prefix, token = re.search(r"(GX-[A-Z-]+-) ([0-9a-f]{32})", command).groups()
        if "\\u4e2d\\u6587" in command:
            self.lines.append("中文")
        if command.endswith(("sleep 30", " -n 30 127.0.0.1")):
            self.lines.append(prefix + token)
            self.busy = True
            if command.endswith("127.0.0.1"):
                self.ping = self.reads_until_ping or None
                if self.ping is None:
                    self.lines.append("Pinging 127.0.0.1 with 32 bytes of data:")
            return
        self.lines += [prefix + token + ":" + ("5.9.2" if prefix == "GX-ZSH-" else str(self.status)), "gx-probe>"]


def server_with_codex_shim(output, herdr, server, log=b""):
    """模拟 herdr server 启动：输出写入 server.log，并在隔离 TMP 放 Codex 垫片（Windows 硬链接本体，其余平台符号链接）。"""
    def start(argv, **kwargs):
        kwargs["stdout"].write(log)
        shim = output / f"tmp/herdr-codex-{server.pid}-0"
        shim.mkdir()
        (shim / ".herdr-codex-launch-v1").write_text("v1\n", encoding="utf-8")
        if sys.platform == "win32":
            os.link(herdr, shim / "codex.exe")
        else:
            os.symlink(herdr, shim / "codex")
        return server
    return start


class HerdrProbeCleanup(unittest.TestCase):
    def test_stop_timeout_still_reaps_own_server_and_writes_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exe, zsh = root / "herdr", root / "zsh"
            exe.write_bytes(b"fixture")
            zsh.write_bytes(b"fixture")
            server = mock.Mock(pid=123)
            server.wait.side_effect = [subprocess.TimeoutExpired("server", 20), 0]

            def call(argv, **kwargs):
                if argv[1:] == ["server", "stop"]:
                    raise subprocess.TimeoutExpired(argv, 20)
                if argv[1:] == ["status", "server", "--json"]:
                    return subprocess.CompletedProcess(argv, 0, RUNNING, "")
                if argv[1] == "workspace":
                    return subprocess.CompletedProcess(argv, 1, "", "intentional fixture failure")
                return subprocess.CompletedProcess(argv, 0, "herdr fixture", "")

            with mock.patch.object(probe.os, "name", "posix"), \
                    mock.patch.object(probe.subprocess, "Popen", side_effect=server_with_codex_shim(root / "evidence", exe, server)), \
                    mock.patch.object(probe.subprocess, "run", side_effect=call):
                with self.assertRaisesRegex(RuntimeError, "intentional fixture failure"):
                    probe.run_probe(exe, zsh, root / "evidence", None)
            server.terminate.assert_called_once()
            self.assertEqual(server.wait.call_count, 2)
            result = json.loads((root / "evidence/result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("cleanup_error", result)
            self.assertTrue((root / "evidence/commands.json").is_file())
            self.assertFalse((root / "evidence/tmp").exists())
            self.assertTrue((root / "evidence/home").is_dir())
            self.assertEqual(exe.read_bytes(), b"fixture")

    def test_unstoppable_server_keeps_its_tmp(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exe, zsh = root / "herdr", root / "zsh"
            exe.write_bytes(b"fixture")
            zsh.write_bytes(b"fixture")
            server = mock.Mock(pid=4242)
            server.wait.side_effect = subprocess.TimeoutExpired("server", 10)

            def call(argv, **kwargs):
                if argv[1:] == ["status", "server", "--json"]:
                    return subprocess.CompletedProcess(argv, 0, RUNNING, "")
                if argv[1] == "workspace":
                    return subprocess.CompletedProcess(argv, 1, "", "intentional fixture failure")
                return subprocess.CompletedProcess(argv, 0, "herdr fixture", "")

            with mock.patch.object(probe, "os", host_os("posix")), \
                    mock.patch.object(probe.subprocess, "Popen", side_effect=server_with_codex_shim(root / "evidence", exe, server)), \
                    mock.patch.object(probe.subprocess, "run", side_effect=call):
                with self.assertRaisesRegex(RuntimeError, "intentional fixture failure"):
                    probe.run_probe(exe, zsh, root / "evidence", None)
            server.kill.assert_called_once()
            result = json.loads((root / "evidence/result.json").read_text(encoding="utf-8"))
            self.assertIn("probe-owned server cleanup failed", result["cleanup_error"])
            self.assertTrue((root / "evidence/tmp/herdr-codex-4242-0/.herdr-codex-launch-v1").is_file())


class FakeProbeCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.herdr, self.zsh = self.root / "herdr", self.root / "zsh"
        for path in (self.herdr, self.zsh):
            path.write_bytes(b"fixture")
        self.server = mock.Mock(pid=4242, returncode=None)
        self.server.poll.return_value = None
        self.server_log = b""
        self.clock = FakeClock()

    def probe_with(self, pane):
        with mock.patch.object(probe, "os", host_os("posix")), \
                mock.patch.object(probe, "time", self.clock), \
                mock.patch.object(probe.subprocess, "Popen", side_effect=server_with_codex_shim(self.root / "evidence", self.herdr, self.server, self.server_log)), \
                mock.patch.object(probe.subprocess, "run", side_effect=pane):
            return probe.run_probe(self.herdr, self.zsh, self.root / "evidence", None)


class HerdrProbeReadiness(FakeProbeCase):
    def test_waits_until_the_server_reports_running(self):
        pane = FakeZshPane(reads_until_prompt=1, not_ready=2)
        self.assertEqual(self.probe_with(pane)["status"], "PASS")
        self.assertEqual(pane.not_ready, -1)
        self.assertEqual(self.clock.sleeps, [0.2, 0.2])

    def test_reports_a_server_that_exits_before_it_is_ready_with_its_log_tail(self):
        self.server.poll.return_value = self.server.returncode = 1
        lines = [f"server line {index}" for index in range(1, 25)] + ["Error: local socket name length exceeds capacity of sun_path"]
        self.server_log = ("\n".join(lines) + "\n").encode()
        with self.assertRaises(RuntimeError) as raised:
            self.probe_with(FakeZshPane(reads_until_prompt=1, not_ready=5))
        message = str(raised.exception)
        self.assertEqual(message.splitlines(), ["isolated server exited: 1; server.log tail:", *lines[-20:]])
        result = json.loads((self.root / "evidence/result.json").read_text(encoding="utf-8"))
        self.assertEqual((result["status"], result["error"]), ("FAIL", message))
        self.assertFalse((self.root / "evidence/tmp").exists())


class HerdrProbeInterrupt(FakeProbeCase):
    def test_types_the_next_command_only_after_the_prompt_returns(self):
        pane = FakeZshPane(reads_until_prompt=3)
        state = self.probe_with(pane)
        self.assertEqual(state["status"], "PASS")
        self.assertEqual(state["checks"], ["zsh-command", "unicode-output", "ctrl-c"])
        self.assertEqual(pane.dropped, [])
        self.assertEqual(pane.interrupts, ["send-keys"])
        self.assertTrue(any(line.startswith("GX-SLEEP-EXIT-") and line.endswith(":130") for line in pane.lines))
        self.assertEqual(self.clock.sleeps, [0.2, 0.2])
        self.assertFalse((self.root / "evidence/tmp").exists())
        self.assertEqual(self.herdr.read_bytes(), b"fixture")

    def test_reports_a_prompt_that_never_returns_after_ctrl_c(self):
        pane = FakeZshPane(reads_until_prompt=None)
        message = "Zsh prompt did not return after Ctrl+C (sleep, send-keys ctrl+c)"
        with self.assertRaisesRegex(TimeoutError, "^" + re.escape(message) + "$"):
            self.probe_with(pane)
        self.assertEqual(pane.dropped, [])
        self.assertTrue(20 <= self.clock.now < 20.5)
        self.assertEqual(set(self.clock.sleeps), {0.2})
        result = json.loads((self.root / "evidence/result.json").read_text(encoding="utf-8"))
        self.assertEqual((result["status"], result["error"]), ("FAIL", message))
        self.assertFalse((self.root / "evidence/tmp").exists())


class FakeKernel32:
    def __init__(self, modules, process=0x1234, enumerated=1):
        self.modules, self.enumerated = modules, enumerated
        self.OpenProcess = mock.Mock(return_value=process)
        self.K32EnumProcessModulesEx = mock.Mock(side_effect=self._enumerate)
        self.K32GetModuleFileNameExW = mock.Mock(side_effect=self._file_name)
        self.CloseHandle = mock.Mock(return_value=1)

    def _enumerate(self, process, array, size, needed, flags):
        needed._obj.value = len(self.modules) * ctypes.sizeof(ctypes.c_void_p)
        for index, (module, _) in enumerate(self.modules[:len(array)]):
            array[index] = module
        return self.enumerated

    def _file_name(self, process, module, buffer, size):
        path = dict(self.modules).get(module)
        if not path:
            return 0
        buffer.value = path
        return len(path)


@contextlib.contextmanager
def fake_win32(kernel32, last_error):
    with mock.patch.object(ctypes, "WinDLL", create=True, return_value=kernel32) as loader, \
            mock.patch.object(ctypes, "get_last_error", create=True, return_value=last_error), \
            mock.patch.object(ctypes, "WinError", create=True, side_effect=lambda code: OSError(code, f"Win32 error {code}")):
        yield loader


class ProcessModulePaths(unittest.TestCase):
    def test_grows_the_module_buffer_and_closes_the_process(self):
        modules = [(0x10000 + index * 0x1000, f"C:\\fixture\\module{index}.dll") for index in range(300)]
        modules[7] = (modules[7][0], "")
        kernel32 = FakeKernel32(modules)
        with fake_win32(kernel32, 0) as loader:
            paths = probe.process_module_paths(4242)
        loader.assert_called_once_with("kernel32", use_last_error=True)
        kernel32.OpenProcess.assert_called_once_with(0x0400 | 0x0010, False, 4242)
        self.assertIs(kernel32.OpenProcess.restype, ctypes.c_void_p)
        self.assertEqual(kernel32.K32EnumProcessModulesEx.argtypes[1], ctypes.POINTER(ctypes.c_void_p))
        self.assertEqual(kernel32.K32EnumProcessModulesEx.call_count, 2)
        self.assertEqual(kernel32.K32EnumProcessModulesEx.call_args[0][4], 0x03)
        self.assertEqual(paths, [path for _, path in modules if path])
        kernel32.CloseHandle.assert_called_once_with(0x1234)

    def test_open_failure_raises_the_win32_error(self):
        kernel32 = FakeKernel32([], process=None)
        with fake_win32(kernel32, 87):
            with self.assertRaisesRegex(OSError, "Win32 error 87"):
                probe.process_module_paths(4242)
        kernel32.K32EnumProcessModulesEx.assert_not_called()
        kernel32.CloseHandle.assert_not_called()

    def test_enumeration_failure_still_closes_the_process(self):
        kernel32 = FakeKernel32([(0x10000, "C:\\fixture\\herdr.exe")], enumerated=0)
        with fake_win32(kernel32, 299):
            with self.assertRaisesRegex(OSError, "Win32 error 299"):
                probe.process_module_paths(4242)
        kernel32.CloseHandle.assert_called_once_with(0x1234)


class AppLocalConPty(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.herdr = self.root / "lib/herdr/herdr.exe"
        self.expected = (self.herdr.parent / "conpty/conpty.dll").resolve()
        self.server = mock.Mock(pid=4242, returncode=None)
        self.server.poll.return_value = None

    def test_retries_until_the_app_local_module_is_listed(self):
        system = str(self.root / "Windows/System32/kernel32.dll")
        queries = [OSError(299, "partial copy"), [system], [system, str(self.expected).upper()]]
        with mock.patch.object(probe, "process_module_paths", side_effect=queries) as query, \
                mock.patch.object(probe.time, "sleep") as sleep:
            self.assertEqual(probe.wait_for_app_local_conpty(self.server, self.herdr), self.expected)
        self.assertEqual(query.call_args_list, [mock.call(4242)] * 3)
        self.assertEqual(sleep.call_count, 2)

    def test_timeout_reports_the_conpty_found_and_every_module(self):
        other = str(self.root / "Windows/System32/kernel32.dll")
        wrong = str(self.root / "Windows/System32/conpty.dll")
        with mock.patch.object(probe, "process_module_paths", return_value=[other, wrong]):
            with self.assertRaises(RuntimeError) as raised:
                probe.wait_for_app_local_conpty(self.server, self.herdr, timeout=0)
        message = str(raised.exception)
        self.assertIn(str(self.expected), message)
        self.assertIn("conpty.dll loaded from: " + str(Path(wrong).resolve()), message)
        self.assertIn("2 modules seen: " + other, message)

    def test_timeout_reports_the_win32_error(self):
        with mock.patch.object(probe, "process_module_paths", side_effect=OSError(5, "Access is denied")):
            with self.assertRaisesRegex(RuntimeError, "module query failed: .*Access is denied"):
                probe.wait_for_app_local_conpty(self.server, self.herdr, timeout=0)

    def test_server_exit_stops_waiting(self):
        self.server.poll.return_value = 3
        self.server.returncode = 3
        with mock.patch.object(probe, "process_module_paths", return_value=[]), \
                mock.patch.object(probe.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, r"exited \(3\)"):
                probe.wait_for_app_local_conpty(self.server, self.herdr)
        sleep.assert_not_called()


class HerdrProbeWindowsBranch(unittest.TestCase):
    def run_windows_probe(self, root, pane):
        herdr, zsh = root / "lib/herdr/herdr.exe", root / "runtime/msys64/usr/bin/zsh.exe"
        for path in (herdr, zsh):
            path.parent.mkdir(parents=True)
            path.write_bytes(b"fixture")
        expected = (herdr.parent / "conpty/conpty.dll").resolve()
        server = mock.Mock(pid=4242, returncode=None)
        server.poll.return_value = None

        def call(argv, **kwargs):
            self.assertNotIn("powershell", Path(argv[0]).name.lower())
            return pane(argv, **kwargs)

        modules = [str(root / "Windows/System32/kernel32.dll"), str(expected)]
        with mock.patch.object(probe, "os", host_os("nt")), \
                mock.patch.dict(os.environ, {"SYSTEMROOT": str(root / "Windows")}), \
                mock.patch.object(probe, "time", FakeClock()), \
                mock.patch.object(probe.subprocess, "Popen", side_effect=server_with_codex_shim(root / "evidence", herdr, server)), \
                mock.patch.object(probe.subprocess, "run", side_effect=call), \
                mock.patch.object(probe, "process_module_paths", return_value=modules) as query:
            state = probe.run_probe(herdr, zsh, root / "evidence", root / "runtime/msys64")
        query.assert_called_with(4242)
        self.assertEqual(herdr.read_bytes(), b"fixture")
        return state, expected

    def test_records_the_loaded_app_local_conpty_without_powershell(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pane = FakeZshPane(reads_until_prompt=2)
            state, expected = self.run_windows_probe(root, pane)
            self.assertEqual((state["status"], state["loaded_conpty"]), ("PASS", str(expected)))
            result = json.loads((root / "evidence/result.json").read_text(encoding="utf-8"))
            self.assertEqual((result["status"], result["loaded_conpty"]), ("PASS", str(expected)))
            self.assertEqual(pane.dropped, [])
            self.assertFalse((root / "evidence/tmp").exists())

    def test_interrupts_native_ping_and_the_win32_input_record_after_they_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            pane = FakeZshPane(reads_until_prompt=2, reads_until_ping=3)
            state, _ = self.run_windows_probe(Path(temporary), pane)
        self.assertEqual(state["checks"], ["zsh-command", "unicode-output", "ctrl-c",
                                           "ctrl-c-native", "ctrl-c-win32-input", "ctrl-c-win32-input-native"])
        self.assertEqual(pane.interrupts, ["send-keys", "send-keys", "send-text", "send-text"])
        self.assertEqual((pane.early, pane.dropped), ([], []))
        pings = [command for command in pane.commands if command.endswith(" -n 30 127.0.0.1")]
        self.assertEqual(len(pings), 2)
        self.assertTrue(all("; '/c/Windows/System32/PING.EXE' -n 30" in command for command in pings))
        for name in ("SLEEP", "PING", "RECORD", "NATIVE-RECORD"):
            self.assertTrue(any(re.fullmatch(f"GX-{name}-EXIT-[0-9a-f]{{32}}:130", line) for line in pane.lines), name)

    def test_the_win32_input_mode_record_is_the_ctrl_c_key_down_and_up(self):
        self.assertEqual(probe.WIN32_CTRL_C, "\x1b[67;46;3;1;8;1_\x1b[67;46;3;0;8;1_")


@unittest.skipUnless(os.name == "nt", "real Win32 module enumeration needs Windows")
class ProcessModulePathsOnWindows(unittest.TestCase):
    def test_lists_the_python_runtime_of_this_process(self):
        import _ctypes
        modules = probe.process_module_paths(os.getpid())
        self.assertTrue(any(re.fullmatch(r"python3\d*\.dll", Path(module).name, re.I) for module in modules), modules)
        resolved = {str(Path(module).resolve()).lower() for module in modules}
        self.assertIn(str(Path(_ctypes.__file__).resolve()).lower(), resolved)

    def test_invalid_process_raises_the_win32_error(self):
        with self.assertRaises(OSError) as raised:
            probe.process_module_paths(0)
        self.assertEqual(raised.exception.winerror, 87)

    def test_proves_an_app_local_dll_in_a_live_child_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dll = root / "conpty/conpty.dll"
            dll.parent.mkdir()
            shutil.copyfile(Path(sys.base_prefix) / "python3.dll", dll)
            child = subprocess.Popen([sys.executable, "-c", "import ctypes, sys; ctypes.WinDLL(sys.argv[1]); sys.stdin.read()", str(dll)],
                                     stdin=subprocess.PIPE)
            try:
                self.assertEqual(probe.wait_for_app_local_conpty(child, root / "herdr.exe"), dll.resolve())
                with self.assertRaisesRegex(RuntimeError, "conpty.dll loaded from: " + re.escape(str(dll.resolve()))):
                    probe.wait_for_app_local_conpty(child, root / "elsewhere/herdr.exe", timeout=0)
            finally:
                child.stdin.close()
                child.wait(timeout=20)


if __name__ == "__main__":
    unittest.main()
