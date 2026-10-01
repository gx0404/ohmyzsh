#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gx_release as release
import gx_build_herdr as builder

SHA = "a" * 40
HERDR_SHA = "1a6b9d4d13d1b547fe0e21197baeb2ac4e27bef0"
VERSION = "1.2.3"
CI = {
    "GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REPOSITORY": release.REPOSITORY,
    "GITHUB_REF": "refs/heads/master", "GX_DEFAULT_BRANCH": "master", "GITHUB_SHA": SHA,
    "GITHUB_WORKFLOW_SHA": SHA, "GITHUB_TOKEN": "unit-test-not-a-real-token",
    "GITHUB_WORKFLOW_REF": release.REPOSITORY + "/.github/workflows/gx-release.yml@refs/heads/master",
}


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def record(name: str, data: bytes) -> dict:
    return {"path": name, "sha256": checksum(data), "size": len(data)}


def archive(path: Path, data: dict[str, bytes]) -> list[dict]:
    with tarfile.open(path, "w:xz") as stream:
        for name, content in data.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            stream.addfile(info, io.BytesIO(content))
    return [record(name, content) for name, content in data.items()]


def asset(path: Path) -> dict:
    return {"filename": path.name, "sha256": release.digest(path), "size": path.stat().st_size}


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.lock = {
            "schema_version": 1, "lock_digest": "b" * 64, "assets": [], "unresolved": [],
            "herdr": {"repository": "https://github.com/gx0404/herdr", "branch_provenance": "gx",
                      "revision": HERDR_SHA, "version": "0.9.1", "rust": "1.96.1", "zig": "0.16.0",
                      "targets": release.TARGETS, "source": {"sha256": "c" * 64},
                      "conpty": {"files": {name: None if name == "herdr.exe" else checksum(name.encode()) for name in (
                          "herdr.exe", "conpty/conpty.dll", "conpty/x64/OpenConsole.exe", "conpty/arm64/OpenConsole.exe",
                          "conpty/herdr-conpty.json", "THIRD-PARTY-NOTICES/LICENSE.txt", "THIRD-PARTY-NOTICES/NOTICE.md")}}},
            "components": [{"id": "fixture", "platforms": list(release.TARGETS),
                            **{field: [{"filename": field + ".txt", "sha256": checksum(field.encode()), "url": "https://fixture.invalid/" + field}] for field in ("licenses", "sources", "build_instructions")}}],
            "msys2_data": {"components": [], "packages": [], "base": {"filename": "base.tar.xz", "sha256": "d" * 64, "url": "https://fixture.invalid/base"}},
        }
        self.lock["herdr"]["source"].update(filename="herdr.zip", url="https://fixture.invalid/herdr.zip")
        self.manifests = {}
        for platform, architecture in release.ARCHITECTURES.items():
            stem = f"ohmyzsh-gx_{VERSION}_{architecture}"
            installer = root / (stem + (".exe" if platform == "windows-x64" else ".deb"))
            installer.write_bytes(b"TEST FIXTURE ONLY; NOT AN INSTALLABLE PACKAGE\n" + platform.encode())
            data = {"ohmyzsh-gx/LICENSE.txt": b"fixture license", "dependencies/herdr/redistribution/vendor.tar.xz": b"fixture source"}
            license_inventory = []
            for ecosystem in ("cargo", "cargo-path", "vendored", "zig", "zig-toolchain"):
                path = f"redistribution/licenses/{ecosystem}/fixture/LICENSE"
                data["dependencies/herdr/" + path] = b"fixture license text: " + ecosystem.encode()
                license_inventory.append({"ecosystem": ecosystem, "package": "fixture", "source_identity": {"fixture": True},
                                          "licenses": [record(path, data["dependencies/herdr/" + path])]})
            license_records = [r for item in license_inventory for r in item["licenses"]]
            data.update({"dependencies/fixture/" + field + "/" + field + ".txt": field.encode() for field in ("licenses", "sources", "build_instructions")})
            sources = root / (stem + "-sources.tar.xz")
            records = archive(sources, data)
            binaries = list(self.lock["herdr"]["conpty"]["files"]) if platform == "windows-x64" else ["herdr"]
            binary_records = [record(name, name.encode()) for name in binaries]
            herdr_build = {
                "schema_version": 1, "platform": platform, "revision": HERDR_SHA, "version": "0.9.1",
                "source_sha256": "c" * 64, "rust": "1.96.1", "zig": "0.16.0", "target": release.TARGETS[platform],
                "locked": True, "release": True, "cargo_vendor_complete": True,
                "rustflags": "-C target-feature=+crt-static", "effective_crt_static": True,
                "libghostty_vt_optimize": "ReleaseFast", "libghostty_vt_simd": True, "conpty_verified": platform == "windows-x64",
                "files": binary_records, "source_artifacts": [record("redistribution/vendor.tar.xz", b"fixture source")],
                "license_artifacts": license_records, "license_inventory": license_inventory, "zig_dependencies_complete": True,
            }
            prefix = "lib/herdr/" if platform == "windows-x64" else "usr/lib/ohmyzsh-gx/lib/herdr/"
            license_prefix = "licenses/herdr/" if platform == "windows-x64" else "usr/share/doc/ohmyzsh-gx/licenses/herdr/"
            manifest = {
                "schema_version": 1, "product": "ohmyzsh-gx", "platform": platform, "architecture": architecture,
                "version": VERSION, "publishable": True, "compliance_complete": True, "lock_digest": self.lock["lock_digest"],
                "source": {"repository": release.REPOSITORY, "revision": SHA, "version": VERSION, "dirty": False,
                           "development": False, "publishable": True},
                "herdr": {k: self.lock["herdr"][k] for k in ("repository", "revision", "version", "rust", "zig", "targets")},
                "herdr_build": herdr_build,
                "payload": ([{**item, "path": prefix + item["path"]} for item in binary_records]
                            + [{**item, "path": license_prefix + item["path"]} for item in license_records]),
                "redistribution": records, "dependencies": release.dependency_inventory(self.lock, platform),
                "validation": {"lifecycle": "pending", "pty": "pending", "native_package_built": True},
                "artifacts": [{**asset(installer), "role": "installer"}, {**asset(sources), "role": "corresponding-sources"}],
            }
            self.manifests[platform] = root / (stem + ".manifest.json")
            write_json(self.manifests[platform], manifest)
            self.refresh(platform)
            for environment in release.ENVIRONMENTS[platform]:
                name = f"ohmyzsh-gx_{VERSION}_{environment}"
                evidence = root / (name + ".evidence.tar.xz")
                evidence_files = archive(evidence, {"terminal.txt": b"unit-test synthetic evidence; not an executed lifecycle"})
                required = release.COMMON_CHECKS | (release.WINDOWS_CHECKS if platform == "windows-x64" else release.LINUX_CHECKS)
                write_json(root / (name + ".validation.json"), {
                    "schema_version": 1, "platform": platform, "environment": environment, "source_revision": SHA,
                    "installer_sha256": release.digest(installer), "disposable_environment": True, "evidence_reviewed": True,
                    "checks": {check: {"status": "passed", "evidence": ["terminal.txt"]} for check in required},
                    "evidence_files": evidence_files, "evidence_archive": asset(evidence),
                })

    def refresh(self, platform):
        path = self.manifests[platform]
        manifest = release.read_json(path)
        files = [self.root / item["filename"] for item in manifest["artifacts"]] + [path]
        path.with_name(path.name.replace(".manifest.json", ".sha256")).write_text(
            "".join(f"{release.digest(p)}  {p.name}\n" for p in files), encoding="ascii")

    def modify(self, platform, change):
        path = self.manifests[platform]
        manifest = release.read_json(path)
        change(manifest)
        write_json(path, manifest)
        self.refresh(platform)

    def verify(self):
        return release.verify_artifacts(self.root, VERSION, SHA, self.lock)


class FakeGitHubHTTP:
    def __init__(self):
        self.tag = None
        self.release = None
        self.assets = []
        self.calls = []
        self.fail_upload = False
        self.null_digest = False
        self.flip_tag_at_end = False

    def open(self, request, timeout):
        url = urllib.parse.urlsplit(request.full_url)
        if url.hostname not in {"api.github.com", "uploads.github.com"}:
            raise AssertionError("Unexpected network destination")
        if request.get_header("Authorization") != "Bearer unit-test-not-a-real-token":
            raise AssertionError("Unexpected authentication")
        method = request.get_method()
        path = url.path.removeprefix("/repos/" + release.REPOSITORY)
        raw = request.data
        data = json.loads(raw) if isinstance(raw, bytes) else None
        self.calls.append((method, path, data))
        if method == "GET" and path.startswith("/git/ref/tags/"):
            if self.tag is None:
                raise urllib.error.HTTPError(request.full_url, 404, "Not found", {}, None)
            result = {"object": {"type": "commit", "sha": self.tag}}
        elif method == "POST" and path == "/git/refs":
            self.tag = data["sha"]
            result = {"object": {"type": "commit", "sha": self.tag}}
        elif method == "GET" and path.startswith("/releases/tags/"):
            if self.release is None:
                raise urllib.error.HTTPError(request.full_url, 404, "Not found", {}, None)
            result = self.release
        elif method == "POST" and path == "/releases":
            self.release = {**data, "id": 123, "html_url": "https://github.com/" + release.REPOSITORY + "/releases/tag/" + data["tag_name"]}
            result = self.release
        elif path == "/releases/123/assets" and method == "GET":
            page = int(urllib.parse.parse_qs(url.query)["page"][0])
            result = self.assets[(page - 1) * 100:page * 100]
        elif path == "/releases/123/assets" and method == "POST":
            content = b"".join(raw)
            name = urllib.parse.parse_qs(url.query)["name"][0]
            result = {"name": name, "size": len(content), "state": "uploaded", "digest": None if self.null_digest else "sha256:" + checksum(content)}
            self.assets.append(result)
            if self.fail_upload:
                self.fail_upload = False
                raise urllib.error.URLError("response lost after successful upload")
        elif path == "/releases/123" and method == "GET":
            if self.flip_tag_at_end:
                self.release["body"] = "changed concurrently"
            result = self.release
        elif path == "/releases/123" and method == "PATCH":
            self.release.update(data)
            result = self.release
        else:
            raise AssertionError(f"Unexpected HTTP boundary: {method} {url.geturl()}")
        return io.BytesIO(json.dumps(result).encode())


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixture = Fixture(self.root)

    def test_complete_contract(self):
        self.assertEqual(len(self.fixture.verify()), 14)

    def test_missing_platform(self):
        self.fixture.manifests["windows-x64"].unlink()
        with self.assertRaisesRegex(release.ReleaseError, "missing"):
            self.fixture.verify()

    def test_metadata_rejections(self):
        changes = [
            lambda m: m.update(schema_version=2), lambda m: m.update(schema_version=True),
            lambda m: m.update(architecture="arm64"), lambda m: m.update(lock_digest="0" * 64),
            lambda m: m["source"].update(dirty=True), lambda m: m["source"].update(development=True),
            lambda m: m["source"].update(revision="d" * 40), lambda m: m["herdr"].update(revision="e" * 40),
            lambda m: m.pop("herdr_build"), lambda m: m["herdr_build"].update(locked=False),
            lambda m: m["herdr_build"].update(rustflags=""), lambda m: m["herdr_build"].update(conpty_verified=False),
        ]
        original = release.read_json(self.fixture.manifests["windows-x64"])
        for change in changes:
            with self.subTest(change=change):
                write_json(self.fixture.manifests["windows-x64"], original)
                self.fixture.modify("windows-x64", change)
                with self.assertRaises(release.ReleaseError):
                    self.fixture.verify()

    def test_changed_installer(self):
        next(self.root.glob("*.exe")).write_bytes(b"tampered")
        with self.assertRaisesRegex(release.ReleaseError, "hash/size"):
            self.fixture.verify()

    def test_changed_sidecar(self):
        next(self.root.glob("*.sha256")).write_text("not a checksum\n", encoding="ascii")
        with self.assertRaisesRegex(release.ReleaseError, "checksum sidecar"):
            self.fixture.verify()

    def test_duplicate_json_keys(self):
        self.fixture.manifests["windows-x64"].write_text('{"schema_version":1,"schema_version":2}', encoding="utf-8")
        with self.assertRaisesRegex(release.ReleaseError, "duplicate JSON"):
            self.fixture.verify()

    def test_missing_license_not_hidden_by_compliance_true(self):
        self.fixture.lock["components"][0]["licenses"] = []
        with self.assertRaisesRegex(release.ReleaseError, "missing locked licenses"):
            self.fixture.verify()

    def test_unresolved_runtime_blocks(self):
        self.fixture.lock["unresolved"] = [{"id": "zsh", "platforms": ["windows-x64"], "reason": "Chinese paths fail"}]
        with self.assertRaisesRegex(release.ReleaseError, "unresolved"):
            self.fixture.verify()

    def test_redistribution_content_not_just_archive_digest(self):
        manifest = release.read_json(self.fixture.manifests["windows-x64"])
        source = self.root / manifest["artifacts"][1]["filename"]
        archive(source, {"ohmyzsh-gx/LICENSE.txt": b"replacement"})
        self.fixture.modify("windows-x64", lambda m: m["artifacts"][1].update(asset(source)))
        with self.assertRaisesRegex(release.ReleaseError, "archive"):
            self.fixture.verify()

    def test_archive_traversal(self):
        path = self.root / "hostile.tar.xz"
        archive(path, {"../outside": b"x"})
        with self.assertRaisesRegex(release.ReleaseError, "unsafe"):
            release.verify_archive(path, [record("safe", b"x")])
        self.assertFalse((self.root.parent / "outside").exists())

    def test_archive_symlink_rejected(self):
        path = self.root / "hostile.tar.xz"
        with tarfile.open(path, "w:xz") as output:
            info = tarfile.TarInfo("link")
            info.type = tarfile.SYMTYPE
            info.linkname = "../outside"
            output.addfile(info)
        with self.assertRaisesRegex(release.ReleaseError, "unexpected"):
            release.verify_archive(path, [record("link", b"x")])

    def test_unknown_local_file(self):
        (self.root / "unreviewed.exe").write_bytes(b"unexpected")
        with self.assertRaisesRegex(release.ReleaseError, "unexpected files"):
            self.fixture.verify()

    def test_missing_unicode_validation_cannot_be_waived(self):
        path = self.root / f"ohmyzsh-gx_{VERSION}_windows-clean.validation.json"
        receipt = release.read_json(path)
        receipt["checks"]["unicode-config-cache"]["status"] = "skipped"
        write_json(path, receipt)
        with self.assertRaisesRegex(release.ReleaseError, "not passed: unicode-config-cache"):
            self.fixture.verify()

    def test_missing_ubuntu_baseline(self):
        (self.root / f"ohmyzsh-gx_{VERSION}_ubuntu-20.04.validation.json").unlink()
        with self.assertRaisesRegex(release.ReleaseError, "missing"):
            self.fixture.verify()

    def test_evidence_must_match_installer(self):
        path = self.root / f"ohmyzsh-gx_{VERSION}_windows-clean.validation.json"
        receipt = release.read_json(path)
        receipt["installer_sha256"] = "d" * 64
        write_json(path, receipt)
        with self.assertRaisesRegex(release.ReleaseError, "installer_sha256"):
            self.fixture.verify()

    def test_evidence_must_be_read_back(self):
        path = self.root / f"ohmyzsh-gx_{VERSION}_windows-clean.validation.json"
        receipt = release.read_json(path)
        receipt["evidence_reviewed"] = False
        write_json(path, receipt)
        with self.assertRaisesRegex(release.ReleaseError, "evidence_reviewed"):
            self.fixture.verify()

    def test_local_publish_rejected_before_network(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(release, "GitHub") as api:
            with self.assertRaisesRegex(release.ReleaseError, "restricted"):
                release.publish(self.root, VERSION, SHA, self.fixture.lock)
            api.assert_not_called()

    def test_untrusted_ref_rejected_before_network(self):
        for overrides in ({"GITHUB_REF": "refs/heads/untrusted"}, {"GITHUB_WORKFLOW_SHA": "f" * 40},
                          {"GITHUB_REPOSITORY": "attacker/ohmyzsh"}, {"GITHUB_EVENT_NAME": "push"},
                          {"GITHUB_WORKFLOW_REF": release.REPOSITORY + "/.github/workflows/other.yml@refs/heads/master"}):
            with self.subTest(overrides=overrides), patch.dict(os.environ, {**CI, **overrides}, clear=True):
                with self.assertRaises(release.ReleaseError):
                    release.trusted_actions(SHA)

    def test_version_max_numeric(self):
        self.assertEqual(release.changelog_version("## 1.9.9(TBD)\n## 1.10.0(2026-09-28)\n"), "1.10.0")
        with self.assertRaises(release.ReleaseError):
            release.changelog_version("## 01.2.3(TBD)")

    def test_prepare_read_only_contract(self):
        def git(repo, *args):
            if args[0] == "rev-parse":
                return SHA
            if args[0] == "status":
                return ""
            if args[0] == "show":
                return "## 1.2.3(TBD)"
            self.fail(str(args))
        with patch.object(release, "git", side_effect=git), patch.object(release, "load_lock", return_value=self.fixture.lock), patch.object(release, "GitHub") as api:
            self.assertEqual(release.prepare(self.root, "HEAD", VERSION)["sha"], SHA)
            with self.assertRaisesRegex(release.ReleaseError, "version differs"):
                release.prepare(self.root, "HEAD", "9.9.9")
            api.assert_not_called()

    def test_prepare_rejects_dirty_or_wrong_checkout(self):
        for responses in ([SHA, SHA, "?? new.py"], [SHA, "d" * 40]):
            with patch.object(release, "git", side_effect=responses):
                with self.assertRaises(release.ReleaseError):
                    release.prepare(self.root, "HEAD", VERSION)

    def test_remote_assets_strict(self):
        files = self.fixture.verify()
        item = {"name": files[0].name, "size": files[0].stat().st_size, "state": "uploaded", "digest": "sha256:" + release.digest(files[0])}
        for overrides in ({"name": "unknown"}, {"size": 0}, {"digest": None}, {"state": "starter"}):
            with self.subTest(overrides=overrides), self.assertRaises(release.ReleaseError):
                release.verify_remote_assets([{**item, **overrides}], files, complete=False)
        with self.assertRaises(release.ReleaseError):
            release.verify_remote_assets([item, item], files, complete=False)

    def publish_with(self, server):
        with patch.dict(os.environ, CI, clear=True), patch("urllib.request.build_opener", return_value=server):
            return release.publish(self.root, VERSION, SHA, self.fixture.lock)

    def test_http_boundary_publishes_only_after_all_remote_digests(self):
        server = FakeGitHubHTTP()
        url = self.publish_with(server)
        self.assertTrue(url.endswith("gx-v" + VERSION))
        self.assertEqual(len(server.assets), 14)
        self.assertEqual(server.calls[-1], ("PATCH", "/releases/123", {"draft": False}))
        self.assertEqual(server.tag, SHA)

    def test_lost_upload_response_is_not_retried_and_draft_resumes(self):
        server = FakeGitHubHTTP()
        server.fail_upload = True
        with self.assertRaises(urllib.error.URLError):
            self.publish_with(server)
        self.assertTrue(server.release["draft"])
        self.assertEqual(len(server.assets), 1)
        self.publish_with(server)
        self.assertEqual(len(server.assets), 14)
        self.assertEqual(len({item["name"] for item in server.assets}), 14)

    def draft_server(self):
        server = FakeGitHubHTTP()
        server.tag = SHA
        server.release = {"id": 123, "tag_name": "gx-v" + VERSION, "draft": True,
                          "body": release.release_marker(self.fixture.verify(), SHA)}
        return server

    def test_other_sha_tag_never_moved(self):
        server = self.draft_server()
        server.tag = "e" * 40
        with self.assertRaisesRegex(release.ReleaseError, "never moved"):
            self.publish_with(server)
        self.assertTrue(all(method == "GET" for method, _, _ in server.calls))

    def test_public_release_never_overwritten(self):
        server = self.draft_server()
        server.release["draft"] = False
        with self.assertRaisesRegex(release.ReleaseError, "never overwritten"):
            self.publish_with(server)
        self.assertTrue(all(method == "GET" for method, _, _ in server.calls))

    def test_different_draft_inventory_rejected(self):
        server = self.draft_server()
        server.release["body"] = "other inventory"
        with self.assertRaisesRegex(release.ReleaseError, "inventory"):
            self.publish_with(server)
        self.assertTrue(all(method == "GET" for method, _, _ in server.calls))

    def test_unknown_remote_asset_never_deleted(self):
        server = self.draft_server()
        server.assets = [{"name": "unexpected", "size": 1, "state": "uploaded", "digest": "sha256:" + "0" * 64}]
        with self.assertRaisesRegex(release.ReleaseError, "unknown"):
            self.publish_with(server)
        self.assertTrue(all(method == "GET" for method, _, _ in server.calls))

    def test_missing_remote_digest_keeps_draft(self):
        server = FakeGitHubHTTP()
        server.null_digest = True
        with self.assertRaisesRegex(release.ReleaseError, "digest mismatch"):
            self.publish_with(server)
        self.assertTrue(server.release["draft"])
        self.assertNotIn("PATCH", [m for m, _, _ in server.calls])

    def test_concurrent_draft_change_keeps_draft(self):
        server = FakeGitHubHTTP()
        server.flip_tag_at_end = True
        with self.assertRaisesRegex(release.ReleaseError, "concurrently"):
            self.publish_with(server)
        self.assertTrue(server.release["draft"])

    def test_paginated_asset_listing(self):
        server = FakeGitHubHTTP()
        server.assets = [{"name": str(index)} for index in range(101)]
        with patch.dict(os.environ, CI, clear=True), patch("urllib.request.build_opener", return_value=server):
            self.assertEqual(len(release.remote_assets(release.GitHub(), 123)), 101)
        self.assertEqual(len(server.calls), 2)

    def test_authenticated_redirect_is_denied(self):
        with self.assertRaisesRegex(release.ReleaseError, "redirect"):
            release.NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.invalid/")

    def test_untrusted_upload_url_is_denied(self):
        with patch.dict(os.environ, CI, clear=True), patch("urllib.request.build_opener") as opener:
            api = release.GitHub()
            with self.assertRaisesRegex(release.ReleaseError, "untrusted"):
                api.request("POST", "https://uploads.github.com/repos/other/repo/releases/1/assets?name=x")
            opener.return_value.open.assert_not_called()

    def test_builder_refuses_local_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(release.ReleaseError, "disposable"):
                builder.ci_boundary([self.root], "windows-x64")

    def test_builder_refuses_token_or_outside_runner_temp(self):
        platform = "windows-x64" if os.name == "nt" else "ubuntu-amd64"
        env = {**CI, "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_TEMP": str(self.root)}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(release.ReleaseError, "tokens"):
                builder.ci_boundary([self.root / "work"], platform)
            with self.assertRaisesRegex(release.ReleaseError, "isolated"):
                builder.ci_boundary([self.root.parent / "outside"], platform)

    def test_builder_accepts_the_gx_shell_integration_runner(self):
        platform = "windows-x64" if os.name == "nt" else "ubuntu-amd64"
        env = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
               "GITHUB_REPOSITORY": release.INTEGRATION_REPOSITORY, "RUNNER_TEMP": str(self.root)}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(builder.ci_boundary([self.root / "work"], platform), "github-actions")
        with patch.dict(os.environ, {**env, "GITHUB_REPOSITORY": "attacker/gx_shell"}, clear=True):
            with self.assertRaisesRegex(release.ReleaseError, "disposable"):
                builder.ci_boundary([self.root / "work"], platform)

    def test_builder_local_root_replaces_runner_temp_but_keeps_the_other_checks(self):
        platform = "windows-x64" if os.name == "nt" else "ubuntu-amd64"
        other = "ubuntu-amd64" if os.name == "nt" else "windows-x64"
        local = {"GX_LOCAL_BUILD_ROOT": str(self.root)}
        with patch.dict(os.environ, local, clear=True):
            self.assertEqual(builder.ci_boundary([self.root / "work", self.root / "cache"], platform), "local")
            with self.assertRaisesRegex(release.ReleaseError, "isolated under GX_LOCAL_BUILD_ROOT"):
                builder.ci_boundary([self.root.parent / "outside"], platform)
            with self.assertRaisesRegex(release.ReleaseError, "isolated"):
                builder.ci_boundary([self.root], platform)
            with self.assertRaisesRegex(release.ReleaseError, "platform differ"):
                builder.ci_boundary([self.root / "work"], other)
        with patch.dict(os.environ, {**local, "GH_TOKEN": "unit-test-not-a-real-token"}, clear=True):
            with self.assertRaisesRegex(release.ReleaseError, "tokens"):
                builder.ci_boundary([self.root / "work"], platform)
        with patch.dict(os.environ, {"GX_LOCAL_BUILD_ROOT": str(self.root / "missing")}, clear=True):
            with self.assertRaisesRegex(release.ReleaseError, "existing directory"):
                builder.ci_boundary([self.root / "missing/work"], platform)
        ci = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
              "GITHUB_REPOSITORY": release.INTEGRATION_REPOSITORY, "RUNNER_TEMP": str(self.root)}
        with patch.dict(os.environ, {**ci, **local}, clear=True):
            with self.assertRaisesRegex(release.ReleaseError, "unset it on CI"):
                builder.ci_boundary([self.root / "work"], platform)

    def test_builder_missing_dependency_license_fails(self):
        vendor = self.root / "vendor"
        (vendor / "crate-1").mkdir(parents=True)
        with self.assertRaisesRegex(release.ReleaseError, "no vendored license"):
            builder.license_inventory(vendor)

    def test_dependency_inventory_cannot_omit_locked_inputs(self):
        self.fixture.modify("windows-x64", lambda m: m.update(dependencies=[]))
        with self.assertRaisesRegex(release.ReleaseError, "dependency inventory"):
            self.fixture.verify()

    def test_draft_without_inventory_marker_fails_closed(self):
        server = self.draft_server()
        server.release["body"] = ""
        with self.assertRaisesRegex(release.ReleaseError, "inventory"):
            self.publish_with(server)
        self.assertTrue(all(method == "GET" for method, _, _ in server.calls))

    def build_fixture(self, *, wrong_rust=False, changed_source=False, missing_cargo_license=False,
                      missing_zig_license=False, changed_zig_cache=False, unknown_zig_hash=False, local=False,
                      member_license=None):
        import struct
        import zipfile

        platform = "windows-x64" if os.name == "nt" else "ubuntu-amd64"
        cache = self.root / "build-cache"
        cache.mkdir()
        write_json(self.root / "scripts/packaging/herdr-license-supplements.json", {
            "schema_version": 1, "herdr_revision": HERDR_SHA,
            "texts": {}, "sources": {}, "cargo": [], "reuse": [], "donors": {}, "zig": [],
        })
        lock = copy.deepcopy(self.fixture.lock)
        pinned = lock["herdr"]
        source = cache / "herdr.zip"
        with zipfile.ZipFile(source, "w") as stream:
            stream.writestr("herdr-source/LICENSE", "fixture herdr license")
            stream.writestr("herdr-source/Cargo.toml", '[package]\nname="herdr"\nversion="0.9.1"\n')
            stream.writestr("herdr-source/scripts/package_windows_conpty.ps1", "# test-only script boundary")
            stream.writestr("herdr-source/vendor/portable-pty/LICENSE.md", "fixture portable pty license")
            stream.writestr("herdr-source/vendor/portable-pty/Cargo.toml", '[package]\nname="portable-pty"\nversion="1.0.0"\n')
            stream.writestr("herdr-source/vendor/libghostty-vt/LICENSE", "fixture ghostty license")
            stream.writestr("herdr-source/vendor/libghostty-vt/build.zig.zon", '.{\n .hash = "fixture-zig-hash",\n}\n')
            if member_license:
                stream.writestr("herdr-source/crates/ghostty-vt/Cargo.toml", '[package]\nname="ghostty-vt"\nversion="0.0.0"\n')
                stream.writestr("herdr-source/crates/ghostty-vt/src/lib.rs", "pub fn fixture() {}\n")
        pinned["source"] = {**asset(source), "url": "https://fixture.invalid/herdr.zip"}
        zig_archive = cache / "zig.zip"
        with zipfile.ZipFile(zig_archive, "w") as stream:
            stream.writestr("zig/" + ("zig.exe" if os.name == "nt" else "zig"), "fixture zig")
            stream.writestr("zig/LICENSE", "fixture zig toolchain license")
            stream.writestr("zig/lib/libc/musl/COPYRIGHT", "fixture musl copyright")
        zig_record = {**asset(zig_archive), "url": "https://fixture.invalid/zig.zip"}
        conpty = cache / "conpty.nupkg"
        conpty.write_bytes(b"test-only package")
        pinned["conpty"]["package"] = {**asset(conpty), "url": "https://fixture.invalid/conpty.nupkg"}
        binary = bytearray(128)
        if platform == "windows-x64":
            binary[:2] = b"MZ"
            struct.pack_into("<I", binary, 60, 64)
            binary[64:68] = b"PE\0\0"
            struct.pack_into("<H", binary, 68, 0x8664)
        else:
            binary[:6] = b"\x7fELF\x02\x01"
            struct.pack_into("<H", binary, 18, 62)
            struct.pack_into("<Q", binary, 32, 64)
            struct.pack_into("<HH", binary, 54, 56, 1)
            struct.pack_into("<I", binary, 64, 1)
        calls = []

        def run(argv, cwd, env, *, capture=False):
            calls.append(argv)
            self.assertEqual(env["RUSTFLAGS"], "-C target-feature=+crt-static")
            self.assertEqual(env["RUSTUP_TOOLCHAIN"], "1.96.1-x86_64-pc-windows-msvc" if platform == "windows-x64" else "1.96.1")
            self.assertEqual(env["RUSTUP_AUTO_INSTALL"], "0")
            self.assertEqual(env["HERDR_PACKAGE_MANAGER"], "windows-installer" if platform == "windows-x64" else "deb")
            self.assertEqual(env["HERDR_BUILD_COMMIT"], pinned["revision"])
            if argv == ["rustc", "--version"]:
                return "rustc " + ("9.9.9" if wrong_rust else "1.96.1") + " (fixture)"
            if argv == ["cargo", "--version"]:
                return "cargo 1.96.1 (fixture)"
            if argv[-1] == "version":
                return "0.16.0"
            if "vendor" in argv:
                self.assertIn("--locked", argv)
                vendor = Path(argv[-1])
                (vendor / "fixture-crate").mkdir(parents=True)
                if not missing_cargo_license:
                    (vendor / "fixture-crate/LICENSE").write_text("fixture license", encoding="utf-8")
                (vendor / "fixture-crate/Cargo.toml").write_text('[package]\nname="fixture-crate"\nversion="1.0.0"\n', encoding="utf-8")
                return '[source.crates-io]\nreplace-with="vendored-sources"\n[source.vendored-sources]\ndirectory="fixture"'
            if "metadata" in argv:
                self.assertIn("--offline", argv)
                packages = [
                    {"id": "herdr-fixture", "name": "herdr", "version": "0.9.1", "license": "Apache-2.0", "source": None, "manifest_path": str(cwd / "Cargo.toml")},
                    {"name": "portable-pty", "version": "1.0.0", "source": None, "manifest_path": str(cwd / "vendor/portable-pty/Cargo.toml")},
                    {"name": "fixture-crate", "version": "1.0.0", "source": "registry+fixture", "manifest_path": str(cwd.parent / "cargo-vendor/fixture-crate/Cargo.toml")},
                ]
                if member_license:
                    packages.append({"id": "ghostty-vt-fixture", "name": "ghostty-vt", "version": "0.0.0", "license": member_license,
                                     "source": None, "manifest_path": str(cwd / "crates/ghostty-vt/Cargo.toml")})
                return json.dumps({"packages": packages, "workspace_members": [p["id"] for p in packages if "id" in p]})
            if "build" in argv:
                for flag in ("--release", "--locked", "--offline"):
                    self.assertIn(flag, argv)
                path = Path(env["CARGO_TARGET_DIR"]) / pinned["targets"][platform] / "release" / ("herdr.exe" if platform == "windows-x64" else "herdr")
                path.parent.mkdir(parents=True)
                path.write_bytes(binary)
                if changed_source:
                    (cwd / "LICENSE").write_text("tampered pinned source", encoding="utf-8")
                package_hash = "unknown-hash" if unknown_zig_hash else "fixture-zig-hash"
                package = cwd / "vendor/libghostty-vt/zig-pkg" / package_hash
                package.mkdir(parents=True)
                (package / "README").write_text("fixture Zig source", encoding="utf-8")
                if not missing_zig_license:
                    (package / "LICENSE").write_text("fixture Zig dependency license", encoding="utf-8")
                zig_cache = Path(env["ZIG_GLOBAL_CACHE_DIR"]) / "p"
                zig_cache.mkdir(parents=True)
                with tarfile.open(zig_cache / (package_hash + ".tar.gz"), "w:gz") as stream:
                    for path in package.iterdir():
                        stream.add(path, arcname=package_hash + "/" + path.name)
                if changed_zig_cache:
                    (package / "README").write_text("modified after caching", encoding="utf-8")
                return ""
            if argv[0] == "pwsh":
                self.assertEqual(argv[1:3], ["-NoProfile", "-File"])
                self.assertTrue(argv[3].endswith("package_windows_conpty.ps1"))
                payload = Path(argv[argv.index("-StageDir") + 1])
                for name in pinned["conpty"]["files"]:
                    path = payload / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(bytes(binary) if name == "herdr.exe" else name.encode())
                return ""
            self.fail(str(argv))

        env = {key: value for key, value in CI.items() if key != "GITHUB_TOKEN"}
        env.update(RUNNER_ENVIRONMENT="github-hosted", RUNNER_TEMP=str(self.root))
        if local:
            env = {"GX_LOCAL_BUILD_ROOT": str(self.root)}
        with patch.dict(os.environ, env, clear=True), patch.object(release, "load_lock", return_value=lock), \
                patch.object(builder.deps, "load_lock", return_value=lock), \
                patch.object(builder.deps, "fetch_artifact", side_effect=builder.deps.verify_artifact), \
                patch.dict(builder.ZIG_ARCHIVES, {platform: zig_record}), patch.object(builder.shutil, "which", side_effect=lambda name: name), \
                patch.object(builder, "run", side_effect=run):
            result = builder.build(self.root, platform, self.root / "work", cache, self.root / "herdr-output")
        self.assertTrue(any("--locked" in call and "build" in call for call in calls))
        return result

    def test_builder_mocked_command_boundaries_produce_verified_receipt(self):
        result = self.build_fixture()
        self.assertTrue(result["cargo_vendor_complete"])
        self.assertEqual(result["builder"], "github-actions")
        self.assertEqual(result["revision"], HERDR_SHA)
        self.assertEqual(result["package_manager"], "windows-installer" if os.name == "nt" else "deb")
        self.assertTrue(result["source_artifacts"])
        self.assertTrue(result["license_artifacts"])
        self.assertTrue((self.root / "herdr-output/herdr-build.json").is_file())

    def test_builder_wrong_rust_fails_before_build(self):
        with self.assertRaisesRegex(release.ReleaseError, "Rust/Cargo"):
            self.build_fixture(wrong_rust=True)
        self.assertFalse((self.root / "herdr-output/herdr-build.json").exists())

    def test_builder_original_source_tampering_rejected(self):
        with self.assertRaisesRegex(release.ReleaseError, "modified pinned source"):
            self.build_fixture(changed_source=True)
        self.assertFalse((self.root / "herdr-output/herdr-build.json").exists())

    def test_builder_materializes_cargo_path_zig_and_runtime_license_texts(self):
        receipt = self.build_fixture()
        output = self.root / "herdr-output"
        inventory = receipt["license_inventory"]
        self.assertEqual({item["ecosystem"] for item in inventory}, {"cargo", "cargo-path", "vendored", "zig", "zig-toolchain"})
        self.assertTrue(receipt["zig_dependencies_complete"])
        paths = {item["path"] for item in receipt["license_artifacts"]}
        self.assertIn("redistribution/licenses/cargo/fixture-crate/LICENSE", paths)
        self.assertIn("redistribution/licenses/cargo-path/portable-pty/LICENSE.md", paths)
        self.assertIn("redistribution/licenses/zig/fixture-zig-hash/LICENSE", paths)
        self.assertIn("redistribution/licenses/zig-toolchain/zig-0.16.0/lib/libc/musl/COPYRIGHT", paths)
        for item in receipt["license_artifacts"]:
            path = output / item["path"]
            self.assertNotEqual(path.suffix, ".json")
            self.assertEqual(release.digest(path), item["sha256"])
            self.assertIn(b"fixture", path.read_bytes())
        self.assertEqual((output / "redistribution/licenses/zig/fixture-zig-hash/LICENSE").read_text(), "fixture Zig dependency license")

    def test_builder_cargo_license_missing_cannot_claim_complete(self):
        with self.assertRaisesRegex(release.ReleaseError, "no vendored license"):
            self.build_fixture(missing_cargo_license=True)
        self.assertFalse((self.root / "herdr-output/herdr-build.json").exists())

    def test_builder_local_receipt_records_the_local_builder(self):
        receipt = self.build_fixture(local=True)
        self.assertEqual(receipt["builder"], "local")
        self.assertEqual(release.read_json(self.root / "herdr-output/herdr-build.json")["builder"], "local")

    def test_builder_workspace_member_inherits_the_matching_root_license(self):
        receipt = self.build_fixture(member_license="Apache-2.0")
        entry = next(item for item in receipt["license_inventory"] if item["package"] == "ghostty-vt")
        self.assertEqual(entry["ecosystem"], "cargo-path")
        self.assertEqual(entry["source_identity"]["license_inherited_from"], {"package": "herdr", "license": "Apache-2.0", "texts": ["LICENSE"]})
        self.assertEqual([item["path"] for item in entry["licenses"]], ["redistribution/licenses/cargo-path/ghostty-vt/workspace-root/LICENSE"])
        self.assertEqual((self.root / "herdr-output" / entry["licenses"][0]["path"]).read_text(encoding="utf-8"), "fixture herdr license")
        release.verify_herdr_license_inventory(receipt)

    def test_builder_workspace_member_with_another_license_is_still_rejected(self):
        with self.assertRaisesRegex(release.ReleaseError, "ghostty-vt: no vendored license"):
            self.build_fixture(member_license="MIT")
        self.assertFalse((self.root / "herdr-output/herdr-build.json").exists())

    def test_workspace_license_needs_membership_and_no_text_of_its_own(self):
        source = self.root / "workspace"
        (source / "crates/member").mkdir(parents=True)
        (source / "LICENSE").write_text("fixture root license", encoding="utf-8")
        (source / "crates/member/Cargo.toml").write_text("[package]\n", encoding="utf-8")
        source = source.resolve()
        root = source / "crates/member"
        names = {item["path"] for item in builder.deps.tree_manifest(source)}
        workspace = {"name": "herdr", "license": "Apache-2.0"}
        member = {"id": "member-id", "name": "member", "license": "Apache-2.0"}
        extra, identity = builder.workspace_license(source, root, member, workspace, {"member-id"}, names, {"Cargo.toml"})
        self.assertEqual(extra, [(source / "LICENSE", "workspace-root/LICENSE")])
        self.assertEqual(identity["license_inherited_from"]["texts"], ["LICENSE"])
        self.assertEqual(builder.workspace_license(source, root, member, workspace, set(), names, {"Cargo.toml"}), ([], {}))
        self.assertEqual(builder.workspace_license(source, root, {**member, "license_file": "COPYING"}, workspace, {"member-id"}, names, {"Cargo.toml"}), ([], {}))
        (root / "LICENSE").write_text("member license", encoding="utf-8")
        self.assertEqual(builder.workspace_license(source, root, member, workspace, {"member-id"}, names, {"Cargo.toml", "LICENSE"}), ([], {}))

    def test_builder_zig_license_missing_cannot_claim_complete(self):
        with self.assertRaisesRegex(release.ReleaseError, "no vendored license"):
            self.build_fixture(missing_zig_license=True)
        self.assertFalse((self.root / "herdr-output/herdr-build.json").exists())

    def test_builder_zig_cache_must_match_compiled_sources(self):
        with self.assertRaisesRegex(release.ReleaseError, "Zig cache differs"):
            self.build_fixture(changed_zig_cache=True)
        self.assertFalse((self.root / "herdr-output/herdr-build.json").exists())

    def test_builder_zig_packages_must_reach_fixed_zon_hashes(self):
        with self.assertRaisesRegex(release.ReleaseError, "not reachable"):
            self.build_fixture(unknown_zig_hash=True)
        self.assertFalse((self.root / "herdr-output/herdr-build.json").exists())

    def test_zon_named_package_hashes_include_semver_dots(self):
        path = self.root / "build.zig.zon"
        values = {"translate_c-0.0.0-Q_BUWhVNBwDOEcIqub4VFPJPB6D9dgwzUMHTX5KWr8Xr", "uucode-0.2.0-ZZjBPlK5VADj7fdoq7G8LIHzD5o6FSkcBXXrRWr4jnrA"}
        path.write_text("\n".join(f' .hash = "{value}",' for value in values), encoding="utf-8")
        self.assertEqual(builder.zon_hashes([path]), values)

    def test_source_archive_licenses_alone_do_not_cover_binary_payload(self):
        self.fixture.modify("windows-x64", lambda m: m.update(payload=[r for r in m["payload"] if not r["path"].startswith("licenses/")]))
        with self.assertRaisesRegex(release.ReleaseError, "license text missing from binary"):
            self.fixture.verify()

    def test_license_json_inventory_cannot_replace_full_text(self):
        self.fixture.modify("windows-x64", lambda m: m["herdr_build"].pop("license_inventory"))
        with self.assertRaisesRegex(release.ReleaseError, "license inventory missing"):
            self.fixture.verify()

    def test_license_archive_rejects_json_disguised_as_license(self):
        path = self.root / "license-only.tar.xz"
        records = archive(path, {"LICENSE": b'{"license":"MIT"}'})
        with self.assertRaisesRegex(release.ReleaseError, "not a binary/JSON"):
            release.verify_archive(path, records, text_paths={"LICENSE"})

    def test_lifecycle_required_checks_are_identical(self):
        import gx_lifecycle
        self.assertEqual(gx_lifecycle.COMMON_CHECKS, release.COMMON_CHECKS)
        self.assertEqual(gx_lifecycle.WINDOWS_CHECKS, release.WINDOWS_CHECKS)
        self.assertEqual(gx_lifecycle.LINUX_CHECKS, release.LINUX_CHECKS)

    def test_real_lifecycle_pending_receipt_is_rejected_by_release(self):
        import gx_lifecycle
        folder = self.root / "lifecycle-producer"
        for subdir in ("logs", "results", "snapshots"):
            (folder / subdir).mkdir(parents=True)
        (folder / "logs/terminal.txt").write_text("SYNTHETIC integration fixture; not a native test", encoding="utf-8")
        checks = {"install": {"status": "passed", "evidence": ["logs/terminal.txt"]}}
        write_json(folder / "results/checks.json", {"status": "passed", "checks": checks})
        installer = next(item for item in release.read_json(self.fixture.manifests["windows-x64"])["artifacts"] if item["role"] == "installer")
        package = {"version": VERSION, "source_revision": SHA, "installer": installer}
        plan = {"evidence": str(folder), "platform": "windows-x64", "environment": "windows-clean",
                "effective": package, "initial": package, "authorization": "unit-test-only"}
        receipt_path, exit_code = gx_lifecycle.finalize(plan, 0)
        self.assertEqual(exit_code, 3)
        receipt = release.read_json(receipt_path)
        self.assertEqual(receipt["source_revision"], SHA)
        self.assertEqual(receipt["installer_sha256"], installer["sha256"])
        self.assertEqual(set(receipt["checks"]), release.COMMON_CHECKS | release.WINDOWS_CHECKS)
        release.verify_archive(folder / receipt["evidence_archive"]["filename"], receipt["evidence_files"])
        with self.assertRaisesRegex(release.ReleaseError, "evidence_reviewed"):
            release.verify_validation(folder, "windows-x64", "windows-clean", VERSION, SHA, installer)

    def test_workflow_uses_the_actual_lifecycle_cli_and_separate_evidence(self):
        text = (release.ROOT / ".github/workflows/gx-release.yml").read_text(encoding="utf-8")
        self.assertNotIn("tests/gx_package_lifecycle.py", text)
        self.assertNotIn("--disposable-ci", text)
        self.assertIn("python scripts/gx_lifecycle.py --manifest $manifest --evidence", text)
        self.assertIn("/opt/gx-python/bin/python3.14 scripts/gx_lifecycle.py --manifest", text)
        self.assertIn("--run-as-user gx-smoke", text)
        self.assertIn("--env GITHUB_REPOSITORY=gx0404/ohmyzsh", text)
        self.assertIn("needs: [prepare, build, windows-lifecycle, linux-lifecycle]", text)
        self.assertIn("name: diagnostics-windows-clean", text)
        self.assertIn("name: gx-evidence-windows-clean", text)
        self.assertIn("*.validation.json", text)
        self.assertIn("*.evidence.tar.xz", text)

    def test_checked_in_split_lock_matches_producer_contract(self):
        import gx_dependencies
        expected = gx_dependencies.load_lock()
        actual = release.load_lock(release.ROOT)
        self.assertEqual(actual["lock_digest"], expected["lock_digest"])
        for platform in release.TARGETS:
            inventory = [{k: item[k] for k in ("filename", "sha256", "size", "url", "repository_path", "git_repository", "commit", "prefix") if k in item}
                         for item in gx_dependencies.all_artifacts(expected, platform)]
            self.assertEqual(release.dependency_inventory(actual, platform), sorted(inventory, key=lambda item: item["filename"]))

    def test_split_lock_checksum_and_runtime_coverage_are_mandatory(self):
        lock = release.read_json(release.ROOT / "scripts/packaging/dependencies.json")
        msys = release.read_json(release.ROOT / "scripts/packaging" / lock["msys2"]["file"])
        redistribution = release.read_json(release.ROOT / "scripts/packaging" / lock["redistribution"]["file"])
        repo = self.root / "split-lock"
        location = repo / "scripts/packaging"
        write_json(location / "dependencies.json", lock)
        write_json(location / lock["msys2"]["file"], msys)
        altered = copy.deepcopy(redistribution)
        altered["msys2_components"][0]["runtime_packages"] = []
        write_json(location / lock["redistribution"]["file"], altered)
        with self.assertRaisesRegex(release.ReleaseError, "redistribution lock checksum"):
            release.load_lock(repo)
        lock["redistribution"]["canonical_sha256"] = release.canonical_digest(altered)
        write_json(location / "dependencies.json", lock)
        with self.assertRaisesRegex(release.ReleaseError, "each locked MSYS2 package"):
            release.load_lock(repo)

    def test_repository_notice_inventory_preserves_checked_source(self):
        component = self.fixture.lock["components"][0]
        item = component["build_instructions"][0]
        item.pop("url")
        item["repository_path"] = "notices/GX-DEPENDENCY-BUILD.txt"
        inventory = release.dependency_inventory(self.fixture.lock, "ubuntu-amd64")
        self.assertIn({k: item[k] for k in ("filename", "sha256", "repository_path")}, inventory)
        item["repository_path"] = "../outside"
        with self.assertRaises(release.ReleaseError):
            release.dependency_inventory(self.fixture.lock, "ubuntu-amd64")

    def test_permissive_source_policy_is_explicit_and_does_not_waive_licenses(self):
        component = self.fixture.lock["components"][0]
        component["source_policy"] = {"kind": "not-required", "basis": "Unit-test fixture MIT redistribution terms"}
        component["license_expression"] = "MIT"
        component["sources"] = []
        for platform in release.TARGETS:
            self.fixture.modify(platform, lambda m, p=platform: m.update(dependencies=release.dependency_inventory(self.fixture.lock, p)))
        self.assertEqual(len(self.fixture.verify()), 14)
        component["license_expression"] = "GPL-3.0"
        with self.assertRaisesRegex(release.ReleaseError, "permissive-license"):
            self.fixture.verify()
        component["license_expression"] = "MIT"
        component["licenses"] = []
        with self.assertRaisesRegex(release.ReleaseError, "missing locked licenses"):
            self.fixture.verify()

    def test_linux_musl_default_null_rustflags_is_explicitly_supported(self):
        self.fixture.modify("ubuntu-amd64", lambda m: m["herdr_build"].update(rustflags=None, effective_crt_static=True))
        self.assertEqual(len(self.fixture.verify()), 14)

    def test_linux_null_rustflags_cannot_hide_dynamic_or_unknown_targets(self):
        for change in ({"target": "x86_64-unknown-linux-gnu"}, {"effective_crt_static": False}, {"effective_crt_static": None}, {"rustflags": "-C target-feature=-crt-static"}):
            build = release.read_json(self.fixture.manifests["ubuntu-amd64"])["herdr_build"]
            build.update(rustflags=None, effective_crt_static=True)
            build.update(change)
            with self.subTest(change=change), self.assertRaises(release.ReleaseError):
                release.verify_herdr_metadata(build, "ubuntu-amd64", self.fixture.lock)

    def test_windows_null_rustflags_remains_forbidden(self):
        build = release.read_json(self.fixture.manifests["windows-x64"])["herdr_build"]
        build.update(rustflags=None, effective_crt_static=True)
        with self.assertRaisesRegex(release.ReleaseError, "Windows requires explicit"):
            release.verify_herdr_metadata(build, "windows-x64", self.fixture.lock)

    def test_missing_rustflags_is_not_a_recorded_null(self):
        build = release.read_json(self.fixture.manifests["ubuntu-amd64"])["herdr_build"]
        build.pop("rustflags")
        with self.assertRaisesRegex(release.ReleaseError, "actual rustflags"):
            release.verify_herdr_metadata(build, "ubuntu-amd64", self.fixture.lock)

    def linux_receipt_fixture(self, kind=1):
        import struct
        folder = self.root / "real-byte-contract"
        (folder / "payload").mkdir(parents=True)
        binary = bytearray(256)
        binary[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", binary, 18, 62)
        struct.pack_into("<Q", binary, 32, 64)
        struct.pack_into("<HH", binary, 54, 56, 1)
        struct.pack_into("<I", binary, 64, kind)
        if kind == 2:
            struct.pack_into("<Q", binary, 72, 128)
            struct.pack_into("<Q", binary, 96, 16)
            struct.pack_into("<q", binary, 128, 1)
        (folder / "payload/herdr").write_bytes(binary)
        info = release.read_json(self.fixture.manifests["ubuntu-amd64"])
        build = info["herdr_build"]
        build.update(rustflags=None, effective_crt_static=True, files=[record("herdr", binary)])
        source = next(item for item in info["artifacts"] if item["role"] == "corresponding-sources")
        with tarfile.open(self.root / source["filename"], "r:xz") as stream:
            for item in build["source_artifacts"] + build["license_artifacts"]:
                path = folder / item["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(stream.extractfile("dependencies/herdr/" + item["path"]).read())
        write_json(folder / "herdr-build.json", build)
        return folder

    def test_null_static_receipt_checks_actual_elf_bytes(self):
        folder = self.linux_receipt_fixture()
        result = release.verify_herdr_directory(folder, "ubuntu-amd64", self.fixture.lock)
        self.assertIsNone(result["rustflags"])
        self.assertTrue(result["effective_crt_static"])

    def test_forged_static_receipt_with_pt_interp_is_rejected(self):
        folder = self.linux_receipt_fixture(kind=3)
        with self.assertRaisesRegex(release.ReleaseError, "PT_INTERP"):
            release.verify_herdr_directory(folder, "ubuntu-amd64", self.fixture.lock)

    def test_forged_static_receipt_with_dt_needed_is_rejected(self):
        folder = self.linux_receipt_fixture(kind=2)
        with self.assertRaisesRegex(release.ReleaseError, "DT_NEEDED"):
            release.verify_herdr_directory(folder, "ubuntu-amd64", self.fixture.lock)

    def supplemental_crate_fixture(self):
        store = builder.load_supplements(release.ROOT)
        rule = store["data"]["cargo"][0]
        upstream = store["data"]["sources"][rule["source"]]
        root = self.root / "supplemental-crate"
        root.mkdir()
        vcs = root / ".cargo_vcs_info.json"
        write_json(vcs, {"git": {"sha1": upstream["revision"]}, "path_in_vcs": rule["crate_path"]})
        write_json(root / ".cargo-checksum.json", {"package": rule["checksum"], "files": {".cargo_vcs_info.json": release.digest(vcs)}})
        package = {"name": rule["name"], "version": rule["version"], "license": rule["license"], "repository": upstream["repository"]}
        return store, root, package

    def test_fixed_cargo_supplement_is_copied_without_modifying_vendor(self):
        store, root, package = self.supplemental_crate_fixture()
        before = builder.deps.tree_manifest(root)
        extra, identity = builder.cargo_supplement(root, package, {}, store)
        self.assertEqual(len(extra), 2)
        entry = builder.copy_licenses(root, [], self.root / "notice-output", "cargo", package["name"], identity, extra)
        self.assertEqual(builder.deps.tree_manifest(root), before)
        self.assertTrue(all(item["path"].startswith("redistribution/licenses/cargo/") for item in entry["licenses"]))
        self.assertIn("Permission is hereby granted", (self.root / "notice-output" / entry["licenses"][1]["path"]).read_text())
        self.assertTrue(all("/" + identity["license_upstream_commit"] + "/" in item["url"] or "/spdx/" in item["url"] for item in identity["supplemental_texts"]))

    def test_cargo_supplement_wrong_checksum_or_vcs_is_rejected(self):
        store, root, package = self.supplemental_crate_fixture()
        path = root / ".cargo-checksum.json"
        info = release.read_json(path)
        original = copy.deepcopy(info)
        info["package"] = "0" * 64
        write_json(path, info)
        with self.assertRaisesRegex(release.ReleaseError, "checksum/license"):
            builder.cargo_supplement(root, package, {}, store)
        write_json(path, original)
        write_json(root / ".cargo_vcs_info.json", {"git": {"sha1": "0" * 40}, "path_in_vcs": "wrong"})
        with self.assertRaisesRegex(release.ReleaseError, ".vcs evidence"):
            builder.cargo_supplement(root, package, {}, store)

    def test_cargo_supplement_wrong_repository_is_rejected(self):
        store, root, package = self.supplemental_crate_fixture()
        package["repository"] = "https://github.com/unrelated/repository"
        with self.assertRaisesRegex(release.ReleaseError, "repository differs"):
            builder.cargo_supplement(root, package, {}, store)

    def test_supplement_lock_has_exact_known_27_crates_and_one_zig_package(self):
        data = builder.load_supplements(release.ROOT)["data"]
        self.assertEqual(len(data["cargo"]), 25)
        self.assertEqual(len(data["reuse"]), 2)
        self.assertEqual(len(data["zig"]), 1)
        self.assertEqual(data["zig"][0]["package_hash"], "N-V-__8AAEFmBABuDGOKxAI6VMg41b9euMZ-z7HS9EcUdaor")
        self.assertEqual(data["texts"]["r-efi-6"]["path"], "AUTHORS")
        self.assertNotIn("ANGLE", json.dumps(data))

    def test_theme_supplement_is_the_original_collection_license_not_theme_comments(self):
        store = builder.load_supplements(release.ROOT)
        files, identity = builder.supplemental_texts(store, store["data"]["zig"][0]["source"])
        self.assertEqual(len(files), 1)
        text = files[0][0].read_text()
        self.assertIn("Permission is hereby granted", text)
        self.assertIn("copyright/license for each individual theme belongs to the author", text)
        self.assertEqual(identity["license_upstream_commit"], "752a9c079396cc9939b86e893578ed81e80c140f")

    def test_copying_rust_source_is_not_a_license(self):
        root = self.root / "license-names"
        (root / "src").mkdir(parents=True)
        (root / "LICENSE").write_text("fixture legal text", encoding="utf-8")
        (root / "src/copying.rs").write_text("pub struct Copying;", encoding="utf-8")
        (root / "src/licenses.rs").write_text("pub struct Licenses;", encoding="utf-8")
        self.assertEqual([p.name for p in builder.license_paths(root)], ["LICENSE"])
        with self.assertRaisesRegex(release.ReleaseError, "source file name is not license"):
            release.verify_license_text(b"pub struct Copying;", "src/copying.rs")
        (root / "LICENSE").unlink()
        with self.assertRaisesRegex(release.ReleaseError, "no vendored license"):
            builder.license_paths(root)

    def test_large_rust_toolchain_copyright_is_not_truncated(self):
        content = b"<!DOCTYPE html><title>Copyright notices</title>" + b" " * (9 * 1024 * 1024)
        release.verify_license_text(content, "vendored/rust-runtime/COPYRIGHT.html")

    def test_complete_copyright_header_notice_is_retained(self):
        root = self.root / "copyright-header"
        root.mkdir()
        (root / "LICENSE").write_text("fixture root notice", encoding="utf-8")
        content = b'/* Redistribution and use in source and binary forms are permitted. THIS SOFTWARE IS PROVIDED AS IS. */'
        (root / "copyright.h").write_bytes(content)
        self.assertIn(root / "copyright.h", builder.license_paths(root))
        release.verify_license_text(content, "copyright.h")

    def test_materialized_known_theme_supplement_without_vendor_mutation(self):
        store = builder.load_supplements(release.ROOT)
        package_hash = store["data"]["zig"][0]["package_hash"]
        source = self.root / "theme-source"
        ghostty = source / "vendor/libghostty-vt"
        ghostty.mkdir(parents=True)
        (ghostty / "LICENSE").write_text("fixture ghostty license", encoding="utf-8")
        (ghostty / "build.zig.zon").write_text(f'.{{\n .hash = "{package_hash}",\n}}', encoding="utf-8")
        original = builder.deps.tree_manifest(source)
        package = ghostty / "zig-pkg" / package_hash
        package.mkdir(parents=True)
        (package / "theme").write_text("# individual author notice\nbackground=#ffffff", encoding="utf-8")
        cache = self.root / "theme-cache"
        cache.mkdir()
        with tarfile.open(cache / (package_hash + ".tar.gz"), "w:gz") as stream:
            stream.add(package / "theme", arcname=package_hash + "/theme")
        toolchain = self.root / "zig-toolchain"
        toolchain.mkdir()
        (toolchain / "LICENSE").write_text("fixture toolchain license", encoding="utf-8")
        before = builder.deps.tree_manifest(package)
        output = self.root / "theme-output"
        result = builder.zig_licenses(source, original, cache, toolchain, output, "windows-x64", "a" * 64, store)
        self.assertEqual(builder.deps.tree_manifest(package), before)
        selected = next(item for item in result if item["ecosystem"] == "zig")
        self.assertEqual(len(selected["licenses"]), 1)
        self.assertIn("Copyright (c) 2011 to Present Mark Badolato", (output / selected["licenses"][0]["path"]).read_text())

    def donor_fixture(self):
        store = builder.load_supplements(release.ROOT)
        store["data"] = copy.deepcopy(store["data"])
        rule = store["data"]["reuse"][0]
        donor = store["data"]["donors"][rule["donor"]]
        root = self.root / "winapi-target"
        source = self.root / "winapi-donor"
        root.mkdir()
        source.mkdir()
        write_json(root / ".cargo-checksum.json", {"package": rule["checksum"], "files": {}})
        checksums = {}
        for item in donor["files"]:
            content = ("TEST donor license " + item["path"]).encode()
            (source / item["path"]).write_bytes(content)
            item.update(sha256=checksum(content), size=len(content))
            checksums[item["path"]] = item["sha256"]
        write_json(source / ".cargo-checksum.json", {"package": donor["checksum"], "files": checksums})
        package = {"name": rule["name"], "version": rule["version"], "repository": rule["repository"], "license": rule["license"]}
        donor_package = {"name": donor["name"], "version": donor["version"], "repository": donor["repository"], "license": rule["license"]}
        return store, root, package, source, {source: donor_package}

    def test_winapi_reuse_requires_exact_family_source_and_text_checksums(self):
        store, root, package, donor, metadata = self.donor_fixture()
        extra, identity = builder.cargo_supplement(root, package, metadata, store)
        self.assertEqual(len(extra), 2)
        self.assertIn("license_origin", identity)
        (donor / "LICENSE-MIT").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(release.ReleaseError, "donor text checksum"):
            builder.cargo_supplement(root, package, metadata, store)

    def test_winapi_reuse_unknown_donor_is_rejected(self):
        store, root, package, _, _ = self.donor_fixture()
        with self.assertRaisesRegex(release.ReleaseError, "donor is missing"):
            builder.cargo_supplement(root, package, {}, store)

    def test_supplement_license_change_is_rejected(self):
        store, root, package = self.supplemental_crate_fixture()
        package["license"] = "GPL-3.0"
        with self.assertRaisesRegex(release.ReleaseError, "checksum/license"):
            builder.cargo_supplement(root, package, {}, store)

    def zsh_release_fixture(self):
        import struct
        import gx_build_zsh
        root = self.root / "zsh-proof-fixture"
        root.mkdir()
        raw = bytearray(128)
        raw[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", raw, 18, 62)
        struct.pack_into("<Q", raw, 32, 64)
        struct.pack_into("<HH", raw, 54, 56, 1)
        struct.pack_into("<I", raw, 64, 1)
        data = {"libexec/zsh/zsh": bytes(raw), "bin/zsh": gx_build_zsh.WRAPPER,
                "share/zsh/functions/compinit": b"fixture completion", "share/zsh/site-functions/.gx-empty": b"fixture site",
                "share/licenses/zsh/LICENCE": b"fixture Zsh license"}
        def material(name):
            return {"filename": name, "sha256": checksum(name.encode()), "url": "https://fixture.invalid/" + name}
        pinned = {"schema_version": 1, "version": "5.9.2+gx-metafied-paths", "source": material("zsh.tar.xz"),
                  "gx_patch": material("gx.patch"), "license_sha256": checksum(data["share/licenses/zsh/LICENCE"]),
                  "functions_count": 1, "functions_canonical_sha256": release.canonical_digest([record("compinit", data["share/zsh/functions/compinit"])]),
                  "linux_toolchain": {"kit": [], "package_records_digest": "a" * 64, "package_count": 10},
                  "platforms": {"ubuntu-amd64": {"modules": material("modules"), "patches": [], "allowed_needed": ["libc.so.6"],
                    "post_gx_source_sha256": {"Src/init.c": "b" * 64}, "toolchain_status": "verified-Ubuntu-20.04-SDK"}}}
        binary = root / "binary"
        binary.write_bytes(raw)
        receipt = {"schema_version": 1, "platform": "ubuntu-amd64", "version": pinned["version"],
                   "source_sha256": pinned["source"]["sha256"], "gx_patch_sha256": pinned["gx_patch"]["sha256"],
                   "static_modules": True, "modules_sha256": pinned["platforms"]["ubuntu-amd64"]["modules"]["sha256"],
                   "fuzz_allowed": 0, "external_dynamic_modules_supported": False,
                   "post_gx_source_sha256": pinned["platforms"]["ubuntu-amd64"]["post_gx_source_sha256"],
                   "source_lock_digest": release.canonical_digest(pinned), "binary_sha256": checksum(raw),
                   "abi": gx_build_zsh.binary_abi(binary, "ubuntu-amd64"), "files": [record(n, b) for n, b in data.items()],
                   "toolchain": {"sdk_packages_digest": "a" * 64, "sdk_package_count": 10, "sdk_signature_chain_verified": True},
                   "commands": ["TEST ONLY synthetic compiler boundary"]}
        materials = {"redistribution/" + item["filename"]: item["filename"].encode() for item in gx_build_zsh.source_artifacts(pinned, "ubuntu-amd64")}
        materials.update({"redistribution/gx_build_zsh.py": b"fixture source", "redistribution/gx_dependencies.py": b"fixture source",
                          "redistribution/zsh-runtime-lock.json": json.dumps(pinned).encode(),
                          "redistribution/BUILD.json": json.dumps({"tools": receipt["toolchain"], "commands": receipt["commands"], "binary_sha256": receipt["binary_sha256"]}).encode()})
        receipt["source_artifacts"] = [record(n, b) for n, b in materials.items()]
        materials["redistribution/ZSH-LICENCE.txt"] = data["share/licenses/zsh/LICENCE"]
        receipt["license_artifacts"] = [record("redistribution/ZSH-LICENCE.txt", data["share/licenses/zsh/LICENCE"])]
        runtime = root / "runtime.tar.xz"
        archive(runtime, {"payload/" + n: b for n, b in data.items()})
        sources = root / "sources.tar.xz"
        redistributed = archive(sources, {"dependencies/zsh/" + n: b for n, b in materials.items()})
        info = {"platform": "ubuntu-amd64", "zsh_build": receipt, "zsh_overlay": [],
                "payload": [record("usr/lib/ohmyzsh-gx/" + n, b) for n, b in data.items()], "redistribution": redistributed}
        return info, {"zsh_data": pinned}, runtime, sources, data

    def test_zsh_runtime_proof_reuses_real_producer_binary_and_function_verifier(self):
        info, lock, runtime, sources, _ = self.zsh_release_fixture()
        release.verify_zsh_runtime(info, lock, runtime, sources)

    def test_zsh_metadata_rejects_source_patch_modules_dynamic_or_unknown_lock(self):
        info, lock, _, _, _ = self.zsh_release_fixture()
        for change in ({"source_sha256": "0" * 64}, {"gx_patch_sha256": "0" * 64}, {"modules_sha256": "0" * 64},
                       {"static_modules": False}, {"external_dynamic_modules_supported": True}, {"source_lock_digest": "0" * 64}):
            altered = copy.deepcopy(info)
            altered["zsh_build"].update(change)
            with self.subTest(change=change), self.assertRaises(release.ReleaseError):
                release.verify_zsh_metadata(altered, lock)
        with self.assertRaisesRegex(release.ReleaseError, "known source-pinned"):
            release.verify_zsh_metadata(info, {})

    def test_zsh_actual_binary_change_is_rejected_even_when_installer_json_is_unchanged(self):
        info, lock, runtime, sources, data = self.zsh_release_fixture()
        data["libexec/zsh/zsh"] += b"tampered"
        archive(runtime, {"payload/" + n: b for n, b in data.items()})
        with self.assertRaisesRegex(release.ReleaseError, "size mismatch"):
            release.verify_zsh_runtime(info, lock, runtime, sources)

    def test_zsh_forged_abi_is_recomputed_from_real_bytes(self):
        info, lock, runtime, sources, _ = self.zsh_release_fixture()
        info["zsh_build"]["abi"]["maximum_glibc"] = "2.29"
        with self.assertRaisesRegex(ValueError, "differs from actual binary"):
            release.verify_zsh_runtime(info, lock, runtime, sources)

    def test_zsh_high_glibc_and_unknown_shared_library_are_rejected(self):
        import gx_build_zsh
        info, lock, runtime, sources, _ = self.zsh_release_fixture()
        for values in ({"maximum_glibc": "2.35"}, {"needed": ["libunexpected.so"]}):
            abi = {**info["zsh_build"]["abi"], **values}
            with self.subTest(values=values), patch.object(gx_build_zsh, "binary_abi", return_value=abi), self.assertRaises(ValueError):
                release.verify_zsh_runtime(info, lock, runtime, sources)

    def test_zsh_function_tree_cannot_change_with_a_forged_receipt(self):
        info, lock, runtime, sources, data = self.zsh_release_fixture()
        name = "share/zsh/functions/compinit"
        data[name] = b"tampered function tree"
        info["zsh_build"]["files"] = [record(n, b) for n, b in data.items()]
        info["payload"] = [record("usr/lib/ohmyzsh-gx/" + n, b) for n, b in data.items()]
        archive(runtime, {"payload/" + n: b for n, b in data.items()})
        with self.assertRaisesRegex(ValueError, "functions receipt differs"):
            release.verify_zsh_runtime(info, lock, runtime, sources)

    def test_windows_overlay_requires_exact_old_new_digest_and_removal(self):
        info, lock, _, _, _ = self.zsh_release_fixture()
        old = "1" * 64
        binary = info["zsh_build"]["binary_sha256"]
        policy = copy.deepcopy(lock["zsh_data"]["platforms"]["ubuntu-amd64"])
        policy.update(replacement_paths=["runtime/msys64/usr/bin/zsh.exe"], remove_original_paths=["runtime/msys64/usr/bin/msys-zsh.dll"],
                      original_runtime_files={"runtime/msys64/usr/bin/zsh.exe": old, "runtime/msys64/usr/bin/msys-zsh.dll": old})
        lock["zsh_data"]["platforms"]["windows-x64"] = policy
        info["platform"] = info["zsh_build"]["platform"] = "windows-x64"
        info["zsh_build"]["source_lock_digest"] = release.canonical_digest(lock["zsh_data"])
        info["zsh_build"]["files"] = [{"path": "runtime/msys64/usr/bin/zsh.exe", "sha256": binary, "size": 128}]
        info["payload"] = copy.deepcopy(info["zsh_build"]["files"])
        info["zsh_overlay"] = [{"path": "runtime/msys64/usr/bin/msys-zsh.dll", "old_sha256": old, "action": "removed"},
                               {"path": "runtime/msys64/usr/bin/zsh.exe", "old_sha256": old, "new_sha256": binary, "action": "replaced"}]
        release.verify_zsh_metadata(info, lock)
        info["zsh_overlay"][1]["old_sha256"] = "2" * 64
        with self.assertRaisesRegex(release.ReleaseError, "old/new SHA"):
            release.verify_zsh_metadata(info, lock)
        info["zsh_overlay"][1]["old_sha256"] = old
        info["payload"].append({"path": "runtime/msys64/usr/bin/msys-zsh.dll", "sha256": old, "size": 5})
        with self.assertRaisesRegex(release.ReleaseError, "dynamic MSYS Zsh leaked"):
            release.verify_zsh_metadata(info, lock)

    def test_workflow_builds_and_verifies_patched_runtime_before_assembly(self):
        text = (release.ROOT / ".github/workflows/gx-release.yml").read_text(encoding="utf-8")
        self.assertIn("gx_build_zsh.py fetch --platform", text)
        self.assertIn("gx_build_zsh.py build --platform", text)
        self.assertIn("gx_build_zsh.py verify --platform", text)
        self.assertIn('--zsh-build "$RUNNER_TEMP/gx-zsh"', text)
        self.assertIn("gx_release.py runtime-proof", text)
        self.assertIn("/usr/share/keyrings/ubuntu-archive-keyring.gpg", text)
        self.assertNotIn("--allow-dirty", text)

    def test_runtime_proof_creation_and_native_package_verification_end_to_end(self):
        zsh_info, zsh_lock, _, zsh_sources, payload = self.zsh_release_fixture()
        platform = "ubuntu-amd64"
        self.fixture.lock["zsh_data"] = zsh_lock["zsh_data"]
        manifest_path = self.fixture.manifests[platform]
        info = release.read_json(manifest_path)
        sources = self.root / info["artifacts"][1]["filename"]
        data = {}
        for source_archive in (sources, zsh_sources):
            with tarfile.open(source_archive, "r:xz") as stream:
                for member in stream:
                    if member.isfile():
                        data[member.name] = stream.extractfile(member).read()
        redistributed = archive(sources, data)
        info.update(zsh_build=zsh_info["zsh_build"], zsh_overlay=[], redistribution=redistributed,
                    dependencies=release.dependency_inventory(self.fixture.lock, platform))
        info["payload"].extend(zsh_info["payload"])
        info["artifacts"][1].update(asset(sources))
        write_json(manifest_path, info)
        self.fixture.refresh(platform)
        stage = self.root / "native-stage"
        write_json(stage / "package-manifest.json", info)
        for name, content in payload.items():
            target = stage / "payload/usr/lib/ohmyzsh-gx" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        for name, content in data.items():
            target = stage / "redistribution" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        proof = release.create_runtime_proof(stage, self.root, platform, VERSION, SHA, self.fixture.lock)
        files, _ = release.verify_package(self.root, platform, VERSION, SHA, self.fixture.lock)
        self.assertEqual(len(files), 5)
        self.assertIn(proof, files)
        self.assertIn(proof.name, (self.root / f"ohmyzsh-gx_{VERSION}_amd64.sha256").read_text())
        with self.assertRaises(release.ReleaseError):
            release.verify_validation(self.root, platform, "ubuntu-20.04", VERSION, SHA,
                                      {**info["artifacts"][0], "sha256": "0" * 64})
        proof.unlink()
        with self.assertRaisesRegex(release.ReleaseError, "missing"):
            release.verify_package(self.root, platform, VERSION, SHA, self.fixture.lock)

    def test_zsh_runtime_proof_rejects_unknown_archive_members(self):
        info, lock, runtime, sources, data = self.zsh_release_fixture()
        archive(runtime, {**{"payload/" + name: value for name, value in data.items()}, "payload/extra.dll": b"untrusted"})
        with self.assertRaisesRegex(release.ReleaseError, "unexpected runtime proof"):
            release.verify_zsh_runtime(info, lock, runtime, sources)

    def test_independent_herdr_source_is_locked_to_the_default_branch_merge(self):
        lock = release.load_lock(release.ROOT)
        source = lock["herdr"]["source"]
        self.assertEqual(lock["herdr"]["repository"], "https://github.com/gx0404/herdr")
        self.assertEqual(lock["herdr"]["branch_provenance"], "feature/gx_herdr")
        self.assertEqual(lock["herdr"]["revision"], "fe708f3cb9fb86d11918883238aa894ad07ea92d")
        self.assertEqual(source["url"], lock["herdr"]["repository"] + "/archive/" + source["commit"] + ".zip")
        self.assertEqual(source["commit"], lock["herdr"]["revision"])
        self.assertEqual(source["prefix"], "herdr-" + lock["herdr"]["revision"] + "/")
        self.assertEqual(source["sha256"], "6cbf86177643b69bdd97b774b326fdae93eec5482cef92912e7c5b4741cb54b5")
        self.assertEqual(source["size"], 15710731)
        self.assertNotIn("git_repository", source)
        component = next(c for c in lock["components"] if c["id"] == "herdr")
        self.assertEqual(component["sources"], [source])
        self.assertEqual(builder.load_supplements(release.ROOT)["data"]["herdr_revision"], lock["herdr"]["revision"])
        self.assertEqual(lock["herdr"]["rust"], "1.96.1")
        self.assertEqual(lock["herdr"]["zig"], "0.16.0")

    def test_independent_archive_rejects_mismatched_commit_url_and_size(self):
        original_read = release.read_json
        path = release.ROOT / "scripts/packaging/dependencies.json"
        original = original_read(path)
        for mutation in (
            {"commit": "a" * 40}, {"prefix": "herdr/"}, {"size": 0},
            {"size": True}, {"sha256": "invalid"},
            {"url": "https://github.com/gx0404/herdr/archive/feature/gx_herdr.zip"},
            {"url": "https://example.org/herdr.zip"},
            {"git_repository": "https://github.com/gx0404/herdr"},
        ):
            lock = copy.deepcopy(original)
            lock["herdr"]["source"].update(mutation)
            with self.subTest(mutation=mutation), patch.object(
                release, "read_json", side_effect=lambda p: lock if p == path else original_read(p)
            ), self.assertRaises(release.ReleaseError):
                release.load_lock(release.ROOT)

    def test_default_branch_lock_rejects_premerge_receipt(self):
        lock = release.load_lock(release.ROOT)
        build = release.read_json(self.fixture.manifests["windows-x64"])["herdr_build"]
        build.update(revision="1a6b9d4d13d1b547fe0e21197baeb2ac4e27bef0",
                     source_sha256="68d613f103bfa5313db884827cb185be4998d4e4a3ec33f770dea73cc1eb22c5")
        with self.assertRaisesRegex(release.ReleaseError, "revision mismatch"):
            release.verify_herdr_metadata(build, "windows-x64", lock)

    def test_previous_revision_receipts_cannot_be_reused_for_handshake_fix(self):
        build = release.read_json(self.fixture.manifests["windows-x64"])["herdr_build"]
        build.update(revision="e9f6c994c49410d784f0a53ea725605b78515300",
                     source_sha256="e60ec78685dfde145d06edc2d96e5bb3401df5c5bff6f2960af4172573273570")
        with self.assertRaisesRegex(release.ReleaseError, "revision mismatch"):
            release.verify_herdr_metadata(build, "windows-x64", self.fixture.lock)

    def test_workflow_security_contract(self):
        text = (release.ROOT / ".github/workflows/gx-release.yml").read_text(encoding="utf-8")
        self.assertIn("default: false", text)
        self.assertEqual(text.count("contents: write"), 1)
        self.assertEqual(text.count("GITHUB_TOKEN:"), 1)
        self.assertNotIn("pull_request_target", text)
        for action in re.findall(r"uses:\s+(\S+)", text):
            self.assertRegex(action, r"@[0-9a-f]{40}$")
        for checkout in text.split("- uses: actions/checkout@")[1:]:
            self.assertIn("persist-credentials: false", checkout.split("- uses:", 1)[0])
        publish_job = text.split("\n  publish:\n", 1)[1]
        self.assertIn("ref: ${{ github.workflow_sha }}", publish_job)
        self.assertNotIn("ref: ${{ needs.prepare.outputs.sha }}", publish_job)
        self.assertIn("python3 -I controller/scripts/gx_release.py publish", publish_job)


if __name__ == "__main__":
    unittest.main()
