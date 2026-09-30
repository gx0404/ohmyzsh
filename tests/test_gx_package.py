#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gx_dependencies as deps
import gx_package as package
from test_gx_dependencies import elf_binary, fixture


def git_fixture(root: Path, files: dict[str, bytes]) -> Path:
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "core.autocrlf", "false"], check=True)
    subprocess.run(["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
    stream = bytearray(b"commit refs/heads/main\ncommitter Packaging Fixture <fixture@example.invalid> 1700000000 +0000\ndata 7\nfixture\n")
    for name, data in files.items():
        stream.extend(f"M 100644 inline {name}\ndata {len(data)}\n".encode())
        stream.extend(data + b"\n")
    stream.extend(b"\ndone\n")
    subprocess.run(["git", "-C", str(root), "fast-import", "--quiet"], input=bytes(stream), check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "read-tree", "--reset", "-u", "HEAD"], check=True)
    return root


def fake_launchers(source: Path, destination: Path, platform: str, lock: dict, rustc: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("gx-zsh", "herdr"):
        path = destination / name
        path.write_bytes(elf_binary())
        path.chmod(0o755)


COMPLETION = b"#compdef herdr\n\n_herdr() { : fixture only }\n"


def fake_completion(herdr: Path, home: Path) -> bytes:
    if herdr.read_bytes() != elf_binary():
        raise AssertionError(f"completion must come from the staged herdr: {herdr}")
    return COMPLETION


def full_fixture(root: Path, **receipt) -> tuple[Path, Path]:
    lock, cache, herdr = fixture(root / "deps")
    if receipt:
        deps.write_json(herdr / "herdr-build.json", {**deps.read_json(herdr / "herdr-build.json"), **receipt})
    bundle = root / "bundle"
    deps.assemble(lock, "ubuntu-amd64", cache, bundle, herdr, zsh_build=herdr.parent / "zsh-build")
    return git_fixture(root / "repo", package_resources(root)), bundle


def advance(repo: Path, files: dict[str, bytes]) -> None:
    stream = bytearray(b"commit refs/heads/main\ncommitter Packaging Fixture <fixture@example.invalid> 1700000100 +0000\n"
                       b"data 7\nadvance\nfrom refs/heads/main^0\n")
    for name, data in files.items():
        stream.extend(f"M 100644 inline {name}\ndata {len(data)}\n".encode())
        stream.extend(data + b"\n")
    stream.extend(b"\ndone\n")
    subprocess.run(["git", "-C", str(repo), "fast-import", "--quiet", "--force"], input=bytes(stream), check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "read-tree", "--reset", "-u", "HEAD"], check=True)


def monorepo_fixture(root: Path) -> tuple[Path, Path]:
    """gx_shell 单仓形态：ohmyzsh/ 与 herdr/ 同一提交，锁只写 monorepo_path。"""
    _, cache, herdr = fixture(root / "deps")
    raw = deps.read_json(root / "deps/dependencies.json")
    raw["herdr"] = {"repository": deps.MONOREPO, "branch_provenance": "gx_shell herdr/ subtree of the release commit",
                    "source": {"monorepo_path": "herdr"}, "rust": "1.96.1", "zig": "0.16.0",
                    "targets": raw["herdr"]["targets"]}
    raw["components"][0].update(sources=[{"monorepo_path": "herdr"}], version="1.2.3")
    files = {"ohmyzsh/" + name: data for name, data in package_resources(root).items()}
    files["ohmyzsh/scripts/packaging/dependencies.json"] = (json.dumps(raw, indent=2) + "\n").encode()
    files["herdr/Cargo.toml"] = b'[package]\nname = "herdr"\nversion = "1.2.3"\n'
    files["herdr/src/main.rs"] = b"fn main() {}\n"
    repo = git_fixture(root / "mono", files) / "ohmyzsh"
    lock = deps.load_lock(repo / "scripts/packaging/dependencies.json")
    deps.fetch_artifact(lock["herdr"]["source"], cache, repository_root=repo)
    receipt = deps.read_json(herdr / "herdr-build.json")
    receipt.update(revision=lock["herdr"]["revision"], version="1.2.3", source_sha256=lock["herdr"]["source"]["sha256"])
    deps.write_json(herdr / "herdr-build.json", receipt)
    bundle = root / "bundle"
    deps.assemble(lock, "ubuntu-amd64", cache, bundle, herdr, zsh_build=herdr.parent / "zsh-build")
    return repo, bundle


def package_resources(root: Path) -> dict[str, bytes]:
    resources = {name: b"fixture\n" for name in package.REQUIRED_RESOURCES | package.BUILD_FILES}
    resources["CHANGELOG.md"] = b"# Fixture\n\n## 1.2.3(TBD)\n"
    resources["scripts/packaging/dependencies.json"] = (root / "deps/dependencies.json").read_bytes()
    resources["scripts/packaging/zsh-runtime-lock.json"] = (root / "deps/zsh-runtime-lock.json").read_bytes()
    resources["scripts/packaging/msys2-lock.json"] = b"{}\n"
    for name in ("control", "preinst", "postinst", "postrm"):
        resources["scripts/packaging/debian/" + name] = (package.ROOT / "scripts/packaging/debian" / name).read_bytes()
    resources["scripts/packaging/windows.iss"] = (package.ROOT / "scripts/packaging/windows.iss").read_bytes()
    for name in package.LINUX_BINARIES:
        resources[name] = elf_binary()
    for face in ("Regular", "Italic", "Bold", "BoldItalic"):
        resources[package.FONT_ROOT + "JetBrainsMonoNerdFont-" + face + ".ttf"] = b"fixture-font"
    resources["gx/config/zshrc.local"] = b"private machine settings\n"
    resources["custom/example.zsh"] = b"user runtime\n"
    resources["gx/wezterm/private.conf"] = b"not package input\n"
    return resources


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gx-package-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_version_is_numeric_maximum(self):
        self.assertEqual(package.current_version("## 0.9.0(TBD)\n## 0.10.1(2026-09-27)\n## 0.8.0(20260901)\n"), "0.10.1")
        with self.assertRaises(package.PackageError):
            package.current_version("## unreleased\n")

    def test_whitelist_excludes_machine_and_runtime_data(self):
        for path in ("gx/config/zshrc.local", "custom/example.zsh", "cache/file", "log/run", ".env", "gx/wezterm/wezterm.lua", "docs/kb/chunks.json", "tests/test.py"):
            self.assertFalse(package.resource_allowed(path), path)
        for path in ("oh-my-zsh.sh", "plugins/herdr/herdr.plugin.zsh", "gx/config/package.zsh", "lib/git.zsh"):
            self.assertTrue(package.resource_allowed(path), path)

    def test_public_notices_are_in_source_snapshot_not_runtime_resources(self):
        name = "scripts/packaging/notices/dependency-LICENSE.txt"
        repo = git_fixture(self.root / "repo", {"CHANGELOG.md": b"## 1.2.3(TBD)\n", name: b"original license\n"})
        self.assertTrue(package.build_input_allowed(name))
        self.assertFalse(package.resource_allowed(name))
        self.assertEqual(package.snapshot(repo, package.clean_source(repo, "HEAD"))[name][0], b"original license\n")

    def test_git_blob_snapshot_preserves_lf_with_crlf_checkout(self):
        repo = git_fixture(self.root / "repo", {"CHANGELOG.md": b"## 1.2.3(TBD)\n", "gx/config/zshrc": b"line one\nline two\n"})
        source = package.clean_source(repo, "HEAD")
        subprocess.run(["git", "-C", str(repo), "config", "core.autocrlf", "true"], check=True)
        (repo / "gx/config/zshrc").write_bytes(b"line one\r\nline two\r\n")
        self.assertFalse(package.clean_source(repo, "HEAD")["dirty"])
        files = package.snapshot(repo, source)
        self.assertEqual(files["gx/config/zshrc"][0], b"line one\nline two\n")

    def test_dirty_ref_fails_without_development_opt_in(self):
        repo = git_fixture(self.root / "repo", {"CHANGELOG.md": b"## 1.2.3(TBD)\n", "gx/config/zshrc": b"original\n"})
        (repo / "gx/config/zshrc").write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(package.PackageError, "clean Git worktree"):
            package.clean_source(repo, "HEAD")
        info = package.clean_source(repo, "HEAD", allow_dirty=True)
        self.assertTrue(info["dirty"])
        self.assertFalse(info["publishable"])
        self.assertEqual(package.snapshot(repo, info)["gx/config/zshrc"][0], b"changed\n")

    def test_index_only_changes_are_dirty_even_if_worktree_matches_head(self):
        repo = git_fixture(self.root / "repo", {"CHANGELOG.md": b"## 1.2.3(TBD)\n", "gx/config/zshrc": b"original\n"})
        oid = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=b"staged only\n", capture_output=True, check=True).stdout.decode().strip()
        subprocess.run(["git", "-C", str(repo), "update-index", "--cacheinfo", "100644," + oid + ",gx/config/zshrc"], check=True)
        with self.assertRaisesRegex(package.PackageError, "clean Git worktree"):
            package.clean_source(repo, "HEAD")

    def test_allow_dirty_marks_even_clean_tree_unpublishable(self):
        repo = git_fixture(self.root / "repo", {"CHANGELOG.md": b"## 1.2.3(TBD)\n"})
        self.assertFalse(package.clean_source(repo, "HEAD", True)["publishable"])

    def test_untracked_private_file_is_never_read(self):
        repo = git_fixture(self.root / "repo", {"CHANGELOG.md": b"## 1.2.3(TBD)\n", "gx/config/zshrc": b"safe\n"})
        (repo / "gx/config/zshrc.local").write_text("private\n")
        source = package.clean_source(repo, "HEAD", True)
        self.assertNotIn("gx/config/zshrc.local", package.snapshot(repo, source))

    def test_monorepo_sibling_changes_do_not_dirty_the_component(self):
        mono = git_fixture(self.root / "mono", {"CHANGELOG.md": b"## 9.9.9(TBD)\n", "ohmyzsh/CHANGELOG.md": b"## 1.2.3(TBD)\n",
                                                "ohmyzsh/gx/config/zshrc": b"safe\n", "herdr/Cargo.toml": b"fixture\n"})
        repo = mono / "ohmyzsh"
        (mono / "herdr/Cargo.toml").write_text("changed sibling\n", encoding="utf-8")
        (mono / "untracked-sibling.txt").write_text("sibling\n", encoding="utf-8")
        info = package.clean_source(repo, "HEAD")
        self.assertFalse(info["dirty"])
        self.assertEqual(info["version"], "1.2.3")
        self.assertIn("gx/config/zshrc", package.snapshot(repo, info))
        (repo / "gx/config/zshrc").write_text("changed component\n", encoding="utf-8")
        with self.assertRaisesRegex(package.PackageError, "clean Git worktree"):
            package.clean_source(repo, "HEAD")

    def test_monorepo_herdr_archive_is_reproducible_from_the_commit(self):
        mono = git_fixture(self.root / "mono", {"herdr/Cargo.toml": b'[package]\nname = "herdr"\nversion = "1.2.3"\n',
                                                "herdr/src/main.rs": b"fn main() {}\n", "ohmyzsh/README": b"component\n"})
        head = package.git(mono, "rev-parse", "HEAD").decode().strip()
        marker = {"repository": deps.MONOREPO, "source": {"monorepo_path": "herdr"}, "rust": "1.96.1"}
        resolved = deps.monorepo_herdr(mono / "ohmyzsh", marker)
        self.assertEqual((resolved["revision"], resolved["version"]), (head, "1.2.3"))
        self.assertEqual(resolved["source"]["filename"], f"herdr-{head}.zip")
        archive = deps.fetch_artifact(resolved["source"], self.root / "cache", repository_root=mono / "ohmyzsh")
        self.assertEqual(deps.sha256_file(archive), resolved["source"]["sha256"])
        deps.extract_archive(archive, self.root / "source", strip=1)
        self.assertEqual((self.root / "source/src/main.rs").read_bytes(), b"fn main() {}\n")
        self.assertFalse((self.root / "source/README").exists())

    def test_monorepo_stage_ref_must_be_the_commit_that_provides_herdr(self):
        repo, bundle = monorepo_fixture(self.root)
        built = package.git(repo, "rev-parse", "HEAD").decode().strip()
        advance(repo.parent, {"herdr/src/main.rs": b"fn main() { changed(); }\n"})
        with self.assertRaisesRegex(package.PackageError, "checked-out commit that provides herdr"):
            package.stage(repo, built, "ubuntu-amd64", bundle, self.root / "stage")
        self.assertFalse((self.root / "stage").exists())

    def test_monorepo_stage_records_gx_shell_and_a_git_free_resolved_lock(self):
        if os.name == "nt":
            self.skipTest("deb stage creates POSIX symlinks; run on Linux (CI/WSL)")
        repo, bundle = monorepo_fixture(self.root)
        output = self.root / "stage"
        with mock.patch.object(package, "compile_launchers", side_effect=fake_launchers), \
                mock.patch.object(package, "herdr_completion", side_effect=fake_completion):
            manifest = package.stage(repo, "HEAD", "ubuntu-amd64", bundle, output)
        package.verify_stage(output)
        head = package.git(repo, "rev-parse", "HEAD").decode().strip()
        self.assertEqual(manifest["source"]["repository"], "gx0404/gx_shell")
        self.assertEqual((manifest["herdr"]["revision"], manifest["herdr"]["version"]), (head, "1.2.3"))
        resolved = deps.read_json(output / "redistribution/ohmyzsh-gx/scripts/packaging/dependencies.json")
        self.assertEqual(resolved["herdr"]["source"]["commit"], head)
        self.assertEqual(deps.read_json(output / "payload/usr/share/ohmyzsh-gx/package-origin.json")["source"]["repository"],
                         "gx0404/gx_shell")

    def test_stage_fixture_layout_and_license_source_manifests(self):
        if os.name == "nt":
            self._stage_windows_boundary()
            return
        repo, bundle = full_fixture(self.root, builder="github-actions")
        output = self.root / "stage 中文 space"
        with mock.patch.object(package, "compile_launchers", side_effect=fake_launchers), \
                mock.patch.object(package, "herdr_completion", side_effect=fake_completion):
            manifest = package.stage(repo, "HEAD", "ubuntu-amd64", bundle, output)
        package.verify_stage(output)
        completion = "usr/share/ohmyzsh-gx/" + package.HERDR_COMPLETION
        self.assertEqual((output / "payload" / completion).read_bytes(), COMPLETION)
        self.assertIn(completion, {item["path"] for item in manifest["payload"]})
        self.assertTrue(manifest["publishable"])
        self.assertEqual(manifest["msys2_overlay"], deps.read_json(bundle / "dependencies-manifest.json")["msys2_overlay"])
        self.assertTrue((output / "payload/usr/bin/gx-zsh").is_symlink())
        self.assertEqual(os.readlink(output / "payload/usr/bin/herdr"), "../lib/ohmyzsh-gx/bin/herdr")
        self.assertFalse((output / "payload/usr/share/ohmyzsh-gx/gx/config/zshrc.local").exists())
        self.assertTrue((output / "payload/usr/share/doc/ohmyzsh-gx/licenses/ohmyzsh-LICENSE.txt").is_file())
        self.assertTrue((output / "redistribution/dependencies/herdr/vendor.tar.gz").is_file())
        self.assertEqual(manifest["validation"], {"lifecycle": "pending", "pty": "pending"})
        self.assertEqual(manifest["herdr_build"], deps.read_json(bundle / "dependencies-manifest.json")["herdr"])
        self.assertEqual(manifest["zsh_build"], deps.read_json(bundle / "dependencies-manifest.json")["zsh"])
        self.assertEqual((output / "payload/usr/lib/ohmyzsh-gx/bin/zsh").read_bytes(), __import__("gx_build_zsh").WRAPPER)
        self.assertEqual(manifest["source"]["revision"], package.git(repo, "rev-parse", "HEAD").decode().strip())

    def _stage_windows_boundary(self):
        repo, bundle = full_fixture(self.root)
        with mock.patch.object(package, "compile_launchers", side_effect=fake_launchers), \
                mock.patch.object(package, "herdr_completion", side_effect=fake_completion) as completion:
            with mock.patch.object(Path, "symlink_to", side_effect=OSError("fixture: no Windows symlink privilege")):
                with self.assertRaises(OSError):
                    package.stage(repo, "HEAD", "ubuntu-amd64", bundle, self.root / "stage")
        self.assertTrue(completion.call_args.args[0].as_posix().endswith("/payload/usr/lib/ohmyzsh-gx/lib/herdr/herdr"))
        self.assertFalse((self.root / "stage").exists())

    def test_only_a_herdr_built_on_github_actions_makes_the_stage_publishable(self):
        if os.name == "nt":
            self.skipTest("deb stage creates POSIX symlinks; run on Linux (CI/WSL)")
        for index, receipt in enumerate(({"builder": "local"}, {}, {"builder": "self-hosted"}, {"builder": "github-actions"})):
            with self.subTest(receipt=receipt):
                root = self.root / str(index)
                root.mkdir()
                repo, bundle = full_fixture(root, **receipt)
                output = root / "stage"
                with mock.patch.object(package, "compile_launchers", side_effect=fake_launchers), \
                        mock.patch.object(package, "herdr_completion", side_effect=fake_completion):
                    manifest = package.stage(repo, "HEAD", "ubuntu-amd64", bundle, output)
                expected = receipt.get("builder") == "github-actions"
                self.assertEqual(manifest["publishable"], expected)
                self.assertEqual(manifest["herdr_build"].get("builder"), receipt.get("builder"))
                self.assertEqual(package.verify_stage(output)["publishable"], expected)

    def test_stage_or_release_without_a_github_actions_herdr_can_never_claim_publishable(self):
        stage = self.root / "stage"
        for name in ("payload", "redistribution", "build-inputs"):
            (stage / name).mkdir(parents=True)
        artifact = self.root / "fixture.exe"
        artifact.write_bytes(b"not a real installer")
        sources = self.root / "fixture-sources.tar.xz"
        sources.write_bytes(b"not real sources")
        path = self.root / "fixture.manifest.json"
        for build in ({"builder": "local"}, {}, {"builder": "self-hosted"}):
            with self.subTest(build=build):
                deps.write_json(stage / "package-manifest.json", {
                    "schema_version": 1, "platform": "windows-x64", "payload": [], "redistribution": [], "build_inputs": [],
                    "compliance_complete": True, "source": {"development": False, "dirty": False}, "publishable": True,
                    "herdr_build": build})
                with self.assertRaisesRegex(package.PackageError, "built on GitHub Actions can be publishable"):
                    package.verify_stage(stage)
                deps.write_json(path, {
                    "schema_version": 1, "product": "ohmyzsh-gx", "publishable": True, "compliance_complete": True,
                    "source": {"development": False, "dirty": False}, "herdr_build": build,
                    "validation": {"native_package_built": True, "lifecycle": "passed", "pty": "passed"},
                    "artifacts": [{"filename": p.name, "sha256": deps.sha256_file(p), "size": p.stat().st_size, "role": role}
                                  for p, role in ((artifact, "installer"), (sources, "corresponding-sources"))]})
                package.verify_release(path)
                with self.assertRaisesRegex(package.PackageError, "herdr not built on GitHub Actions cannot be released"):
                    package.verify_release(path, require_release=True)
        deps.write_json(stage / "package-manifest.json", {
            "schema_version": 1, "platform": "windows-x64", "payload": [], "redistribution": [], "build_inputs": [],
            "compliance_complete": True, "source": {"development": False, "dirty": False}, "publishable": True,
            "herdr_build": {"builder": "github-actions"}})
        # 构建者合格时越过这一检查，停在夹具没有提供的源码锁上。
        with self.assertRaises(FileNotFoundError):
            package.verify_stage(stage)

    def test_verify_stage_ties_the_msys2_overlay_record_to_the_staged_runtime(self):
        stage = self.root / "stage"
        fstab = stage / "payload/runtime/msys64/etc/fstab"
        fstab.parent.mkdir(parents=True)
        fstab.write_bytes(b"none / cygdrive binary,posix=0,noacl,user 0 0\n")
        for name in ("redistribution", "build-inputs"):
            (stage / name).mkdir()
        change = {"path": "runtime/msys64/etc/fstab", "old_sha256": "0" * 64, "new_sha256": deps.sha256_file(fstab), "action": "replaced"}
        manifest = {"schema_version": 1, "platform": "windows-x64", "payload": package.payload_manifest(stage / "payload"),
                    "redistribution": [], "build_inputs": [], "compliance_complete": True, "publishable": False,
                    "source": {"development": False, "dirty": False}, "msys2_overlay": [change]}
        deps.write_json(stage / "package-manifest.json", {**manifest, "msys2_overlay": [{**change, "new_sha256": "1" * 64}]})
        with self.assertRaisesRegex(package.PackageError, "overlay record: runtime/msys64/etc/fstab"):
            package.verify_stage(stage)
        deps.write_json(stage / "package-manifest.json", manifest)
        # 记录与载荷一致时越过这一检查，停在夹具没有提供的源码锁上。
        with self.assertRaises(FileNotFoundError):
            package.verify_stage(stage)

    def test_committed_herdr_completion_is_rejected_because_stage_generates_it(self):
        repo, bundle = full_fixture(self.root)
        advance(repo, {package.HERDR_COMPLETION: b"#compdef herdr\n"})
        with mock.patch.object(package, "herdr_completion", side_effect=fake_completion) as completion:
            with self.assertRaisesRegex(package.PackageError, "generated at stage time"):
                package.stage(repo, "HEAD", "ubuntu-amd64", bundle, self.root / "stage")
        completion.assert_not_called()
        self.assertFalse((self.root / "stage").exists())

    def test_herdr_completion_runs_the_staged_binary_in_an_isolated_environment(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, COMPLETION, b"")

        herdr, home = self.root / "lib/herdr/herdr", self.root / "completion-home"
        user = {"HERDR_LANG": "en", "HERDR_SESSION": "user", "HERDR_CONFIG_PATH": "user.toml", "SYSTEMROOT": "C:\\Windows"}
        with mock.patch.dict(os.environ, user), mock.patch.object(package.subprocess, "run", side_effect=run):
            self.assertEqual(package.herdr_completion(herdr, home), COMPLETION)
        (argv, kwargs), = calls
        self.assertEqual(argv, [str(herdr), "completion", "zsh"])
        self.assertEqual((kwargs["cwd"], kwargs["stdin"]), (home, subprocess.DEVNULL))
        env = kwargs["env"]
        self.assertEqual(env["HERDR_CONFIG_PATH"], str(home / "config.toml"))
        for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "TMP", "TEMP"):
            self.assertEqual(env[name], str(home), name)
        self.assertEqual(env["HERDR_LANG"], "zh-CN")
        for name in ("HERDR_SESSION", "PATH"):
            self.assertNotIn(name, env)
        self.assertTrue(home.is_dir())

    def test_herdr_completion_failure_blocks_the_stage(self):
        for index, (code, stdout, stderr) in enumerate(((2, b"", b"unknown subcommand"), (0, b"_herdr() {}\n", b""))):
            with self.subTest(code=code), \
                    mock.patch.object(package.subprocess, "run",
                                      return_value=subprocess.CompletedProcess([], code, stdout, stderr)):
                with self.assertRaisesRegex(package.PackageError, "did not generate its zsh completion"):
                    package.herdr_completion(self.root / "herdr", self.root / f"home-{index}")

    def test_herdr_completion_timeout_is_a_package_error(self):
        with mock.patch.object(package.subprocess, "run", side_effect=subprocess.TimeoutExpired(["herdr", "completion", "zsh"], 120)):
            with self.assertRaisesRegex(package.PackageError, "did not generate its zsh completion within 120 s"):
                package.herdr_completion(self.root / "herdr", self.root / "home")

    def test_missing_source_payload_blocks_before_output(self):
        repo, bundle = full_fixture(self.root)
        (bundle / "redistribution/herdr/vendor.tar.gz").unlink()
        with self.assertRaisesRegex(deps.DependencyError, "inventory mismatch"):
            package.stage(repo, "HEAD", "ubuntu-amd64", bundle, self.root / "stage")
        self.assertFalse((self.root / "stage").exists())

    def test_requested_version_cannot_override_changelog(self):
        repo, bundle = full_fixture(self.root)
        with self.assertRaisesRegex(package.PackageError, "CHANGELOG"):
            package.stage(repo, "HEAD", "ubuntu-amd64", bundle, self.root / "stage", version="9.9.9")

    def test_missing_compiler_version_is_a_hard_failure(self):
        lock, _, _ = fixture(self.root / "deps")
        with mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "rustc 1.94.1\n", "")):
            with self.assertRaisesRegex(package.PackageError, "Rust 1.96.1"):
                package.compile_launchers(self.root / "main.rs", self.root / "bin", "ubuntu-amd64", lock, "rustc")

    def test_windows_launchers_use_the_msvc_toolchain_even_when_rustup_defaults_to_gnu(self):
        lock, _, _ = fixture(self.root / "deps")
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs.get("env")))
            if "-o" in argv:
                Path(argv[argv.index("-o") + 1]).write_bytes(b"MZ fixture")
            return subprocess.CompletedProcess(argv, 0, "rustc 1.96.1 (fixture)\n", "")

        with mock.patch.dict(os.environ, {"RUSTUP_TOOLCHAIN": "1.96.1-x86_64-pc-windows-gnu"}), \
                mock.patch.object(subprocess, "run", side_effect=run), mock.patch.object(package.deps, "check_binary"):
            package.compile_launchers(self.root / "main.rs", self.root / "bin", "windows-x64", lock, "rustc")
        self.assertEqual(len(calls), 3)
        self.assertEqual({env["RUSTUP_TOOLCHAIN"] for _, env in calls}, {"1.96.1-x86_64-pc-windows-msvc"})
        self.assertEqual({env["RUSTUP_AUTO_INSTALL"] for _, env in calls}, {"0"})
        self.assertTrue(all(argv[argv.index("--target") + 1] == "x86_64-pc-windows-msvc" for argv, _ in calls[1:]))

    def test_source_archive_reproducible_and_excludes_external_symlinks(self):
        source = self.root / "sources"
        source.mkdir()
        (source / "LICENSE").write_bytes(b"fixture\n")
        package.source_archive(source, self.root / "one.tar.xz", 1700000000)
        package.source_archive(source, self.root / "two.tar.xz", 1700000000)
        self.assertEqual(deps.sha256_file(self.root / "one.tar.xz"), deps.sha256_file(self.root / "two.tar.xz"))
        with tarfile.open(self.root / "one.tar.xz") as archive:
            self.assertEqual(archive.getmembers()[0].uid, 0)
            self.assertEqual(archive.getmembers()[0].mtime, 1700000000)

    def test_release_requires_sources_and_rejects_tampering(self):
        artifact = self.root / "fixture.deb"
        artifact.write_bytes(b"not a real DEB")
        sources = self.root / "fixture-sources.tar.xz"
        sources.write_bytes(b"not real sources")
        manifest = {"schema_version": 1, "product": "ohmyzsh-gx", "publishable": False, "source": {"development": True, "dirty": True}, "compliance_complete": True, "artifacts": [{"filename": p.name, "sha256": deps.sha256_file(p), "size": p.stat().st_size, "role": role} for p, role in ((artifact, "installer"), (sources, "corresponding-sources"))]}
        path = self.root / "fixture.manifest.json"
        deps.write_json(path, manifest)
        package.verify_release(path)
        with self.assertRaisesRegex(package.PackageError, "cannot be released"):
            package.verify_release(path, require_release=True)
        sources.write_bytes(b"tampered")
        with self.assertRaisesRegex(package.PackageError, "hash/size mismatch"):
            package.verify_release(path)

    def test_maintainer_scripts_do_not_modify_users_or_install_packages(self):
        for name in ("preinst", "postinst", "postrm"):
            text = (package.ROOT / "scripts/packaging/debian" / name).read_text(encoding="utf-8")
            self.assertNotIn("$HOME", text)
            self.assertNotIn("apt ", text)
            self.assertNotIn("chsh", text)
            self.assertIn("set -eu", text)
        control = (package.ROOT / "scripts/packaging/debian/control").read_text()
        for dependency in ("zsh", "git", "fzf", "zsh-autosuggestions", "zsh-syntax-highlighting", "fontconfig"):
            self.assertIn(dependency, control)

    def test_windows_installer_owned_path_and_busy_policy(self):
        text = (package.ROOT / "scripts/packaging/windows.iss").read_text(encoding="utf-8")
        for required in ("PrivilegesRequired=lowest", "CloseApplications=no", "PathEntry", "EntryCount(Value, Owned) = 1", "RegWriteExpandStringValue", "ResolvedHerdr", "BusyFile", "Fonts(False)"):
            self.assertIn(required, text)
        self.assertNotIn("taskkill", text.lower())
        self.assertNotIn("runtime\\msys64\\usr\\bin", text)
        self.assertNotIn("[UninstallDelete]", text)
        self.assertNotIn("Ord(Directory[I]) > 127", text)
        self.assertNotIn("Pos(' ', Directory) > 0", text)
        self.assertIn("Unicode and spaces are supported", text)

    def test_cli_prepare_from_real_git_snapshot(self):
        repo = git_fixture(self.root / "repo", {"CHANGELOG.md": b"## 1.2.3(TBD)\n"})
        result = subprocess.run([sys.executable, str(package.ROOT / "scripts/gx_package.py"), "prepare", "--repo", str(repo), "--ref", "HEAD"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["version"], "1.2.3")


class NativeDebFixture(unittest.TestCase):
    def test_real_dpkg_deb_structure_only(self):
        if os.name == "nt" or not shutil.which("dpkg-deb"):
            self.fail("--native-deb requires Linux and dpkg-deb; cannot substitute an archive fixture for native packaging")
        with tempfile.TemporaryDirectory(prefix="gx-native-deb-fixture-") as temporary:
            root = Path(temporary)
            repo, bundle = full_fixture(root)
            stage = root / "stage"
            with mock.patch.object(package, "compile_launchers", side_effect=fake_launchers), \
                    mock.patch.object(package, "herdr_completion", side_effect=fake_completion):
                manifest = package.stage(repo, "HEAD", "ubuntu-amd64", bundle, stage, allow_dirty=True)
            result = package.build(stage, root / "artifacts")
            package.verify_release(Path(result["manifest"]))
            deb = next((root / "artifacts").glob("*.deb"))
            listing = subprocess.run(["dpkg-deb", "--contents", str(deb)], capture_output=True, text=True, check=True).stdout
            for required in ("./usr/bin/gx-zsh -> ../lib/ohmyzsh-gx/bin/gx-zsh", "./usr/lib/ohmyzsh-gx/lib/herdr/herdr", "./usr/share/ohmyzsh-gx/gx/config/package.zsh", "root/root"):
                self.assertIn(required, listing)
            extracted = root / "extracted"
            subprocess.run(["dpkg-deb", "--extract", str(deb), str(extracted)], check=True)
            self.assertEqual((extracted / "usr/bin/herdr").read_bytes(), elf_binary())
            self.assertFalse((extracted / "usr/share/ohmyzsh-gx/gx/config/zshrc.local").exists())
            self.assertFalse(manifest["publishable"])
            print("Real dpkg-deb fixture: metadata, symlinks, root ownership, extraction and SHA-256 verified; binaries are unit fixtures, not runtime acceptance.")


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromTestCase(PackageTests)


if __name__ == "__main__":
    native = "--native-deb" in sys.argv
    if native:
        sys.argv.remove("--native-deb")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NativeDebFixture if native else PackageTests)
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
