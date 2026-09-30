#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import gx_dependencies as deps
import gx_release as release

ZIG_ARCHIVES = {
    "windows-x64": {
        "filename": "zig-x86_64-windows-0.16.0.zip",
        "url": "https://ziglang.org/download/0.16.0/zig-x86_64-windows-0.16.0.zip",
        "sha256": "68659eb5f1e4eb1437a722f1dd889c5a322c9954607f5edcf337bc3684a75a7e",
    },
    "ubuntu-amd64": {
        "filename": "zig-x86_64-linux-0.16.0.tar.xz",
        "url": "https://ziglang.org/download/0.16.0/zig-x86_64-linux-0.16.0.tar.xz",
        "sha256": "70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00",
    },
}


def ci_boundary(paths: list[Path], platform: str) -> str:
    # GX_LOCAL_BUILD_ROOT 是本机构建入口：隔离根换成该目录，receipt 记 builder=local，
    # 打包链据此把 stage 标为不可发布；CI runner 上不接受，避免发布链混入本机产物。
    local = os.environ.get("GX_LOCAL_BUILD_ROOT")
    if local:
        release.require(os.environ.get("GITHUB_ACTIONS") != "true", "GX_LOCAL_BUILD_ROOT is for local builds; unset it on CI runners")
        root = Path(local).resolve()
        release.require(root.is_dir(), "GX_LOCAL_BUILD_ROOT must be an existing directory")
    else:
        release.require(os.environ.get("GITHUB_ACTIONS") == "true"
                        and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
                        and os.environ.get("GITHUB_REPOSITORY") in {release.REPOSITORY, release.MONOREPO_REPOSITORY},
                        "herdr CI builder requires a disposable GitHub-hosted gx0404/ohmyzsh or gx0404/gx_shell runner; "
                        "set GX_LOCAL_BUILD_ROOT for a non-publishable local build")
        root = Path(os.environ["RUNNER_TEMP"]).resolve()
    release.require((os.name == "nt") == (platform == "windows-x64"), "builder OS and target platform differ")
    for path in paths:
        release.require(path.resolve() != root and path.resolve().is_relative_to(root),
                        "build/cache/output must be isolated under " + ("GX_LOCAL_BUILD_ROOT" if local else "RUNNER_TEMP"))
    release.require(not os.environ.get("GITHUB_TOKEN") and not os.environ.get("GH_TOKEN"), "do not expose API tokens to dependency build scripts")
    return "local" if local else "github-actions"


def run(argv: list[str], cwd: Path, env: dict, *, capture: bool = False) -> str:
    process = subprocess.run(argv, cwd=cwd, env=env, check=True, text=True, encoding="utf-8", capture_output=capture)
    return process.stdout.strip() if capture else ""


def archive_tree(root: Path, destination: Path) -> None:
    with tarfile.open(destination, "w:xz", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted(root.rglob("*")):
            release.require(not path.is_symlink(), f"source archive symlink requires review: {path}")
            if not path.is_file():
                continue
            info = archive.gettarinfo(str(path), path.relative_to(root).as_posix())
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = "root"
            with path.open("rb") as stream:
                archive.addfile(info, stream)


def record(path: Path, root: Path) -> dict:
    return {"path": path.relative_to(root).as_posix(), "sha256": deps.sha256_file(path), "size": path.stat().st_size}


def load_supplements(repo: Path) -> dict:
    path = repo / "scripts/packaging/herdr-license-supplements.json"
    data = release.read_json(path)
    release.check_fields(data, {"schema_version": 1}, "herdr license supplements")
    # 补充许可按 crate 名/版本/校验和逐条核对，herdr_revision 只记录审计时的基线。
    release.require(release.is_hash(data.get("herdr_revision"), 40), "herdr license supplements need an audited herdr revision")
    root = path.parent / "notices/herdr-build"
    for item in data["texts"].values():
        notice = deps.inside(root, item["notice"])
        release.regular_file(notice)
        release.require(deps.sha256_file(notice) == item["sha256"] and notice.stat().st_size == item["size"],
                        f"pinned supplemental license checksum mismatch: {item['notice']}")
        release.require(b"\0" not in notice.read_bytes(), "supplemental license is not text")
        deps.relative_path(item["path"])
    for source in data["sources"].values():
        release.require(source["repository"].startswith("https://github.com/") and release.is_hash(source["revision"], 40), "supplemental license needs an immutable GitHub source")
        release.require(bool(source["texts"]) and all(key in data["texts"] for key in source["texts"]), "supplemental source has missing texts")
    seen = set()
    for item in data["cargo"] + data["reuse"]:
        key = (item["name"], item["version"])
        release.require(key not in seen and release.is_hash(item["checksum"]), "duplicate or unpinned Cargo license supplement")
        seen.add(key)
    return {"data": data, "root": root, "path": path}


def supplemental_texts(store: dict, source_id: str) -> tuple[list[tuple[Path, str]], dict]:
    data = store["data"]
    source = data["sources"][source_id]
    files = []
    origins = []
    repository = source["repository"].removeprefix("https://github.com/")
    release.require(len(repository.split("/")) == 2, "invalid supplemental source repository")
    for key in source["texts"]:
        item = data["texts"][key]
        path = deps.inside(store["root"], item["notice"])
        release.regular_file(path)
        release.require(path.stat().st_size == item["size"] and deps.sha256_file(path) == item["sha256"], "supplemental license changed after lock validation")
        url = item.get("url", f"https://raw.githubusercontent.com/{repository}/{source['revision']}/{item['path']}")
        parts = url.removeprefix("https://raw.githubusercontent.com/").split("/")
        release.require(url.startswith("https://raw.githubusercontent.com/") and len(parts) >= 4 and release.is_hash(parts[2], 40), "license download URL must contain a full immutable commit")
        files.append((path, "upstream/" + str(deps.relative_path(item["path"]))))
        origins.append({"url": url, "sha256": item["sha256"], "size": item["size"], "role": item.get("role", "Original upstream license text")})
    return files, {"license_upstream_commit": source["revision"], "license_repository": source["repository"], "supplemental_texts": origins}


def cargo_supplement(root: Path, package: dict, by_root: dict, store: dict | None) -> tuple[list[tuple[Path, str]], dict]:
    if store is None:
        return [], {}
    data = store["data"]
    rules = [item for item in data["cargo"] + data["reuse"] if (item["name"], item["version"]) == (package["name"], package["version"])]
    if not rules:
        return [], {}
    release.require(len(rules) == 1, "ambiguous license supplement")
    rule = rules[0]
    checksum = deps.read_json(root / ".cargo-checksum.json")
    release.require(checksum["package"] == rule["checksum"] and package.get("license") == rule["license"], "Cargo license supplement does not match the locked crate checksum/license")
    if "source" in rule:
        source = data["sources"][rule["source"]]
        repositories = {source["repository"], source["repository"] + "/tree/main/" + rule["crate_path"]}
        release.require(package.get("repository") in repositories, "Cargo repository differs from supplemental license origin")
        vcs_path = root / ".cargo_vcs_info.json"
        vcs = deps.read_json(vcs_path)
        release.require(checksum["files"].get(".cargo_vcs_info.json") == deps.sha256_file(vcs_path)
                        and vcs["git"]["sha1"] == source["revision"] and vcs.get("path_in_vcs", "") == rule["crate_path"],
                        "Cargo .vcs evidence differs from the pinned supplemental source")
        files, identity = supplemental_texts(store, rule["source"])
        identity.update({"cargo_lock_checksum": rule["checksum"], "crate_path": rule["crate_path"], "selected_license": "MIT"})
        return files, identity
    donor = data["donors"][rule["donor"]]
    candidates = [(p, item) for p, item in by_root.items() if (item["name"], item["version"]) == (donor["name"], donor["version"])]
    release.require(len(candidates) == 1 and package.get("repository") == rule["repository"] == donor["repository"], "winapi family license donor is missing or from another repository")
    donor_root, donor_package = candidates[0]
    donor_checksums = deps.read_json(donor_root / ".cargo-checksum.json")
    release.require(donor_checksums["package"] == donor["checksum"] and donor_package.get("repository") == donor["repository"]
                    and donor_package.get("license") == rule["license"] and bool(donor["basis"]), "winapi donor checksum/license mismatch")
    files = []
    for item in donor["files"]:
        path = deps.inside(donor_root, item["path"])
        release.regular_file(path)
        release.require(path.stat().st_size == item["size"] and deps.sha256_file(path) == item["sha256"]
                        and donor_checksums["files"].get(item["path"]) == item["sha256"], "winapi donor text checksum mismatch")
        files.append((path, "upstream/" + item["path"]))
    return files, {"cargo_lock_checksum": rule["checksum"], "license_origin": donor}


def license_paths(root: Path, *, allowed: set[str] | None = None, declared: str | None = None, require_primary: bool = True) -> list[Path]:
    candidates = []
    primary = False
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if allowed is not None and name not in allowed:
            continue
        parts = path.relative_to(root).parts
        is_license = path.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "UNLICENSE"))
        named = is_license or path.name.upper().startswith(("NOTICE", "COPYRIGHT"))
        in_license_dir = any(part.casefold() in {"licenses", "licences", "copying"} for part in parts[:-1])
        if not path.is_dir() and (named or in_license_dir or name == declared):
            release.regular_file(path)
            release.require(path.stat().st_size <= 64 * 1024 * 1024, f"license text exceeds review limit: {name}")
            content = path.read_bytes()
            if not release.source_file_contains_license(name, content):
                continue
            release.verify_license_text(content, name)
            candidates.append(path)
            primary |= name == declared or ((is_license or in_license_dir) and (len(parts) == 1 or parts[0].casefold() in {"licenses", "licences", "copying"}))
    release.require(not require_primary or (primary and bool(candidates)), f"{root.name}: no vendored license text; resolve redistribution before release")
    if declared:
        release.require(root / deps.relative_path(declared) in candidates, f"declared Cargo license-file missing: {declared}")
    return candidates


def license_inventory(vendor: Path) -> list[dict]:
    packages = sorted(p for p in vendor.iterdir() if p.is_dir())
    release.require(bool(packages), "cargo vendor produced no dependencies")
    return [{"package": package.name, "licenses": [record(path, vendor) for path in license_paths(package)]}
            for package in packages]


def copy_licenses(root: Path, paths: list[Path], output: Path, ecosystem: str, package: str, source_identity: dict,
                  extra: list[tuple[Path, str]] | None = None) -> dict:
    destination = output / "redistribution/licenses" / deps.relative_path(ecosystem) / deps.relative_path(package)
    records = []
    for path, relative in [(path, path.relative_to(root).as_posix()) for path in paths] + (extra or []):
        target = deps.inside(destination, relative)
        release.require(not target.exists(), f"duplicate license destination: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        release.require(deps.sha256_file(target) == deps.sha256_file(path), "license copy checksum mismatch")
        records.append(record(target, output))
    return {"ecosystem": ecosystem, "package": package, "source_identity": source_identity, "licenses": records}


def workspace_license(source: Path, root: Path, package: dict, workspace: dict, members: set[str],
                      original_names: set[str], allowed: set[str]) -> tuple[list[tuple[Path, str]], dict]:
    # 没有任何自带许可文本的 workspace 成员（如上游新增的 crates/ghostty-vt）只在 license 表达式与根
    # crate 完全相同时沿用根目录许可文本，并在清单里记录来源；表达式不同或不是成员仍按缺许可拒绝。
    if (root == source or package.get("id") not in members or package.get("license_file")
            or not package.get("license") or package["license"] != workspace.get("license")
            or license_paths(root, allowed=allowed, require_primary=False)):
        return [], {}
    texts = license_paths(source, allowed={name for name in original_names if "/" not in name})
    names = [path.relative_to(source).as_posix() for path in texts]
    return ([(path, "workspace-root/" + name) for path, name in zip(texts, names)],
            {"license_inherited_from": {"package": workspace["name"], "license": workspace["license"], "texts": names}})


def cargo_licenses(vendor: Path, source: Path, metadata: dict, original: list[dict], output: Path, source_hash: str,
                   supplements: dict | None = None) -> list[dict]:
    by_root = {}
    for package in metadata["packages"]:
        manifest = Path(package["manifest_path"]).resolve()
        root = manifest.parent
        expected_root = source if package["source"] is None else vendor
        release.require(root.is_relative_to(expected_root.resolve()), f"Cargo metadata left the verified source/vendor tree: {package['name']}")
        release.require(root not in by_root, "duplicate Cargo metadata package root")
        by_root[root] = package
    release.require(any(p["name"] == "herdr" for p in by_root.values()), "missing herdr metadata")
    release.require({p.resolve() for p in vendor.iterdir() if p.is_dir()} <= set(by_root), "cargo vendor contains packages absent from locked metadata")
    original_names = {r["path"] for r in original}
    workspace = by_root.get(source.resolve(), {})
    members = set(metadata.get("workspace_members", []))
    result = []
    for root, package in sorted(by_root.items()):
        remote = package["source"] is not None
        relative = root.relative_to(source.resolve()).as_posix() if not remote else root.name
        allowed = None if remote else {p.relative_to(root).as_posix() for name in original_names if (p := source / name).is_relative_to(root)}
        extra, origin = (cargo_supplement(root, package, by_root, supplements) if remote
                         else workspace_license(source.resolve(), root, package, workspace, members, original_names, allowed))
        paths = license_paths(root, allowed=allowed, declared=package.get("license_file"), require_primary=not extra)
        identity = {"name": package["name"], "version": package["version"], "cargo_source": package["source"],
                    "root": relative, "manifest_sha256": deps.sha256_file(root / "Cargo.toml"), **origin}
        if not remote:
            identity["herdr_source_sha256"] = source_hash
        result.append(copy_licenses(root, paths, output, "cargo" if remote else "cargo-path", root.name, identity, extra))
    return result


def zon_hashes(paths: list[Path]) -> set[str]:
    import re
    result = set()
    for path in paths:
        result.update(re.findall(r'^\s*\.hash\s*=\s*"([A-Za-z0-9_.+-]+)"\s*,', path.read_text(encoding="utf-8"), re.M))
    return result


def verify_zig_package(archive: Path, package: Path) -> None:
    actual = deps.tree_manifest(package)
    expected = {package.name + "/" + r["path"]: r for r in actual}
    seen = set()
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream:
            if member.isdir():
                continue
            release.require(member.isfile() and member.name in expected and member.name not in seen, f"unexpected cached Zig archive member: {member.name}")
            item = expected[member.name]
            with stream.extractfile(member) as content:
                release.require(member.size == item["size"] and release.stream_digest(content) == item["sha256"], f"Zig cache differs from compiled package: {member.name}")
            seen.add(member.name)
    release.require(seen == set(expected), "Zig cache does not cover every compiled package file")


def zig_licenses(source: Path, original: list[dict], cache: Path, zig_root: Path, output: Path, platform: str, source_hash: str,
                 supplements: dict | None = None) -> list[dict]:
    ghostty = source / "vendor/libghostty-vt"
    original_names = {r["path"] for r in original}
    prefix = "vendor/libghostty-vt/"
    allowed = {name[len(prefix):] for name in original_names if name.startswith(prefix)}
    result = [copy_licenses(ghostty, license_paths(ghostty, allowed=allowed), output, "vendored", "libghostty-vt", {"herdr_source_sha256": source_hash})]
    result.append(copy_licenses(zig_root, license_paths(zig_root), output, "zig-toolchain", "zig-0.16.0", ZIG_ARCHIVES[platform]))
    packages_root = ghostty / "zig-pkg"
    release.require(packages_root.is_dir() and cache.is_dir(), "missing Zig compiled packages/cache; license completeness cannot be established")
    release.require(not any(name.startswith(prefix + "zig-pkg/") for name in original_names), "pinned source unexpectedly includes an unaudited Zig package cache")
    packages = {p.name: p for p in packages_root.iterdir() if p.is_dir() and not p.is_symlink()}
    release.require(bool(packages) and len(packages) == len(list(packages_root.iterdir())), "invalid Zig compiled package directory")
    release.require({p.name for p in cache.iterdir()} == {name + ".tar.gz" for name in packages}, "Zig package/cache inventory differs")
    hashes = zon_hashes([source / name for name in original_names if name.endswith(".zon")])
    pending = dict(packages)
    while pending:
        reached = set(pending) & hashes
        release.require(bool(reached), "Zig package not reachable from the fixed source .zon hashes")
        for name in sorted(reached):
            package = pending.pop(name)
            cached = cache / (name + ".tar.gz")
            verify_zig_package(cached, package)
            hashes.update(zon_hashes(list(package.rglob("*.zon"))))
            rules = [] if supplements is None else [rule for rule in supplements["data"]["zig"] if rule["package_hash"] == name]
            release.require(len(rules) <= 1, "ambiguous Zig license supplement")
            extra, origin = supplemental_texts(supplements, rules[0]["source"]) if rules else ([], {})
            paths = license_paths(package, require_primary=not extra)
            result.append(copy_licenses(package, paths, output, "zig", name,
                                        {"package_hash": name, "cache_sha256": deps.sha256_file(cached), "herdr_source_sha256": source_hash, **origin}, extra))
    return result


def build(repo: Path, platform: str, work: Path, cache: Path, output: Path) -> dict:
    builder = ci_boundary([work, cache, output], platform)
    release.require(not work.exists() and not output.exists(), "build/output directory exists; never reuse unverified build state")
    release.require(not any(a.resolve().is_relative_to(b.resolve()) for a in (work, cache, output) for b in (work, cache, output) if a != b), "build/cache/output directories must not overlap")
    pinned = release.load_lock(repo)["herdr"]
    work.mkdir(parents=True)
    source = work / "source"
    source_archive = deps.fetch_artifact(pinned["source"], cache)
    deps.extract_archive(source_archive, source, strip=1)
    original = deps.tree_manifest(source)
    zig_archive = deps.fetch_artifact(ZIG_ARCHIVES[platform], cache)
    zig_root = work / "zig"
    deps.extract_archive(zig_archive, zig_root, strip=1)
    zig = zig_root / ("zig.exe" if platform == "windows-x64" else "zig")
    zig.chmod(0o755)
    cargo = shutil.which("cargo")
    rustc = shutil.which("rustc")
    release.require(bool(cargo) and bool(rustc), "install the pinned Rust toolchain first")
    env = os.environ.copy()
    for name in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "CARGO_ENCODED_RUSTFLAGS", "HERDR_BUILD_CHANNEL", "HERDR_BUILD_ID", "LIBGHOSTTY_VT_WINDOWS_LIBC", "LIBGHOSTTY_VT_ZIG_SYSTEM_DIR"):
        env.pop(name, None)
    target = pinned["targets"][platform]
    env.update({
        # 本机 rustup 的默认 host 可能是 GNU：Windows 目标显式选 MSVC 工具链；CI runner 上两者等价。
        # 钉住的工具链缺失时直接失败：不让 rustup 自动下载安装，构建不改动本机工具链。
        "RUSTUP_TOOLCHAIN": pinned["rust"] + ("-" + target if platform == "windows-x64" else ""),
        "RUSTUP_AUTO_INSTALL": "0",
        "CARGO_HOME": str(work / "cargo-home"),
        "CARGO_TARGET_DIR": str(work / "target"), "CARGO_INCREMENTAL": "0",
        "RUSTFLAGS": "-C target-feature=+crt-static", "ZIG": str(zig),
        "ZIG_GLOBAL_CACHE_DIR": str(work / "zig-global-cache"), "ZIG_LOCAL_CACHE_DIR": str(work / "zig-local-cache"),
        "LIBGHOSTTY_VT_OPTIMIZE": "ReleaseFast", "LIBGHOSTTY_VT_SIMD": "true",
        "HERDR_BUILD_COMMIT": pinned["revision"],
        # 包身份编译进 herdr：关闭自更新/渠道切换，--version 显示 gx 包标识。
        "HERDR_PACKAGE_MANAGER": "windows-installer" if platform == "windows-x64" else "deb",
    })
    rust_version = run([rustc, "--version"], source, env, capture=True)
    cargo_version = run([cargo, "--version"], source, env, capture=True)
    release.require(rust_version.split()[1] == pinned["rust"] and cargo_version.split()[1] == pinned["rust"], "Rust/Cargo toolchain does not match the lock")
    release.require(run([str(zig), "version"], source, env, capture=True) == pinned["zig"], "Zig version mismatch")
    vendor = work / "cargo-vendor"
    vendor_config = work / "vendor.toml"
    vendor_config.write_text(run([cargo, "vendor", "--locked", str(vendor)], source, env, capture=True) + "\n", encoding="utf-8")
    vendor_before = deps.tree_manifest(vendor)
    release.require(bool(vendor_before), "cargo vendor produced no dependencies")
    cargo_prefix = [cargo, "--config", str(vendor_config)]
    metadata = json.loads(run(cargo_prefix + ["metadata", "--offline", "--locked", "--format-version", "1"], source, env, capture=True))
    own = [p for p in metadata["packages"] if p["name"] == "herdr" and p["source"] is None]
    release.require(len(own) == 1 and own[0]["version"] == pinned["version"], "herdr Cargo version differs from lock")
    run(cargo_prefix + ["build", "--release", "--locked", "--offline", "--target", target], source, env)
    deps.verify_tree(vendor, vendor_before)
    binary = work / "target" / target / "release" / ("herdr.exe" if platform == "windows-x64" else "herdr")
    deps.check_binary(binary, platform, static=platform == "ubuntu-amd64")
    output.mkdir(parents=True)
    payload = output / "payload"
    if platform == "windows-x64":
        conpty = deps.fetch_artifact(pinned["conpty"]["package"], cache)
        run(["pwsh", "-NoProfile", "-File", str(source / "scripts/package_windows_conpty.ps1"),
             "-HerdrExe", str(binary), "-PackagePath", str(conpty), "-StageDir", str(payload),
             "-OutputPath", str(work / "herdr-windows.zip")], source, env)
        release.require({p["path"] for p in deps.tree_manifest(payload)} == set(pinned["conpty"]["files"]), "ConPTY packaging changed the exact seven-file layout")
        for name, checksum in pinned["conpty"]["files"].items():
            release.require(checksum is None or deps.sha256_file(payload / name) == checksum, f"ConPTY checksum mismatch: {name}")
    else:
        payload.mkdir()
        shutil.copy2(binary, payload / "herdr")
    for item in original:
        path = source / item["path"]
        release.require(path.is_file() and deps.sha256_file(path) == item["sha256"], f"build modified pinned source: {item['path']}")
    redistribution = output / "redistribution"
    redistribution.mkdir()
    shutil.copy2(source_archive, redistribution / source_archive.name)
    archive_tree(vendor, redistribution / "cargo-vendor.tar.xz")
    supplements = load_supplements(repo)
    shutil.copy2(supplements["path"], redistribution / "herdr-license-supplements.json")
    licenses = cargo_licenses(vendor, source, metadata, original, output, pinned["source"]["sha256"], supplements)
    zig_packages = work / "zig-global-cache/p"
    licenses.extend(zig_licenses(source, original, zig_packages, zig_root, output, platform, pinned["source"]["sha256"], supplements))
    archive_tree(zig_packages, redistribution / "zig-packages.tar.xz")
    license_file = redistribution / "license-inventory.json"
    deps.write_json(license_file, {"schema_version": 1, "packages": licenses})
    license_records = [item for package in licenses for item in package["licenses"]]
    release.require(bool(license_records), "license inventory is empty")
    for item in license_records:
        release.require(item["size"] > 0 and deps.sha256_file(output / item["path"]) == item["sha256"], "license text changed before receipt generation")
    instructions = redistribution / "BUILD.json"
    deps.write_json(instructions, {
        "repository": pinned["repository"], "branch_provenance": pinned["branch_provenance"], "revision": pinned["revision"],
        "source": pinned["source"], "rust": rust_version, "cargo": cargo_version, "zig": ZIG_ARCHIVES[platform],
        "zig_checksum_source": "https://ziglang.org/download/index.json", "target": target,
        "argv": ["cargo", "--config", "vendor.toml", "build", "--release", "--locked", "--offline", "--target", target],
        "environment": {k: env[k] for k in ("RUSTFLAGS", "LIBGHOSTTY_VT_OPTIMIZE", "LIBGHOSTTY_VT_SIMD", "HERDR_BUILD_COMMIT", "HERDR_PACKAGE_MANAGER")},
        "rebuild": ["Extract the pinned herdr source ZIP and cargo-vendor.tar.xz into separate directories.",
                    "Configure [source.crates-io] replace-with='vendored-sources'; [source.vendored-sources] directory='<extracted cargo vendor>'.",
                    "Install the recorded Rust target and verified Zig archive; set ZIG to that executable.",
                    "Extract zig-packages.tar.xz into ZIG_GLOBAL_CACHE_DIR/p if present, then use the recorded environment and argv.",
                    "Windows requires MSVC/Windows SDK and dotnet; run the original package_windows_conpty.ps1 with the locked NuGet package. Linux requires musl-tools, CMake and Ninja."],
    })
    receipt = {
        "schema_version": 1, "repository": pinned["repository"], "branch_provenance": pinned["branch_provenance"],
        "revision": pinned["revision"], "version": pinned["version"], "platform": platform, "target": target,
        "builder": builder, "source_sha256": pinned["source"]["sha256"], "rust": pinned["rust"], "zig": pinned["zig"],
        "locked": True, "release": True, "cargo_vendor_complete": True, "conpty_verified": platform == "windows-x64",
        "rustflags": env["RUSTFLAGS"], "effective_crt_static": True, "package_manager": env["HERDR_PACKAGE_MANAGER"],
        "libghostty_vt_optimize": "ReleaseFast", "libghostty_vt_simd": True,
        "files": deps.tree_manifest(payload), "toolchains": {"rust": rust_version, "cargo": cargo_version, "zig": ZIG_ARCHIVES[platform]},
        "source_artifacts": [record(p, output) for p in sorted(redistribution.iterdir()) if p.is_file()],
        "license_artifacts": license_records, "license_inventory": licenses, "zig_dependencies_complete": True,
    }
    deps.write_json(output / "herdr-build.json", receipt)
    deps.verify_herdr(deps.load_lock(repo / "scripts/packaging/dependencies.json"), platform, output)
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fixed-source herdr build on a disposable CI runner, or a non-publishable local build "
                                                 "under GX_LOCAL_BUILD_ROOT. Never modifies a local user toolchain or publishes.")
    parser.add_argument("--repo", type=Path, default=release.ROOT)
    parser.add_argument("--platform", choices=tuple(release.TARGETS), required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = build(args.repo.resolve(), args.platform, args.work.resolve(), args.cache.resolve(), args.output.resolve())
        print(json.dumps({"revision": receipt["revision"], "target": receipt["target"], "output": str(args.output)}))
        return 0
    except (ValueError, OSError, KeyError, IndexError, subprocess.CalledProcessError) as error:
        print(f"gx-build-herdr: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
