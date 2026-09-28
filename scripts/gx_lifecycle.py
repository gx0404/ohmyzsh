#!/usr/bin/env python3
"""真实安装包验收入口；默认拒绝系统操作，pending/failed 永不变成发布批准。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import uuid

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "gx0404/ohmyzsh"
CONFIRMATION = "I_UNDERSTAND_THIS_IS_A_DISPOSABLE_VM"
PLATFORMS = {"windows-x64": ".exe", "ubuntu-amd64": ".deb"}
COMMON_CHECKS = {
    "install", "reinstall", "upgrade", "uninstall", "user-data-preserved", "command-resolution",
    "herdr-tui", "zsh-pane", "ctrl-c", "resize", "detach-attach", "cwd", "agent-detection",
    "completion", "history", "p10k", "gitstatus", "zoxide", "unicode-input", "unicode-home",
    "unicode-config-cache", "space-paths", "managed-update-blocked",
}
WINDOWS_CHECKS = {"path-ownership", "path-conflict", "locked-file-rollback", "offline-start", "existing-installations-preserved", "long-paths"}
LINUX_CHECKS = {"dpkg-no-user-home", "purge-preserves-user-data"}
PROFILE_CHECKS = {"unicode-home", "unicode-config-cache", "space-paths", "history", "zoxide", "managed-update-blocked"}
TUI_CHECKS = {"herdr-tui", "zsh-pane", "ctrl-c", "resize", "detach-attach", "cwd", "completion", "unicode-input", "space-paths"}
PENDING_REASONS = {
    "agent-detection": "A real target agent has not been provided or exercised; a fake process name is not acceptance.",
    "p10k": "Packaged p10k cold/warm prompt rendering assertions remain required beyond the core TUI driver.",
    "gitstatus": "Packaged gitstatus daemon and prompt assertions remain required beyond the core TUI driver.",
    "offline-start": "No enforced network-isolated startup environment has been validated.",
    "existing-installations-preserved": "A pre-populated real foreign installation matrix remains required.",
    "long-paths": "A separate >260-character Windows path scenario remains required.",
}


class LifecycleError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise LifecycleError(message)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, f"duplicate JSON key: {key}")
        value[key] = item
    return value


def read_json(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
    require(isinstance(result, dict), "JSON object required")
    return result


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_relative(name: str, basename: bool = False) -> str:
    require(isinstance(name, str) and bool(name), "nonempty relative path required")
    require(not any(ord(ch) < 32 for ch in name) and not any(ch in name for ch in "\\:"), "unsafe path")
    path = PurePosixPath(name)
    require(not path.is_absolute() and all(part not in {"", ".", ".."} for part in name.split("/")), "unsafe path")
    require(not basename or path.name == name, "artifact filename must be a basename")
    return name


def disposable_guard(environment=None, *, disposable_vm=False, confirmation="") -> str:
    env = os.environ if environment is None else environment
    if (env.get("GITHUB_ACTIONS") == "true" and env.get("RUNNER_ENVIRONMENT") == "github-hosted"
            and env.get("GITHUB_REPOSITORY") == REPOSITORY):
        return "github-hosted"
    require(disposable_vm and confirmation == CONFIRMATION,
            "REFUSED: use the gx0404/ohmyzsh GitHub-hosted runner, or explicitly acknowledge a disposable VM; no installation was attempted")
    return "explicit-disposable-vm"


def required_checks(platform: str) -> set[str]:
    require(platform in PLATFORMS, "unsupported platform")
    return COMMON_CHECKS | (WINDOWS_CHECKS if platform == "windows-x64" else LINUX_CHECKS)


def verify_manifest(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink(), "manifest must be a regular file")
    info = read_json(path)
    require(info.get("schema_version") == 1 and info.get("product") == "ohmyzsh-gx", "invalid package manifest")
    platform = info.get("platform")
    require(platform in PLATFORMS, "unsupported manifest platform")
    require(re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", info.get("version", "")) is not None, "invalid version")
    source = info.get("source", {})
    require(source.get("repository") == REPOSITORY and re.fullmatch(r"[0-9a-f]{40}", source.get("revision", "")) is not None, "invalid source provenance")
    require(info.get("compliance_complete") is True and info.get("validation", {}).get("native_package_built") is True, "a built, redistribution-complete native package is required")
    records = info.get("artifacts")
    require(isinstance(records, list) and len(records) == 2, "exactly one installer and one corresponding-sources artifact required")
    require({item.get("role") for item in records if isinstance(item, dict)} == {"installer", "corresponding-sources"}, "invalid artifact roles")
    names = set()
    installer = None
    for record in records:
        name = safe_relative(record.get("filename"), basename=True)
        require(name.casefold() not in names, "duplicate artifact filename")
        names.add(name.casefold())
        artifact = path.parent / name
        require(artifact.is_file() and not artifact.is_symlink(), f"missing or symlinked artifact: {name}")
        require(type(record.get("size")) is int and record["size"] > 0 and artifact.stat().st_size == record["size"], f"artifact size mismatch: {name}")
        require(re.fullmatch(r"[0-9a-f]{64}", record.get("sha256", "")) is not None and digest(artifact) == record["sha256"], f"artifact hash mismatch: {name}")
        if record["role"] == "installer":
            require(artifact.suffix.lower() == PLATFORMS[platform], "installer extension does not match platform")
            with artifact.open("rb") as stream:
                magic = stream.read(8)
            require(magic.startswith(b"MZ") if platform == "windows-x64" else magic == b"!<arch>\n", "not a native EXE/DEB container")
            installer = {**record, "path": str(artifact.resolve())}
    return {"manifest": str(path.resolve()), "manifest_sha256": digest(path), "platform": platform,
            "version": info["version"], "source_revision": source["revision"], "installer": installer}


def verify_upgrade(initial: dict, installer: Path | None, manifest: Path | None = None) -> dict | None:
    if installer is None:
        require(manifest is None, "--upgrade-manifest needs --upgrade-installer")
        return None
    candidate = verify_manifest(manifest or installer.with_suffix(".manifest.json"))
    require(Path(candidate["installer"]["path"]) == installer.resolve(), "upgrade installer differs from its manifest")
    require(candidate["platform"] == initial["platform"], "upgrade platform mismatch")
    require(tuple(map(int, candidate["version"].split("."))) > tuple(map(int, initial["version"].split("."))), "upgrade must be a genuinely newer version, not a reinstall")
    require(candidate["installer"]["sha256"] != initial["installer"]["sha256"], "upgrade artifact is identical")
    return candidate


def host_environment(platform: str) -> str:
    if platform == "windows-x64":
        require(os.name == "nt", "Windows installer lifecycle requires Windows")
        return "windows-clean"
    require(sys.platform.startswith("linux"), "DEB lifecycle requires native Linux, not Windows Python")
    fields = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value.strip('"')
    require(fields.get("ID") == "ubuntu" and fields.get("VERSION_ID") in {"20.04", "24.04"}, "Ubuntu 20.04 or 24.04 required")
    return "ubuntu-" + fields["VERSION_ID"]


def plan_paths(evidence: Path, platform: str) -> dict:
    user = evidence / "user"
    home = user / "HOME 中文 用户"
    local = user / "LOCALAPPDATA 独立 中文 配置"
    config = user / "XDG 独立 中文 配置"
    return {"user": str(user), "home": str(home), "local": str(local), "roaming": str(user / "APPDATA 中文"),
            "config": str(config), "cache": str(user / "XDG cache"), "data": str(user / "XDG data"),
            "state": str(user / "XDG state"), "tmp": str(user / "tmp"),
            "profile": str((local if platform == "windows-x64" else config) / "ohmyzsh-gx/profile")}


def clean_environment(plan: dict) -> dict:
    paths = plan["paths"]
    env = {key: value for key, value in os.environ.items() if key.upper() in {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "OS"}}
    env.update({"HOME": paths["home"], "USERPROFILE": paths["home"], "LOCALAPPDATA": paths["local"], "APPDATA": paths["roaming"],
                "XDG_CONFIG_HOME": paths["config"], "XDG_CACHE_HOME": paths["cache"], "XDG_DATA_HOME": paths["data"], "XDG_STATE_HOME": paths["state"],
                "TMP": paths["tmp"], "TEMP": paths["tmp"], "TMPDIR": paths["tmp"], "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "xterm-256color",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "HERDR_SESSION": plan["session"], "HERDR_LANG": "en"})
    if plan["platform"] == "windows-x64":
        env["PATH"] = str(Path(env["SYSTEMROOT"]) / "System32")
        env["HOMEDRIVE"], env["HOMEPATH"] = Path(paths["home"]).drive, str(Path(paths["home"]))[len(Path(paths["home"]).drive):]
    else:
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    return env


def create_plan(args, initial: dict, upgrade: dict | None, authorization: str) -> dict:
    evidence = args.evidence.absolute()
    require(not evidence.exists() and not evidence.is_symlink(), "evidence must be a new directory")
    require(not any(ord(ch) < 32 or ch == '"' for ch in str(evidence)), "unsafe evidence path")
    require(evidence.parent.exists() and evidence.parent.resolve() == evidence.parent, "evidence parent must exist and contain no symlink traversal")
    environment = host_environment(initial["platform"])
    if initial["platform"] == "ubuntu-amd64":
        import pwd
        require(os.geteuid() == 0, "start the installer orchestration already privileged; this script never invokes sudo")
        require(bool(args.run_as_user), "Linux requires --run-as-user naming an existing non-root test account")
        account = pwd.getpwnam(args.run_as_user)
        require(account.pw_uid != 0, "the runtime test account must not be root")
    evidence.mkdir()
    paths = plan_paths(evidence, initial["platform"])
    for name, value in paths.items():
        if name != "profile":
            Path(value).mkdir(parents=True, exist_ok=True)
    (evidence / "logs").mkdir()
    (evidence / "results").mkdir()
    (evidence / "snapshots").mkdir()
    (evidence / "package-admin-home").mkdir()
    for name in (".zshrc", ".zsh_history"):
        (Path(paths["home"]) / name).write_text("GX lifecycle untouched HOME sentinel\n", encoding="utf-8")
    token = uuid.uuid4().hex[:12]
    install = str(Path(os.environ.get("SYSTEMDRIVE", "C:")) / ("gx-lifecycle-" + token)) if initial["platform"] == "windows-x64" else "/usr/lib/ohmyzsh-gx"
    if initial["platform"] == "windows-x64":
        install = os.environ.get("SYSTEMDRIVE", "C:") + "\\gx-lifecycle-" + token
        require(not Path(install).exists(), "fresh Windows install directory required")
    plan = {"schema_version": 1, "product": "ohmyzsh-gx", "platform": initial["platform"], "environment": environment,
            "evidence": str(evidence), "paths": paths, "initial": initial, "upgrade": upgrade, "effective": upgrade or initial,
            "install_root": install, "session": "gx-lifecycle-" + token, "run_as_user": args.run_as_user,
            "authorization": authorization, "disposable_environment": True}
    write_json(evidence / "plan.json", plan)
    return plan


def load_plan(path: Path) -> dict:
    plan = read_json(path)
    require(plan.get("schema_version") == 1 and plan.get("product") == "ohmyzsh-gx" and plan.get("platform") in PLATFORMS, "invalid lifecycle plan")
    root = Path(plan["evidence"])
    require(root.is_absolute() and path.resolve() == root / "plan.json" and not path.is_symlink(), "plan/evidence mismatch")
    require(root.resolve() == root and not any(ord(ch) < 32 or ch == '"' for ch in str(root)), "unsafe evidence directory")
    require(plan["paths"] == plan_paths(root, plan["platform"]), "user environment escaped the evidence directory")
    require(re.fullmatch(r"gx-lifecycle-[0-9a-f]{12}", plan["session"]) is not None, "unsafe session identifier")
    if plan["platform"] == "windows-x64":
        require(re.fullmatch(r"[A-Za-z]:\\gx-lifecycle-[0-9a-f]{12}", plan["install_root"]) is not None, "unsafe Windows install root")
    else:
        require(plan["install_root"] == "/usr/lib/ohmyzsh-gx", "unsafe Linux install root")
    for value in plan["paths"].values():
        target = Path(value)
        require(target.resolve().is_relative_to(root), "user path contains a symlink escape")
    for package in (plan["initial"], plan.get("upgrade")):
        if package:
            require(verify_manifest(Path(package["manifest"])) == package, "package changed after preflight")
    require(plan["effective"] == (plan.get("upgrade") or plan["initial"]), "effective package mismatch")
    return plan


def captured(plan: dict, label: str, argv: list[str], env: dict, *, expected=0, cwd: Path | None = None, timeout=180) -> subprocess.CompletedProcess:
    require(re.fullmatch(r"[a-z0-9-]+", label) is not None, "invalid log label")
    folder = Path(plan["evidence"]) / "logs"
    require(not (folder / (label + ".json")).exists(), "refusing to overwrite process evidence")
    try:
        result = subprocess.run(argv, env=env, cwd=cwd or plan["paths"]["home"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, start_new_session=os.name != "nt")
    except subprocess.TimeoutExpired as error:
        (folder / (label + ".stdout.log")).write_bytes(error.stdout or b"")
        (folder / (label + ".stderr.log")).write_bytes(error.stderr or b"")
        write_json(folder / (label + ".json"), {"argv": argv, "status": "timeout"})
        raise
    (folder / (label + ".stdout.log")).write_bytes(result.stdout)
    (folder / (label + ".stderr.log")).write_bytes(result.stderr)
    write_json(folder / (label + ".json"), {"argv": argv, "cwd": str(cwd or plan["paths"]["home"]), "exit_code": result.returncode})
    require(result.returncode == expected, f"{label} exited {result.returncode}; see saved stdout/stderr")
    return result


def snapshot_tree(root: Path) -> list[dict]:
    result = []
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink() and not getattr(path, "is_junction", lambda: False)(), "user fixture contains a symlink/reparse point")
        if path.is_file():
            require(path.name not in {".env", "id_rsa", "id_ed25519", "credentials", "auth.json"} and ".gnupg" not in path.parts, "private files are not lifecycle evidence")
            result.append({"path": path.relative_to(root).as_posix(), "sha256": digest(path), "size": path.stat().st_size})
    return result


PROFILE_SCRIPT = r'''setopt ERR_EXIT PIPE_FAIL
[[ -o interactive && -o login ]]
[[ $HOME == "$GX_EXPECTED_HOME" && $GX_PROFILE_DIR == "$GX_EXPECTED_PROFILE" ]]
[[ $ZDOTDIR == "$GX_PROFILE_DIR" && $GX_PROFILE_DIR != "$HOME" ]]
[[ $ZSH_COMPDUMP == "$GX_PROFILE_DIR"/* && $HISTFILE == "$GX_PROFILE_DIR"/* ]]
[[ $ZSH_CACHE_DIR == "$GX_PROFILE_DIR"/* && $XDG_CACHE_HOME == "$GX_PROFILE_DIR"/* ]]
[[ -s "$ZSH_COMPDUMP" && -n ${_comps[git]} && -n ${functions[omz]} ]]
[[ -z ${TTY:-} && -z $ZSH_THEME && ${+functions[p10k]} == 0 ]]
[[ -n ${functions[_zsh_autosuggest_start]} && -n ${functions[_zsh_highlight]} ]]
mkdir -p "$HOME/中文 工作 空格"
cd "$HOME/中文 工作 空格"
git init --quiet
print -r -- 中文输出
zoxide add "$PWD"
_gx_found=$(zoxide query -- "${PWD:t}")
if [[ $OSTYPE == (cygwin|msys)* ]]; then
  _gx_found=$(cygpath -u -- "$_gx_found")
fi
[[ ${_gx_found:A} == ${PWD:A} ]]
print -s -- "$GX_HISTORY_MARKER"
fc -W "$HISTFILE"
fc -R "$HISTFILE"
fc -ln -20 > "$GX_HISTORY_CAPTURE"
print -r -- "GX_DUMP=$ZSH_COMPDUMP"
print -r -- "GX_HOME=$HOME"
print -r -- "GX_PROFILE=$GX_PROFILE_DIR"
print -r -- "GX_CWD=$PWD"
print -r -- GX_REAL_PROFILE_OK
'''


def profile_probe(plan: dict, phase: str) -> dict:
    require(plan["platform"] == "windows-x64" or os.geteuid() != 0, "runtime validation must run as an ordinary user")
    root = Path(plan["install_root"])
    launcher = root / "bin" / ("gx-zsh.exe" if plan["platform"] == "windows-x64" else "gx-zsh")
    herdr = root / "bin" / ("herdr.exe" if plan["platform"] == "windows-x64" else "herdr")
    env = clean_environment(plan)
    folder = Path(plan["evidence"])
    script = folder / "logs" / ("profile-" + phase + ".zsh")
    script.write_text(PROFILE_SCRIPT, encoding="utf-8")
    saved_cache = folder / "logs" / (phase + "-previous-cache")
    for cache in Path(plan["paths"]["profile"]).glob(".zcompdump-*"):
        require(cache.is_file() and not cache.is_symlink(), "unexpected completion cache object")
        saved_cache.mkdir(exist_ok=True)
        cache.rename(saved_cache / cache.name)
    native_paths = {"GX_EXPECTED_HOME": plan["paths"]["home"], "GX_EXPECTED_PROFILE": plan["paths"]["profile"],
                    "GX_LIFECYCLE_SCRIPT": str(script), "GX_HISTORY_CAPTURE": str(folder / "logs" / (phase + "-history.txt"))}
    for key, value in native_paths.items():
        if plan["platform"] == "windows-x64":
            converted = captured(plan, phase + "-" + key.lower().replace("_", "-"), [str(root / "runtime/msys64/usr/bin/cygpath.exe"), "-u", "--", value], env)
            value = converted.stdout.decode("utf-8").strip()
        env[key] = value
    env["GX_HISTORY_MARKER"] = "GX-LIFECYCLE-HISTORY-" + plan["session"]
    require(any(ord(ch) > 127 for ch in env["GX_EXPECTED_HOME"]) and " " in env["GX_EXPECTED_HOME"], "Chinese/space HOME required")
    require(any(ord(ch) > 127 for ch in env["GX_EXPECTED_PROFILE"]) and " " in env["GX_EXPECTED_PROFILE"], "Chinese/space profile required")
    home_before = {name: digest(Path(plan["paths"]["home"]) / name) for name in (".zshrc", ".zsh_history")}
    dumps = []
    for temperature in ("cold", "warm"):
        result = captured(plan, phase + "-" + temperature, [str(launcher), "-c", 'source "$GX_LIFECYCLE_SCRIPT"'], env)
        lines = result.stdout.decode("utf-8").splitlines()
        require("GX_REAL_PROFILE_OK" in lines and "中文输出" in lines, "real profile did not produce its checked marker")
        cache = [p for p in Path(plan["paths"]["profile"]).glob(".zcompdump-*") if p.is_file() and not p.name.endswith(".zwc")]
        require(len(cache) == 1, "expected the actual profile's single completion dump")
        dumps.append({"path": str(cache[0]), "sha256": digest(cache[0]), "mtime_ns": cache[0].stat().st_mtime_ns})
    require(dumps[0] == dumps[1], "warm startup unexpectedly rewrote the completion dump")
    require(all(digest(Path(plan["paths"]["home"]) / name) == value for name, value in home_before.items()), "launcher changed ordinary HOME startup/history files")
    require(env["GX_HISTORY_MARKER"] in Path(native_paths["GX_HISTORY_CAPTURE"]).read_text(encoding="utf-8"), "Zsh history write/read did not round-trip")
    for index, argv in enumerate((["update"], ["channel", "set", "preview"])):
        result = subprocess.run([str(herdr), *argv], env=env, cwd=plan["paths"]["home"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        (folder / "logs" / f"{phase}-managed-{index}.log").write_bytes(result.stdout)
        require(result.returncode != 0 and b"managed by Oh My Zsh GX" in result.stdout, "managed update entry point did not reject mutation")
    write_json(folder / "logs" / (phase + "-profile-summary.json"), {"completion_dumps": dumps, "home_sentinels_preserved": True, "history_round_trip": True,
               "scope": "real installed gx-zsh profile, not interactive TUI/p10k rendering"})
    records = {name: {"status": "passed", "evidence": [f"logs/{phase}-cold.stdout.log", f"logs/{phase}-profile-summary.json"]} for name in PROFILE_CHECKS}
    records["managed-update-blocked"]["evidence"] = [f"logs/{phase}-managed-0.log", f"logs/{phase}-managed-1.log"]
    records["history"]["evidence"].append(f"logs/{phase}-history.txt")
    return records


def consume_tui_result(output: Path, platform: str, binary: Path) -> dict:
    state = read_json(output / "result.json")
    require(state.get("status") == "passed" and state.get("fixture_profile") is False, "prototype or failed TUI evidence cannot approve an installed package")
    require(state.get("platform") == platform and state.get("herdr_sha256") == digest(binary), "TUI binary/platform differs from the installed package")
    require(state.get("transport") == ("windows-system-conpty" if platform == "windows-x64" else "unix-controlling-pty"), "native controlling terminal evidence required")
    checks = state.get("checks", {})
    require(set(checks) == TUI_CHECKS, "TUI core check set is incomplete")
    if platform == "windows-x64":
        require(Path(state.get("inner_conpty", "")).resolve() == (binary.parent / "conpty/conpty.dll").resolve(), "TUI did not prove the packaged inner ConPTY")
    for name, result in checks.items():
        require(result.get("status") == "passed" and bool(result.get("evidence")), f"TUI check missing: {name}")
        for item in result["evidence"]:
            path = output / safe_relative(item)
            require(path.is_file() and not path.is_symlink() and path.stat().st_size > 0, "TUI evidence missing or empty")
    return checks


def worker(args) -> int:
    plan = load_plan(args.plan)
    require(re.fullmatch(r"[a-z0-9-]+", args.phase or "") is not None, "worker needs a safe --phase label")
    folder = Path(plan["evidence"])
    records = {}
    try:
        if args.worker == "profile":
            records = profile_probe(plan, args.phase)
        elif args.worker in {"snapshot", "compare"}:
            trees = {"user": snapshot_tree(Path(plan["paths"]["user"])), "package_admin_home": snapshot_tree(folder / "package-admin-home")}
            if args.worker == "snapshot":
                write_json(folder / "snapshots" / (args.phase + ".json"), {"trees": trees})
            else:
                require(re.fullmatch(r"[a-z0-9-]+", args.reference or "") is not None, "compare needs a snapshot reference")
                before = read_json(folder / "snapshots" / (args.reference + ".json"))["trees"]
                require(before == trees, "package operation changed isolated user or package-admin HOME data")
                write_json(folder / "logs" / (args.phase + "-preserved.json"), {"reference": args.reference, "matched": True, "trees": before})
        elif args.worker == "tui":
            require(plan["platform"] == "windows-x64" or os.geteuid() != 0, "TUI probe must run as an ordinary user")
            root = Path(plan["install_root"])
            windows = plan["platform"] == "windows-x64"
            raw = root / "lib/herdr" / ("herdr.exe" if windows else "herdr")
            shell = root / "runtime/msys64/usr/bin/zsh.exe" if windows else root / "bin/zsh"
            resources = root / "share/ohmyzsh-gx" if windows else Path("/usr/share/ohmyzsh-gx")
            output = folder / "logs" / (args.phase + "-tui")
            argv = [sys.executable, str(ROOT / "scripts/gx_tui_probe.py"), "--herdr", str(raw), "--zsh", str(shell),
                    "--output", str(output), "--installed-profile", "--profile-source", str(resources / "gx/config/zshrc"),
                    "--gx-root", str(resources), "--gx-bin", str(root / "bin"), "--client-entry", str(root / "bin" / ("herdr.exe" if windows else "herdr"))]
            if windows:
                argv += ["--msys-root", str(root / "runtime/msys64")]
            captured(plan, args.phase + "-tui-command", argv, clean_environment(plan), timeout=330)
            core = consume_tui_result(output, plan["platform"], raw)
            records = {name: {"status": "passed", "evidence": [f"logs/{args.phase}-tui/{item}" for item in result["evidence"]] + [f"logs/{args.phase}-tui/result.json"]}
                       for name, result in core.items()}
        else:
            require(plan["platform"] == "windows-x64" or os.geteuid() != 0, "headless runtime probe must not run as root")
            root = Path(plan["install_root"])
            raw = root / "lib/herdr" / ("herdr.exe" if plan["platform"] == "windows-x64" else "herdr")
            shell = root / "runtime/msys64/usr/bin/zsh.exe" if plan["platform"] == "windows-x64" else root / "bin/zsh"
            output = folder / "logs" / (args.phase + "-headless")
            argv = [sys.executable, str(ROOT / "scripts/gx_probe_herdr.py"), "--herdr", str(raw), "--zsh", str(shell), "--output", str(output)]
            if plan["platform"] == "windows-x64":
                argv += ["--msys-root", str(root / "runtime/msys64")]
            captured(plan, args.phase + "-headless-command", argv, clean_environment(plan))
            state = read_json(output / "result.json")
            require(state.get("status") == "PASS" and {"zsh-command", "ctrl-c"} <= set(state.get("checks", [])), "headless probe did not prove the expected subset")
            records = {name: {"status": "passed", "evidence": [f"logs/{args.phase}-headless/result.json", f"logs/{args.phase}-headless/commands.json"]} for name in ("zsh-pane", "ctrl-c")}
        write_json(folder / "results" / (args.phase + "-" + args.worker + ".json"), {"checks": records, "status": "passed", "scope": args.worker})
        return 0
    except Exception as error:
        names = {"profile": PROFILE_CHECKS, "headless": {"zsh-pane", "ctrl-c"}, "tui": TUI_CHECKS}.get(args.worker, set())
        evidence = f"logs/{args.phase}-{args.worker}-error.json"
        write_json(folder / evidence, {"error": str(error), "scope": args.worker})
        write_json(folder / "results" / (args.phase + "-" + args.worker + ".json"), {"status": "failed", "checks": {name: {"status": "failed", "reason": str(error), "evidence": [evidence]} for name in names}})
        print(f"gx-lifecycle worker: {error}", file=sys.stderr)
        return 1


def finalize(plan: dict, native_exit: int) -> tuple[Path, int]:
    folder = Path(plan["evidence"])
    checks = {name: {"status": "pending", "reason": PENDING_REASONS.get(name, "This check has not produced successful native execution evidence."), "evidence": []} for name in sorted(required_checks(plan["platform"]))}
    failed_scope = native_exit != 0
    for path in sorted((folder / "results").glob("*.json")):
        record = read_json(path)
        failed_scope |= record.get("status") == "failed"
        for name, result in record.get("checks", {}).items():
            require(name in checks and result.get("status") in {"passed", "failed", "pending"}, "invalid worker check")
            require(not (name in PENDING_REASONS and result["status"] == "passed"), f"unimplemented check cannot be promoted by a result file: {name}")
            if name in TUI_CHECKS - {"space-paths", "zsh-pane", "ctrl-c"} and result["status"] == "passed":
                require(record.get("scope") == "tui", "interactive checks require the real TUI worker, not profile/headless evidence")
                receipts = [item for item in result.get("evidence", []) if item.endswith("/result.json")]
                require(len(receipts) == 1, "interactive check requires its detailed TUI receipt")
                state = read_json(folder / safe_relative(receipts[0]))
                require(state.get("status") == "passed" and state.get("fixture_profile") is False and state.get("checks", {}).get(name, {}).get("status") == "passed", "prototype/failed TUI evidence cannot pass lifecycle")
            if checks[name]["status"] != "failed" and result["status"] != "pending":
                checks[name] = result
    files = []
    for prefix in ("logs", "results", "snapshots"):
        for path in sorted((folder / prefix).rglob("*")):
            if path.is_file():
                require(not path.is_symlink(), "symlinked evidence is forbidden")
                files.append({"path": path.relative_to(folder).as_posix(), "size": path.stat().st_size, "sha256": digest(path)})
    inventory = {item["path"]: item for item in files}
    for name, result in checks.items():
        if result["status"] == "passed":
            require(bool(result.get("evidence")), f"passed check lacks evidence: {name}")
        for entry in result.get("evidence", []):
            safe_relative(entry)
            require(entry in inventory and inventory[entry]["size"] > 0, f"missing/empty evidence for {name}")
    complete = all(value["status"] == "passed" for value in checks.values()) and not failed_scope
    failed = failed_scope or any(value["status"] == "failed" for value in checks.values())
    effective = plan["effective"]
    stem = f"ohmyzsh-gx_{effective['version']}_{plan['environment']}"
    archive = folder / (stem + ".evidence.tar.xz")
    with tarfile.open(archive, "w:xz", format=tarfile.PAX_FORMAT) as stream:
        for item in files:
            info = stream.gettarinfo(str(folder / item["path"]), arcname=item["path"])
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with (folder / item["path"]).open("rb") as source:
                stream.addfile(info, source)
    receipt = {"schema_version": 1, "platform": plan["platform"], "environment": plan["environment"], "source_revision": effective["source_revision"],
               "installer_sha256": effective["installer"]["sha256"], "installer_size": effective["installer"]["size"], "version": effective["version"],
               "initial_installer_sha256": plan["initial"]["installer"]["sha256"], "disposable_environment": True, "authorization": plan["authorization"],
               "evidence_reviewed": complete, "status": "passed" if complete else ("failed" if failed else "pending"), "native_exit_code": native_exit,
               "checks": checks, "evidence_files": files, "evidence_archive": {"filename": archive.name, "sha256": digest(archive), "size": archive.stat().st_size}}
    path = folder / (stem + ".validation.json")
    write_json(path, receipt)
    return path, 0 if complete else (1 if failed else 3)


def dispatch_argv(plan: dict, args) -> list[str]:
    path = str(Path(plan["evidence"]) / "plan.json")
    if plan["platform"] == "windows-x64":
        powershell = Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        command = [str(powershell), "-NoProfile", "-NonInteractive", "-File", str(ROOT / "scripts/gx_smoke_windows.ps1"), "-Plan", path, "-Python", sys.executable]
        if args.disposable_vm:
            command += ["-DisposableVm", "-ConfirmDisposableVm", args.confirm_disposable_vm]
    else:
        command = ["bash", str(ROOT / "scripts/gx_smoke_linux.sh"), "--plan", path, "--python", sys.executable]
        if args.disposable_vm:
            command += ["--disposable-vm", "--confirm-disposable-vm", args.confirm_disposable_vm]
    return command


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--evidence", type=Path, help="new directory; its parent must exist")
    parser.add_argument("--upgrade-installer", type=Path, help="genuinely newer EXE/DEB; receipt binds to this version after upgrade and fresh-install verification")
    parser.add_argument("--upgrade-manifest", type=Path, help="defaults to the upgrade installer's .manifest.json sibling")
    parser.add_argument("--run-as-user", help="Linux: existing non-root account; orchestration itself must already run as root")
    parser.add_argument("--disposable-vm", action="store_true")
    parser.add_argument("--confirm-disposable-vm", default="")
    parser.add_argument("--worker", choices=("profile", "headless", "tui", "snapshot", "compare"), help=argparse.SUPPRESS)
    parser.add_argument("--plan", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--phase", help=argparse.SUPPRESS)
    parser.add_argument("--reference", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        authorization = disposable_guard(disposable_vm=args.disposable_vm, confirmation=args.confirm_disposable_vm)
        if args.worker:
            require(args.plan is not None, "worker requires --plan")
            return worker(args)
        require(args.manifest is not None and args.evidence is not None, "--manifest and --evidence are required")
        initial = verify_manifest(args.manifest)
        upgrade = verify_upgrade(initial, args.upgrade_installer, args.upgrade_manifest)
        plan = create_plan(args, initial, upgrade, authorization)
        command = dispatch_argv(plan, args)
        write_json(Path(plan["evidence"]) / "logs/dispatch.json", {"argv": command, "scope": "native EXE/DEB lifecycle; this does not run during unit tests"})
        try:
            with (Path(plan["evidence"]) / "logs/native.log").open("wb") as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
            code = result.returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            write_json(Path(plan["evidence"]) / "logs/dispatch-error.json", {"error": str(error)})
            code = 1
        receipt, code = finalize(plan, code)
        print(json.dumps({"receipt": str(receipt), "exit_code": code, "release_approved": code == 0}))
        return code
    except (LifecycleError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"gx-lifecycle: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
