import argparse
import importlib.util
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

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("gx_lifecycle", ROOT / "scripts/gx_lifecycle.py")
gx = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gx)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gx-lifecycle-unit-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def artifact(self, platform="windows-x64", version="1.2.3", suffix=""):
        folder = self.root / (version + suffix)
        folder.mkdir()
        exe = folder / ("ohmyzsh-gx_" + version + gx.PLATFORMS[platform])
        exe.write_bytes((b"MZ" if platform == "windows-x64" else b"!<arch>\n") + b"unit fixture, never executed " + version.encode())
        sources = folder / "sources.tar.xz"
        sources.write_bytes(b"unit source fixture, never executed")
        data = {"schema_version": 1, "product": "ohmyzsh-gx", "platform": platform, "version": version,
                "source": {"repository": gx.REPOSITORY, "revision": "a" * 40}, "compliance_complete": True,
                "validation": {"native_package_built": True, "lifecycle": "pending", "pty": "pending"},
                "artifacts": [{"filename": path.name, "role": role, "size": path.stat().st_size, "sha256": gx.digest(path)} for path, role in ((exe, "installer"), (sources, "corresponding-sources"))]}
        manifest = exe.with_suffix(".manifest.json")
        gx.write_json(manifest, data)
        return manifest, exe, data

    def receipt_plan(self):
        folder = self.root / "evidence"
        folder.mkdir()
        for child in ("logs", "results", "snapshots"):
            (folder / child).mkdir()
        artifact = {"version": "1.2.3", "source_revision": "a" * 40, "installer": {"sha256": "b" * 64, "size": 100}}
        return {"evidence": str(folder), "platform": "windows-x64", "environment": "windows-clean", "initial": artifact,
                "effective": artifact, "authorization": "unit-test-only"}

    def test_guard_rejects_default_and_partial_github_environment(self):
        for env in ({}, {"GITHUB_ACTIONS": "true"}, {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "self-hosted", "GITHUB_REPOSITORY": gx.REPOSITORY},
                    {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "GITHUB_REPOSITORY": "other/repo"}):
            with self.subTest(env=env), self.assertRaises(gx.LifecycleError):
                gx.disposable_guard(env)

    def test_guard_accepts_exact_hosted_context(self):
        self.assertEqual(gx.disposable_guard({"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "GITHUB_REPOSITORY": gx.REPOSITORY}), "github-hosted")

    def test_local_guard_requires_both_deliberate_arguments(self):
        with self.assertRaises(gx.LifecycleError):
            gx.disposable_guard({}, disposable_vm=True)
        with self.assertRaises(gx.LifecycleError):
            gx.disposable_guard({}, confirmation=gx.CONFIRMATION)
        self.assertEqual(gx.disposable_guard({}, disposable_vm=True, confirmation=gx.CONFIRMATION), "explicit-disposable-vm")

    def test_cli_refusal_happens_before_read_or_subprocess(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(gx, "verify_manifest") as read, mock.patch.object(gx.subprocess, "run") as run:
            self.assertEqual(gx.main(["--manifest", "missing", "--evidence", str(self.root / "new")]), 2)
            read.assert_not_called()
            run.assert_not_called()
            self.assertFalse((self.root / "new").exists())

    def test_workers_cannot_bypass_guard(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(gx, "load_plan") as read:
            self.assertEqual(gx.main(["--worker", "profile", "--plan", "missing", "--phase", "anything"]), 2)
            read.assert_not_called()

    def test_manifest_hash_and_size_verified_without_execution(self):
        for platform in gx.PLATFORMS:
            manifest, installer, _ = self.artifact(platform, suffix=platform)
            with mock.patch.object(gx.subprocess, "run") as run:
                record = gx.verify_manifest(manifest)
                self.assertEqual(record["installer"]["path"], str(installer))
                run.assert_not_called()

    def test_tampered_installer_is_rejected(self):
        manifest, installer, _ = self.artifact()
        installer.write_bytes(b"MZtampered")
        with self.assertRaises(gx.LifecycleError):
            gx.verify_manifest(manifest)

    def test_tampered_sources_are_rejected(self):
        manifest, _, _ = self.artifact()
        (manifest.parent / "sources.tar.xz").write_bytes(b"changed")
        with self.assertRaises(gx.LifecycleError):
            gx.verify_manifest(manifest)

    def test_path_traversal_and_duplicate_roles_rejected(self):
        manifest, _, data = self.artifact()
        data["artifacts"][0]["filename"] = "../escape.exe"
        gx.write_json(manifest, data)
        with self.assertRaises(gx.LifecycleError):
            gx.verify_manifest(manifest)
        data["artifacts"][0]["role"] = "corresponding-sources"
        gx.write_json(manifest, data)
        with self.assertRaises(gx.LifecycleError):
            gx.verify_manifest(manifest)

    def test_duplicate_json_key_rejected(self):
        path = self.root / "duplicate.json"
        path.write_text('{"a":1,"a":2}')
        with self.assertRaises(gx.LifecycleError):
            gx.read_json(path)

    def test_false_size_is_not_integer_size(self):
        manifest, _, data = self.artifact()
        data["artifacts"][0]["size"] = True
        gx.write_json(manifest, data)
        with self.assertRaises(gx.LifecycleError):
            gx.verify_manifest(manifest)

    def test_not_native_container_rejected_even_with_matching_hash(self):
        manifest, installer, data = self.artifact()
        installer.write_bytes(b"not an installer")
        data["artifacts"][0].update(size=installer.stat().st_size, sha256=gx.digest(installer))
        gx.write_json(manifest, data)
        with self.assertRaises(gx.LifecycleError):
            gx.verify_manifest(manifest)

    def test_upgrade_must_be_newer_and_have_its_manifest(self):
        old, same, _ = self.artifact()
        initial = gx.verify_manifest(old)
        with self.assertRaises(gx.LifecycleError):
            gx.verify_upgrade(initial, same)
        new, installer, _ = self.artifact(version="1.2.4")
        self.assertEqual(gx.verify_upgrade(initial, installer)["manifest"], str(new))
        self.assertIsNone(gx.verify_upgrade(initial, None))

    def test_upgrade_platform_mismatch(self):
        old, _, _ = self.artifact()
        _, new, _ = self.artifact("ubuntu-amd64", "1.2.4")
        with self.assertRaises(gx.LifecycleError):
            gx.verify_upgrade(gx.verify_manifest(old), new)

    def test_missing_dependency_is_not_treated_as_a_skipped_success(self):
        manifest, _, data = self.artifact()
        data["compliance_complete"] = False
        gx.write_json(manifest, data)
        with self.assertRaises(gx.LifecycleError):
            gx.verify_manifest(manifest)

    def test_isolated_environment_does_not_inherit_tokens_or_user_home(self):
        plan = {"platform": "windows-x64", "paths": gx.plan_paths(self.root / "中文 证据", "windows-x64"), "session": "gx-lifecycle-abcdef123456"}
        with mock.patch.dict(os.environ, {"SYSTEMROOT": "C:\\Windows", "HOME": "real-home", "USERPROFILE": "real-home", "SECRET_TOKEN": "do-not-copy", "PATH": "user-sdk"}, clear=True):
            env = gx.clean_environment(plan)
        self.assertNotIn("SECRET_TOKEN", env)
        self.assertNotIn("user-sdk", env["PATH"])
        for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            self.assertIn(str(self.root), env[key])
        self.assertNotEqual(plan["paths"]["home"], plan["paths"]["profile"])

    def test_profile_probe_does_not_accept_ascii_zdotdir_substitution(self):
        self.assertIn('$ZDOTDIR == "$GX_PROFILE_DIR"', gx.PROFILE_SCRIPT)
        self.assertIn("${+functions[p10k]} == 0", gx.PROFILE_SCRIPT)
        self.assertIn("-z $ZSH_THEME", gx.PROFILE_SCRIPT)
        self.assertIn('fc -W "$HISTFILE"', gx.PROFILE_SCRIPT)

    def test_snapshot_detects_user_edit_and_does_not_store_content(self):
        file = self.root / "中文 文件"
        file.write_text("first", encoding="utf-8")
        first = gx.snapshot_tree(self.root)
        file.write_text("second", encoding="utf-8")
        self.assertNotEqual(first, gx.snapshot_tree(self.root))
        self.assertEqual(set(first[0]), {"path", "sha256", "size"})

    def test_sensitive_snapshot_is_rejected(self):
        (self.root / "auth.json").write_text("not a real credential")
        with self.assertRaises(gx.LifecycleError):
            gx.snapshot_tree(self.root)

    def test_pending_receipt_is_nonzero_and_never_marks_reviewed(self):
        plan = self.receipt_plan()
        folder = Path(plan["evidence"])
        (folder / "logs/native.log").write_text("actual lifecycle subset log")
        gx.write_json(folder / "results/native.json", {"status": "passed", "checks": {"install": {"status": "passed", "evidence": ["logs/native.log"]}}})
        path, code = gx.finalize(plan, 0)
        receipt = gx.read_json(path)
        self.assertEqual(code, 3)
        self.assertEqual(receipt["status"], "pending")
        self.assertFalse(receipt["evidence_reviewed"])
        self.assertEqual(receipt["checks"]["herdr-tui"]["status"], "pending")
        self.assertEqual(set(receipt["checks"]), gx.required_checks("windows-x64"))
        with tarfile.open(folder / receipt["evidence_archive"]["filename"]) as archive:
            self.assertEqual(set(archive.getnames()), {r["path"] for r in receipt["evidence_files"]})

    def test_native_failure_is_nonzero_with_artifact_identity(self):
        plan = self.receipt_plan()
        path, code = gx.finalize(plan, 1)
        receipt = gx.read_json(path)
        self.assertEqual(code, 1)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["installer_sha256"], "b" * 64)

    def test_passed_check_requires_nonempty_evidence(self):
        plan = self.receipt_plan()
        folder = Path(plan["evidence"])
        (folder / "logs/empty.log").touch()
        gx.write_json(folder / "results/native.json", {"checks": {"install": {"status": "passed", "evidence": ["logs/empty.log"]}}})
        with self.assertRaises(gx.LifecycleError):
            gx.finalize(plan, 0)

    def test_unknown_checks_are_rejected(self):
        plan = self.receipt_plan()
        gx.write_json(Path(plan["evidence"]) / "results/native.json", {"checks": {"imaginary": {"status": "passed", "evidence": []}}})
        with self.assertRaises(gx.LifecycleError):
            gx.finalize(plan, 0)

    def test_result_json_cannot_promote_unimplemented_p10k(self):
        plan = self.receipt_plan()
        folder = Path(plan["evidence"])
        (folder / "logs/not-a-prompt.log").write_text("file existence is not end-to-end proof")
        gx.write_json(folder / "results/native.json", {"checks": {"p10k": {"status": "passed", "evidence": ["logs/not-a-prompt.log"]}}})
        with self.assertRaises(gx.LifecycleError):
            gx.finalize(plan, 0)

    def test_profile_log_cannot_claim_interactive_checks(self):
        plan = self.receipt_plan()
        folder = Path(plan["evidence"])
        (folder / "logs/headless.log").write_text("not a TUI")
        gx.write_json(folder / "results/native.json", {"scope": "headless", "checks": {"herdr-tui": {"status": "passed", "evidence": ["logs/headless.log"]}}})
        with self.assertRaises(gx.LifecycleError):
            gx.finalize(plan, 0)

    def test_tui_prototype_or_failure_cannot_approve_package(self):
        binary = self.root / "herdr"
        binary.write_bytes(b"unit binary never executed")
        for status, fixture in (("passed", True), ("failed", False)):
            gx.write_json(self.root / "result.json", {"status": status, "fixture_profile": fixture})
            with self.assertRaises(gx.LifecycleError):
                gx.consume_tui_result(self.root, "windows-x64", binary)

    def test_tui_binary_and_transport_are_bound_to_package(self):
        binary = self.root / "herdr"
        binary.write_bytes(b"unit binary never executed")
        state = {"status": "passed", "fixture_profile": False, "platform": "windows-x64", "herdr_sha256": gx.digest(binary), "transport": "MSYS-script-not-native"}
        gx.write_json(self.root / "result.json", state)
        with self.assertRaises(gx.LifecycleError):
            gx.consume_tui_result(self.root, "windows-x64", binary)
        state["transport"] = "windows-system-conpty"
        state["herdr_sha256"] = "0" * 64
        gx.write_json(self.root / "result.json", state)
        with self.assertRaises(gx.LifecycleError):
            gx.consume_tui_result(self.root, "windows-x64", binary)

    def test_existing_evidence_is_refused_before_host_operations(self):
        args = argparse.Namespace(evidence=self.root, run_as_user=None)
        with mock.patch.object(gx, "host_environment") as host, self.assertRaises(gx.LifecycleError):
            gx.create_plan(args, {"platform": "windows-x64"}, None, "unit-test")
        host.assert_not_called()

    def test_plan_revalidates_artifacts_and_rejects_directory_escape(self):
        manifest, installer, _ = self.artifact()
        package = gx.verify_manifest(manifest)
        evidence = self.root / "new-evidence"
        args = argparse.Namespace(evidence=evidence, run_as_user=None)
        with mock.patch.object(gx, "host_environment", return_value="windows-clean"), mock.patch.dict(os.environ, {"SYSTEMDRIVE": "C:"}):
            plan = gx.create_plan(args, package, None, "unit-test-only")
        path = evidence / "plan.json"
        self.assertEqual(gx.load_plan(path), plan)
        plan["paths"]["home"] = str(self.root / "outside")
        gx.write_json(path, plan)
        with self.assertRaises(gx.LifecycleError):
            gx.load_plan(path)
        plan["paths"] = gx.plan_paths(evidence, "windows-x64")
        gx.write_json(path, plan)
        installer.write_bytes(b"MZ changed after preflight")
        with self.assertRaises(gx.LifecycleError):
            gx.load_plan(path)

    def test_non_tty_probe_cannot_claim_tui_or_p10k_passed(self):
        self.assertFalse({"herdr-tui", "p10k", "gitstatus", "completion", "unicode-input"} & gx.PROFILE_CHECKS)
        self.assertIn("herdr-tui", gx.TUI_CHECKS)
        self.assertIn("detach-attach", gx.TUI_CHECKS)
        self.assertIn("p10k", gx.PENDING_REASONS)

    def test_process_timeout_keeps_partial_evidence(self):
        plan = self.receipt_plan()
        plan["paths"] = {"home": str(self.root)}
        error = subprocess.TimeoutExpired(["not-executed"], 180, output=b"partial output", stderr=b"partial error")
        with mock.patch.object(gx.subprocess, "run", side_effect=error), self.assertRaises(subprocess.TimeoutExpired):
            gx.captured(plan, "timeout", ["not-executed"], {})
        self.assertEqual((Path(plan["evidence"]) / "logs/timeout.stdout.log").read_bytes(), b"partial output")
        self.assertEqual(gx.read_json(Path(plan["evidence"]) / "logs/timeout.json")["status"], "timeout")

    def test_checks_match_current_release_consumer(self):
        spec = importlib.util.spec_from_file_location("gx_release_contract", ROOT / "scripts/gx_release.py")
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        self.assertEqual(gx.COMMON_CHECKS, release.COMMON_CHECKS)
        self.assertEqual(gx.WINDOWS_CHECKS, release.WINDOWS_CHECKS)
        self.assertEqual(gx.LINUX_CHECKS, release.LINUX_CHECKS)
        plan = self.receipt_plan()
        path, _ = gx.finalize(plan, 0)
        with self.assertRaises(release.ReleaseError):
            release.verify_validation(path.parent, "windows-x64", "windows-clean", "1.2.3", "a" * 40, {"sha256": "b" * 64})

    def test_native_syntax_and_default_refusal(self):
        env = os.environ.copy()
        for name in ("GITHUB_ACTIONS", "RUNNER_ENVIRONMENT", "GITHUB_REPOSITORY"):
            env.pop(name, None)
        bash = shutil.which("bash")
        self.assertIsNotNone(bash, "bash syntax checking is a required test dependency")
        linux = ROOT / "scripts/gx_smoke_linux.sh"
        syntax = subprocess.run([bash, "-n", str(linux)], env=env, capture_output=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        refused = subprocess.run([bash, str(linux)], env=env, capture_output=True)
        self.assertEqual(refused.returncode, 2, refused.stderr)
        self.assertIn(b"REFUSED", refused.stderr)
        if os.name == "nt":
            powershell = Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            windows = ROOT / "scripts/gx_smoke_windows.ps1"
            command = "$tokens=$null;$errors=$null;[System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)|Out-Null;if($errors.Count){$errors|Out-String|Write-Error;exit 1}"
            encoded = __import__("base64").b64encode((command.replace("$args[0]", "'" + str(windows).replace("'", "''") + "'")).encode("utf-16le")).decode()
            syntax = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], env=env, capture_output=True)
            self.assertEqual(syntax.returncode, 0, syntax.stderr)
            refused = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(windows)], env=env, capture_output=True)
            self.assertEqual(refused.returncode, 2, refused.stderr)
            self.assertIn(b"REFUSED", refused.stderr)


if __name__ == "__main__":
    unittest.main()
