#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

import gx_dependencies as deps
from gx_p10k_metadata import runtime_identity

ROOT = Path(__file__).resolve().parent.parent
RESOURCE_FILES = {
    "oh-my-zsh.sh", "LICENSE.txt", "gx/config/zshrc", "gx/config/zshenv",
    "gx/config/package.zsh", "gx/config/p10k.zsh", "gx/config/terminal.zsh",
}
BUILD_FILES = {
    "CHANGELOG.md", "scripts/gx-launcher/main.rs", "scripts/gx_package.py", "scripts/gx_p10k_metadata.py",
    "scripts/gx_build_herdr.py", "scripts/gx_release.py", "scripts/packaging/herdr-license-supplements.json",
    "scripts/gx_dependencies.py", "scripts/gx_build_zsh.py", "scripts/packaging/zsh-runtime-lock.json", "scripts/packaging/dependencies.json",
    "scripts/packaging/msys2-lock.json", "scripts/packaging/redistribution-lock.json", "scripts/packaging/windows.iss",
    "scripts/packaging/debian/control", "scripts/packaging/debian/postinst",
    "scripts/packaging/debian/postrm", "scripts/packaging/debian/preinst",
}
FONT_ROOT = "gx/fonts/JetBrainsMonoNerd/"
LINUX_BINARIES = {"gx/bin/gitstatusd-linux-x86_64", "gx/bin/zoxide-linux-x86_64"}
REQUIRED_RESOURCES = RESOURCE_FILES | {
    "lib/cli.zsh", "lib/git.zsh", "plugins/herdr/herdr.plugin.zsh",
    "gx/omz-custom/themes/powerlevel10k/powerlevel10k.zsh-theme",
    "gx/omz-custom/themes/powerlevel10k/LICENSE",
    "gx/omz-custom/themes/powerlevel10k/internal/p10k.zsh",
    "gx/omz-custom/themes/powerlevel10k/gitstatus/gitstatus.plugin.zsh",
}


class PackageError(ValueError):
    pass


def git(repo: Path, *args: str) -> bytes:
    process = subprocess.run(["git", "-C", str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode:
        raise PackageError(process.stderr.decode("utf-8", errors="replace").strip())
    return process.stdout


def build_input_allowed(name: str) -> bool:
    return name in BUILD_FILES or name.startswith(("scripts/packaging/notices/", "scripts/packaging/patches/zsh/"))


def resource_allowed(name: str) -> bool:
    if name in RESOURCE_FILES or name in LINUX_BINARIES:
        return True
    if name.startswith(("plugins/", "gx/omz-custom/", FONT_ROOT)):
        return not any(part in {"tests", ".git", ".github"} for part in PurePosixPath(name).parts)
    path = PurePosixPath(name)
    return (len(path.parts) == 2 and path.parts[0] in {"lib", "tools", "themes"}
            and (path.suffix in {".zsh", ".sh", ".zsh-theme"}))


def current_version(text: str) -> str:
    found = re.findall(r"^##\s+(\d+)\.(\d+)\.(\d+)\s*\((?:TBD|\d{8}|\d{4}-\d{2}-\d{2})\)\s*$", text, re.M)
    if not found:
        raise PackageError("CHANGELOG.md has no valid fork version")
    return ".".join(map(str, max(tuple(map(int, version)) for version in found)))


def clean_source(repo: Path, ref: str, allow_dirty: bool = False) -> dict:
    if ref.startswith("-"):
        raise PackageError("invalid Git ref")
    revision = git(repo, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
    if not deps.REVISION.fullmatch(revision):
        raise PackageError("expected full Git commit SHA")
    dirty = (
        bool(git(repo, "diff", "--name-only", "--no-ext-diff", "HEAD", "--"))
        or bool(git(repo, "diff", "--cached", "--name-only", "--no-ext-diff", "HEAD", "--"))
        or bool(git(repo, "ls-files", "--others", "--exclude-standard", "-z"))
    )
    if dirty and not allow_dirty:
        raise PackageError("official package requires a clean Git worktree; --allow-dirty is local development only")
    if allow_dirty and revision != git(repo, "rev-parse", "HEAD").decode().strip():
        raise PackageError("--allow-dirty can only use HEAD, not overlay an unrelated commit")
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8") if allow_dirty else git(repo, "show", revision + ":CHANGELOG.md").decode()
    return {
        "repository": "gx0404/ohmyzsh", "revision": revision,
        "version": current_version(text), "dirty": dirty, "development": allow_dirty,
        "publishable": not allow_dirty,
        "source_date_epoch": int(git(repo, "show", "-s", "--format=%ct", revision).decode()),
    }


def snapshot(repo: Path, source: dict) -> dict[str, tuple[bytes, int]]:
    entries = {}
    for record in git(repo, "ls-tree", "-rz", source["revision"]).split(b"\0"):
        if not record:
            continue
        header, raw_name = record.split(b"\t", 1)
        mode, kind, oid = header.decode().split()
        name = raw_name.decode("utf-8")
        if not (resource_allowed(name) or build_input_allowed(name)):
            continue
        deps.relative_path(name)
        if kind != "blob":
            raise PackageError(f"submodules are not release inputs: {name}")
        entries[name] = (oid, int(mode, 8))
    ids = [oid for oid, _ in entries.values()]
    process = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], input=("\n".join(ids) + "\n").encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    offset = 0
    result = {}
    for name, (_, mode) in entries.items():
        end = process.stdout.index(b"\n", offset)
        header = process.stdout[offset:end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise PackageError("unexpected Git blob response")
        length = int(header[2])
        result[name] = (process.stdout[end + 1:end + 1 + length], mode)
        offset = end + 2 + length
    if source["development"]:
        candidates = set(result) | RESOURCE_FILES | BUILD_FILES
        for raw_name in git(repo, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
            if raw_name:
                name = raw_name.decode()
                if resource_allowed(name) or build_input_allowed(name):
                    candidates.add(name)
        for name in candidates:
            path = deps.inside(repo, name)
            if path.is_symlink():
                result[name] = (os.readlink(path).encode(), 0o120000)
            elif path.is_file():
                data = path.read_bytes()
                if b"\0" not in data:
                    data = data.replace(b"\r\n", b"\n")
                result[name] = (data, entries.get(name, ("", 0o100644))[1])
            else:
                result.pop(name, None)
    for name, (data, mode) in list(result.items()):
        if mode == 0o120000:
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), data.decode()))
            deps.relative_path(target)
            if target not in result or result[target][1] == 0o120000:
                raise PackageError(f"unresolved source symlink: {name}")
            result[name] = result[target]
        elif mode not in {0o100644, 0o100755}:
            raise PackageError(f"unsupported source mode: {name}")
    return result


def write_snapshot(files: dict[str, tuple[bytes, int]], destination: Path) -> None:
    for name, (data, mode) in files.items():
        path = deps.inside(destination, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755 if mode & 0o111 else 0o644)


def compile_launchers(source: Path, destination: Path, platform: str, lock: dict, rustc: str) -> None:
    version = subprocess.run([rustc, "--version"], check=True, capture_output=True, text=True).stdout.split()
    if len(version) < 2 or version[1] != lock["herdr"]["rust"]:
        raise PackageError(f"launcher compiler must be Rust {lock['herdr']['rust']}")
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("gx-zsh", "herdr"):
        target = destination / (name + (".exe" if platform == "windows-x64" else ""))
        command = [rustc, str(source), "--edition=2021", "-C", "opt-level=s", "-C", "strip=symbols", "-C", "target-feature=+crt-static", "--target", lock["herdr"]["targets"][platform], "-o", str(target)]
        if name == "herdr":
            command.extend(["--cfg", "gx_herdr"])
        subprocess.run(command, check=True)
        deps.check_binary(target, platform, static=platform == "ubuntu-amd64")
        target.chmod(0o755)


def merge_tree(source: Path, destination: Path) -> None:
    for record in deps.tree_manifest(source):
        deps.install_mapping(source, destination, {"from": record["path"], "to": record["path"]})


def stage(repo: Path, ref: str, platform: str, dependency_bundle: Path, output: Path, *, allow_dirty: bool = False, version: str | None = None, rustc: str = "rustc") -> dict:
    source = clean_source(repo, ref, allow_dirty)
    if version and version != source["version"]:
        raise PackageError("requested version does not match CHANGELOG.md")
    files = snapshot(repo, source)
    missing = (REQUIRED_RESOURCES | BUILD_FILES) - files.keys()
    if missing:
        raise PackageError(f"Git snapshot missing package inputs: {sorted(missing)}")
    if output.exists():
        raise PackageError(f"stage already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".gx-stage-", dir=output.parent) as temporary:
        work = Path(temporary)
        snap = work / "snapshot"
        write_snapshot(files, snap)
        lock = deps.load_lock(snap / "scripts/packaging/dependencies.json")
        for item in lock.get("vendored_files", []):
            name = str(deps.relative_path(item["path"]))
            if name not in files or hashlib.sha256(files[name][0]).hexdigest() != item["sha256"]:
                raise PackageError(f"vendored font/binary differs from its verified upstream release: {name}")
        dependency = deps.verify_bundle(lock, platform, dependency_bundle)
        result_root = work / "result"
        payload = result_root / "payload"
        prefix = payload if platform == "windows-x64" else payload / "usr/lib/ohmyzsh-gx"
        resources = payload / ("share/ohmyzsh-gx" if platform == "windows-x64" else "usr/share/ohmyzsh-gx")
        resource_files = {name: entry for name, entry in files.items() if resource_allowed(name) and name not in LINUX_BINARIES and not name.startswith(FONT_ROOT)}
        write_snapshot(resource_files, resources)
        theme_identity = runtime_identity(resources, platform, dependency["zsh"]["binary_sha256"])
        (resources / "p10k-runtime-id").write_text(theme_identity + "\n", encoding="ascii", newline="\n")
        merge_tree(dependency_bundle / "payload", prefix)
        if platform == "ubuntu-amd64":
            for name, destination in (("gx/bin/zoxide-linux-x86_64", "bin/zoxide"), ("gx/bin/gitstatusd-linux-x86_64", "lib/gitstatus/gitstatusd-linux-x86_64")):
                if name not in files:
                    raise PackageError(f"missing locked Linux binary: {name}")
                target = prefix / destination
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(files[name][0])
                target.chmod(0o755)
                deps.check_binary(target, platform)
        fonts = {name: value for name, value in files.items() if name.startswith(FONT_ROOT) and name.endswith(".ttf")}
        if len(fonts) != 4:
            raise PackageError("expected four pinned JetBrainsMono Nerd Font faces")
        font_root = payload / ("fonts" if platform == "windows-x64" else "usr/share/fonts/truetype/ohmyzsh-gx")
        font_root.mkdir(parents=True)
        for name, (data, _) in fonts.items():
            (font_root / PurePosixPath(name).name).write_bytes(data)
        compile_launchers(snap / "scripts/gx-launcher/main.rs", prefix / "bin", platform, lock, rustc)
        if platform == "ubuntu-amd64":
            (payload / "usr/bin").mkdir(parents=True)
            for name in ("gx-zsh", "herdr"):
                (payload / "usr/bin" / name).symlink_to("../lib/ohmyzsh-gx/bin/" + name)
            control_root = payload / "DEBIAN"
            control_root.mkdir()
            size = sum(p.stat().st_size for p in payload.rglob("*") if p.is_file()) // 1024
            replacements = {"@VERSION@": source["version"] + ("~dev" if source["development"] else ""), "@INSTALLED_SIZE@": str(size)}
            for name in ("control", "preinst", "postinst", "postrm"):
                text = files["scripts/packaging/debian/" + name][0].decode()
                for key, value in replacements.items():
                    text = text.replace(key, value)
                target = control_root / name
                target.write_text(text, encoding="utf-8", newline="\n")
                target.chmod(0o644 if name == "control" else 0o755)
        licenses = payload / ("licenses" if platform == "windows-x64" else "usr/share/doc/ohmyzsh-gx/licenses")
        licenses.mkdir(parents=True)
        (licenses / "ohmyzsh-LICENSE.txt").write_bytes(files["LICENSE.txt"][0])
        for path in (dependency_bundle / "redistribution").rglob("*"):
            if path.is_file() and ("licenses" in path.parts or "license" in path.name.lower()):
                target = licenses / path.relative_to(dependency_bundle / "redistribution")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        deps.write_json(resources / "dependencies-manifest.json", dependency)
        deps.write_json(resources / "package-origin.json", {"source": source, "herdr": {k: lock["herdr"][k] for k in ("repository", "revision", "version", "rust", "zig")}, "platform": platform})
        shutil.copytree(dependency_bundle / "redistribution", result_root / "redistribution/dependencies")
        write_snapshot(files, result_root / "redistribution/ohmyzsh-gx")
        (result_root / "build-inputs").mkdir()
        (result_root / "build-inputs/windows.iss").write_bytes(files["scripts/packaging/windows.iss"][0])
        manifest = {
            "schema_version": 1, "product": "ohmyzsh-gx", "platform": platform,
            "architecture": "x86_64" if platform == "windows-x64" else "amd64",
            "version": source["version"], "source": source,
            "herdr": {k: lock["herdr"][k] for k in ("repository", "revision", "version", "rust", "zig", "targets")},
            "herdr_build": dependency["herdr"],
            "zsh_build": dependency["zsh"], "zsh_overlay": dependency["zsh_overlay"],
            "lock_digest": lock["lock_digest"], "publishable": source["publishable"],
            "compliance_complete": True, "dependencies": dependency["artifacts"],
            "payload": payload_manifest(payload), "redistribution": deps.tree_manifest(result_root / "redistribution"),
            "build_inputs": deps.tree_manifest(result_root / "build-inputs"),
            "validation": {"lifecycle": "pending", "pty": "pending"},
        }
        deps.write_json(result_root / "package-manifest.json", manifest)
        result_root.rename(output)
    return manifest


def payload_manifest(root: Path) -> list[dict]:
    result = []
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        deps.relative_path(name)
        if path.is_symlink():
            if name not in {"usr/bin/gx-zsh", "usr/bin/herdr"}:
                raise PackageError(f"unexpected payload symlink: {name}")
            link = os.readlink(path)
            expected = "../lib/ohmyzsh-gx/bin/" + path.name
            if link != expected or not path.resolve().is_relative_to(root.resolve()):
                raise PackageError(f"unsafe payload symlink: {name}")
            result.append({"path": name, "symlink": link})
        elif path.is_file():
            result.append({"path": name, "sha256": deps.sha256_file(path), "size": path.stat().st_size,
                           "executable": bool(path.stat().st_mode & 0o111)})
        elif not path.is_dir():
            raise PackageError(f"special payload file: {name}")
    return result


def verify_stage(path: Path) -> dict:
    manifest = deps.read_json(path / "package-manifest.json")
    if manifest.get("schema_version") != 1 or manifest.get("platform") not in deps.PLATFORMS:
        raise PackageError("invalid stage manifest")
    if manifest["payload"] != payload_manifest(path / "payload"):
        raise PackageError("staged payload changed after manifest generation")
    deps.verify_tree(path / "redistribution", manifest["redistribution"])
    deps.verify_tree(path / "build-inputs", manifest["build_inputs"])
    if not manifest.get("compliance_complete"):
        raise PackageError("stage has incomplete redistribution inputs")
    if (manifest["source"].get("development") or manifest["source"].get("dirty")) and manifest.get("publishable"):
        raise PackageError("development stage cannot be publishable")
    lock = deps.load_lock(path / "redistribution/ohmyzsh-gx/scripts/packaging/dependencies.json")
    if lock["lock_digest"] != manifest["lock_digest"] or deps.compliance_errors(lock, manifest["platform"]):
        raise PackageError("stage source lock is not redistribution-complete or differs from its manifest")
    if manifest["herdr"]["revision"] != lock["herdr"]["revision"]:
        raise PackageError("stage herdr revision does not match its source lock")
    if not manifest.get("zsh_build"):
        raise PackageError("stage lacks mandatory patched Zsh build provenance")
    import gx_build_zsh
    payload = path / "payload"
    if manifest["platform"] == "ubuntu-amd64":
        payload /= "usr/lib/ohmyzsh-gx"
    gx_build_zsh.verify_receipt(lock["zsh_data"], manifest["platform"], path, receipt=manifest["zsh_build"], subset=True,
                                materials_root=path / "redistribution/dependencies/zsh", payload_root=payload)
    return manifest


def source_archive(source: Path, destination: Path, epoch: int) -> None:
    with tarfile.open(destination, "w:xz", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            info = archive.gettarinfo(str(path), arcname=path.relative_to(source).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = epoch
            info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            with path.open("rb") as stream:
                archive.addfile(info, stream)


def build(stage_dir: Path, output: Path, *, iscc: str = "ISCC.exe", dpkg_deb: str = "dpkg-deb") -> dict:
    manifest = verify_stage(stage_dir)
    if output.exists():
        raise PackageError(f"output exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    platform = manifest["platform"]
    version = manifest["version"] + ("-dev" if manifest["source"]["development"] else "")
    stem = f"ohmyzsh-gx_{version}_{manifest['architecture']}"
    with tempfile.TemporaryDirectory(prefix=".gx-native-", dir=output.parent) as temporary:
        work = Path(temporary)
        artifact = work / (stem + (".exe" if platform == "windows-x64" else ".deb"))
        environment = os.environ.copy()
        environment["SOURCE_DATE_EPOCH"] = str(manifest["source"]["source_date_epoch"])
        if platform == "windows-x64":
            if os.name != "nt":
                raise PackageError("Inno Setup packaging must run on a Windows builder")
            subprocess.run([iscc, "/Qp", "/DGxVersion=" + manifest["version"], "/DGxPayload=" + str((stage_dir / "payload").resolve()), "/DGxOutput=" + str(work.resolve()), "/DGxFilename=" + stem, str((stage_dir / "build-inputs/windows.iss").resolve())], env=environment, check=True)
        else:
            if os.name == "nt":
                raise PackageError("run DEB packaging inside WSL/Linux, not Windows Python (ownership and symlink semantics)")
            subprocess.run([dpkg_deb, "--root-owner-group", "--build", str((stage_dir / "payload").resolve()), str(artifact)], env=environment, check=True)
            fields = subprocess.run([dpkg_deb, "--field", str(artifact), "Package", "Architecture", "Version"], check=True, capture_output=True, text=True).stdout
            if "ohmyzsh-gx" not in fields or "amd64" not in fields:
                raise PackageError("native DEB metadata does not match the requested package")
        if not artifact.is_file() or not artifact.stat().st_size:
            raise PackageError("native packager did not produce an artifact")
        sources = work / (stem + "-sources.tar.xz")
        source_archive(stage_dir / "redistribution", sources, manifest["source"]["source_date_epoch"])
        manifest["artifacts"] = [
            {"filename": path.name, "sha256": deps.sha256_file(path), "size": path.stat().st_size,
             "role": "installer" if path == artifact else "corresponding-sources"}
            for path in (artifact, sources)
        ]
        manifest_path = work / (stem + ".manifest.json")
        manifest["validation"]["native_package_built"] = True
        deps.write_json(manifest_path, manifest)
        checksum = work / (stem + ".sha256")
        checksum.write_text("".join(f"{deps.sha256_file(path)}  {path.name}\n" for path in (artifact, sources, manifest_path)), encoding="ascii", newline="\n")
        if verify_stage(stage_dir)["payload"] != manifest["payload"]:
            raise PackageError("stage changed during native packaging")
        work.rename(output)
    return {"manifest": str(output / manifest_path.name), "checksums": str(output / checksum.name), "artifacts": manifest["artifacts"], "publishable": manifest["publishable"]}


def verify_release(manifest_path: Path, require_release: bool = False) -> dict:
    manifest = deps.read_json(manifest_path)
    if manifest.get("schema_version") != 1 or manifest.get("product") != "ohmyzsh-gx":
        raise PackageError("unknown release manifest")
    if require_release and (not manifest.get("publishable") or manifest["source"].get("development") or manifest["source"].get("dirty")):
        raise PackageError("development/dirty packages cannot be released")
    roles = set()
    for artifact in manifest["artifacts"]:
        filename = artifact["filename"]
        if deps.relative_path(filename).name != filename:
            raise PackageError("release artifact path must be a basename")
        path = manifest_path.parent / filename
        if not path.is_file() or deps.sha256_file(path) != artifact["sha256"] or path.stat().st_size != artifact["size"]:
            raise PackageError(f"release artifact hash/size mismatch: {filename}")
        roles.add(artifact["role"])
    if roles != {"installer", "corresponding-sources"} or not manifest.get("compliance_complete"):
        raise PackageError("release must include installer and complete corresponding sources")
    if require_release:
        validation = manifest.get("validation", {})
        if validation.get("native_package_built") is not True or any(validation.get(field) != "passed" for field in ("lifecycle", "pty")):
            raise PackageError("release requires recorded native-package lifecycle and real PTY acceptance")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build native GX packages from an explicit Git snapshot and an offline locked dependency bundle.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "stage"):
        command = commands.add_parser(name)
        command.add_argument("--repo", type=Path, default=ROOT)
        command.add_argument("--ref", default="HEAD")
        command.add_argument("--allow-dirty", action="store_true", help="local development only; output can never be released")
        command.add_argument("--version")
        if name == "stage":
            command.add_argument("--platform", choices=deps.PLATFORMS, required=True)
            command.add_argument("--dependencies", type=Path, required=True)
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--rustc", default="rustc")
    command = commands.add_parser("build")
    command.add_argument("--stage", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--iscc", default="ISCC.exe")
    command.add_argument("--dpkg-deb", default="dpkg-deb")
    command = commands.add_parser("verify")
    command.add_argument("--manifest", type=Path, required=True)
    command.add_argument("--require-release", action="store_true")
    command = commands.add_parser("verify-stage")
    command.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = clean_source(args.repo, args.ref, args.allow_dirty)
            if args.version and args.version != result["version"]:
                raise PackageError("requested version differs from CHANGELOG.md")
        elif args.command == "stage":
            result = stage(args.repo, args.ref, args.platform, args.dependencies, args.output, allow_dirty=args.allow_dirty, version=args.version, rustc=args.rustc)
            result = {"stage": str(args.output), "source": result["source"], "platform": result["platform"], "publishable": result["publishable"]}
        elif args.command == "build":
            result = build(args.stage, args.output, iscc=args.iscc, dpkg_deb=args.dpkg_deb)
        elif args.command == "verify":
            result = verify_release(args.manifest, args.require_release)
            result = {"verified": True, "publishable": result["publishable"], "validation": result["validation"]}
        else:
            result = verify_stage(args.stage)
            result = {"verified": True, "platform": result["platform"]}
        print(json.dumps(result, indent=2))
        return 0
    except (PackageError, deps.DependencyError, OSError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"gx-package: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
