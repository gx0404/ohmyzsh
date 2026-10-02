#!/usr/bin/env python3
from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gx_dependencies as deps
import gx_build_zsh as zsh


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact(cache: Path, name: str, data: bytes) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    (cache / name).write_bytes(data)
    return {"filename": name, "sha256": digest(data), "url": "https://example.org/fixtures/" + name}


def elf_binary() -> bytes:
    data = bytearray(120)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", data, 18, 62)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, 1)
    struct.pack_into("<I", data, 64, 1)
    return bytes(data)


def pe_binary() -> bytes:
    data = bytearray(128)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<H", data, 68, 0x8664)
    return bytes(data)


def tar_bytes(entries: dict[str, bytes], links: dict[str, str] | None = None) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for name, content in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755 if name.endswith((".exe", "herdr")) else 0o644
            archive.addfile(info, io.BytesIO(content))
        for name, target in (links or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            archive.addfile(info)
    return out.getvalue()


def zsh_fixture(root: Path) -> dict:
    cache = root / "cache"
    source = artifact(cache, "zsh-fixture-source.tar.gz", tar_bytes({"zsh/source.c": b"fixture source"}))
    patch = artifact(cache, "zsh-fixture.patch", b"fixture patch, not real Zsh\n")
    modules = artifact(cache, "fixture.config.modules", b"name=zsh/main link=static auto=yes load=yes\n")
    stage = root / "zsh-stage"
    (stage / "libexec/zsh").mkdir(parents=True)
    (stage / "libexec/zsh/zsh").write_bytes(elf_binary())
    (stage / "share/zsh/functions").mkdir(parents=True)
    (stage / "share/zsh/functions/compinit").write_bytes(b"fixture completion\n")
    (stage / "share/licenses/zsh").mkdir(parents=True)
    (stage / "share/licenses/zsh/LICENCE").write_bytes(b"fixture Zsh license\n")
    options = {"modules": modules, "patches": [], "post_gx_source_sha256": {"source.c": digest(b"patched fixture")}, "allowed_needed": []}
    pinned = {"schema_version": 1, "version": "5.9.2+gx-metafied-paths", "source": source, "gx_patch": patch,
              "license_sha256": digest(b"fixture Zsh license\n"), "functions_canonical_sha256": deps.canonical_digest(deps.tree_manifest(stage / "share/zsh/functions")),
              "platforms": {platform: copy.deepcopy(options) for platform in deps.PLATFORMS}}
    deps.write_json(root / "zsh-runtime-lock.json", pinned)
    evidence = {"source_sha256": source["sha256"], "gx_patch_sha256": patch["sha256"], "static_modules": True,
                "modules_sha256": modules["sha256"], "fuzz_allowed": 0, "post_gx_source_sha256": options["post_gx_source_sha256"],
                "binary_sha256": digest(elf_binary()), "tools": {"compiler": "unit fixture only"}, "commands": ["fixture generation"],
                "build_provenance": "unit-fixture-not-runtime-acceptance"}
    zsh.record_build(pinned, "ubuntu-amd64", stage, cache, root / "zsh-build", evidence)
    return {"file": "zsh-runtime-lock.json", "canonical_sha256": deps.canonical_digest(pinned)}


def fixture(root: Path) -> tuple[dict, Path, Path]:
    cache = root / "cache"
    zsh_lock = zsh_fixture(root)
    source = artifact(cache, "herdr-source.tar.gz", tar_bytes({"herdr/Cargo.toml": b"fixture"}))
    license_file = artifact(cache, "fixture-LICENSE.txt", b"Fixture only; not an actual third-party license.\n")
    instructions = artifact(cache, "fixture-build.txt", b"Fixture only; no production executable.\n")
    lock = {
        "schema_version": 1,
        "herdr": {
            "repository": "https://github.com/gx0404/herdr", "revision": "e9f6c994c49410d784f0a53ea725605b78515300",
            "version": "0.9.1", "source": source, "rust": "1.96.1", "zig": "0.16.0",
            "targets": {"ubuntu-amd64": "x86_64-unknown-linux-musl", "windows-x64": "x86_64-pc-windows-msvc"},
        },
        "assets": [], "unresolved": [], "zsh_runtime": zsh_lock,
        "components": [{"id": "herdr", "version": "0.9.1", "platforms": list(deps.PLATFORMS), "licenses": [license_file], "sources": [source], "build_instructions": [instructions]}],
        "required_payload": {"ubuntu-amd64": ["lib/herdr/herdr"]},
    }
    deps.write_json(root / "dependencies.json", lock)
    lock = deps.load_lock(root / "dependencies.json")
    build = root / "herdr-build"
    (build / "payload").mkdir(parents=True)
    (build / "payload/herdr").write_bytes(elf_binary())
    (build / "payload/herdr").chmod(0o755)
    (build / "vendor.tar.gz").write_bytes(b"not real vendored sources; fixture only")
    (build / "licenses.txt").write_bytes(b"fixture licenses")
    receipt = {
        "schema_version": 1, "platform": "ubuntu-amd64", "revision": lock["herdr"]["revision"], "version": "0.9.1",
        "target": "x86_64-unknown-linux-musl", "source_sha256": source["sha256"],
        "rust": "1.96.1", "zig": "0.16.0", "locked": True, "release": True, "cargo_vendor_complete": True,
        "files": deps.tree_manifest(build / "payload"),
        "source_artifacts": [{"path": "vendor.tar.gz", "sha256": deps.sha256_file(build / "vendor.tar.gz")}],
        "license_artifacts": [{"path": "licenses.txt", "sha256": deps.sha256_file(build / "licenses.txt")}],
    }
    deps.write_json(build / "herdr-build.json", receipt)
    return lock, cache, build


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gx-deps-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_real_lock_has_authenticated_142_package_closure(self):
        lock = deps.load_lock()
        packages = lock["msys2_data"]["packages"]
        self.assertEqual(len(packages), 142)
        self.assertEqual(sum(p["origin"] == "signed-base" for p in packages), 84)
        self.assertEqual(sum(p["origin"] == "signed-package" for p in packages), 58)
        self.assertEqual(lock["herdr"]["version"], "0.9.3")

    def test_msys_runtime_is_the_hang_fixed_release_over_the_base_snapshot(self):
        lock = deps.load_lock()
        runtime = next(p for p in lock["msys2_data"]["packages"] if p["name"] == "msys2-runtime")
        self.assertEqual((runtime["version"], runtime["origin"], runtime["upgrades_base"]), ("3.6.10-6", "signed-package", "3.6.10-5"))
        component = next(c for c in lock["msys2_data"]["components"] if c["id"] == "msys2-msys2-runtime")
        self.assertEqual(component["sources"][0]["filename"], "msys2-runtime-3.6.10-6.src.tar.zst")
        devel = next(p for p in lock["zsh_data"]["windows_toolchain"]["packages"] if p["name"] == "msys2-runtime-devel")
        self.assertEqual(devel["version"], runtime["version"])

    def test_linux_learner_tools_are_signed_packages_with_corresponding_sources(self):
        msys = deps.load_lock()["msys2_data"]
        packages = {p["name"]: p for p in msys["packages"]}
        owners = {p["name"]: c for c in msys["components"] for p in c["runtime_packages"]}
        added = {"diffutils", "patch", "unzip", "zip", "tree", "bc", "procps-ng", "vim", "rsync", "jq", "libxxhash", "popt", "oniguruma"}
        database = [d for d in msys["signed_databases"] if d.get("packages")]
        self.assertEqual(len(database), 1)
        self.assertEqual(set(database[0]["packages"]), added | {"msys2-runtime"})
        for name in sorted(added):
            with self.subTest(package=name):
                package, component = packages[name], owners[name]
                self.assertEqual(package["origin"], "signed-package")
                self.assertTrue(package["url"].startswith("https://repo.msys2.org/msys/x86_64/"))
                self.assertEqual(package["signature_url"], package["url"] + ".sig")
                self.assertEqual(component["id"], "msys2-" + package["base"])
                self.assertEqual(component["version"], package["version"])
                self.assertEqual([s["filename"] for s in component["sources"]],
                                 [f"{package['base']}-{package['version']}.src.tar.zst", f"{package['base']}-{package['version']}.src.tar.zst.sig"])
                self.assertEqual(component["licenses"][0]["repository_path"], f"notices/msys2/{package['base']}-{package['version']}-LICENSES.txt")
                self.assertTrue(component["verification"]["source_members"])

    def test_runtime_overlay_mounts_tmp_and_takes_home_from_environment(self):
        msys = deps.load_lock()["msys2_data"]
        overlay = {entry["path"]: artifact for entry, artifact in deps.msys_overlay(msys)}
        self.assertEqual(set(overlay), {"etc/fstab", "etc/nsswitch.conf"})
        text = {name: deps.inside(deps.DEFAULT_LOCK.parent, item["repository_path"]).read_text(encoding="utf-8").splitlines()
                for name, item in overlay.items()}
        self.assertIn("none / cygdrive binary,posix=0,noacl,user 0 0", text["etc/fstab"])
        self.assertIn("none /tmp usertemp binary,posix=0,noacl 0 0", text["etc/fstab"])
        self.assertEqual([line for line in text["etc/nsswitch.conf"] if line.startswith("db_home:")], ["db_home: env windows cygwin desc"])
        self.assertFalse(deps.excluded_runtime("etc/fstab"))
        self.assertEqual({c["path"] for c in deps.msys_overlay_changes(msys)}, {"runtime/msys64/etc/fstab", "runtime/msys64/etc/nsswitch.conf"})

    def msys_overlay_fixture(self, original: bytes) -> dict:
        cache = self.root / "cache"
        base = artifact(cache, "base.tar.gz", tar_bytes({"msys64/etc/fstab": original, "msys64/usr/bin/msys-2.0.dll": pe_binary(), "msys64/tmp/state": b"state"}))
        package = {**artifact(cache, "tool.pkg.tar.gz", tar_bytes({"usr/bin/tool.exe": pe_binary()})), "origin": "signed-package"}
        modified = artifact(cache, "GX-msys2-etc-fstab", b"none / cygdrive binary 0 0\nnone /tmp usertemp binary 0 0\n")
        return {"base": base, "packages": [package], "components": [{"id": "msys2-filesystem", "sources": [modified]}],
                "overlay": [{"component": "msys2-filesystem", "filename": modified["filename"], "old_sha256": digest(b"stock fstab\n"),
                             "path": "etc/fstab", "sha256": modified["sha256"]}]}

    def test_assembled_runtime_carries_overlay_only_over_the_pinned_original(self):
        msys = self.msys_overlay_fixture(b"stock fstab\n")
        runtime = self.root / "runtime"
        (self.root / "work").mkdir()
        upgrades, changes = deps.assemble_msys_runtime(msys, self.root / "cache", runtime, self.root / "work")
        self.assertEqual(upgrades, [])
        self.assertEqual((runtime / "etc/fstab").read_bytes(), b"none / cygdrive binary 0 0\nnone /tmp usertemp binary 0 0\n")
        self.assertEqual(changes, [{"path": "runtime/msys64/etc/fstab", "old_sha256": digest(b"stock fstab\n"),
                                    "new_sha256": msys["overlay"][0]["sha256"], "action": "replaced"}])
        self.assertTrue((runtime / "usr/bin/tool.exe").is_file())
        self.assertFalse((runtime / "tmp").exists())
        msys = self.msys_overlay_fixture(b"upstream changed fstab\n")
        (self.root / "work-changed").mkdir()
        with self.assertRaisesRegex(deps.DependencyError, "differs before GX overlay"):
            deps.assemble_msys_runtime(msys, self.root / "cache", self.root / "changed", self.root / "work-changed")

    def test_overlay_entry_must_replace_one_file_with_a_locked_component_source(self):
        msys = self.msys_overlay_fixture(b"stock fstab\n")
        entry = msys["overlay"][0]
        for broken in ({**entry, "sha256": "0" * 64}, {**entry, "filename": "missing"}, {**entry, "component": "msys2-other"},
                       {**entry, "old_sha256": None}, {**entry, "path": "etc/passwd"}, {**entry, "path": "../fstab"}):
            with self.subTest(broken=broken), self.assertRaises(deps.DependencyError):
                deps.msys_overlay({**msys, "overlay": [broken]})
        with self.assertRaisesRegex(deps.DependencyError, "etc/fstab"):
            deps.msys_overlay({**msys, "overlay": [entry, entry]})

    def base_upgrade_fixture(self, doc: bytes = b"old doc", upgrades: str | None = "1.0-1") -> dict:
        # 旧版登记三个文件（含空格和中文名、一个符号链接），另列两个解包时本就跳过的路径。
        cache = self.root / "cache"
        local = "msys64/var/lib/pacman/local/msys2-runtime-1.0-1/"
        listed = ["usr/", "usr/bin/", "usr/bin/msys-2.0.dll", "usr/share/doc/a b中.txt", "usr/bin/alias.exe", "etc/passwd", "usr/lib/py/__pycache__/m.pyc"]
        mtree = ["#mtree", "/set type=file mode=644", f"./.PKGINFO size=1 sha256digest={digest(b'x')}", "./usr/bin time=1 type=dir",
                 f"./usr/bin/msys-2.0.dll sha256digest={digest(b'old dll')}", f"./usr/share/doc/a\\040b\\344\\270\\255.txt sha256digest={digest(b'old doc')}",
                 "./usr/bin/alias.exe type=link link=msys-2.0.dll", f"./etc/passwd sha256digest={digest(b'p')}"]
        base = artifact(cache, "base.tar.gz", tar_bytes(
            {"msys64/usr/bin/msys-2.0.dll": b"old dll", "msys64/usr/share/doc/a b中.txt": doc, local + "desc": b"%NAME%\nmsys2-runtime\n",
             local + "files": ("%FILES%\n" + "\n".join(listed) + "\n\n").encode(), local + "mtree": gzip.compress(("\n".join(mtree) + "\n").encode())},
            {"msys64/usr/bin/alias.exe": "msys-2.0.dll"}))
        package = {**artifact(cache, "msys2-runtime-1.0-2.pkg.tar.gz", tar_bytes({"usr/bin/msys-2.0.dll": b"new dll", "usr/share/doc/a b中.txt": b"new doc"},
                                                                                 {"usr/bin/alias.exe": "msys-2.0.dll"})),
                   "name": "msys2-runtime", "origin": "signed-package", "version": "1.0-2"}
        if upgrades:
            package["upgrades_base"] = upgrades
        return {"base": base, "packages": [package], "components": []}

    def test_signed_package_replaces_its_recorded_base_version_only(self):
        def assemble(name: str, msys: dict) -> tuple[Path, list]:
            (self.root / f"work-{name}").mkdir()
            upgrades, _ = deps.assemble_msys_runtime(msys, self.root / "cache", self.root / name, self.root / f"work-{name}")
            return self.root / name, upgrades
        runtime, upgrades = assemble("upgraded", self.base_upgrade_fixture())
        self.assertEqual(upgrades, [{"name": "msys2-runtime", "old_version": "1.0-1", "new_version": "1.0-2", "removed_files": 3}])
        for name, content in (("usr/bin/msys-2.0.dll", b"new dll"), ("usr/share/doc/a b中.txt", b"new doc"), ("usr/bin/alias.exe", b"new dll")):
            self.assertEqual((runtime / name).read_bytes(), content)
        self.assertFalse((runtime / "var/lib/pacman/local/msys2-runtime-1.0-1").exists())
        for name, doc, upgrades, error in (("tampered", b"changed doc", "1.0-1", "differs from its pacman record before upgrade: usr/share/doc/a b中.txt"),
                                           ("plain", b"old doc", None, "install collision"),
                                           ("absent", b"old doc", "9.9-9", "does not contain msys2-runtime 9.9-9")):
            with self.subTest(name=name), self.assertRaisesRegex(deps.DependencyError, error):
                assemble(name, self.base_upgrade_fixture(doc, upgrades))
        self.assertEqual((self.root / "tampered/usr/bin/msys-2.0.dll").read_bytes(), b"old dll")
        msys = copy.deepcopy(deps.load_lock()["msys2_data"])
        next(p for p in msys["packages"] if p["origin"] == "signed-base")["upgrades_base"] = "1.0-1"
        with self.assertRaisesRegex(deps.DependencyError, "only a signed package"):
            deps.validate_msys(msys)

    def test_mtree_paths_are_byte_escapes_decoded_as_utf8(self):
        records = deps.mtree_records("/set type=file\n./a\\040b\\344\\270\\255.txt sha256digest=aa\n./l type=link link=x\\040y\n")
        self.assertEqual(records, {"a b中.txt": {"type": "file", "sha256digest": "aa"}, "l": {"type": "link", "link": "x y"}})

    def test_windows_bundle_check_rejects_changed_msys_overlay_or_upgrade_record(self):
        msys = self.msys_overlay_fixture(b"stock fstab\n")
        msys["packages"][0].update(name="msys2-runtime", version="1.0-2", upgrades_base="1.0-1")
        payload = self.root / "payload"
        (payload / "runtime/msys64/etc").mkdir(parents=True)
        (payload / "runtime/msys64/etc/fstab").write_bytes(b"none / cygdrive binary 0 0\nnone /tmp usertemp binary 0 0\n")
        manifest = {"msys2_upgrades": [{"name": "msys2-runtime", "old_version": "1.0-1", "new_version": "1.0-2", "removed_files": 162}],
                    "msys2_overlay": deps.msys_overlay_changes(msys)}
        deps.verify_msys_runtime(msys, manifest, payload)
        upgrade = manifest["msys2_upgrades"][0]
        for broken, error in (({**manifest, "msys2_upgrades": []}, "base upgrade provenance"),
                              ({**manifest, "msys2_upgrades": [{**upgrade, "removed_files": 0}]}, "base upgrade provenance"),
                              ({**manifest, "msys2_upgrades": [{**upgrade, "old_version": "1.0-0"}]}, "base upgrade provenance"),
                              ({**manifest, "msys2_overlay": []}, "overlay provenance")):
            with self.subTest(error=error, broken=broken), self.assertRaisesRegex(deps.DependencyError, error):
                deps.verify_msys_runtime(msys, broken, payload)
        leftover = payload / "runtime/msys64/var/lib/pacman/local/msys2-runtime-1.0-1"
        leftover.mkdir(parents=True)
        with self.assertRaisesRegex(deps.DependencyError, "record leaked"):
            deps.verify_msys_runtime(msys, manifest, payload)
        leftover.rmdir()
        (payload / "runtime/msys64/etc/fstab").write_bytes(b"none / cygdrive binary 0 0\n")
        with self.assertRaisesRegex(deps.DependencyError, "differs from the lock: runtime/msys64/etc/fstab"):
            deps.verify_msys_runtime(msys, manifest, payload)

    def test_redistribution_herdr_version_must_match_the_locked_herdr(self):
        fixture(self.root)
        lock = deps.read_json(self.root / "dependencies.json")
        lock["components"][0]["version"] = "0.9.0"
        deps.write_json(self.root / "dependencies.json", lock)
        with self.assertRaisesRegex(deps.DependencyError, "redistribution herdr version 0.9.0 differs from the locked herdr 0.9.1"):
            deps.load_lock(self.root / "dependencies.json")

    def test_production_redistribution_complete_and_missing_sources_fail_closed(self):
        lock = deps.load_lock()
        self.assertEqual(deps.compliance_errors(lock, "windows-x64"), [])
        self.assertEqual(deps.compliance_errors(lock, "ubuntu-amd64"), [])
        self.assertEqual(len(lock["msys2_data"]["components"]), 127)
        lock["components"][0]["sources"] = []
        with self.assertRaisesRegex(deps.DependencyError, "release inputs incomplete"):
            deps.verify_inputs(lock, "windows-x64", self.root)

    def test_hash_mismatch_never_overwrites_cached_file(self):
        item = artifact(self.root, "input.zip", b"good")
        (self.root / "input.zip").write_bytes(b"bad")
        with self.assertRaisesRegex(deps.DependencyError, "SHA-256 mismatch"):
            deps.fetch_artifact(item, self.root)
        self.assertEqual((self.root / "input.zip").read_bytes(), b"bad")

    def test_missing_and_unpinned_artifacts_fail(self):
        item = {"filename": "missing", "sha256": digest(b"missing"), "url": "https://example.org/missing"}
        with self.assertRaisesRegex(deps.DependencyError, "missing cached"):
            deps.verify_artifact(item, self.root)
        item["sha256"] = None
        with self.assertRaises((deps.DependencyError, TypeError)):
            deps.artifact_shape(item)

    def test_transport_and_filename_validation(self):
        item = artifact(self.root, "input", b"good")
        for url in ("http://example.org/input", "https://user:password@example.org/input", "file:///tmp/input"):
            with self.subTest(url=url), self.assertRaises(deps.DependencyError):
                deps.artifact_shape({**item, "url": url})
        with self.assertRaises(deps.DependencyError):
            deps.artifact_shape({**item, "filename": "../escape"})

    def test_private_and_escaping_paths(self):
        for name in ("../escape", "/etc/passwd", "C:/escape", "a\\b", ".env", "a/.git/config", "gx/config/zshrc.local"):
            with self.subTest(name=name), self.assertRaises(deps.DependencyError):
                deps.relative_path(name)

    def test_tar_traversal_is_rejected_without_escape(self):
        archive = self.root / "bad.tar.gz"
        archive.write_bytes(tar_bytes({"../escape": b"bad"}))
        with self.assertRaises(deps.DependencyError):
            deps.extract_archive(archive, self.root / "output")
        self.assertFalse((self.root / "escape").exists())

    def test_strip_does_not_hide_archive_traversal(self):
        archive = self.root / "bad.tar.gz"
        archive.write_bytes(tar_bytes({"../escape": b"bad"}))
        with self.assertRaises(deps.DependencyError):
            deps.extract_archive(archive, self.root / "output", strip=1)

    def test_runtime_state_is_not_materialized(self):
        archive = self.root / "runtime.tar.gz"
        archive.write_bytes(tar_bytes({"msys64/usr/bin/zsh.exe": pe_binary(), "msys64/home/user/.history": b"state", "msys64/var/cache/pacman/pkg/cache": b"state", "msys64/etc/pacman.d/gnupg/private": b"state", "msys64/usr/lib/__pycache__/test.pyc": b"cache"}))
        output = self.root / "runtime"
        deps.extract_archive(archive, output, strip=1, runtime=True)
        self.assertEqual([x["path"] for x in deps.tree_manifest(output)], ["usr/bin/zsh.exe"])

    def test_safe_file_symlink_is_materialized(self):
        archive = self.root / "links.tar.gz"
        archive.write_bytes(tar_bytes({"root/bin/target": b"data"}, {"root/bin/alias": "target"}))
        deps.extract_archive(archive, self.root / "output", strip=1)
        self.assertEqual((self.root / "output/bin/alias").read_bytes(), b"data")
        self.assertFalse((self.root / "output/bin/alias").is_symlink())

    def test_unsafe_link_is_rejected(self):
        archive = self.root / "links.tar.gz"
        archive.write_bytes(tar_bytes({}, {"root/link": "../../escape"}))
        with self.assertRaises(deps.DependencyError):
            deps.extract_archive(archive, self.root / "output", strip=1)

    def test_zip_case_collision_is_rejected(self):
        archive = self.root / "case.zip"
        with zipfile.ZipFile(archive, "w") as out:
            out.writestr("File", "first")
            out.writestr("file", "second")
        with self.assertRaises(deps.DependencyError):
            deps.extract_archive(archive, self.root / "output")

    def test_tree_mutation_and_extra_file_fail(self):
        (self.root / "a").write_bytes(b"a")
        manifest = deps.tree_manifest(self.root)
        (self.root / "b").write_bytes(b"b")
        with self.assertRaisesRegex(deps.DependencyError, "extra"):
            deps.verify_tree(self.root, manifest)

    def test_wrong_architecture_and_dynamic_elf_fail(self):
        binary = self.root / "program"
        binary.write_bytes(pe_binary())
        with self.assertRaises(deps.DependencyError):
            deps.check_binary(binary, "ubuntu-amd64")
        data = bytearray(elf_binary())
        struct.pack_into("<I", data, 64, 3)
        binary.write_bytes(data)
        with self.assertRaisesRegex(deps.DependencyError, "dynamic interpreter"):
            deps.check_binary(binary, "ubuntu-amd64", static=True)

    def test_fixture_assembly_is_offline_and_inventory_verified(self):
        lock, cache, build = fixture(self.root)
        output = self.root / "bundle"
        manifest = deps.assemble(lock, "ubuntu-amd64", cache, output, build, zsh_build=build.parent / "zsh-build")
        self.assertTrue(manifest["compliance_complete"])
        deps.verify_bundle(lock, "ubuntu-amd64", output)
        self.assertTrue((output / "redistribution/herdr/vendor.tar.gz").is_file())
        self.assertEqual((output / "payload/lib/herdr/herdr").read_bytes(), elf_binary())

    def test_existing_output_is_preserved(self):
        lock, cache, build = fixture(self.root)
        output = self.root / "existing"
        output.mkdir()
        (output / "user-data").write_text("keep")
        with self.assertRaisesRegex(deps.DependencyError, "already exists"):
            deps.assemble(lock, "ubuntu-amd64", cache, output, build, zsh_build=build.parent / "zsh-build")
        self.assertEqual((output / "user-data").read_text(), "keep")

    def test_wrong_fork_receipt_and_missing_sources_fail(self):
        lock, _, build = fixture(self.root)
        receipt = deps.read_json(build / "herdr-build.json")
        receipt["revision"] = "1" * 40
        deps.write_json(build / "herdr-build.json", receipt)
        with self.assertRaisesRegex(deps.DependencyError, "revision mismatch"):
            deps.verify_herdr(lock, "ubuntu-amd64", build)
        receipt["revision"] = lock["herdr"]["revision"]
        receipt["source_artifacts"] = []
        deps.write_json(build / "herdr-build.json", receipt)
        with self.assertRaisesRegex(deps.DependencyError, "complete dependency sources"):
            deps.verify_herdr(lock, "ubuntu-amd64", build)

    def test_dependency_closure_cannot_drop_a_provider(self):
        msys = copy.deepcopy(deps.load_lock()["msys2_data"])
        msys["packages"] = [p for p in msys["packages"] if p["name"] != "bash"]
        with self.assertRaisesRegex(deps.DependencyError, "closure incomplete"):
            deps.validate_msys(msys)

    def test_crlf_json_checkout_has_same_canonical_lock_digest(self):
        expected = deps.load_lock()
        for name in ("dependencies.json", "msys2-lock.json", "redistribution-lock.json", "zsh-runtime-lock.json"):
            data = (deps.DEFAULT_LOCK.parent / name).read_bytes().replace(b"\r\n", b"\n")
            (self.root / name).write_bytes(data.replace(b"\n", b"\r\n"))
        self.assertEqual(deps.load_lock(self.root / "dependencies.json", repository=deps.ROOT)["lock_digest"], expected["lock_digest"])

    def independent_source(self) -> dict:
        commit = "a" * 40
        return {
            "filename": f"herdr-{commit}.zip", "sha256": "b" * 64, "size": 1,
            "git_repository": "https://github.com/gx0404/herdr", "commit": commit,
            "prefix": f"herdr-{commit}/",
        }

    def test_independent_git_source_requires_a_full_commit_and_prefix(self):
        item = self.independent_source()
        deps.artifact_shape(item)
        for broken in (
            {**item, "url": "https://example.org/herdr.zip"},
            {**item, "commit": "a" * 39},
            {**item, "prefix": "herdr/"},
            {**item, "git_repository": "https://github.com/gx0404/gx_shell"},
        ):
            with self.subTest(broken=broken), self.assertRaises(deps.DependencyError):
                deps.artifact_shape(broken)

    def test_monorepo_source_is_rejected(self):
        commit = "a" * 40
        item = {"filename": f"herdr-{commit}.zip", "sha256": "b" * 64,
                "monorepo_path": "herdr", "commit": commit}
        with self.assertRaisesRegex(deps.DependencyError, "independent"):
            deps.artifact_shape(item)

    def test_checked_in_lock_uses_independent_herdr_source(self):
        lock = deps.load_lock()
        self.assertEqual(lock["herdr"]["repository"], "https://github.com/gx0404/herdr")
        self.assertEqual(lock["herdr"]["branch_provenance"], "feature/gx_herdr")
        self.assertEqual(lock["herdr"]["revision"], lock["herdr"]["source"]["commit"])
        self.assertEqual(lock["herdr"]["source"]["url"],
                         lock["herdr"]["repository"] + "/archive/" + lock["herdr"]["revision"] + ".zip")
        self.assertNotIn("git_repository", lock["herdr"]["source"])

    def test_reserved_windows_paths_are_rejected(self):
        for name in ("a/NUL", "a/COM1.txt", "file.", "file "):
            with self.subTest(name=name), self.assertRaises(deps.DependencyError):
                deps.relative_path(name)

    def test_repository_notice_is_verified_and_crlf_normalized(self):
        packaging = self.root / "packaging"
        (packaging / "notices").mkdir(parents=True)
        source = packaging / "notices/NOTICE.txt"
        source.write_bytes(b"copyright\r\npermission\r\n")
        item = {"filename": "NOTICE.txt", "repository_path": "notices/NOTICE.txt", "sha256": digest(b"copyright\npermission\n")}
        cached = deps.fetch_artifact(item, self.root / "cache", packaging)
        self.assertEqual(cached.read_bytes(), b"copyright\npermission\n")
        source.write_bytes(b"changed")
        with self.assertRaisesRegex(deps.DependencyError, "SHA-256 mismatch"):
            deps.fetch_artifact(item, self.root / "other-cache", packaging)
        with self.assertRaises(deps.DependencyError):
            deps.artifact_shape({**item, "repository_path": "../outside"})

    def test_gpl_cannot_claim_permissive_source_exemption(self):
        lock, _, _ = fixture(self.root)
        component = lock["components"][0]
        component.update(license_expression="GPL-3.0-or-later", sources=[], source_policy={"kind": "not-required", "basis": "unsupported claim"})
        self.assertTrue(any("exemption" in error for error in deps.compliance_errors(lock, "ubuntu-amd64")))
        component["license_expression"] = "OFL-1.1"
        component["source_policy"]["basis"] = "Exact OFL grant has no corresponding-source delivery condition."
        self.assertEqual(deps.compliance_errors(lock, "ubuntu-amd64"), [])
        component["licenses"] = []
        self.assertTrue(any("licenses" in error for error in deps.compliance_errors(lock, "ubuntu-amd64")))

    def test_production_repository_notice_hashes_match_real_material(self):
        lock = deps.load_lock()
        for item in deps.all_artifacts(lock, "windows-x64"):
            if "repository_path" in item:
                content = deps.inside(deps.DEFAULT_LOCK.parent, item["repository_path"]).read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(digest(content), item["sha256"], item["filename"])
                self.assertGreater(len(content.strip()), 50, item["filename"])

    def test_msys_corresponding_sources_cover_exact_versions_and_signer(self):
        lock = deps.load_lock()
        components = lock["msys2_data"]["components"]
        covered = [(p["name"], p["version"]) for c in components for p in c["runtime_packages"]]
        self.assertEqual(len(covered), len(set(covered)))
        self.assertEqual(len(covered), 142)
        for component in components:
            self.assertEqual(component["verification"]["signature_signer"], "5F944B027F7FE2091985AA2EFA11531AA0AA7F57")
            self.assertTrue(component["sources"][0]["filename"].endswith(".src.tar.zst"))
            self.assertTrue(component["build_instructions"][0]["filename"].endswith("-PKGBUILD.txt"))

    def test_manifest_cannot_omit_locked_dependency_records(self):
        lock, cache, build = fixture(self.root)
        bundle = self.root / "bundle"
        deps.assemble(lock, "ubuntu-amd64", cache, bundle, build, zsh_build=build.parent / "zsh-build")
        manifest = deps.read_json(bundle / "dependencies-manifest.json")
        manifest["artifacts"] = []
        deps.write_json(bundle / "dependencies-manifest.json", manifest)
        with self.assertRaisesRegex(deps.DependencyError, "complete locked input set"):
            deps.verify_bundle(lock, "ubuntu-amd64", bundle)

    def test_manifest_cannot_claim_an_unlocked_msys_overlay(self):
        lock, cache, build = fixture(self.root)
        bundle = self.root / "bundle"
        deps.assemble(lock, "ubuntu-amd64", cache, bundle, build, zsh_build=build.parent / "zsh-build")
        manifest = deps.read_json(bundle / "dependencies-manifest.json")
        self.assertEqual(manifest["msys2_overlay"], [])
        manifest["msys2_overlay"] = [{"path": "runtime/msys64/etc/fstab", "old_sha256": "0" * 64, "new_sha256": "1" * 64, "action": "replaced"}]
        deps.write_json(bundle / "dependencies-manifest.json", manifest)
        with self.assertRaisesRegex(deps.DependencyError, "MSYS2 overlay provenance"):
            deps.verify_bundle(lock, "ubuntu-amd64", bundle)

    def test_windows_conpty_seven_file_contract_and_signature_receipt(self):
        lock, _, build = fixture(self.root)
        (build / "payload/herdr").unlink()
        pinned_names = deps.load_lock()["herdr"]["conpty"]["files"]
        hashes = {}
        for name in pinned_names:
            path = build / "payload" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(pe_binary() if name.endswith((".exe", ".dll")) else b"fixture notice or marker")
            hashes[name] = None if name == "herdr.exe" else deps.sha256_file(path)
        lock["herdr"]["conpty"] = {"files": hashes}
        receipt = deps.read_json(build / "herdr-build.json")
        receipt.update(platform="windows-x64", target="x86_64-pc-windows-msvc", conpty_verified=True, files=deps.tree_manifest(build / "payload"))
        deps.write_json(build / "herdr-build.json", receipt)
        self.assertEqual(len(deps.verify_herdr(lock, "windows-x64", build)["files"]), 7)
        receipt["conpty_verified"] = False
        deps.write_json(build / "herdr-build.json", receipt)
        with self.assertRaisesRegex(deps.DependencyError, "Authenticode"):
            deps.verify_herdr(lock, "windows-x64", build)
        receipt["conpty_verified"] = True
        deps.write_json(build / "herdr-build.json", receipt)
        (build / "payload/conpty/arm64/OpenConsole.exe").unlink()
        with self.assertRaisesRegex(deps.DependencyError, "inventory mismatch"):
            deps.verify_herdr(lock, "windows-x64", build)

    def test_missing_zsh_receipt_is_not_an_unpatched_fallback(self):
        lock, cache, build = fixture(self.root)
        with self.assertRaisesRegex(deps.DependencyError, "--zsh-build is required"):
            deps.assemble(lock, "ubuntu-amd64", cache, self.root / "output", build)
        self.assertFalse((self.root / "output").exists())

    def test_static_module_claim_and_patch_must_match_source_lock(self):
        lock, _, _ = fixture(self.root)
        build = self.root / "zsh-build"
        receipt = deps.read_json(build / "zsh-build.json")
        for field, bad in (("static_modules", False), ("gx_patch_sha256", "0" * 64), ("modules_sha256", "0" * 64)):
            modified = {**receipt, field: bad}
            with self.subTest(field=field), self.assertRaisesRegex(deps.DependencyError, "mismatch"):
                zsh.verify_receipt(lock["zsh_data"], "ubuntu-amd64", build, receipt=modified)

    def test_zsh_old_binary_or_missing_license_is_rejected(self):
        lock, _, _ = fixture(self.root)
        build = self.root / "zsh-build"
        (build / "payload/libexec/zsh/zsh.old").write_bytes(elf_binary())
        with self.assertRaisesRegex(deps.DependencyError, "inventory mismatch"):
            zsh.verify_receipt(lock["zsh_data"], "ubuntu-amd64", build)
        (build / "payload/libexec/zsh/zsh.old").unlink()
        (build / "redistribution/ZSH-LICENCE.txt").unlink()
        with self.assertRaisesRegex(deps.DependencyError, "license asset missing"):
            zsh.verify_receipt(lock["zsh_data"], "ubuntu-amd64", build)

    def test_linux_zsh_max_glibc_is_2_31_not_host_version(self):
        pinned = zsh.load_lock()
        abi = {"format": "ELF64", "machine": "x86_64", "interpreter": "/lib64/ld-linux-x86-64.so.2", "needed": ["libc.so.6"], "maximum_glibc": "2.31"}
        zsh.validate_abi(abi, "ubuntu-amd64", pinned)
        with self.assertRaisesRegex(deps.DependencyError, "GLIBC_2.38"):
            zsh.validate_abi({**abi, "maximum_glibc": "2.38"}, "ubuntu-amd64", pinned)
        with self.assertRaisesRegex(deps.DependencyError, "interpreter"):
            zsh.validate_abi({**abi, "interpreter": "/tmp/build/ld.so"}, "ubuntu-amd64", pinned)

    def test_linux_receipt_cannot_bypass_pending_baseline_sdk(self):
        lock, _, _ = fixture(self.root)
        lock["zsh_data"]["platforms"]["ubuntu-amd64"]["toolchain_status"] = "pending-verified-Ubuntu-20.04-SDK"
        with self.assertRaisesRegex(deps.DependencyError, "verified Ubuntu 20.04 SDK"):
            zsh.verify_receipt(lock["zsh_data"], "ubuntu-amd64", self.root / "zsh-build")

    def test_mingw_or_cygwin_cannot_substitute_for_private_msys(self):
        pinned = zsh.load_lock()
        for libraries in (["kernel32.dll", "cygwin1.dll"], ["kernel32.dll", "msvcrt.dll"]):
            with self.assertRaisesRegex(deps.DependencyError, "private MSYS ABI"):
                zsh.validate_abi({"imports": libraries}, "windows-x64", pinned)

    def test_zero_fuzz_patch_hunks_and_context_refresh_gate(self):
        source = self.root / "source"
        source.mkdir()
        (source / "file.c").write_text("prefix\na\nold\nb\nc\nold2\nd\n", encoding="utf-8")
        patch = b"--- a/file.c\n+++ b/file.c\n@@ -1,3 +1,3 @@\n a\n-old\n+new\n b\n@@ -4,3 +4,3 @@\n c\n-old2\n+new2\n d\n"
        zsh.apply_patch(source, patch, 1)
        self.assertEqual((source / "file.c").read_text(), "prefix\na\nnew\nb\nc\nnew2\nd\n")
        with self.assertRaisesRegex(deps.DependencyError, "context mismatch"):
            zsh.apply_patch(source, patch, 1)
        pinned = zsh.load_lock()
        for entry in pinned["platforms"]["windows-x64"]["patches"]:
            if entry.get("refreshed"):
                a = deps.inside(deps.DEFAULT_LOCK.parent, entry["original"]["repository_path"]).read_bytes()
                b = deps.inside(deps.DEFAULT_LOCK.parent, entry["refreshed"]["repository_path"]).read_bytes()
                self.assertEqual(zsh.patch_changes(a), zsh.patch_changes(b))

    def test_windows_overlay_requires_original_hashes_and_replaces_both_names(self):
        payload = self.root / "runtime"
        source = self.root / "zsh-build/payload"
        old_names = ["runtime/msys64/usr/bin/zsh.exe", "runtime/msys64/usr/bin/zsh-5.9.2.exe"]
        removed = "runtime/msys64/usr/bin/msys-zsh-5.9.2.dll"
        for name in old_names + [removed]:
            dest = payload / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"original")
        for name in old_names:
            dest = source / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"patched")
        policy = {"replacement_paths": old_names, "remove_original_paths": [removed], "original_runtime_files": {name: digest(b"original") for name in old_names + [removed]}, "required_runtime_dlls": []}
        pinned = {"platforms": {"windows-x64": policy}}
        receipt = {"files": deps.tree_manifest(source)}
        (payload / old_names[0]).write_bytes(b"unexpected")
        with self.assertRaisesRegex(deps.DependencyError, "differs before GX overlay"):
            deps.merge_zsh_overlay(pinned, "windows-x64", source.parent, payload, receipt)
        self.assertTrue((payload / removed).exists())
        (payload / old_names[0]).write_bytes(b"original")
        changes = deps.merge_zsh_overlay(pinned, "windows-x64", source.parent, payload, receipt)
        self.assertEqual(len(changes), 3)
        self.assertFalse((payload / removed).exists())
        for name in old_names:
            self.assertEqual((payload / name).read_bytes(), b"patched")

    def test_wrong_platform_bundle_is_rejected(self):
        lock, cache, build = fixture(self.root)
        output = self.root / "bundle"
        deps.assemble(lock, "ubuntu-amd64", cache, output, build, zsh_build=build.parent / "zsh-build")
        with self.assertRaisesRegex(deps.DependencyError, "platform/lock"):
            deps.verify_bundle(lock, "windows-x64", output)


if __name__ == "__main__":
    unittest.main()
