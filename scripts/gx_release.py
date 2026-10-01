#!/usr/bin/env python3
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
import tempfile
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "gx0404/ohmyzsh"
INTEGRATION_REPOSITORY = "gx0404/gx_shell"
TARGETS = {"windows-x64": "x86_64-pc-windows-msvc", "ubuntu-amd64": "x86_64-unknown-linux-musl"}
ARCHITECTURES = {"windows-x64": "x86_64", "ubuntu-amd64": "amd64"}
ENVIRONMENTS = {"windows-x64": ("windows-clean",), "ubuntu-amd64": ("ubuntu-20.04", "ubuntu-24.04")}
COMMON_CHECKS = {
    "install", "reinstall", "upgrade", "uninstall", "user-data-preserved", "command-resolution",
    "herdr-tui", "zsh-pane", "ctrl-c", "resize", "detach-attach", "cwd", "agent-detection",
    "completion", "history", "p10k", "gitstatus", "zoxide", "unicode-input", "unicode-home",
    "unicode-config-cache", "space-paths", "managed-update-blocked",
}
WINDOWS_CHECKS = {"path-ownership", "path-conflict", "locked-file-rollback", "offline-start", "existing-installations-preserved", "long-paths"}
LINUX_CHECKS = {"dpkg-no-user-home", "purge-preserves-user-data"}


class ReleaseError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseError(message)


def is_hash(value: object, length: int = 64) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return stream_digest(stream)


def stream_digest(stream) -> str:
    result = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        result.update(block)
    return result.hexdigest()


def canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    require(isinstance(value, dict), f"JSON object required: {path.name}")
    return value


def relative_name(value: object, *, basename: bool = False) -> str:
    require(isinstance(value, str) and bool(value), "nonempty path required")
    require(not any(ord(c) < 32 for c in value) and "\\" not in value and ":" not in value, "unsafe artifact path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in {"", ".", ".."} for p in value.split("/")), "unsafe artifact path")
    require(not basename or path.name == value, "artifact filename must be a basename")
    return value


def regular_file(path: Path) -> None:
    require(path.is_file() and not path.is_symlink() and path.stat().st_size > 0, f"missing, empty or symlinked file: {path}")


def check_fields(value: dict, expected: dict, label: str) -> None:
    require(isinstance(value, dict), f"{label}: object required")
    for key, expected_value in expected.items():
        require(type(value.get(key)) is type(expected_value) and value[key] == expected_value, f"{label}: {key} mismatch")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def changelog_version(text: str) -> str:
    values = re.findall(r"^##\s+(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\s*\((?:TBD|\d{8}|\d{4}-\d{2}-\d{2})\)\s*$", text, re.M)
    require(bool(values), "CHANGELOG.md has no fork SemVer")
    return ".".join(map(str, max(tuple(map(int, value)) for value in values)))


def dependencies_module():
    # gx_release 常以 `python -I` 运行（sys.path 不含脚本目录）；独立仓 herdr 的
    # 锁解析与生产者共用 gx_dependencies 的同一实现，保证 lock_digest 一致。
    scripts = str(Path(__file__).resolve().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import gx_dependencies
    return gx_dependencies


def load_lock(repo: Path) -> dict:
    path = repo / "scripts/packaging/dependencies.json"
    lock = read_json(path)
    check_fields(lock, {"schema_version": 1}, "dependency lock")
    herdr = lock.get("herdr")
    build = {"rust": "1.96.1", "zig": "0.16.0", "targets": TARGETS,
             "build_argv": ["cargo", "build", "--release", "--locked", "--target", "{target}"]}
    check_fields(herdr, {
        "repository": "https://github.com/gx0404/herdr", "branch_provenance": "feature/gx_herdr", **build,
    }, "herdr lock")
    require(is_hash(herdr.get("revision"), 40), "herdr revision must be a full commit SHA")
    source = herdr.get("source")
    require(isinstance(source, dict)
            and source.get("commit") == herdr["revision"]
            and source.get("prefix") == f"herdr-{herdr['revision']}/"
            and is_hash(source.get("sha256"))
            and type(source.get("size")) is int and source["size"] > 0,
            "herdr source must be a pinned independent checkout archive")
    require((source.get("git_repository") == herdr["repository"] and "url" not in source)
            or ("git_repository" not in source
                and source.get("url") == f"{herdr['repository']}/archive/{herdr['revision']}.zip"),
            "herdr archive URL must identify the locked independent commit")
    dependencies_module().artifact_shape(source)
    msys = lock["msys2"]
    data = read_json(path.parent / relative_name(msys["file"], basename=True))
    require(canonical_digest(data) == msys["canonical_sha256"], "MSYS2 lock checksum mismatch")
    lock["msys2_data"] = data
    redistribution = lock.get("redistribution")
    if redistribution:
        content = read_json(path.parent / relative_name(redistribution["file"], basename=True))
        check_fields(content, {"schema_version": 1}, "redistribution lock")
        require(canonical_digest(content) == redistribution["canonical_sha256"], "redistribution lock checksum mismatch")
        lock["components"] = content["components"]
        lock["vendored_files"] = content.get("vendored_files", [])
        components = content["msys2_components"]
        packaged = [(p["name"], p["version"]) for component in components for p in component["runtime_packages"]]
        expected = [(p["name"], p["version"]) for p in data["packages"]]
        require(sorted(packaged) == sorted(expected) and len(packaged) == len(set(packaged)),
                "redistribution inventory must cover each locked MSYS2 package exactly once")
        data["components"] = components
    require(isinstance(lock.get("components"), list) and bool(lock["components"]), "dependency components missing")
    zsh = lock.get("zsh_runtime")
    require(isinstance(zsh, dict) and bool(zsh), "release lock requires a known patched Zsh runtime")
    if zsh:
        pinned = read_json(path.parent / relative_name(zsh["file"], basename=True))
        check_fields(pinned, {"schema_version": 1, "version": "5.9.2+gx-metafied-paths"}, "Zsh runtime lock")
        require(canonical_digest(pinned) == zsh["canonical_sha256"], "Zsh runtime source lock checksum mismatch")
        lock["zsh_data"] = pinned
    lock["lock_digest"] = canonical_digest({k: v for k, v in lock.items() if k != "lock_digest"})
    return lock


def trusted_actions(sha: str, environment=None) -> None:
    env = os.environ if environment is None else environment
    require(env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and env.get("GITHUB_REPOSITORY") == REPOSITORY, "publish is restricted to the manual gx0404/ohmyzsh Actions workflow")
    branch = env.get("GX_DEFAULT_BRANCH", "")
    ref = "refs/heads/" + branch
    require(bool(branch) and env.get("GITHUB_REF") == ref, "publish workflow must run from the repository default branch")
    require(env.get("GITHUB_WORKFLOW_REF") == REPOSITORY + "/.github/workflows/gx-release.yml@" + ref,
            "unexpected publishing workflow/ref")
    require(is_hash(sha, 40) and sha == env.get("GITHUB_SHA") == env.get("GITHUB_WORKFLOW_SHA"),
            "publish source must equal the trusted default-branch workflow SHA; arbitrary refs are build-only")


def prepare(repo: Path, ref: str, version: str | None, publish: bool = False) -> dict:
    require(bool(ref) and not ref.startswith("-") and not any(ord(c) < 32 for c in ref), "invalid Git ref")
    sha = git(repo, "rev-parse", "--verify", ref + "^{commit}")
    require(is_hash(sha, 40) and sha == git(repo, "rev-parse", "HEAD"), "prepare requires the selected commit checked out at HEAD")
    require(not git(repo, "status", "--porcelain", "--untracked-files=all", "--", "."), "release preparation requires a clean source checkout")
    actual = changelog_version(git(repo, "show", sha + ":./CHANGELOG.md"))
    require(not version or version == actual, "version differs from CHANGELOG.md")
    lock = load_lock(repo)
    if publish:
        trusted_actions(sha)
    return {"sha": sha, "version": actual, "tag": "gx-v" + actual, "herdr_sha": lock["herdr"]["revision"],
            "rust": lock["herdr"]["rust"], "zig": lock["herdr"]["zig"], "lock_digest": lock["lock_digest"]}


def file_records(records: object) -> dict:
    require(isinstance(records, list) and bool(records), "nonempty file inventory required")
    result = {}
    folded = set()
    for item in records:
        require(isinstance(item, dict), "file record must be an object")
        name = relative_name(item.get("path"))
        require(name.casefold() not in folded and is_hash(item.get("sha256"))
                and type(item.get("size")) is int and item["size"] >= 0, f"invalid/duplicate file inventory: {name}")
        result[name] = item
        folded.add(name.casefold())
    return result


def source_file_contains_license(name: str, content: bytes) -> bool:
    if PurePosixPath(name).suffix.casefold() not in {".rs", ".py", ".c", ".h", ".cc", ".cpp", ".go", ".js", ".ts", ".zig"}:
        return True
    text = b" ".join(content.lower().split())
    grant = b"permission is hereby granted" in text or b"redistribution and use in source and binary forms" in text
    return grant and b"this software" in text and b"as is" in text


def verify_license_text(content: bytes, name: str) -> None:
    require(0 < len(content) <= 64 * 1024 * 1024, f"invalid license text size: {name}")
    try:
        json.loads(content)
        is_json = True
    except (ValueError, UnicodeDecodeError):
        is_json = False
    require(b"\0" not in content and not is_json, f"license must contain text, not a binary/JSON index: {name}")
    require(source_file_contains_license(name, content), f"source file name is not license evidence without a complete grant: {name}")


def verify_archive(path: Path, records: list, *, text_paths: set[str] | None = None) -> None:
    expected = file_records(records)
    found = set()
    with tarfile.open(path, "r:xz") as archive:
        for member in archive:
            name = relative_name(member.name.rstrip("/"))
            if member.isdir():
                continue
            require(member.isfile() and name not in found and name in expected, f"unexpected archive member: {name}")
            require(member.size == expected[name]["size"], f"archive size mismatch: {name}")
            with archive.extractfile(member) as stream:
                if text_paths and name in text_paths:
                    require(0 < member.size <= 64 * 1024 * 1024, f"invalid license text size: {name}")
                    content = stream.read()
                    verify_license_text(content, name)
                    actual_digest = hashlib.sha256(content).hexdigest()
                else:
                    actual_digest = stream_digest(stream)
                require(actual_digest == expected[name]["sha256"], f"archive checksum mismatch: {name}")
            found.add(name)
    require(found == set(expected), "archive is missing declared source/license/evidence files")


def check_artifact(folder: Path, record: dict) -> Path:
    path = folder / relative_name(record["filename"], basename=True)
    regular_file(path)
    require(type(record.get("size")) is int and record["size"] == path.stat().st_size
            and is_hash(record.get("sha256")) and record["sha256"] == digest(path), f"artifact hash/size mismatch: {path.name}")
    return path


def dependency_inventory(lock: dict, platform: str) -> list[dict]:
    entries = [lock["herdr"]["source"]]
    if lock.get("zsh_data"):
        pinned = lock["zsh_data"]
        entries.extend([pinned["source"], pinned["gx_patch"], pinned["platforms"][platform]["modules"], *pinned.get("original_recipes", [])])
        if platform == "ubuntu-amd64":
            entries.extend(pinned["linux_toolchain"]["kit"])
        for patch in pinned["platforms"][platform]["patches"]:
            entries.append(patch["original"])
            if patch.get("refreshed"):
                entries.append(patch["refreshed"])
    entries.extend(a for a in lock["assets"] if platform in a["platforms"])
    components = [c for c in lock["components"] if platform in c["platforms"]]
    if platform == "windows-x64":
        msys = lock["msys2_data"]
        components += msys["components"]
        entries.append(msys["base"])
        entries.extend(p for p in msys["packages"] if p["origin"] == "signed-package")
    for component in components:
        for field in ("licenses", "sources", "build_instructions"):
            entries.extend(component.get(field, []))
    result = {}
    for item in entries:
        name = relative_name(item["filename"], basename=True)
        require(is_hash(item.get("sha256")), "dependency must have a locked checksum")
        if "git_repository" in item:
            require(item["git_repository"] == "https://github.com/gx0404/herdr"
                    and is_hash(item.get("commit"), 40)
                    and item.get("prefix") == f"herdr-{item['commit']}/"
                    and "url" not in item,
                    "Git dependency must be a pinned independent herdr checkout without a URL")
        elif "monorepo_path" in item:
            raise ReleaseError("monorepo dependencies are no longer supported")
        elif "repository_path" in item:
            location = relative_name(item["repository_path"])
            require(location.startswith(("notices/", "patches/zsh/")) and "url" not in item,
                    "repository dependency must be a locked packaging notice or Zsh patch without a URL")
        else:
            url = urllib.parse.urlsplit(item["url"])
            require(url.scheme == "https" and bool(url.hostname) and not url.username and not url.password and not url.fragment,
                    "dependency requires a public HTTPS source")
        entry = {key: item[key] for key in ("filename", "sha256", "size", "url", "repository_path", "git_repository", "commit", "prefix") if key in item}
        require(name not in result or result[name] == entry, "conflicting dependency inventory")
        result[name] = entry
    return sorted(result.values(), key=lambda item: item["filename"])


def verify_herdr_metadata(build: dict, platform: str, lock: dict) -> None:
    check_fields(build, {
        "schema_version": 1, "platform": platform, "revision": lock["herdr"]["revision"],
        "version": lock["herdr"]["version"], "source_sha256": lock["herdr"]["source"]["sha256"],
        "rust": "1.96.1", "zig": "0.16.0", "target": TARGETS[platform], "locked": True,
        "release": True, "cargo_vendor_complete": True,
        "libghostty_vt_optimize": "ReleaseFast", "libghostty_vt_simd": True,
    }, "herdr_build (packager must propagate the verified dependency build receipt)")
    require("rustflags" in build, "herdr_build must record the actual rustflags, including null defaults")
    if platform == "windows-x64":
        require(build["rustflags"] == "-C target-feature=+crt-static", "Windows requires explicit CRTstatic rustflags")
    else:
        require(build["target"] == "x86_64-unknown-linux-musl" and build.get("effective_crt_static") is True,
                "Linux requires the exact musl target and effective_crt_static=true")
        require(build["rustflags"] is None or build["rustflags"] == "-C target-feature=+crt-static",
                "Linux rustflags must record either musl defaults or explicit CRTstatic")


def verify_linux_static(path: Path) -> None:
    import struct
    data = path.read_bytes()
    require(len(data) >= 64 and data[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", data, 18)[0] == 62, "herdr must be an amd64 ELF binary")
    offset = struct.unpack_from("<Q", data, 32)[0]
    size, count = struct.unpack_from("<HH", data, 54)
    require(size >= 56 and count > 0 and offset + size * count <= len(data), "invalid ELF program headers")
    for index in range(count):
        position = offset + index * size
        kind = struct.unpack_from("<I", data, position)[0]
        require(kind != 3, "herdr ELF has PT_INTERP; dynamic Linux binaries are forbidden")
        if kind == 2:
            start = struct.unpack_from("<Q", data, position + 8)[0]
            length = struct.unpack_from("<Q", data, position + 32)[0]
            require(length % 16 == 0 and start + length <= len(data), "invalid ELF dynamic table")
            require(not any(struct.unpack_from("<q", data, p)[0] == 1 for p in range(start, start + length, 16)),
                    "herdr ELF has DT_NEEDED; dynamic Linux binaries are forbidden")


def verify_herdr_directory(folder: Path, platform: str, lock: dict) -> dict:
    build = read_json(folder / "herdr-build.json")
    verify_herdr_metadata(build, platform, lock)
    files = file_records(build["files"])
    observed = set()
    for path in (folder / "payload").rglob("*"):
        require(not path.is_symlink(), "symlinked herdr payload")
        if path.is_file():
            observed.add(path.relative_to(folder / "payload").as_posix())
    require(observed == set(files), "herdr payload inventory differs from receipt")
    for name, item in files.items():
        path = folder / "payload" / name
        require(path.stat().st_size == item["size"] and digest(path) == item["sha256"], "herdr payload checksum mismatch")
    if platform == "ubuntu-amd64":
        require(set(files) == {"herdr"}, "unexpected Linux herdr payload")
        verify_linux_static(folder / "payload/herdr")
    else:
        require(build.get("conpty_verified") is True and set(files) == set(lock["herdr"]["conpty"]["files"]), "unverified ConPTY payload")
        for name, checksum in lock["herdr"]["conpty"]["files"].items():
            require(checksum is None or files[name]["sha256"] == checksum, "ConPTY checksum mismatch")
    for field in ("source_artifacts", "license_artifacts"):
        for name, item in file_records(build[field]).items():
            path = folder / name
            require(path.resolve().is_relative_to(folder.resolve()) and path.is_file() and not path.is_symlink(), "unsafe herdr redistribution path")
            require(path.stat().st_size == item["size"] and digest(path) == item["sha256"], f"herdr redistribution checksum mismatch: {name}")
            if field == "license_artifacts":
                verify_license_text(path.read_bytes(), name)
    verify_herdr_license_inventory(build)
    return {"platform": platform, "revision": build["revision"], "rustflags": build["rustflags"],
            "effective_crt_static": build.get("effective_crt_static", platform == "windows-x64"),
            "binary_sha256": files["herdr.exe" if platform == "windows-x64" else "herdr"]["sha256"],
            "license_text_files": len(build["license_artifacts"]), "source_artifacts": len(build["source_artifacts"])}


def verify_compliance(info: dict, lock: dict) -> None:
    platform = info["platform"]
    components = [c for c in lock["components"] if platform in c["platforms"]]
    if platform == "windows-x64":
        components += lock["msys2_data"]["components"]
    require(bool(components), "locked redistribution components missing")
    require(not [u for u in lock.get("unresolved", []) if platform in u["platforms"]], "unresolved dependency lock inputs")
    records = file_records(info["redistribution"])
    require("ohmyzsh-gx/LICENSE.txt" in records, "Oh My Zsh license missing from sources")
    for item in lock.get("vendored_files", []):
        name = "ohmyzsh-gx/" + relative_name(item["path"])
        require(is_hash(item.get("sha256")) and records.get(name, {}).get("sha256") == item["sha256"], f"vendored input differs from lock: {name}")
    for component in components:
        policy = component.get("source_policy", {"kind": "required"})
        optional = policy.get("kind") == "not-required"
        if optional:
            permitted = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "OFL-1.1", "CC0-1.0", "Zsh"}
            expressions = component.get("license_expression", "").split(" AND ")
            require(bool(policy.get("basis")) and bool(expressions) and set(expressions) <= permitted,
                    f"{component['id']}: source exemption requires explicit permissive-license basis")
        else:
            require(policy.get("kind") == "required", "unknown source obligation policy")
        for field in ("licenses", "sources", "build_instructions"):
            require(isinstance(component.get(field), list) and (bool(component[field]) or (field == "sources" and optional)),
                    f"{component['id']}: missing locked {field}")
            for item in component[field]:
                name = f"dependencies/{relative_name(component['id'], basename=True)}/{field}/{relative_name(item['filename'], basename=True)}"
                require(is_hash(item.get("sha256")) and records.get(name, {}).get("sha256") == item["sha256"], f"redistribution mismatch: {name}")
    dependencies = info.get("dependencies")
    require(isinstance(dependencies, list), "package dependency inventory missing")
    require(sorted(dependencies, key=lambda item: item["filename"]) == dependency_inventory(lock, platform),
            "package dependency inventory differs from the complete platform lock")
    build = info.get("herdr_build")
    verify_herdr_metadata(build, platform, lock)
    for field in ("source_artifacts", "license_artifacts"):
        require(bool(build.get(field)), f"herdr_build missing {field}")
        for item in build[field]:
            name = "dependencies/herdr/" + relative_name(item["path"])
            require(is_hash(item.get("sha256")) and records.get(name, {}).get("sha256") == item["sha256"], f"herdr redistribution missing: {name}")
    binary_files = file_records(build["files"])
    prefix = "lib/herdr/" if platform == "windows-x64" else "usr/lib/ohmyzsh-gx/lib/herdr/"
    payload = {r["path"]: r for r in info["payload"]}
    for name, item in binary_files.items():
        require(payload.get(prefix + name, {}).get("sha256") == item["sha256"], "herdr build receipt does not match packaged payload")
    if platform == "windows-x64":
        require(build.get("conpty_verified") is True and set(binary_files) == set(lock["herdr"]["conpty"]["files"]), "unverified or incomplete ConPTY layout")
        for name, checksum in lock["herdr"]["conpty"]["files"].items():
            require(checksum is None or binary_files[name]["sha256"] == checksum, f"ConPTY checksum mismatch: {name}")
    license_records = verify_herdr_license_inventory(build)
    license_prefix = "licenses/herdr/" if platform == "windows-x64" else "usr/share/doc/ohmyzsh-gx/licenses/herdr/"
    for name, item in license_records.items():
        installed = payload.get(license_prefix + name, {})
        require(installed.get("sha256") == item["sha256"] and installed.get("size") == item["size"],
                f"license text missing from binary package payload: {name}")


def verify_herdr_license_inventory(build: dict) -> dict:
    require(build.get("zig_dependencies_complete") is True, "Zig dependency sources/licenses were not completely audited")
    inventory = build.get("license_inventory")
    require(isinstance(inventory, list) and bool(inventory), "herdr license inventory missing")
    require({item.get("ecosystem") for item in inventory} == {"cargo", "cargo-path", "vendored", "zig", "zig-toolchain"},
            "license inventory must cover Cargo, path crates, vendored Ghostty, Zig packages and Zig runtime")
    license_records = file_records(build["license_artifacts"])
    declared = []
    identities = set()
    for item in inventory:
        name = relative_name(item["package"], basename=True)
        identity = (item["ecosystem"], name)
        require(identity not in identities and isinstance(item.get("source_identity"), dict) and bool(item["source_identity"]), "duplicate or untraceable license package")
        identities.add(identity)
        require(bool(item.get("licenses")), f"empty license package: {name}")
        declared.extend(item["licenses"])
    require(file_records(declared) == license_records, "license inventory differs from materialized license texts")
    for name, item in license_records.items():
        require(name.startswith("redistribution/licenses/") and not name.casefold().endswith(".json") and item["size"] > 0,
                "license artifacts must contain standalone license texts, not an inventory JSON")
    return license_records


def zsh_verifier():
    import importlib
    trusted = str(Path(__file__).resolve().parent)
    if trusted not in sys.path:
        sys.path.insert(0, trusted)
    module = importlib.import_module("gx_build_zsh")
    require(Path(module.__file__).resolve().parent == Path(trusted), "Zsh verifier must come from the trusted controller")
    return module


def verify_zsh_metadata(info: dict, lock: dict) -> dict:
    platform = info["platform"]
    pinned = lock.get("zsh_data")
    require(isinstance(pinned, dict), "release requires a known source-pinned patched Zsh runtime")
    build = info.get("zsh_build")
    check_fields(build, {
        "schema_version": 1, "version": pinned["version"], "platform": platform,
        "source_sha256": pinned["source"]["sha256"], "gx_patch_sha256": pinned["gx_patch"]["sha256"],
        "modules_sha256": pinned["platforms"][platform]["modules"]["sha256"], "static_modules": True,
        "fuzz_allowed": 0, "external_dynamic_modules_supported": False,
        "post_gx_source_sha256": pinned["platforms"][platform]["post_gx_source_sha256"],
        "source_lock_digest": canonical_digest(pinned),
    }, "patched Zsh build")
    require(is_hash(build.get("binary_sha256")), "Zsh binary digest missing")
    receipt_files = file_records(build["files"])
    payload = {}
    for item in info["payload"]:
        name = relative_name(item["path"])
        require(name not in payload, "duplicate package payload record")
        payload[name] = item
    prefix = "" if platform == "windows-x64" else "usr/lib/ohmyzsh-gx/"
    for name, record in receipt_files.items():
        actual = payload.get(prefix + name, {})
        require(actual.get("sha256") == record["sha256"] and actual.get("size") == record["size"], "Zsh receipt differs from package payload: " + name)
    changes = []
    if platform == "windows-x64":
        policy = pinned["platforms"][platform]
        for name in sorted(set(policy["replacement_paths"]) | set(policy["remove_original_paths"])):
            entry = {"path": name, "old_sha256": policy["original_runtime_files"][name],
                     "action": "removed" if name in policy["remove_original_paths"] else "replaced"}
            if entry["action"] == "removed":
                require(name not in payload, "unpatched dynamic MSYS Zsh leaked into release payload")
            else:
                entry["new_sha256"] = build["binary_sha256"]
                require(receipt_files.get(name, {}).get("sha256") == build["binary_sha256"], "nested Zsh binary does not match patched runtime")
            changes.append(entry)
    require(info.get("zsh_overlay") == changes, "Zsh overlay old/new SHA provenance differs from locked source")
    redistributed = file_records(info["redistribution"])
    for item in build["source_artifacts"] + build["license_artifacts"]:
        name = "dependencies/zsh/" + relative_name(item["path"])
        require(redistributed.get(name, {}).get("sha256") == item["sha256"] and redistributed.get(name, {}).get("size") == item["size"], "Zsh source/license differs from release archive: " + name)
    return build


def extract_verified_members(archive_path: Path, output: Path, expected: dict, *, subset: bool = False) -> None:
    found = set()
    with tarfile.open(archive_path, "r:xz") as archive:
        for member in archive:
            name = relative_name(member.name.rstrip("/"))
            if member.isdir():
                continue
            if name not in expected and subset:
                continue
            require(member.isfile() and name in expected and name not in found, "unexpected runtime proof member: " + name)
            record = expected[name]
            require(member.size == record["size"], "runtime proof member size mismatch: " + name)
            target = output / name
            require(target.resolve().is_relative_to(output.resolve()), "runtime proof path escape")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination)
            require(digest(target) == record["sha256"], "runtime proof member checksum mismatch: " + name)
            found.add(name)
    require(found == set(expected), "runtime proof/source archive omits declared Zsh files")


def verify_zsh_runtime(info: dict, lock: dict, runtime_archive: Path, source_archive: Path) -> None:
    build = verify_zsh_metadata(info, lock)
    regular_file(runtime_archive)
    runtime_files = {"payload/" + name: record for name, record in file_records(build["files"]).items()}
    materials = {"dependencies/zsh/" + item["path"]: item for item in build["source_artifacts"] + build["license_artifacts"]}
    with tempfile.TemporaryDirectory(prefix="gx-release-zsh-") as temporary:
        root = Path(temporary)
        extract_verified_members(runtime_archive, root, runtime_files)
        extract_verified_members(source_archive, root, materials, subset=True)
        zsh_verifier().verify_receipt(lock["zsh_data"], info["platform"], root, receipt=build,
                                      materials_root=root / "dependencies/zsh")


def create_runtime_proof(stage: Path, folder: Path, platform: str, version: str, sha: str, lock: dict) -> Path:
    stem = f"ohmyzsh-gx_{version}_{ARCHITECTURES[platform]}"
    metadata = folder / (stem + ".manifest.json")
    info = read_json(metadata)
    check_fields(info, {"platform": platform, "version": version, "lock_digest": lock["lock_digest"]}, "runtime proof package")
    check_fields(info["source"], {"revision": sha}, "runtime proof source")
    build = verify_zsh_metadata(info, lock)
    stage_info = read_json(stage / "package-manifest.json")
    require(stage_info["payload"] == info["payload"] and stage_info["zsh_build"] == build, "stage changed after native installer build")
    native_files = [check_artifact(folder, record) for record in info["artifacts"]]
    sums = folder / (stem + ".sha256")
    original = "".join(f"{digest(path)}  {path.name}\n" for path in native_files + [metadata])
    require(sums.read_text(encoding="ascii") == original, "native checksum sidecar mismatch before runtime proof")
    target = folder / (stem + ".runtime.tar.xz")
    require(not target.exists(), "runtime proof already exists")
    prefix = stage / "payload" if platform == "windows-x64" else stage / "payload/usr/lib/ohmyzsh-gx"
    zsh_verifier().verify_receipt(lock["zsh_data"], platform, stage, receipt=build, subset=True,
                                  materials_root=stage / "redistribution/dependencies/zsh", payload_root=prefix)
    with tempfile.TemporaryDirectory(prefix=".gx-proof-", dir=folder) as temporary:
        archive_path = Path(temporary) / target.name
        with tarfile.open(archive_path, "w:xz", format=tarfile.PAX_FORMAT) as archive:
            for item in build["files"]:
                path = prefix / relative_name(item["path"])
                require(path.is_file() and not path.is_symlink() and digest(path) == item["sha256"], "staged runtime changed")
                member = archive.gettarinfo(str(path), "payload/" + item["path"])
                member.uid = member.gid = member.mtime = 0
                member.uname = member.gname = "root"
                with path.open("rb") as source:
                    archive.addfile(member, source)
        verify_zsh_runtime(info, lock, archive_path, folder / (stem + "-sources.tar.xz"))
        archive_path.rename(target)
    sums.write_text(original + f"{digest(target)}  {target.name}\n", encoding="ascii", newline="\n")
    return target


def verify_package(folder: Path, platform: str, version: str, sha: str, lock: dict) -> tuple[list[Path], dict]:
    stem = f"ohmyzsh-gx_{version}_{ARCHITECTURES[platform]}"
    metadata = folder / (stem + ".manifest.json")
    sums = folder / (stem + ".sha256")
    regular_file(metadata)
    regular_file(sums)
    info = read_json(metadata)
    check_fields(info, {"schema_version": 1, "product": "ohmyzsh-gx", "platform": platform,
                       "architecture": ARCHITECTURES[platform], "version": version, "publishable": True,
                       "compliance_complete": True, "lock_digest": lock["lock_digest"]}, metadata.name)
    check_fields(info.get("source"), {"repository": REPOSITORY, "revision": sha, "version": version,
                                     "dirty": False, "development": False, "publishable": True}, "package source")
    check_fields(info.get("herdr"), {k: lock["herdr"][k] for k in ("repository", "revision", "version", "rust", "zig", "targets")}, "package herdr")
    require(info.get("validation", {}).get("native_package_built") is True, "native installer was not built")
    names = {"installer": stem + (".exe" if platform == "windows-x64" else ".deb"), "corresponding-sources": stem + "-sources.tar.xz"}
    records = info.get("artifacts", [])
    require(len(records) == 2 and {a["role"] for a in records} == set(names), "installer and corresponding-sources required exactly once")
    for record in records:
        require(record["filename"] == names[record["role"]], "unexpected package asset name")
    files = [check_artifact(folder, record) for record in records]
    runtime_files = [folder / (stem + ".runtime.tar.xz")] if lock.get("zsh_data") else []
    for path in runtime_files:
        regular_file(path)
    expected_sums = "".join(f"{digest(path)}  {path.name}\n" for path in files + [metadata] + runtime_files)
    require(sums.read_text(encoding="ascii") == expected_sums, "checksum sidecar mismatch")
    verify_compliance(info, lock)
    text_paths = {"dependencies/herdr/" + item["path"] for item in info["herdr_build"]["license_artifacts"]}
    verify_archive(folder / names["corresponding-sources"], info["redistribution"], text_paths=text_paths)
    if runtime_files:
        verify_zsh_runtime(info, lock, runtime_files[0], folder / names["corresponding-sources"])
    return files + [metadata, sums] + runtime_files, info


def verify_validation(folder: Path, platform: str, environment: str, version: str, sha: str, installer: dict) -> list[Path]:
    stem = f"ohmyzsh-gx_{version}_{environment}"
    receipt_path = folder / (stem + ".validation.json")
    regular_file(receipt_path)
    receipt = read_json(receipt_path)
    check_fields(receipt, {"schema_version": 1, "platform": platform, "environment": environment,
                          "source_revision": sha, "installer_sha256": installer["sha256"],
                          "disposable_environment": True, "evidence_reviewed": True}, "lifecycle receipt")
    checks = receipt.get("checks", {})
    required = COMMON_CHECKS | (WINDOWS_CHECKS if platform == "windows-x64" else LINUX_CHECKS)
    require(isinstance(checks, dict) and set(checks) == required, "lifecycle checks missing or unknown; no skipped/waived checks accepted")
    evidence = file_records(receipt["evidence_files"])
    for name, result in checks.items():
        require(isinstance(result, dict) and result.get("status") == "passed" and bool(result.get("evidence")), f"lifecycle check not passed: {name}")
        for item in result["evidence"]:
            require(item in evidence and evidence[item]["size"] > 0, f"missing check evidence: {name}")
    archive_record = receipt["evidence_archive"]
    require(archive_record["filename"] == stem + ".evidence.tar.xz", "unexpected evidence archive name")
    archive = check_artifact(folder, archive_record)
    verify_archive(archive, receipt["evidence_files"])
    return [receipt_path, archive]


def verify_artifacts(folder: Path, version: str, sha: str, lock: dict) -> list[Path]:
    require(is_hash(sha, 40), "full source SHA required")
    require(re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version) is not None, "X.Y.Z version required")
    files = []
    for platform in TARGETS:
        package_files, info = verify_package(folder, platform, version, sha, lock)
        files.extend(package_files)
        installer = next(r for r in info["artifacts"] if r["role"] == "installer")
        for environment in ENVIRONMENTS[platform]:
            files.extend(verify_validation(folder, platform, environment, version, sha, installer))
    require({p.name for p in folder.iterdir()} == {p.name for p in files}, "unexpected files in release artifact directory")
    return files


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ReleaseError("refusing authenticated GitHub API redirect")


class GitHub:
    def __init__(self):
        self.token = os.environ["GITHUB_TOKEN"]
        require(bool(self.token), "GITHUB_TOKEN missing")
        self.base = "https://api.github.com/repos/" + REPOSITORY
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method: str, path: str, data=None, binary: Path | None = None):
        if path.startswith("https://"):
            require(re.fullmatch(r"https://uploads\.github\.com/repos/" + REPOSITORY + r"/releases/[1-9]\d*/assets\?name=[A-Za-z0-9_.%+-]+", path) is not None, "untrusted upload URL")
            url = path
        else:
            require(path.startswith("/") and not path.startswith("//") and ".." not in path, "invalid API path")
            url = self.base + path
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ohmyzsh-gx-release/1",
                   "Content-Type": "application/octet-stream" if binary else "application/json"}
        for attempt in range(3):
            stream = None
            try:
                if binary:
                    stream = binary.open("rb")
                    body = iter(lambda: stream.read(1024 * 1024), b"")
                    headers["Content-Length"] = str(binary.stat().st_size)
                else:
                    body = json.dumps(data).encode() if data is not None else None
                request = urllib.request.Request(url, data=body, headers=headers, method=method)
                with self.opener.open(request, timeout=180) as response:
                    raw = response.read()
                    return json.loads(raw, object_pairs_hook=unique_object) if raw else None
            except (urllib.error.URLError, TimeoutError) as error:
                transient = not isinstance(error, urllib.error.HTTPError) or error.code in (429, 500, 502, 503, 504)
                if method != "GET" or not transient or attempt == 2:
                    raise
                if isinstance(error, urllib.error.HTTPError):
                    error.close()
                time.sleep(2 ** attempt)
            finally:
                if stream:
                    stream.close()

    def optional(self, path: str):
        try:
            return self.request("GET", path)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                error.close()
                return None
            raise


def remote_commit(api: GitHub, tag: str) -> str | None:
    ref = api.optional("/git/ref/tags/" + urllib.parse.quote(tag, safe=""))
    if ref is None:
        return None
    obj = ref["object"]
    for _ in range(8):
        require(is_hash(obj.get("sha"), 40), "invalid remote Git object")
        if obj["type"] == "commit":
            return obj["sha"]
        require(obj["type"] == "tag", "tag does not resolve to a commit")
        obj = api.request("GET", "/git/tags/" + obj["sha"])["object"]
    raise ReleaseError("annotated tag chain too deep")


def remote_assets(api: GitHub, release_id: int) -> list:
    result = []
    for page in range(1, 101):
        batch = api.request("GET", f"/releases/{release_id}/assets?per_page=100&page={page}")
        require(isinstance(batch, list), "invalid remote asset list")
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise ReleaseError("remote asset pagination exceeds safety limit")


def verify_remote_assets(assets: list, files: list[Path], *, complete: bool) -> set[str]:
    expected = {path.name: path for path in files}
    names = [a["name"] for a in assets]
    require(len(names) == len(set(names)) and set(names) <= set(expected)
            and (not complete or set(names) == set(expected)), "unknown, duplicate or missing draft assets")
    for asset in assets:
        path = expected[asset["name"]]
        require(asset.get("state") == "uploaded" and type(asset.get("size")) is int
                and asset["size"] == path.stat().st_size and asset.get("digest") == "sha256:" + digest(path),
                f"remote asset size/digest mismatch: {path.name}")
    return set(names)


def release_marker(files: list[Path], sha: str) -> str:
    inventory = [{"name": p.name, "size": p.stat().st_size, "sha256": digest(p)} for p in sorted(files)]
    return f"<!-- ohmyzsh-gx source={sha} inventory={canonical_digest(inventory)} -->"


def publish(folder: Path, version: str, sha: str, lock: dict) -> str:
    trusted_actions(sha)
    files = verify_artifacts(folder, version, sha, lock)
    marker = release_marker(files, sha)
    tag = "gx-v" + version
    api = GitHub()
    commit = remote_commit(api, tag)
    require(commit is None or commit == sha, "existing tag points to another commit; tags are never moved")
    release = api.optional("/releases/tags/" + tag)
    if release is not None:
        require(release.get("draft") is True, "public releases are never overwritten")
        require(commit == sha and release.get("tag_name") == tag and release.get("body", "").splitlines()[:1] == [marker],
                "draft does not match this immutable SHA and complete asset inventory")
        require(type(release.get("id")) is int and release["id"] > 0, "invalid release id")
        verify_remote_assets(remote_assets(api, release["id"]), files, complete=False)
    if commit is None:
        api.request("POST", "/git/refs", {"ref": "refs/tags/" + tag, "sha": sha})
        require(remote_commit(api, tag) == sha, "created tag failed immutable SHA verification")
    if release is None:
        release = api.request("POST", "/releases", {
            "tag_name": tag, "target_commitish": sha, "name": "Oh My Zsh GX " + version,
            "draft": True, "prerelease": False,
            "body": marker + "\n\nWindows x64 and Ubuntu amd64 packages. Corresponding sources, licenses, SHA-256 checksums and lifecycle evidence are attached. Windows installer is unsigned.\n",
        })
    require(type(release.get("id")) is int and release["id"] > 0 and release.get("draft") is True, "invalid draft response")
    release_id = release["id"]
    uploaded = verify_remote_assets(remote_assets(api, release_id), files, complete=False)
    for path in files:
        if path.name not in uploaded:
            api.request("POST", f"https://uploads.github.com/repos/{REPOSITORY}/releases/{release_id}/assets?name="
                        + urllib.parse.quote(path.name, safe=""), binary=path)
    verify_remote_assets(remote_assets(api, release_id), files, complete=True)
    require(remote_commit(api, tag) == sha, "release tag changed; draft remains unpublished")
    current = api.request("GET", f"/releases/{release_id}")
    require(current.get("draft") is True and current.get("tag_name") == tag
            and current.get("body", "").splitlines()[:1] == [marker], "draft changed concurrently; refusing publication")
    result = api.request("PATCH", f"/releases/{release_id}", {"draft": False})
    require(result.get("draft") is False and result.get("tag_name") == tag, "publication response could not be verified")
    return result["html_url"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only by default. Publishing is restricted to the trusted manual Actions workflow.")
    parser.add_argument("action", choices=("prepare", "runtime-proof", "verify", "verify-package", "verify-herdr", "publish"), nargs="?", default="verify")
    parser.add_argument("--stage", type=Path, help="runtime-proof only: actual native-package stage to audit")
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--version")
    parser.add_argument("--sha")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "dist")
    parser.add_argument("--platform", choices=tuple(TARGETS))
    parser.add_argument("--herdr-build", type=Path, help="verify-herdr only: read-only provenance, payload and static binary checks")
    parser.add_argument("--publish", action="store_true", help="prepare only: enforce trusted source restrictions; never writes API")
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            record = prepare(args.repo, args.ref, args.version, args.publish)
            output = "".join(f"{key}={value}\n" for key, value in record.items())
            print(output, end="")
            if os.environ.get("GITHUB_OUTPUT"):
                with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                    stream.write(output)
            return 0
        require(not args.publish, "--publish is only valid with prepare")
        if args.action == "verify-herdr":
            require(args.platform in TARGETS and args.herdr_build is not None, "verify-herdr requires --platform and --herdr-build")
            print(json.dumps(verify_herdr_directory(args.herdr_build, args.platform, load_lock(args.repo)), indent=2))
            return 0
        require(is_hash(args.sha, 40), "--sha requires a complete source SHA")
        version = changelog_version(git(args.repo, "show", args.sha + ":./CHANGELOG.md"))
        require(not args.version or args.version == version, "version differs from selected CHANGELOG.md")
        lock = load_lock(args.repo)
        if args.action == "publish":
            prepare(args.repo, args.sha, version, True)
            print(publish(args.artifacts, version, args.sha, lock))
        elif args.action == "runtime-proof":
            require(args.platform in TARGETS and args.stage is not None, "runtime-proof requires --platform and --stage")
            print(create_runtime_proof(args.stage, args.artifacts, args.platform, version, args.sha, lock))
        elif args.action == "verify-package":
            require(args.platform in TARGETS, "verify-package requires --platform")
            files, _ = verify_package(args.artifacts, args.platform, version, args.sha, lock)
            print(f"Verified {len(files)} package files; lifecycle/PTY approval is NOT implied.")
        else:
            files = verify_artifacts(args.artifacts, version, args.sha, lock)
            print(f"Verified {len(files)} release files, both platforms and all lifecycle evidence.")
        return 0
    except (ValueError, OSError, KeyError, TypeError, IndexError, tarfile.TarError, subprocess.CalledProcessError) as error:
        print(f"gx-release: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
