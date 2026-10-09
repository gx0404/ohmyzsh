#!/usr/bin/env python3
"""在独立用户环境中验证 herdr 的真实 Zsh 窗格；不安装到系统、不接管既有会话。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

# 终端在 win32-input-mode 下为 Ctrl+C 发送的按下/抬起记录（Vk=67 'C'、Sc=46、Uc=3、
# LEFT_CTRL_PRESSED）；herdr 客户端原样转发这类记录，经 pane send-text 注入即走同一条链路。
WIN32_CTRL_C = "\x1b[67;46;3;1;8;1_\x1b[67;46;3;0;8;1_"


def process_module_paths(pid: int) -> list:
    """列出 Windows 进程已加载模块的完整路径。

    直接调用 Win32 而不启动 PowerShell：托管 runner 上 PowerShell 冷启动可超过 20 秒。
    ctypes 的 Windows 专有部分只在调用时加载，Linux 与 Python 3.8 照常导入本模块。
    """
    import ctypes

    handle, dword = ctypes.c_void_p, ctypes.c_uint32
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, arguments, result in (
            ("OpenProcess", [dword, ctypes.c_int, dword], handle),
            ("K32EnumProcessModulesEx", [handle, ctypes.POINTER(handle), dword, ctypes.POINTER(dword), dword], ctypes.c_int),
            ("K32GetModuleFileNameExW", [handle, handle, ctypes.c_wchar_p, dword], dword),
            ("CloseHandle", [handle], ctypes.c_int)):
        function = getattr(kernel32, name)
        function.argtypes, function.restype = arguments, result
    query_information, vm_read, list_modules_all = 0x0400, 0x0010, 0x03
    process = kernel32.OpenProcess(query_information | vm_read, False, pid)
    if not process:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        capacity = 256
        while True:
            modules = (handle * capacity)()
            needed = dword()
            if not kernel32.K32EnumProcessModulesEx(process, modules, ctypes.sizeof(modules),
                                                    ctypes.byref(needed), list_modules_all):
                raise ctypes.WinError(ctypes.get_last_error())
            if needed.value <= ctypes.sizeof(modules):
                break
            capacity = needed.value // ctypes.sizeof(handle) + 64
        buffer = ctypes.create_unicode_buffer(32768)
        paths = []
        for module in modules[:needed.value // ctypes.sizeof(handle)]:
            # 枚举后才卸载的模块查不到名字，跳过即可；调用方会限时重试。
            length = kernel32.K32GetModuleFileNameExW(process, module, buffer, len(buffer))
            if length:
                paths.append(buffer[:length])
        return paths
    finally:
        kernel32.CloseHandle(process)


def wait_for_app_local_conpty(server, herdr: Path, timeout: float = 10.0) -> Path:
    """证明自有 herdr server 加载的是 herdr 旁 conpty/ 下的 conpty.dll（解析后路径、不分大小写）。

    server 刚启动时模块表可能不完整或暂时读不到，限时重试；失败时报告所见模块或 Win32 错误。
    """
    expected = (herdr.parent / "conpty/conpty.dll").resolve()
    deadline = time.monotonic() + timeout
    while True:
        try:
            modules = process_module_paths(server.pid)
        except OSError as error:
            detail = f"module query failed: {error}"
        else:
            conpty = [str(Path(module).resolve()) for module in modules if Path(module).name.lower() == "conpty.dll"]
            if str(expected).lower() in {path.lower() for path in conpty}:
                return expected
            detail = (f"conpty.dll loaded from: {', '.join(conpty) or 'nowhere'}; "
                      f"{len(modules)} modules seen: {', '.join(modules)}")
        if server.poll() is not None:
            raise RuntimeError(f"isolated server exited ({server.returncode}) before app-local ConPTY was proven; {detail}")
        if time.monotonic() >= deadline:
            raise RuntimeError(f"app-local ConPTY {expected} not proven in server {server.pid} within {timeout:g}s; {detail}")
        time.sleep(0.2)


def run_probe(herdr: Path, zsh: Path, output: Path, msys_root: Path | None) -> dict:
    herdr = herdr.resolve(strict=True)
    zsh = zsh.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=False)
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "OS"}}
    for name, relative in {
        "HOME": "home", "USERPROFILE": "home", "APPDATA": "roaming", "LOCALAPPDATA": "local",
        "XDG_CONFIG_HOME": "config", "XDG_CACHE_HOME": "cache", "XDG_STATE_HOME": "state",
        "XDG_DATA_HOME": "data", "TMP": "tmp", "TEMP": "tmp", "TMPDIR": "tmp",
    }.items():
        path = output / relative
        path.mkdir(exist_ok=True)
        env[name] = str(path)
    session = "gx-probe-" + uuid.uuid4().hex[:16]
    env.update(HERDR_SESSION=session, HERDR_LANG="en", TERM="xterm-256color", LANG="C.UTF-8",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, NO_COLOR="1")
    if os.name == "nt":
        if msys_root is None:
            raise ValueError("--msys-root is required on Windows")
        msys_root = msys_root.resolve(strict=True)
        system = Path(env["SYSTEMROOT"]) / "System32"
        env["PATH"] = os.pathsep.join(map(str, [msys_root / "usr/bin", msys_root / "ucrt64/bin", system]))
        env.update(MSYSTEM="MSYS", MSYS2_PATH_TYPE="inherit", CHERE_INVOKING="1")
        result = subprocess.run([str(msys_root / "usr/bin/cygpath.exe"), "-u", "--", env["HOME"], str(system / "PING.EXE")],
                                env=env, check=True, capture_output=True, text=True, encoding="utf-8")
        env["ZDOTDIR"], ping = result.stdout.splitlines()
    else:
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
        env["ZDOTDIR"] = env["HOME"]
    (output / "home/.zshenv").write_text(
        "skip_global_compinit=1\ntypeset -U path PATH\npath=(/usr/bin /ucrt64/bin $path)\n",
        encoding="utf-8",
    )
    (output / "home/.zshrc").write_text("PROMPT='gx-probe> '\n", encoding="utf-8")
    config = output / "config/probe.toml"
    config.write_text(
        "[terminal]\ndefault_shell = " + json.dumps(str(zsh), ensure_ascii=False)
        + '\nshell_mode = "login"\n[update]\nversion_check = false\nmanifest_check = false\n',
        encoding="utf-8",
    )
    env["HERDR_CONFIG_PATH"] = str(config)
    transcript = []

    def cli(*args: str, check=True):
        result = subprocess.run([str(herdr), *args], env=env, cwd=output / "home",
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        transcript.append({"args": list(args), "exit_code": result.returncode,
                           "stdout": result.stdout, "stderr": result.stderr})
        if check and result.returncode:
            raise RuntimeError(f"herdr {args!r} failed ({result.returncode}): {result.stderr or result.stdout}")
        return result

    version = cli("--version").stdout.strip()
    cli("config", "check")
    server = None
    state = {"status": "FAIL", "session": session, "version": version, "output": str(output),
             "scope": "headless server with real Zsh PTY; not interactive TUI or installer lifecycle"}
    try:
        with (output / "server.log").open("wb") as log:
            server = subprocess.Popen([str(herdr), "server"], env=env, cwd=output / "home",
                                      stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 30
        while True:
            # herdr status 不论 server 是否在运行都返回 0；只有 running 为 true 才算就绪。
            status = cli("status", "server", "--json", check=False)
            try:
                ready = status.returncode == 0 and json.loads(status.stdout).get("running") is True
            except (ValueError, AttributeError):
                ready = False
            if ready:
                break
            if server.poll() is not None:
                # 启动即退出（如 Linux 套接字路径超出 sun_path）只在 server.log 里留原因，附末尾以便从 CI 证据诊断。
                tail = (output / "server.log").read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
                raise RuntimeError(f"isolated server exited: {server.returncode}; server.log tail:\n" + "\n".join(tail))
            if time.monotonic() >= deadline:
                raise TimeoutError("isolated server did not become ready")
            time.sleep(0.2)
        created = json.loads(cli("workspace", "create", "--cwd", str(output / "home")).stdout)
        pane = created["result"]["root_pane"]["pane_id"]
        def send(command):
            cli("pane", "send-text", pane, command)
            cli("pane", "send-keys", pane, "Enter")

        def wait_screen(ready, failure):
            deadline = time.monotonic() + 20
            while True:
                screen = cli("pane", "read", pane, "--source", "recent-unwrapped", "--lines", "200", "--format", "text").stdout
                (output / "pane.txt").write_text(screen, encoding="utf-8")
                if ready(screen):
                    return screen
                if time.monotonic() >= deadline:
                    raise TimeoutError(failure)
                time.sleep(0.2)

        def wait_text(needle):
            return wait_screen(lambda screen: needle in screen, f"Zsh pane did not produce {needle!r}")

        def after(line_marker, needle):
            def ready(screen):
                _, found, rest = screen.partition(line_marker)
                return bool(found) and any(needle in line for line in rest.splitlines()[1:])
            return ready

        token = uuid.uuid4().hex
        marker = "GX-ZSH-" + token
        send("printf '%s%s:%s\\n' GX-ZSH- " + token + ' "$ZSH_VERSION"')
        wait_text(marker + ":5.")

        def interrupt(name, command, key, label, before="", running=None):
            start = f"GX-{name}-{token}"
            send(f"{before}printf '%s%s\\n' GX-{name}- {token}; {command}")
            wait_screen(after(start, running) if running else lambda screen: start in screen, f"{label} did not start")
            cli("pane", key[0], pane, key[1])
            # MSYS2 Zsh 处理中断时会丢弃提前到达的键入：新提示符出现后才输入下一条命令。
            wait_screen(after(start, "gx-probe>"), f"Zsh prompt did not return after Ctrl+C ({label})")
            send(f"printf '%s%s:%s\\n' GX-{name}-EXIT- {token} \"$?\"")
            return wait_text(f"GX-{name}-EXIT-{token}:130")

        keys, record = ("send-keys", "ctrl+c"), ("send-text", WIN32_CTRL_C)
        screen = interrupt("SLEEP", "sleep 30", keys, "sleep, send-keys ctrl+c", before="printf '%b\\n' '\\u4e2d\\u6587'; ")
        if "中文" not in screen.splitlines():
            raise RuntimeError("Unicode output was not preserved in the pane")
        checks = ["zsh-command", "unicode-output", "ctrl-c"]
        if os.name == "nt":
            # ping 的输出随系统语言变化，只认目标地址：它出现在起始标记之后，原生程序才已在前台运行。
            native = "'" + ping.replace("'", "'\\''") + "' -n 30 127.0.0.1"
            interrupt("PING", native, keys, "native ping, send-keys ctrl+c", running="127.0.0.1")
            interrupt("RECORD", "sleep 30", record, "sleep, win32-input-mode Ctrl+C record")
            interrupt("NATIVE-RECORD", native, record, "native ping, win32-input-mode Ctrl+C record", running="127.0.0.1")
            checks += ["ctrl-c-native", "ctrl-c-win32-input", "ctrl-c-win32-input-native"]
        state.update(pane=pane, zsh_marker=marker, server_pid=server.pid, checks=checks)
        if os.name == "nt":
            state["loaded_conpty"] = str(wait_for_app_local_conpty(server, herdr))
        state["status"] = "PASS"
    except Exception as error:
        state["error"] = str(error)
        raise
    finally:
        try:
            if server is not None:
                try:
                    stopped = cli("server", "stop", check=False)
                    if stopped.returncode:
                        state.update(status="FAIL", cleanup_error=f"server stop failed: {stopped.returncode}")
                except (OSError, subprocess.SubprocessError) as error:
                    state.update(status="FAIL", cleanup_error=f"server stop command failed: {error}")
                try:
                    server.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    state.update(status="FAIL", cleanup_error="server did not stop; only the probe-owned server is terminated")
                    server.terminate()
                    try:
                        server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=10)
            # server 已停止才删：herdr 在隔离 TMP 放的 Codex 垫片是 herdr 本体的硬链接/副本或符号链接，不属于证据。
            shutil.rmtree(output / "tmp", ignore_errors=True)
        except (OSError, subprocess.SubprocessError) as error:
            state.update(status="FAIL", cleanup_error=f"probe-owned server cleanup failed: {error}")
        finally:
            (output / "commands.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (output / "result.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if state["status"] != "PASS":
        raise RuntimeError(state.get("cleanup_error", "probe failed"))
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--herdr", required=True, type=Path)
    parser.add_argument("--zsh", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new isolated evidence directory")
    parser.add_argument("--msys-root", type=Path)
    args = parser.parse_args()
    try:
        result = run_probe(args.herdr, args.zsh, args.output.resolve(), args.msys_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
