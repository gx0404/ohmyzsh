#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCK = ROOT / "scripts/packaging/dependencies.json"
PLATFORMS = ("windows-x64", "ubuntu-amd64")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
PRIVATE_PARTS = {".git", ".ssh", ".gnupg", "node_modules", "__pycache__"}
RUNTIME_EXCLUDES = (
    "home", "tmp", "var/cache", "var/log", "var/tmp", "etc/pacman.d/gnupg",
    "etc/ssh", "etc/passwd", "etc/group", "etc/mtab", "etc/post-install",
    "dev", "proc",
)
PACKAGE_METADATA = {".PKGINFO", ".BUILDINFO", ".MTREE", ".INSTALL"}


class DependencyError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DependencyError(f"JSON object required: {path}")
    return value


def relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or any(ord(c) < 32 for c in value):
        raise DependencyError(f"unsafe relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or any(p in PRIVATE_PARTS for p in path.parts):
        raise DependencyError(f"unsafe relative path: {value!r}")
    if any(p == ".env" or p.startswith(".env.") or p in {"zshrc.local", "id_rsa", "id_ed25519"} for p in path.parts):
        raise DependencyError(f"private input forbidden: {value!r}")
    if any(p.endswith((".", " ")) or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p) for p in path.parts):
        raise DependencyError(f"nonportable archive path: {value!r}")
    return path


def inside(root: Path, name: str) -> Path:
    path = root / relative_path(name)
    if not path.resolve().is_relative_to(root.resolve()):
        raise DependencyError(f"path leaves input root: {name}")
    return path


def artifact_shape(item: dict) -> None:
    if not isinstance(item, dict) or not isinstance(item.get("sha256"), str) or not SHA256.fullmatch(item["sha256"]):
        raise DependencyError("artifact needs a verified SHA-256; null/placeholder hashes are not accepted")
    name = item.get("filename", "")
    if relative_path(name).name != name:
        raise DependencyError(f"artifact filename must be a basename: {name}")
    if "git_repository" in item:
        commit = item.get("commit", "")
        if (item["git_repository"] != "https://github.com/gx0404/herdr"
                or not isinstance(commit, str) or not REVISION.fullmatch(commit)
                or item.get("prefix") != f"herdr-{commit}/"
                or any(key in item for key in ("url", "repository_path", "monorepo_path"))):
            raise DependencyError(f"Git source must name the pinned independent herdr commit: {name}")
    elif "monorepo_path" in item:
        raise DependencyError("monorepo sources are no longer supported; pin the independent herdr repository")
    elif "repository_path" in item:
        location = relative_path(item["repository_path"])
        if not location.parts or not (location.parts[0] == "notices" or location.parts[:2] == ("patches", "zsh")) or "url" in item:
            raise DependencyError(f"repository artifact must be under packaging/notices or patches/zsh with no URL: {name}")
    else:
        url = urllib.parse.urlsplit(item.get("url", ""))
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
            raise DependencyError(f"artifact requires a public HTTPS source: {name}")


def verify_artifact(item: dict, cache: Path) -> Path:
    artifact_shape(item)
    path = inside(cache, item["filename"])
    if not path.is_file() or path.is_symlink():
        raise DependencyError(f"missing cached artifact: {path}")
    actual = sha256_file(path)
    if actual != item["sha256"]:
        raise DependencyError(f"SHA-256 mismatch: {item['filename']}: expected {item['sha256']}, got {actual}")
    return path


def fetch_artifact(item: dict, cache: Path, repository_root: Path | None = None) -> Path:
    artifact_shape(item)
    cache.mkdir(parents=True, exist_ok=True)
    path = inside(cache, item["filename"])
    if path.exists():
        return verify_artifact(item, cache)
    with tempfile.NamedTemporaryFile(dir=cache, prefix=".download-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            if "git_repository" in item:
                if repository_root is None:
                    raise DependencyError("an independent Git source requires --herdr-source-root")
                actual = git_output(repository_root, "rev-parse", f"{item['commit']}^{{commit}}").decode().strip()
                if actual != item["commit"]:
                    raise DependencyError("herdr source checkout is not at the locked commit")
                stream.write(git_output(repository_root, "archive", "--format=zip",
                                        f"--prefix={item['prefix']}", item["commit"]))
            elif "monorepo_path" in item:
                raise DependencyError("monorepo source archives are no longer supported")
            elif "repository_path" in item:
                source = inside(repository_root or DEFAULT_LOCK.parent, item["repository_path"])
                if source.is_symlink() or not source.is_file():
                    raise DependencyError(f"missing repository notice: {source}")
                content = source.read_bytes()
                content.decode("utf-8")
                stream.write(content.replace(b"\r\n", b"\n"))
            else:
                request = urllib.request.Request(item["url"], headers={"User-Agent": "ohmyzsh-gx-packager/1"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    if urllib.parse.urlsplit(response.url).scheme != "https":
                        raise DependencyError("refusing non-HTTPS redirect")
                    shutil.copyfileobj(response, stream)
        except BaseException:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        if sha256_file(temporary) != item["sha256"]:
            raise DependencyError(f"download SHA-256 mismatch: {item['filename']}")
        if path.exists():
            raise DependencyError(f"download destination appeared concurrently: {path}")
        temporary.rename(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def tree_manifest(root: Path) -> list[dict]:
    records = []
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        relative_path(name)
        if path.is_symlink():
            raise DependencyError(f"dependency payload must not contain symlinks: {name}")
        if path.is_file():
            records.append({"path": name, "sha256": sha256_file(path), "size": path.stat().st_size})
        elif not path.is_dir():
            raise DependencyError(f"special file forbidden: {name}")
    return records


def verify_tree(root: Path, records: list[dict]) -> None:
    expected = {}
    for record in records:
        name = str(relative_path(record["path"]))
        if name in expected:
            raise DependencyError(f"duplicate manifest path: {name}")
        expected[name] = record
    actual = {entry["path"]: entry for entry in tree_manifest(root)}
    if actual != expected:
        missing = sorted(expected.keys() - actual.keys())
        extra = sorted(actual.keys() - expected.keys())
        changed = sorted(k for k in actual.keys() & expected.keys() if actual[k] != expected[k])
        raise DependencyError(f"payload inventory mismatch: missing={missing}, extra={extra}, changed={changed}")


def check_binary(path: Path, platform: str, *, static: bool = False) -> None:
    data = path.read_bytes()
    if platform == "windows-x64":
        if len(data) < 64 or data[:2] != b"MZ":
            raise DependencyError(f"not a PE binary: {path}")
        offset = struct.unpack_from("<I", data, 60)[0]
        if offset + 24 > len(data) or data[offset:offset + 4] != b"PE\0\0" or struct.unpack_from("<H", data, offset + 4)[0] != 0x8664:
            raise DependencyError(f"not an x64 PE binary: {path}")
    else:
        if len(data) < 64 or data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", data, 18)[0] != 62:
            raise DependencyError(f"not an amd64 ELF binary: {path}")
        if static:
            offset = struct.unpack_from("<Q", data, 32)[0]
            size, count = struct.unpack_from("<HH", data, 54)
            if size < 56 or not count or offset + size * count > len(data):
                raise DependencyError(f"invalid ELF program headers: {path}")
            for index in range(count):
                kind = struct.unpack_from("<I", data, offset + index * size)[0]
                if kind == 3:
                    raise DependencyError(f"herdr must not have a dynamic interpreter: {path}")
                if kind == 2:
                    start, length = struct.unpack_from("<Q", data, offset + index * size + 8)[0], struct.unpack_from("<Q", data, offset + index * size + 32)[0]
                    if start + length > len(data):
                        raise DependencyError(f"invalid ELF dynamic table: {path}")
                    if any(struct.unpack_from("<q", data, pos)[0] == 1 for pos in range(start, start + length - 15, 16)):
                        raise DependencyError(f"herdr has dynamic NEEDED libraries: {path}")


def excluded_runtime(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + "/") for prefix in RUNTIME_EXCLUDES)


def runtime_skipped(name: str) -> bool:
    return "__pycache__" in PurePosixPath(name).parts or name in PACKAGE_METADATA or excluded_runtime(name)


@contextlib.contextmanager
def open_tar(path: Path, zstd: str | None = None):
    try:
        archive = tarfile.open(path, "r:*")
    except tarfile.ReadError:
        if not path.name.endswith(".zst") or not zstd:
            raise DependencyError(f"cannot read {path.name}; use Python with zstd support or --zstd") from None
        with tempfile.TemporaryFile() as stream:
            subprocess.run([zstd, "-d", "-c", str(path.resolve())], stdout=stream, check=True)
            stream.seek(0)
            with tarfile.open(fileobj=stream, mode="r:") as archive:
                yield archive
        return
    with archive:
        yield archive


def extract_archive(path: Path, destination: Path, *, strip: int = 0, runtime: bool = False, zstd: str | None = None) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    links = []
    seen = set()

    def mapped(name: str) -> str | None:
        if runtime and "__pycache__" in PurePosixPath(name).parts:
            return None
        original = relative_path(name)
        parts = original.parts[strip:]
        if not parts:
            return None
        result = PurePosixPath(*parts).as_posix()
        if result in PACKAGE_METADATA or (runtime and runtime_skipped(result)):
            return None
        return result

    def put(name: str, data, mode: int, is_dir: bool = False):
        name = mapped(name)
        if name is None:
            return
        key = name.casefold()
        if key in seen and not is_dir:
            raise DependencyError(f"duplicate archive member: {name}")
        seen.add(key)
        target = inside(destination, name)
        if is_dir:
            target.mkdir(parents=True, exist_ok=True)
            return
        if target.exists():
            raise DependencyError(f"archive collision: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as out:
            shutil.copyfileobj(data, out)
        target.chmod(0o755 if mode & 0o111 else 0o644)

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise DependencyError(f"ZIP symlink forbidden: {member.filename}")
                with archive.open(member) as stream:
                    put(member.filename, stream, mode, member.is_dir())
    else:
        with open_tar(path, zstd) as archive:
            for member in archive:
                name = mapped(member.name)
                if name is None:
                    continue
                if member.isdir():
                    put(member.name, io.BytesIO(), member.mode, True)
                elif member.isfile():
                    with archive.extractfile(member) as stream:
                        put(member.name, stream, member.mode)
                elif member.issym() or member.islnk():
                    if member.issym():
                        target = member.linkname
                        if target.startswith("/") and runtime:
                            target = target.lstrip("/")
                        else:
                            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                    else:
                        target = mapped(member.linkname)
                    if not target:
                        raise DependencyError(f"invalid archive link: {name}")
                    relative_path(target)
                    links.append((name, target))
                else:
                    raise DependencyError(f"special archive member: {member.name}")
    while links:
        pending = []
        for name, target in links:
            source = inside(destination, target)
            output = inside(destination, name)
            if source.is_file():
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists():
                    raise DependencyError(f"archive link collision: {name}")
                shutil.copy2(source, output)
            else:
                pending.append((name, target))
        if len(pending) == len(links):
            raise DependencyError(f"unresolved or directory archive links: {pending[:5]}")
        links = pending


def git_output(anchor: Path, *args: str) -> bytes:
    process = subprocess.run(["git", "-C", str(anchor), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise DependencyError(f"git {args[0]} failed: {detail}")
    return process.stdout


def load_lock(path: Path = DEFAULT_LOCK, repository: Path | None = None) -> dict:
    lock = read_json(path)
    if lock.get("schema_version") != 1:
        raise DependencyError("unsupported dependency lock schema")
    herdr = lock.get("herdr", {})
    if not REVISION.fullmatch(herdr.get("revision", "")) or herdr.get("repository") != "https://github.com/gx0404/herdr":
        raise DependencyError("herdr must be pinned to a full revision in gx0404/herdr")
    artifact_shape(herdr["source"])
    for item in lock.get("assets", []):
        artifact_shape(item)
        if not set(item.get("platforms", [])) <= set(PLATFORMS):
            raise DependencyError("unknown asset platform")
        for mapping in item.get("install", []):
            relative_path(mapping["from"])
            relative_path(mapping["to"])
    msys = lock.get("msys2")
    if msys:
        path_msys = inside(path.parent, msys["file"])
        lock["msys2_data"] = read_json(path_msys)
        if canonical_digest(lock["msys2_data"]) != msys["canonical_sha256"]:
            raise DependencyError("MSYS2 lock checksum mismatch")
        validate_msys(lock["msys2_data"])
    redistribution = lock.get("redistribution")
    if redistribution:
        data = read_json(inside(path.parent, redistribution["file"]))
        if data.get("schema_version") != 1 or canonical_digest(data) != redistribution["canonical_sha256"]:
            raise DependencyError("redistribution lock checksum/schema mismatch")
        lock["components"] = data["components"]
        lock["vendored_files"] = data.get("vendored_files", [])
        components = data["msys2_components"]
        packaged = [(p["name"], p["version"]) for c in components for p in c["runtime_packages"]]
        expected = [(p["name"], p["version"]) for p in lock["msys2_data"]["packages"]]
        if sorted(packaged) != sorted(expected) or len(packaged) != len(set(packaged)):
            raise DependencyError("corresponding source inventory does not cover every locked MSYS2 package exactly once")
        lock["msys2_data"]["components"] = components
    if msys:
        msys_overlay(lock["msys2_data"])
    zsh = lock.get("zsh_runtime")
    if zsh:
        import gx_build_zsh
        lock["zsh_data"] = gx_build_zsh.load_lock(inside(path.parent, zsh["file"]))
        if canonical_digest(lock["zsh_data"]) != zsh["canonical_sha256"]:
            raise DependencyError("Zsh runtime source lock checksum mismatch")
    for component in lock.get("components", []):
        if component.get("id") == "herdr" and component.get("version") != lock["herdr"].get("version"):
            raise DependencyError(f"redistribution herdr version {component.get('version')} differs from the locked herdr {lock['herdr'].get('version')}")
    lock["lock_digest"] = canonical_digest({k: v for k, v in lock.items() if k != "lock_digest"})
    return lock


def validate_msys(msys: dict) -> None:
    artifact_shape(msys["base"])
    packages = msys["packages"]
    names = {entry["name"] for entry in packages}
    if len(names) != len(packages):
        raise DependencyError("duplicate MSYS2 package")
    provided = names | {re.split(r"[<>=]", x, maxsplit=1)[0] for entry in packages for x in entry.get("provides", [])}
    for entry in packages:
        artifact_shape(entry)
        if entry.get("origin") not in {"signed-base", "signed-package"}:
            raise DependencyError("unverified MSYS2 package origin")
        if "upgrades_base" in entry and (entry["origin"] != "signed-package" or not re.fullmatch(r"[\w.+~:-]+", str(entry["upgrades_base"]))):
            raise DependencyError(f"only a signed package can upgrade a base package version: {entry['name']}")
        for dependency in entry["dependencies"]:
            if re.split(r"[<>=]", dependency, maxsplit=1)[0] not in provided:
                raise DependencyError(f"MSYS2 dependency closure incomplete: {entry['name']} -> {dependency}")


def platform_components(lock: dict, platform: str) -> list[dict]:
    entries = [c for c in lock["components"] if platform in c["platforms"]]
    if platform == "windows-x64":
        entries += lock["msys2_data"]["components"]
    return entries


def compliance_errors(lock: dict, platform: str) -> list[str]:
    errors = []
    if not lock.get("zsh_data"):
        errors.append("gx-zsh: missing source-pinned patched runtime lock")
    for component in platform_components(lock, platform):
        name = component["id"]
        policy = component.get("source_policy", {"kind": "required"})
        optional_sources = policy.get("kind") == "not-required"
        if optional_sources:
            allowed = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "OFL-1.1", "CC0-1.0", "Zsh"}
            expressions = component.get("license_expression", "").split(" AND ")
            if not policy.get("basis") or not expressions or not set(expressions) <= allowed:
                errors.append(f"{name}: source exemption needs an explicit permissive-license basis")
        elif policy.get("kind") != "required":
            errors.append(f"{name}: invalid source obligation policy")
        for field in ("licenses", "sources", "build_instructions"):
            if not component.get(field):
                if not (field == "sources" and optional_sources):
                    errors.append(f"{name}: missing locked {field}")
            else:
                for artifact in component[field]:
                    try:
                        artifact_shape(artifact)
                    except DependencyError as error:
                        errors.append(f"{name}.{field}: {error}")
    for missing in lock.get("unresolved", []):
        if platform in missing["platforms"]:
            errors.append(f"{missing['id']}: {missing['reason']}")
    return errors


def all_artifacts(lock: dict, platform: str) -> list[dict]:
    entries = [lock["herdr"]["source"]]
    if lock.get("zsh_data"):
        import gx_build_zsh
        entries.extend(gx_build_zsh.source_artifacts(lock["zsh_data"], platform))
    entries.extend(a for a in lock["assets"] if platform in a["platforms"])
    for component in platform_components(lock, platform):
        for field in ("licenses", "sources", "build_instructions"):
            entries.extend(component.get(field, []))
    if platform == "windows-x64":
        msys = lock["msys2_data"]
        entries.append(msys["base"])
        entries.extend(p for p in msys["packages"] if p["origin"] == "signed-package")
    names = {}
    for item in entries:
        artifact_shape(item)
        previous = names.setdefault(item["filename"], item)
        if previous["sha256"] != item["sha256"]:
            raise DependencyError(f"conflicting artifact name: {item['filename']}")
    return list(names.values())


def verify_inputs(lock: dict, platform: str, cache: Path) -> list[dict]:
    errors = compliance_errors(lock, platform)
    if errors:
        raise DependencyError("release inputs incomplete:\n" + "\n".join(errors))
    artifacts = all_artifacts(lock, platform)
    for artifact in artifacts:
        verify_artifact(artifact, cache)
    return artifacts


def verify_herdr(lock: dict, platform: str, build: Path) -> dict:
    receipt = read_json(build / "herdr-build.json")
    pinned = lock["herdr"]
    for field, expected in {
        "schema_version": 1, "revision": pinned["revision"], "version": pinned["version"],
        "platform": platform, "target": pinned["targets"][platform],
        "source_sha256": pinned["source"]["sha256"], "rust": pinned["rust"], "zig": pinned["zig"],
        "locked": True, "release": True, "cargo_vendor_complete": True,
    }.items():
        if receipt.get(field) != expected:
            raise DependencyError(f"herdr build receipt {field} mismatch")
    verify_tree(build / "payload", receipt["files"])
    binary = build / "payload" / ("herdr.exe" if platform == "windows-x64" else "herdr")
    check_binary(binary, platform, static=platform == "ubuntu-amd64")
    if platform == "windows-x64":
        if {r["path"] for r in receipt["files"]} != set(pinned["conpty"]["files"]):
            raise DependencyError("herdr ConPTY payload must retain the exact seven-file layout")
        if receipt.get("conpty_verified") is not True:
            raise DependencyError("missing NuGet and Microsoft Authenticode verification")
        for name, digest in pinned["conpty"]["files"].items():
            if digest is not None and sha256_file(build / "payload" / name) != digest:
                raise DependencyError(f"pinned ConPTY file mismatch: {name}")
    source_records = receipt.get("source_artifacts", [])
    license_records = receipt.get("license_artifacts", [])
    if not source_records or not license_records:
        raise DependencyError("herdr receipt requires complete dependency sources and licenses, not only herdr LICENSE")
    for item in source_records + license_records:
        path = inside(build, item["path"])
        if not path.is_file() or not SHA256.fullmatch(item["sha256"]) or sha256_file(path) != item["sha256"]:
            raise DependencyError(f"invalid herdr redistribution artifact: {item['path']}")
    return receipt


def install_mapping(extracted: Path, output: Path, mapping: dict) -> None:
    source = inside(extracted, mapping["from"])
    destination = inside(output, mapping["to"])
    if not source.exists():
        raise DependencyError(f"missing locked archive member: {mapping['from']}")
    if destination.exists():
        raise DependencyError(f"dependency install collision: {mapping['to']}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
        if mapping.get("executable"):
            destination.chmod(0o755)


def msys_overlay(msys: dict) -> list[tuple[dict, dict]]:
    # GX 改过的 MSYS2 包内文件（如 etc/fstab）：新内容作为所属组件的对应源码随再分发材料
    # 发布，锁里钉住原文件摘要；上游改动原文件时 assemble 失败，必须人工复核后再更新。
    sources = {c["id"]: c.get("sources", []) for c in msys.get("components", [])}
    entries = []
    seen = set()
    for entry in msys.get("overlay", []):
        name = str(relative_path(entry["path"]))
        matches = [a for a in sources.get(entry["component"], []) if a["filename"] == entry["filename"]]
        if (name in seen or excluded_runtime(name) or not isinstance(entry.get("old_sha256"), str)
                or not SHA256.fullmatch(entry["old_sha256"]) or len(matches) != 1 or matches[0]["sha256"] != entry["sha256"]):
            raise DependencyError(f"MSYS2 overlay entry must replace one locked file with a component source: {name}")
        seen.add(name)
        entries.append((entry, matches[0]))
    return entries


def msys_overlay_changes(msys: dict) -> list[dict]:
    return [{"path": "runtime/msys64/" + entry["path"], "old_sha256": entry["old_sha256"], "new_sha256": entry["sha256"], "action": "replaced"}
            for entry, _ in msys_overlay(msys)]


def merge_msys_overlay(msys: dict, cache: Path, runtime: Path) -> list[dict]:
    for entry, artifact in msys_overlay(msys):
        target = inside(runtime, entry["path"])
        if not target.is_file() or target.is_symlink() or sha256_file(target) != entry["old_sha256"]:
            raise DependencyError(f"original MSYS2 file differs before GX overlay: {entry['path']}")
        shutil.copyfile(verify_artifact(artifact, cache), target)
    return msys_overlay_changes(msys)


def mtree_records(text: str) -> dict[str, dict]:
    # mtree 按字节做 \ooo 八进制转义（空格、中文等文件名）：先还原成字节再按 UTF-8 解码。
    def unescape(value: str) -> str:
        return re.sub(rb"\\([0-7]{3})", lambda m: bytes([int(m.group(1), 8)]), value.encode("utf-8")).decode("utf-8")
    records = {}
    defaults = {}
    for line in text.splitlines():
        fields = line.split()
        values = {key: unescape(value) for key, _, value in (f.partition("=") for f in fields[1:])}
        if fields[:1] == ["/set"]:
            defaults.update(values)
        elif fields and fields[0].startswith("./"):
            records[unescape(fields[0][2:])] = {**defaults, **values}
    return records


def remove_base_package(runtime: Path, name: str, version: str) -> int:
    # 锁定的新签名包整体替换 base 快照里的旧版本（如 msys2-runtime 修复挂死的补丁版）：先按 pacman 本地库
    # 的文件清单与 mtree 摘要核对全部旧文件，全部一致后才删除，并删掉该条目，不留新旧混装或错误的版本记录。
    entry = inside(runtime, f"var/lib/pacman/local/{name}-{version}")
    if not (entry / "files").is_file() or not (entry / "mtree").is_file():
        raise DependencyError(f"base snapshot does not contain {name} {version} to upgrade")
    files = (entry / "files").read_text(encoding="utf-8")
    if "%FILES%\n" not in files:
        raise DependencyError(f"pacman record of {name} {version} lists no files")
    records = mtree_records(gzip.decompress((entry / "mtree").read_bytes()).decode("utf-8"))
    doomed = []
    for old in files.split("%FILES%\n", 1)[1].split("\n\n", 1)[0].splitlines():
        if not old or old.endswith("/") or runtime_skipped(old):
            continue
        record = records.get(old, {})
        expected = record.get("sha256digest")
        if record.get("type") == "link":
            link = record.get("link", "")
            source = link.lstrip("/") if link.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(old), link))
            expected = records.get(source, {}).get("sha256digest")
        target = inside(runtime, old)
        if not expected or not target.is_file() or target.is_symlink() or sha256_file(target) != expected:
            raise DependencyError(f"base file differs from its pacman record before upgrade: {old}")
        doomed.append(target)
    for target in doomed:
        target.unlink()
    shutil.rmtree(entry)
    return len(doomed)


def assemble_msys_runtime(msys: dict, cache: Path, runtime: Path, work: Path, zstd: str | None = None) -> tuple[list[dict], list[dict]]:
    extract_archive(verify_artifact(msys["base"], cache), runtime, strip=1, runtime=True, zstd=zstd)
    upgrades = []
    for index, package in enumerate(msys["packages"]):
        if package["origin"] == "signed-package":
            if "upgrades_base" in package:
                removed = remove_base_package(runtime, package["name"], package["upgrades_base"])
                upgrades.append({"name": package["name"], "old_version": package["upgrades_base"], "new_version": package["version"], "removed_files": removed})
            unpacked = work / f"package-{index}"
            extract_archive(verify_artifact(package, cache), unpacked, runtime=True, zstd=zstd)
            for item in tree_manifest(unpacked):
                install_mapping(unpacked, runtime, {"from": item["path"], "to": item["path"]})
    for path in runtime.rglob("*"):
        if excluded_runtime(path.relative_to(runtime).as_posix()) and path.is_file():
            raise DependencyError(f"runtime state leaked: {path}")
    return upgrades, merge_msys_overlay(msys, cache, runtime)


def verify_msys_runtime(msys: dict, manifest: dict, payload: Path) -> None:
    upgrades = [(p["name"], p["upgrades_base"], p["version"]) for p in msys.get("packages", []) if "upgrades_base" in p]
    recorded = manifest.get("msys2_upgrades")
    if (not isinstance(recorded, list) or not all(isinstance(r, dict) for r in recorded)
            or [(r.get("name"), r.get("old_version"), r.get("new_version")) for r in recorded] != upgrades
            or any(type(r.get("removed_files")) is not int or r["removed_files"] < 1 for r in recorded)):
        raise DependencyError("MSYS2 base upgrade provenance does not match the lock")
    for name, old, _ in upgrades:
        if inside(payload, f"runtime/msys64/var/lib/pacman/local/{name}-{old}").exists():
            raise DependencyError(f"replaced base package record leaked into the payload: {name} {old}")
    changes = msys_overlay_changes(msys)
    if manifest.get("msys2_overlay") != changes:
        raise DependencyError("MSYS2 overlay provenance does not match the lock")
    for record in changes:
        path = inside(payload, record["path"])
        if not path.is_file() or sha256_file(path) != record["new_sha256"]:
            raise DependencyError(f"GX-modified MSYS2 file differs from the lock: {record['path']}")


def merge_zsh_overlay(pinned: dict, platform: str, source: Path, payload: Path, receipt: dict) -> list[dict]:
    changes = []
    replacements = set()
    removed = set()
    if platform == "windows-x64":
        policy = pinned["platforms"][platform]
        replacements = set(policy["replacement_paths"])
        removed = set(policy["remove_original_paths"])
        for name, checksum in policy["original_runtime_files"].items():
            old = inside(payload, name)
            if not old.is_file() or old.is_symlink() or sha256_file(old) != checksum:
                raise DependencyError(f"original MSYS2 Zsh differs before GX overlay: {name}")
        for name in policy["required_runtime_dlls"]:
            if not inside(payload, name).is_file():
                raise DependencyError(f"GX Zsh private MSYS DLL absent: {name}")
        for name in sorted(replacements | removed):
            changes.append({"path": name, "old_sha256": policy["original_runtime_files"][name], "action": "removed" if name in removed else "replaced"})
    records = {entry["path"]: entry for entry in receipt["files"]}
    for name in records:
        if inside(payload, name).exists() and name not in replacements:
            raise DependencyError(f"unexpected GX Zsh overlay collision: {name}")
    for name in removed:
        inside(payload, name).unlink()
    for name in replacements:
        inside(payload, name).unlink()
    for name in records:
        install_mapping(source / "payload", payload, {"from": name, "to": name})
    for change in changes:
        if change["action"] == "replaced":
            change["new_sha256"] = records[change["path"]]["sha256"]
    return changes


def assemble(lock: dict, platform: str, cache: Path, output: Path, herdr_build: Path, zstd: str | None = None, *, zsh_build: Path | None = None) -> dict:
    if zsh_build is None:
        raise DependencyError("--zsh-build is required; unpatched system/MSYS Zsh is not a fallback")
    import gx_build_zsh
    artifacts = verify_inputs(lock, platform, cache)
    zsh_receipt = gx_build_zsh.verify_receipt(lock["zsh_data"], platform, zsh_build)
    receipt = verify_herdr(lock, platform, herdr_build)
    if output.exists():
        raise DependencyError(f"output already exists (never overwrite a runtime): {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".gx-dependencies-", dir=output.parent) as temporary:
        work = Path(temporary)
        bundle = work / "bundle"
        payload = bundle / "payload"
        payload.mkdir(parents=True)
        msys_upgrades, msys_changes = [], []
        if platform == "windows-x64":
            msys_upgrades, msys_changes = assemble_msys_runtime(lock["msys2_data"], cache, payload / "runtime/msys64", work, zstd)
        for index, asset in enumerate(lock["assets"]):
            if platform not in asset["platforms"]:
                continue
            extracted = work / f"asset-{index}"
            archive = verify_artifact(asset, cache)
            if asset.get("format", "archive") == "file":
                extracted.mkdir()
                shutil.copy2(archive, extracted / archive.name)
            else:
                extract_archive(archive, extracted, strip=asset.get("strip_components", 0), zstd=zstd)
            for mapping in asset["install"]:
                install_mapping(extracted, payload, mapping)
        shutil.copytree(herdr_build / "payload", payload / "lib/herdr")
        for record in receipt["source_artifacts"] + receipt["license_artifacts"]:
            source = inside(herdr_build, record["path"])
            target = bundle / "redistribution/herdr" / relative_path(record["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for component in platform_components(lock, platform):
            for field in ("licenses", "sources", "build_instructions"):
                for artifact in component[field]:
                    destination = bundle / "redistribution" / relative_path(component["id"]) / field / artifact["filename"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(verify_artifact(artifact, cache), destination)
        zsh_changes = merge_zsh_overlay(lock["zsh_data"], platform, zsh_build, payload, zsh_receipt)
        for record in zsh_receipt["source_artifacts"] + zsh_receipt["license_artifacts"]:
            source = inside(zsh_build, record["path"])
            target = bundle / "redistribution/zsh" / relative_path(record["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for name in lock["required_payload"][platform]:
            if not inside(payload, name).is_file():
                raise DependencyError(f"required runtime input absent: {name}")
        result = {
            "schema_version": 1, "platform": platform, "lock_digest": lock["lock_digest"],
            "herdr": receipt, "zsh": zsh_receipt, "zsh_overlay": zsh_changes,
            "msys2_upgrades": msys_upgrades, "msys2_overlay": msys_changes,
            "components": platform_components(lock, platform),
            "artifacts": [{k: a[k] for k in ("filename", "sha256", "url", "repository_path") if k in a} for a in artifacts],
            "payload": tree_manifest(payload), "redistribution": tree_manifest(bundle / "redistribution"),
            "compliance_complete": True,
        }
        write_json(bundle / "dependencies-manifest.json", result)
        bundle.rename(output)
    return result


def verify_bundle(lock: dict, platform: str, bundle: Path) -> dict:
    manifest = read_json(bundle / "dependencies-manifest.json")
    if manifest.get("schema_version") != 1 or manifest.get("platform") != platform or manifest.get("lock_digest") != lock["lock_digest"]:
        raise DependencyError("dependency bundle does not match platform/lock")
    if manifest.get("compliance_complete") is not True or compliance_errors(lock, platform):
        raise DependencyError("dependency bundle is not redistribution-complete")
    verify_tree(bundle / "payload", manifest["payload"])
    verify_tree(bundle / "redistribution", manifest["redistribution"])
    expected_artifacts = [{k: a[k] for k in ("filename", "sha256", "url", "repository_path") if k in a} for a in all_artifacts(lock, platform)]
    if manifest.get("artifacts") != expected_artifacts or manifest.get("components") != platform_components(lock, platform):
        raise DependencyError("dependency inventory does not match the complete locked input set")
    for name in lock["required_payload"][platform]:
        if not inside(bundle / "payload", name).is_file():
            raise DependencyError(f"required runtime input absent: {name}")
    for component in platform_components(lock, platform):
        for field in ("licenses", "sources", "build_instructions"):
            for artifact in component[field]:
                path = inside(bundle / "redistribution", f"{component['id']}/{field}/{artifact['filename']}")
                if not path.is_file() or sha256_file(path) != artifact["sha256"]:
                    raise DependencyError(f"missing or changed locked redistribution input: {path.name}")
    import gx_build_zsh
    if not manifest.get("zsh"):
        raise DependencyError("dependency bundle lacks mandatory patched Zsh receipt")
    gx_build_zsh.verify_receipt(lock["zsh_data"], platform, bundle, receipt=manifest["zsh"], subset=True, materials_root=bundle / "redistribution/zsh")
    expected_changes = []
    if platform == "windows-x64":
        policy = lock["zsh_data"]["platforms"][platform]
        binary_digest = manifest["zsh"]["binary_sha256"]
        for name in sorted(set(policy["replacement_paths"]) | set(policy["remove_original_paths"])):
            record = {"path": name, "old_sha256": policy["original_runtime_files"][name], "action": "removed" if name in policy["remove_original_paths"] else "replaced"}
            if record["action"] == "removed":
                if inside(bundle / "payload", name).exists():
                    raise DependencyError("unpatched MSYS Zsh shared runtime leaked into patched payload")
            else:
                record["new_sha256"] = binary_digest
            expected_changes.append(record)
    if manifest.get("zsh_overlay") != expected_changes:
        raise DependencyError("Zsh overlay source provenance does not match the locked original MSYS package")
    verify_msys_runtime(lock["msys2_data"] if platform == "windows-x64" else {}, manifest, bundle / "payload")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Locked GX dependencies. assemble is offline and rejects missing sources/licenses.")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("audit", "fetch", "verify", "assemble", "verify-bundle"):
        command = commands.add_parser(name)
        command.add_argument("--platform", choices=PLATFORMS, required=True)
        if name in {"fetch", "verify", "assemble"}:
            command.add_argument("--cache", type=Path, required=True)
        if name == "assemble":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--herdr-build", type=Path, required=True)
            command.add_argument("--zsh-build", type=Path, required=True)
            command.add_argument("--zstd")
        if name == "verify-bundle":
            command.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        lock = load_lock(args.lock)
        if args.command == "audit":
            errors = compliance_errors(lock, args.platform)
            print(json.dumps({"platform": args.platform, "lock_digest": lock["lock_digest"], "ready": not errors, "errors": errors}, indent=2))
            return 1 if errors else 0
        if args.command == "fetch":
            for item in all_artifacts(lock, args.platform):
                fetch_artifact(item, args.cache, args.lock.parent)
            print("All currently locked artifacts verified; fetch does not imply release readiness.")
        elif args.command == "verify":
            verify_inputs(lock, args.platform, args.cache)
            print("Locked source, license and runtime inputs verified.")
        elif args.command == "assemble":
            result = assemble(lock, args.platform, args.cache, args.output, args.herdr_build, args.zstd, zsh_build=args.zsh_build)
            print(json.dumps({"bundle": str(args.output), "lock_digest": result["lock_digest"]}))
        else:
            verify_bundle(lock, args.platform, args.bundle)
            print("Dependency bundle verified.")
        return 0
    except (DependencyError, OSError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"gx-dependencies: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
