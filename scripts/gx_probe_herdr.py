#!/usr/bin/env python3
"""在独立用户环境中验证 herdr 的真实 Zsh 窗格；不安装到系统、不接管既有会话。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


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
        result = subprocess.run([str(msys_root / "usr/bin/cygpath.exe"), "-u", "--", env["HOME"]],
                                env=env, check=True, capture_output=True, text=True, encoding="utf-8")
        env["ZDOTDIR"] = result.stdout.strip()
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
            status = cli("status", check=False)
            if status.returncode == 0:
                break
            if server.poll() is not None:
                raise RuntimeError(f"isolated server exited: {server.returncode}")
            if time.monotonic() >= deadline:
                raise TimeoutError("isolated server did not become ready")
            time.sleep(0.2)
        created = json.loads(cli("workspace", "create", "--cwd", str(output / "home")).stdout)
        pane = created["result"]["root_pane"]["pane_id"]
        def send(command):
            cli("pane", "send-text", pane, command)
            cli("pane", "send-keys", pane, "Enter")

        def wait_text(needle):
            deadline = time.monotonic() + 20
            while True:
                screen = cli("pane", "read", pane, "--source", "recent-unwrapped", "--lines", "200", "--format", "text").stdout
                (output / "pane.txt").write_text(screen, encoding="utf-8")
                if needle in screen:
                    return screen
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Zsh pane did not produce {needle!r}")
                time.sleep(0.2)

        token = uuid.uuid4().hex
        marker = "GX-ZSH-" + token
        send("printf '%s%s:%s\\n' GX-ZSH- " + token + ' "$ZSH_VERSION"')
        wait_text(marker + ":5.")
        send("printf '%b\\n' '\\u4e2d\\u6587'; printf '%s%s\\n' GX-SLEEP- " + token + "; sleep 30")
        wait_text("GX-SLEEP-" + token)
        cli("pane", "send-keys", pane, "ctrl+c")
        send("printf '%s%s:%s\\n' GX-INTERRUPT- " + token + ' "$?"')
        screen = wait_text("GX-INTERRUPT-" + token + ":130")
        if "中文" not in screen.splitlines():
            raise RuntimeError("Unicode output was not preserved in the pane")
        state.update(pane=pane, zsh_marker=marker, server_pid=server.pid,
                     checks=["zsh-command", "unicode-output", "ctrl-c"])
        if os.name == "nt":
            powershell = Path(env["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            command = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); " + f"(Get-Process -Id {server.pid}).Modules | Where-Object {{ $_.ModuleName -ieq 'conpty.dll' }} | ForEach-Object {{ $_.FileName }}"
            modules = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
                                     env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
            loaded = [Path(line.strip()).resolve() for line in modules.stdout.splitlines() if line.strip()]
            expected = (herdr.parent / "conpty/conpty.dll").resolve()
            if modules.returncode or expected not in loaded:
                raise RuntimeError(f"app-local ConPTY not proven: {modules.stdout} {modules.stderr}")
            state["loaded_conpty"] = str(expected)
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
