#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile

import gx_dependencies as deps

DEFAULT_LOCK = deps.DEFAULT_LOCK.parent / "zsh-runtime-lock.json"
WRAPPER = b'''#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
export FPATH="$root/share/zsh/functions:$root/share/zsh/site-functions"
unset MODULE_PATH
exec "$root/libexec/zsh/zsh" "$@"
'''
SOURCE_FILES = ("Src/init.c", "Src/subst.c", "Src/Modules/system.c", "Src/parse.c")


def binary_abi(path: Path, platform: str) -> dict:
    deps.check_binary(path, platform)
    data = path.read_bytes()
    if platform == "windows-x64":
        pe = struct.unpack_from("<I", data, 60)[0]
        count = struct.unpack_from("<H", data, pe + 6)[0]
        optional_size = struct.unpack_from("<H", data, pe + 20)[0]
        optional = pe + 24
        if optional_size < 128 or optional + optional_size + count * 40 > len(data):
            raise deps.DependencyError("truncated PE sections")
        if struct.unpack_from("<H", data, optional)[0] != 0x20B:
            raise deps.DependencyError("Zsh must be PE32+ x64")
        sections = []
        for index in range(count):
            start = optional + optional_size + index * 40
            virtual_size, address, size, offset = struct.unpack_from("<IIII", data, start + 8)
            sections.append((address, max(virtual_size, size), offset))

        def rva(value):
            for address, size, offset in sections:
                if address <= value < address + size:
                    result = offset + value - address
                    if result < len(data):
                        return result
            raise deps.DependencyError("PE import address outside file")

        def cstring(offset):
            end = data.find(b"\0", offset)
            if end < 0:
                raise deps.DependencyError("invalid PE import string")
            return data[offset:end].decode("ascii").lower()

        imports = []
        for directory, descriptor_size, name_offset in ((1, 20, 12), (13, 32, 4)):
            entry = optional + 112 + directory * 8
            if entry + 8 > optional + optional_size:
                continue
            address, size = struct.unpack_from("<II", data, entry)
            if not address:
                continue
            start = rva(address)
            end = min(start + size, len(data))
            for offset in range(start, end - descriptor_size + 1, descriptor_size):
                if not any(data[offset:offset + descriptor_size]):
                    break
                if directory == 13 and not struct.unpack_from("<I", data, offset)[0] & 1:
                    raise deps.DependencyError("unsupported VA-based delayed PE import")
                imports.append(cstring(rva(struct.unpack_from("<I", data, offset + name_offset)[0])))
        if not imports:
            raise deps.DependencyError("Zsh PE has no import table")
        return {"format": "PE32+", "machine": "x86_64", "imports": sorted(set(imports))}
    section_offset = struct.unpack_from("<Q", data, 40)[0]
    section_size, section_count = struct.unpack_from("<HH", data, 58)
    needed = []
    versions = []
    interpreter = None
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, phcount = struct.unpack_from("<HH", data, 54)
    if phsize < 56 or not phcount or phoff + phsize * phcount > len(data):
        raise deps.DependencyError("invalid Zsh ELF program headers")
    for i in range(phcount):
        pos = phoff + i * phsize
        kind = struct.unpack_from("<I", data, pos)[0]
        offset = struct.unpack_from("<Q", data, pos + 8)[0]
        size = struct.unpack_from("<Q", data, pos + 32)[0]
        if kind == 3:
            interpreter = data[offset:offset + size].rstrip(b"\0").decode("ascii")
    if section_count:
        if section_size < 64 or section_offset + section_size * section_count > len(data):
            raise deps.DependencyError("invalid ELF section table")
        sections = [struct.unpack_from("<IIQQQQIIQQ", data, section_offset + i * section_size) for i in range(section_count)]
        for section in sections:
            kind, offset, size, link = section[1], section[4], section[5], section[6]
            if kind not in (6, 0x6FFFFFFE):
                continue
            if offset + size > len(data) or link >= len(sections):
                raise deps.DependencyError("invalid ELF dynamic/version section")
            strings = sections[link]
            table = data[strings[4]:strings[4] + strings[5]]

            def text(index):
                end = table.find(b"\0", index)
                if index >= len(table) or end < 0:
                    raise deps.DependencyError("ELF string outside table")
                return table[index:end].decode("ascii")

            if kind == 6:
                for pos in range(offset, offset + size - 15, 16):
                    tag, value = struct.unpack_from("<qQ", data, pos)
                    if tag == 1:
                        needed.append(text(value))
            else:
                pos = offset
                seen = set()
                while pos not in seen and pos + 16 <= offset + size:
                    seen.add(pos)
                    _, number, _, auxiliary, following = struct.unpack_from("<HHIII", data, pos)
                    aux = pos + auxiliary
                    for _ in range(number):
                        if aux + 16 > offset + size:
                            raise deps.DependencyError("invalid ELF version auxiliary entry")
                        _, _, _, name, next_aux = struct.unpack_from("<IHHII", data, aux)
                        value = text(name)
                        if value.startswith("GLIBC_"):
                            versions.append(value[6:])
                        aux += next_aux
                    if not following:
                        break
                    pos += following
    if interpreter and not versions:
        raise deps.DependencyError("dynamic Zsh ELF has no verifiable GLIBC version requirements")
    if any(not re.fullmatch(r"\d+(?:\.\d+)+", v) for v in versions):
        raise deps.DependencyError("unsupported non-numeric GLIBC ABI requirement")
    maximum = max(versions, key=lambda x: tuple(map(int, x.split(".")))) if versions else None
    return {"format": "ELF64", "machine": "x86_64", "interpreter": interpreter, "needed": sorted(set(needed)), "glibc_versions": sorted(set(versions)), "maximum_glibc": maximum}


def validate_abi(abi: dict, platform: str, pinned: dict) -> None:
    if platform == "windows-x64":
        imports = set(abi["imports"])
        required = set(pinned["platforms"][platform]["required_imports"])
        if not required <= imports or imports - required - set(pinned["platforms"][platform]["system_imports"]):
            raise deps.DependencyError(f"Zsh does not use the locked private MSYS ABI: {sorted(imports)}")
    else:
        maximum = abi["maximum_glibc"]
        if maximum and tuple(map(int, maximum.split("."))) > (2, 31):
            raise deps.DependencyError(f"Zsh requires GLIBC_{maximum}; Ubuntu 20.04 limit is GLIBC_2.31")
        if abi["interpreter"] not in (None, "/lib64/ld-linux-x86-64.so.2"):
            raise deps.DependencyError("unapproved ELF interpreter")
        allowed = set(pinned["platforms"][platform]["allowed_needed"])
        if set(abi["needed"]) - allowed:
            raise deps.DependencyError(f"unapproved Linux Zsh shared libraries: {abi['needed']}")


def patch_changes(data: bytes) -> list[bytes]:
    return [line for line in data.splitlines() if line.startswith((b"+", b"-")) and not line.startswith((b"+++", b"---"))]


def apply_patch(source: Path, content: bytes, strip: int) -> None:
    lines = content.decode("utf-8").splitlines(keepends=True)
    index = 0
    changed = False
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise deps.DependencyError("malformed unified patch header")
        name = lines[index + 1][4:].split()[0]
        parts = PurePosixPath(name).parts[strip:]
        path = deps.inside(source, str(PurePosixPath(*parts)))
        data = path.read_text(encoding="utf-8").splitlines(keepends=True)
        index += 2
        last = 0
        delta = 0
        while index < len(lines) and lines[index].startswith("@@ "):
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[index])
            if not match:
                raise deps.DependencyError("malformed unified patch hunk")
            old_count, new_count = int(match[2] or 1), int(match[4] or 1)
            expected = int(match[1]) - 1 + delta
            old, new = [], []
            index += 1
            while index < len(lines) and not lines[index].startswith(("@@ ", "--- ", "diff ")):
                line = lines[index]
                if line.startswith(" "):
                    old.append(line[1:]); new.append(line[1:])
                elif line.startswith("-"):
                    old.append(line[1:])
                elif line.startswith("+"):
                    new.append(line[1:])
                else:
                    break
                index += 1
            if len(old) != old_count or len(new) != new_count:
                raise deps.DependencyError("patch hunk count mismatch")
            matches = [pos for pos in range(last, len(data) - len(old) + 1) if data[pos:pos + len(old)] == old]
            if expected in matches:
                position = expected
            elif len(matches) == 1:
                position = matches[0]
            else:
                raise deps.DependencyError(f"patch context mismatch or ambiguous hunk: {path.name}")
            data[position:position + len(old)] = new
            delta = position - (int(match[1]) - 1) + len(new) - len(old)
            last = position + len(new)
            changed = True
        path.write_text("".join(data), encoding="utf-8", newline="\n")
    if not changed:
        raise deps.DependencyError("patch contains no applicable hunks")


def load_lock(path: Path = DEFAULT_LOCK) -> dict:
    pinned = deps.read_json(path)
    if pinned.get("schema_version") != 1 or pinned.get("version") != "5.9.2+gx-metafied-paths":
        raise deps.DependencyError("unsupported GX Zsh lock")
    deps.artifact_shape(pinned["source"])
    for platform in deps.PLATFORMS:
        for item in source_artifacts(pinned, platform):
            deps.artifact_shape(item)
    return pinned


def source_artifacts(pinned: dict, platform: str) -> list[dict]:
    entries = [pinned["source"], pinned["gx_patch"], pinned["platforms"][platform]["modules"], *pinned.get("original_recipes", [])]
    if platform == "ubuntu-amd64" and pinned.get("linux_toolchain"):
        entries.extend(pinned["linux_toolchain"]["kit"])
    for patch in pinned["platforms"][platform]["patches"]:
        entries.append(patch["original"])
        if patch.get("refreshed"):
            entries.append(patch["refreshed"])
    return entries


def prepare_source(pinned: dict, platform: str, cache: Path, output: Path) -> dict:
    if output.exists():
        raise deps.DependencyError("Zsh source output must be new")
    deps.extract_archive(deps.verify_artifact(pinned["source"], cache), output, strip=1)
    for item in pinned["platforms"][platform]["patches"]:
        original = deps.verify_artifact(item["original"], cache).read_bytes()
        content = original
        if item.get("refreshed"):
            content = deps.verify_artifact(item["refreshed"], cache).read_bytes()
            if patch_changes(original) != patch_changes(content):
                raise deps.DependencyError("MSYS context refresh changed added/deleted source lines")
        apply_patch(output, content, item["strip"])
    pre = {name: deps.sha256_file(output / name) for name in SOURCE_FILES}
    if pre != pinned["platforms"][platform]["pre_gx_source_sha256"]:
        raise deps.DependencyError("pre-GX Zsh source hashes differ from the locked platform patches")
    apply_patch(output, deps.verify_artifact(pinned["gx_patch"], cache).read_bytes(), 1)
    post = {name: deps.sha256_file(output / name) for name in SOURCE_FILES}
    if post != pinned["platforms"][platform]["post_gx_source_sha256"]:
        raise deps.DependencyError("post-GX Zsh source hashes differ from the locked patch")
    return {"pre_gx_source_sha256": pre, "post_gx_source_sha256": post, "fuzz_allowed": 0}


def canonical_payload(stage: Path, platform: str, output: Path, pinned: dict) -> dict:
    exe = "zsh.exe" if platform == "windows-x64" else "zsh"
    binary = stage / "libexec/zsh" / exe
    abi = binary_abi(binary, platform)
    validate_abi(abi, platform, pinned)
    source_functions = stage / "share/zsh/functions"
    function_records = sorted(deps.tree_manifest(source_functions), key=lambda item: item["path"])
    if deps.canonical_digest(function_records) != pinned["functions_canonical_sha256"]:
        raise deps.DependencyError("Zsh completion/functions tree does not match the locked source build")
    license_file = stage / "share/licenses/zsh/LICENCE"
    if deps.sha256_file(license_file) != pinned["license_sha256"]:
        raise deps.DependencyError("Zsh license mismatch")
    prefix = output / "runtime/msys64" if platform == "windows-x64" else output
    shutil.copytree(source_functions, prefix / "share/zsh/functions")
    (prefix / "share/zsh/site-functions").mkdir(parents=True)
    (prefix / "share/zsh/site-functions/.gx-empty").write_text("Package-managed site functions. External dynamic Zsh modules are unsupported.\n", encoding="utf-8", newline="\n")
    if platform == "windows-x64":
        for name in ("usr/bin/zsh.exe", "usr/bin/zsh-5.9.2.exe"):
            target = prefix / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary, target)
    else:
        (prefix / "libexec/zsh").mkdir(parents=True)
        shutil.copy2(binary, prefix / "libexec/zsh/zsh")
        (prefix / "libexec/zsh/zsh").chmod(0o755)
        (prefix / "bin").mkdir()
        (prefix / "bin/zsh").write_bytes(WRAPPER)
        (prefix / "bin/zsh").chmod(0o755)
    (prefix / "share/licenses/zsh").mkdir(parents=True)
    shutil.copy2(license_file, prefix / "share/licenses/zsh/LICENCE")
    return abi


def run(command: list[str], cwd: Path, env: dict, log: Path) -> str:
    with log.open("wb") as stream:
        process = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
    if process.returncode:
        raise deps.DependencyError(f"Zsh build command failed ({process.returncode}); see {log}")
    return log.read_text(encoding="utf-8", errors="replace")


def record_build(pinned: dict, platform: str, stage: Path, materials: Path, output: Path, evidence: dict) -> dict:
    if output.exists():
        raise deps.DependencyError("Zsh receipt output must not exist")
    required = {"source_sha256": pinned["source"]["sha256"], "gx_patch_sha256": pinned["gx_patch"]["sha256"], "static_modules": True,
                "modules_sha256": pinned["platforms"][platform]["modules"]["sha256"], "fuzz_allowed": 0}
    for key, expected in required.items():
        if evidence.get(key) != expected:
            raise deps.DependencyError(f"Zsh build evidence {key} mismatch")
    if evidence.get("post_gx_source_sha256") != pinned["platforms"][platform]["post_gx_source_sha256"]:
        raise deps.DependencyError("Zsh build evidence patched-source mismatch")
    if not evidence.get("tools") or not evidence.get("commands"):
        raise deps.DependencyError("Zsh build evidence lacks observed toolchain and build commands")
    binary = stage / "libexec/zsh" / ("zsh.exe" if platform == "windows-x64" else "zsh")
    if evidence.get("binary_sha256") != deps.sha256_file(binary):
        raise deps.DependencyError("Zsh build evidence binary hash mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".gx-zsh-record-", dir=output.parent) as temporary:
        work = Path(temporary) / "bundle"
        payload = work / "payload"
        abi = canonical_payload(stage, platform, payload, pinned)
        if platform == "ubuntu-amd64" and pinned["platforms"][platform].get("toolchain_status", "").startswith("pending"):
            raise deps.DependencyError("Linux receipt is blocked until the verified Ubuntu 20.04 SDK enters the source lock")
        redistribution = work / "redistribution"
        redistribution.mkdir()
        for item in source_artifacts(pinned, platform):
            target = redistribution / item.get("repository_path", item["filename"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(deps.verify_artifact(item, materials), target)
        license_source = stage / "share/licenses/zsh/LICENCE"
        shutil.copy2(license_source, redistribution / "ZSH-LICENCE.txt")
        shutil.copy2(Path(__file__), redistribution / "gx_build_zsh.py")
        shutil.copy2(Path(deps.__file__), redistribution / "gx_dependencies.py")
        deps.write_json(redistribution / "zsh-runtime-lock.json", pinned)
        deps.write_json(redistribution / "BUILD.json", evidence)
        sources = [{"path": "redistribution/" + p.relative_to(redistribution).as_posix(), "sha256": deps.sha256_file(p), "size": p.stat().st_size} for p in sorted(redistribution.rglob("*")) if p.is_file() and p.name != "ZSH-LICENCE.txt"]
        receipt = {"schema_version": 1, "version": pinned["version"], "platform": platform,
                   **required, "abi": abi, "external_dynamic_modules_supported": False,
                   "binary_sha256": evidence["binary_sha256"], "source_lock_digest": deps.canonical_digest(pinned),
                   "post_gx_source_sha256": evidence["post_gx_source_sha256"],
                   "toolchain": evidence["tools"], "commands": evidence["commands"],
                   "build_provenance": evidence.get("build_provenance", "source-build"),
                   "files": deps.tree_manifest(payload), "source_artifacts": sources,
                   "license_artifacts": [{"path": "redistribution/ZSH-LICENCE.txt", "sha256": pinned["license_sha256"], "size": license_source.stat().st_size}],
                   "upstream_tests": evidence.get("upstream_tests", {}),
                   "excluded_build_outputs": ["libexec/zsh/zsh.old", "libexec/zsh/zsh.old.exe"],
                   "validation": {"lifecycle": "pending", "pty": "pending"}}
        deps.write_json(work / "zsh-build.json", receipt)
        verify_receipt(pinned, platform, work)
        work.rename(output)
    return receipt


def verify_receipt(pinned: dict, platform: str, build: Path, *, receipt: dict | None = None, subset: bool = False, materials_root: Path | None = None, payload_root: Path | None = None) -> dict:
    receipt = receipt or deps.read_json(build / "zsh-build.json")
    expected = {"schema_version": 1, "version": pinned["version"], "platform": platform,
                "source_sha256": pinned["source"]["sha256"], "gx_patch_sha256": pinned["gx_patch"]["sha256"],
                "static_modules": True, "modules_sha256": pinned["platforms"][platform]["modules"]["sha256"],
                "fuzz_allowed": 0, "external_dynamic_modules_supported": False,
                "post_gx_source_sha256": pinned["platforms"][platform]["post_gx_source_sha256"]}
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise deps.DependencyError(f"Zsh receipt {key} mismatch")
    payload = payload_root or build / "payload"
    if not subset:
        deps.verify_tree(payload, receipt["files"])
    else:
        for item in receipt["files"]:
            path = deps.inside(payload, item["path"])
            if not path.is_file() or deps.sha256_file(path) != item["sha256"] or path.stat().st_size != item["size"]:
                raise deps.DependencyError(f"Zsh overlay file mismatch: {item['path']}")
    prefix = payload / "runtime/msys64" if platform == "windows-x64" else payload
    binary = prefix / ("usr/bin/zsh.exe" if platform == "windows-x64" else "libexec/zsh/zsh")
    actual = binary_abi(binary, platform)
    validate_abi(actual, platform, pinned)
    if platform == "ubuntu-amd64" and pinned["platforms"][platform].get("toolchain_status", "").startswith("pending"):
        raise deps.DependencyError("Linux receipt requires the verified Ubuntu 20.04 SDK source lock")
    if actual != receipt.get("abi"):
        raise deps.DependencyError("Zsh ABI receipt differs from actual binary")
    functions = sorted(deps.tree_manifest(prefix / "share/zsh/functions"), key=lambda item: item["path"])
    if deps.canonical_digest(functions) != pinned["functions_canonical_sha256"]:
        raise deps.DependencyError("Zsh functions receipt differs from source lock")
    base = "runtime/msys64/" if platform == "windows-x64" else ""
    allowed = {base + "share/zsh/functions/" + f["path"] for f in functions}
    allowed |= {base + "share/zsh/site-functions/.gx-empty", base + "share/licenses/zsh/LICENCE"}
    allowed |= {base + "usr/bin/zsh.exe", base + "usr/bin/zsh-5.9.2.exe"} if platform == "windows-x64" else {"bin/zsh", "libexec/zsh/zsh"}
    if {f["path"] for f in receipt["files"]} != allowed:
        raise deps.DependencyError("Zsh receipt has an incomplete or unexpected file set")
    if platform == "windows-x64":
        if deps.sha256_file(prefix / "usr/bin/zsh-5.9.2.exe") != deps.sha256_file(binary):
            raise deps.DependencyError("versioned nested Zsh still points to an old executable")
    elif (prefix / "bin/zsh").read_bytes() != WRAPPER:
        raise deps.DependencyError("Linux nested-Zsh wrapper does not implement the relocatable FPATH contract")
    if deps.sha256_file(prefix / "share/licenses/zsh/LICENCE") != pinned["license_sha256"]:
        raise deps.DependencyError("Zsh runtime license mismatch")
    materials_root = materials_root or build
    artifacts = receipt.get("source_artifacts", []) + receipt.get("license_artifacts", [])
    by_name = {}
    for item in artifacts:
        path = deps.inside(materials_root, item["path"])
        if not path.is_file() or path.is_symlink() or deps.sha256_file(path) != item["sha256"]:
            raise deps.DependencyError(f"Zsh corresponding-source/license asset missing or changed: {item['path']}")
        by_name[path.name] = item["sha256"]
    for item in source_artifacts(pinned, platform):
        if by_name.get(item["filename"]) != item["sha256"]:
            raise deps.DependencyError(f"Zsh receipt omits locked source material: {item['filename']}")
    if by_name.get("ZSH-LICENCE.txt") != pinned["license_sha256"] or not {"BUILD.json", "gx_build_zsh.py", "gx_dependencies.py", "zsh-runtime-lock.json"} <= by_name.keys():
        raise deps.DependencyError("Zsh receipt lacks license text or rebuild instructions")
    if not receipt.get("toolchain") or not receipt.get("commands"):
        raise deps.DependencyError("Zsh receipt lacks actual build toolchain/command evidence")
    if receipt.get("binary_sha256") != deps.sha256_file(binary) or receipt.get("source_lock_digest") != deps.canonical_digest(pinned):
        raise deps.DependencyError("Zsh binary/source-lock receipt mismatch")
    build_record = deps.read_json(materials_root / "redistribution/BUILD.json")
    if build_record.get("tools") != receipt["toolchain"] or build_record.get("commands") != receipt["commands"] or build_record.get("binary_sha256") != receipt["binary_sha256"]:
        raise deps.DependencyError("Zsh BUILD instructions differ from the receipt")
    if deps.read_json(materials_root / "redistribution/zsh-runtime-lock.json") != pinned:
        raise deps.DependencyError("Zsh redistributed source lock differs from build input")
    if platform == "windows-x64":
        expected_packages = [{k: item[k] for k in ("name", "version", "sha256")} for item in pinned["windows_toolchain"]["packages"]]
        if receipt["toolchain"].get("locked_packages") != expected_packages:
            raise deps.DependencyError("Zsh Windows compiler package inventory mismatch")
    elif pinned.get("linux_toolchain"):
        sdk = pinned["linux_toolchain"]
        if receipt["toolchain"].get("sdk_packages_digest") != sdk["package_records_digest"] or receipt["toolchain"].get("sdk_package_count") != sdk["package_count"]:
            raise deps.DependencyError("Zsh Focal compiler package inventory mismatch")
        if receipt["toolchain"].get("sdk_signature_chain_verified") is not True:
            raise deps.DependencyError("Zsh Focal SDK signature/index/package verification is missing")
    return receipt


def build_windows(pinned: dict, cache: Path, work: Path, output: Path, jobs: int, repository_root: Path) -> dict:
    if os.name != "nt":
        raise deps.DependencyError("MSYS Zsh build requires a Windows builder")
    if work.exists() or output.exists():
        raise deps.DependencyError("Zsh work/output directories must be new")
    work.mkdir(parents=True)
    for item in source_artifacts(pinned, "windows-x64"):
        deps.fetch_artifact(item, cache, repository_root)
    base = pinned["windows_toolchain"]["base"]
    root = work / "msys64"
    deps.extract_archive(deps.fetch_artifact(base, cache), root, strip=1, runtime=True)
    for index, item in enumerate(pinned["windows_toolchain"]["packages"]):
        archive = deps.fetch_artifact(item, cache)
        unpacked = work / f"tool-{index}"
        deps.extract_archive(archive, unpacked, runtime=True)
        for record in deps.tree_manifest(unpacked):
            destination = deps.inside(root, record["path"])
            if destination.exists():
                if deps.sha256_file(destination) != record["sha256"]:
                    raise deps.DependencyError(f"conflicting isolated MSYS build-tool file: {record['path']}")
            else:
                deps.install_mapping(unpacked, root, {"from": record["path"], "to": record["path"]})
    source = work / "source"
    proof = prepare_source(pinned, "windows-x64", cache, source)
    home = work / "home"
    home.mkdir()
    (work / "tmp").mkdir()
    logs = work / "logs"
    logs.mkdir()
    env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE"}}
    env.update(HOME=str(home), USERPROFILE=str(home), TMP=str(work / "tmp"), TEMP=str(work / "tmp"), MSYSTEM="MSYS", CHERE_INVOKING="1", MSYS2_PATH_TYPE="strict", PATH=str(root / "usr/bin"))
    cygpath = root / "usr/bin/cygpath.exe"
    (root / "tmp").mkdir(exist_ok=True)
    posix = subprocess.run([str(cygpath), "-u", str(work.resolve())], env=env, check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    env.update(HOME=posix + "/home", TMPDIR=posix + "/tmp", TMPPREFIX=posix + "/tmp/zsh", LANG="C.UTF-8")
    (work / "config.modules").write_bytes(deps.verify_artifact(pinned["platforms"]["windows-x64"]["modules"], cache).read_bytes())
    script = work / "build.sh"
    args = " ".join(pinned["platforms"]["windows-x64"]["configure_args"])
    script.write_text(f'''#!/usr/bin/bash
set -euo pipefail
ROOT=$1
export PATH=/usr/bin:/bin
export HOME="$ROOT/home" TMPDIR="$ROOT/tmp" TMPPREFIX="$ROOT/tmp/zsh"
export CFLAGS="-O2 -ffile-prefix-map=$ROOT=."
mkdir -p "$ROOT/build" "$ROOT/stage"
cd "$ROOT/build"
"$ROOT/source/configure" {args}
cp "$ROOT/config.modules" config.modules
make prep
make -j{jobs}
make DESTDIR="$ROOT/stage" install.bin install.modules install.fns
mkdir -p "$ROOT/stage/share/licenses/zsh"
cp "$ROOT/source/LICENCE" "$ROOT/stage/share/licenses/zsh/LICENCE"
"$ROOT/stage/libexec/zsh/zsh.exe" --version
make TESTNUM=A09 check
make TESTNUM=D03 check
''', encoding="utf-8", newline="\n")
    tools = {}
    for name, argv in (("gcc", ["gcc.exe", "--version"]), ("target", ["gcc.exe", "-dumpmachine"]), ("make", ["make.exe", "--version"])):
        binary = root / "usr/bin" / argv[0]
        tools[name] = {"stdout": run([str(binary), *argv[1:]], work, env, logs / (name + ".log")), "sha256": deps.sha256_file(binary)}
    tools["locked_packages"] = [{k: item[k] for k in ("name", "version", "sha256")} for item in pinned["windows_toolchain"]["packages"]]
    command = [str(root / "usr/bin/bash.exe"), "--noprofile", "--norc", posix + "/build.sh", posix]
    text = run(command, work, env, logs / "build.log")
    if not all(name in text for name in ("A09", "D03")) or text.count("1 successful test script, 0 failures, 0 skipped") != 2:
        raise deps.DependencyError("Zsh A09/D03 tests did not produce zero-failure/zero-skip evidence")
    for path, expected in proof["post_gx_source_sha256"].items():
        if deps.sha256_file(source / path) != expected:
            raise deps.DependencyError("Zsh build modified locked patched source")
    evidence = {**proof, "source_sha256": pinned["source"]["sha256"], "gx_patch_sha256": pinned["gx_patch"]["sha256"], "static_modules": True,
                "modules_sha256": pinned["platforms"]["windows-x64"]["modules"]["sha256"], "tools": tools,
                "binary_sha256": deps.sha256_file(work / "stage/libexec/zsh/zsh.exe"),
                "commands": ["configure " + args, "make prep", f"make -j{jobs}", "make install.bin install.modules install.fns", "make TESTNUM=A09 check", "make TESTNUM=D03 check"],
                "upstream_tests": {"A09": "passed", "D03": "passed", "log_sha256": deps.sha256_file(logs / "build.log")}}
    return record_build(pinned, "windows-x64", work / "stage", cache, output, evidence)


def build_linux(pinned: dict, cache: Path, work: Path, output: Path | None, repository_root: Path, sdk_cache: Path | None, keyring: Path, verify_only: bool = False) -> dict:
    if os.name == "nt" or sys.platform != "linux":
        raise deps.DependencyError("Focal SDK replay must run under Linux/WSL, never Windows Python")
    if work.exists() or (output is not None and output.exists()):
        raise deps.DependencyError("Linux Zsh work/output directories must be new")
    sdk = pinned.get("linux_toolchain", {})
    if sdk.get("status") != "verified-Ubuntu-20.04-SDK" or not keyring.is_file():
        raise deps.DependencyError("verified Focal SDK and Ubuntu public archive keyring are required")
    work = work.resolve()
    work.mkdir(parents=True)
    kit = work / "kit"
    kit.mkdir()
    for item in source_artifacts(pinned, "ubuntu-amd64"):
        deps.fetch_artifact(item, cache, repository_root)
    for item in sdk["kit"]:
        shutil.copy2(deps.verify_artifact(item, cache), kit / item["filename"])
    packages = deps.read_json(kit / "packages-lock.json")["packages"]
    if len(packages) != sdk["package_count"] or deps.canonical_digest(packages) != sdk["package_records_digest"]:
        raise deps.DependencyError("Focal SDK package lock differs from source lock")
    (kit / "downloads").mkdir()
    (kit / "patches").mkdir()
    shutil.copy2(deps.verify_artifact(pinned["source"], cache), kit / "downloads" / pinned["source"]["filename"])
    shutil.copy2(deps.verify_artifact(pinned["gx_patch"], cache), kit / "patches" / pinned["gx_patch"]["filename"])
    shutil.copy2(deps.verify_artifact(pinned["platforms"]["ubuntu-amd64"]["modules"], cache), kit / "static-linux.config.modules")
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT"}}
    (work / "home").mkdir()
    (work / "tmp").mkdir()
    env.update(HOME=str(work / "home"), TMPDIR=str(work / "tmp"), LANG="C.UTF-8", LC_ALL="C.UTF-8", PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, str(kit / "reproduce_focal.py"), "--work", str(work / "sdk"), "--keyring", str(keyring.resolve())]
    if sdk_cache:
        command += ["--cache", str(sdk_cache.resolve())]
    if verify_only:
        command.append("--verify-only")
    run(command, work, env, work / "replay.log")
    verification = deps.read_json(work / "sdk/verified.json")
    if verification.get("packages") != sdk["package_count"] or verification.get("release_package_hash_chain") is not True:
        raise deps.DependencyError("Focal SDK signature replay failed")
    if verify_only:
        return {"sdk_verified": True, "package_count": len(packages)}
    stage = work / "sdk/rootfs/work/stage-focal"
    source = work / "sdk/rootfs/work/source/zsh-5.9.2"
    post = {name: deps.sha256_file(source / name) for name in SOURCE_FILES}
    if post != pinned["platforms"]["ubuntu-amd64"]["post_gx_source_sha256"]:
        raise deps.DependencyError("Focal build source hash mismatch")
    log = work / "sdk/logs/build_focal.sh.log"
    text = log.read_text(encoding="utf-8", errors="replace")
    if text.count("1 successful test script, 0 failures, 0 skipped") != 2:
        raise deps.DependencyError("Focal A09/D03 zero-failure zero-skip evidence is absent")
    tools_log = work / "sdk/logs/populate_rootfs.sh.log"
    evidence = {"source_sha256": pinned["source"]["sha256"], "gx_patch_sha256": pinned["gx_patch"]["sha256"],
                "static_modules": True, "fuzz_allowed": 0, "modules_sha256": pinned["platforms"]["ubuntu-amd64"]["modules"]["sha256"],
                "post_gx_source_sha256": post, "binary_sha256": deps.sha256_file(stage / "libexec/zsh/zsh"),
                "tools": {"sdk_packages_digest": sdk["package_records_digest"], "sdk_package_count": sdk["package_count"],
                          "sdk_signature_chain_verified": True, "observed_tools": tools_log.read_text(encoding="utf-8"), "verification": verification},
                "commands": ["reproduce_focal.py: verify official Ubuntu signatures/indexes and exact packages", "populate_rootfs.sh in private PRoot", "build_focal.sh in Focal userland"],
                "upstream_tests": {"A09": "passed", "D03": "passed", "log_sha256": deps.sha256_file(log)}}
    return record_build(pinned, "ubuntu-amd64", stage, cache, output, evidence)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build or verify source-pinned GX Zsh receipts; never install into a real HOME/system.")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("fetch", "build", "record", "verify", "check-abi", "verify-sdk"):
        command = commands.add_parser(name)
        command.add_argument("--platform", choices=deps.PLATFORMS, required=True)
        if name in ("fetch", "build", "record", "verify-sdk"):
            command.add_argument("--cache", type=Path, required=True)
        if name in ("build", "record"):
            command.add_argument("--output", type=Path, required=True)
        if name in ("build", "verify-sdk"):
            command.add_argument("--work", type=Path, required=True)
            command.add_argument("--jobs", type=int, default=4)
            command.add_argument("--sdk-cache", type=Path)
            command.add_argument("--keyring", type=Path, default=Path("/usr/share/keyrings/ubuntu-archive-keyring.gpg"))
        if name == "record":
            command.add_argument("--stage", type=Path, required=True)
            command.add_argument("--evidence", type=Path, required=True)
        if name == "verify":
            command.add_argument("--build", type=Path, required=True)
        if name == "check-abi":
            command.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        pinned = load_lock(args.lock)
        if args.command == "fetch":
            entries = source_artifacts(pinned, args.platform)
            if args.platform == "windows-x64":
                entries += pinned["windows_toolchain"]["packages"]
            for item in entries:
                deps.fetch_artifact(item, args.cache, args.lock.parent)
            result = {"verified_inputs": len(entries)}
        elif args.command == "verify-sdk":
            if args.platform != "ubuntu-amd64":
                raise deps.DependencyError("verify-sdk is the Ubuntu signature-chain replay gate")
            result = build_linux(pinned, args.cache, args.work, None, args.lock.parent, args.sdk_cache, args.keyring, verify_only=True)
        elif args.command == "build":
            if not 1 <= args.jobs <= 32:
                raise deps.DependencyError("jobs must be between 1 and 32")
            if args.platform == "windows-x64":
                result = build_windows(pinned, args.cache, args.work, args.output, args.jobs, args.lock.parent)
            else:
                result = build_linux(pinned, args.cache, args.work, args.output, args.lock.parent, args.sdk_cache, args.keyring)
        elif args.command == "record":
            result = record_build(pinned, args.platform, args.stage, args.cache, args.output, deps.read_json(args.evidence))
        elif args.command == "verify":
            result = verify_receipt(pinned, args.platform, args.build)
        else:
            result = binary_abi(args.binary, args.platform)
            validate_abi(result, args.platform, pinned)
        print(json.dumps({"ok": True, "platform": args.platform, "abi": result.get("abi", result if args.command == "check-abi" else None), "files": len(result.get("files", []))}, indent=2))
        return 0
    except (ValueError, OSError, KeyError, struct.error, subprocess.CalledProcessError) as error:
        print(f"gx-build-zsh: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
