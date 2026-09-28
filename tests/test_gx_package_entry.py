import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gx_package_entry as entry


class PackageEntry(unittest.TestCase):
    def test_missing_inputs_fail_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {
            "GX_PACKAGE_PLATFORM": "ubuntu-amd64", "GX_PACKAGE_OUTPUT": temp,
        }, clear=True), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(entry.main([]), 2)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_windows_requires_explicit_existing_compiler_input(self):
        with self.assertRaisesRegex(ValueError, "GX_ISCC"):
            entry.commands({"GX_DEPENDENCY_BUNDLE": "bundle"}, "windows-x64", Path("output"))

    def test_arguments_are_not_shell_interpolated(self):
        environment = {
            "GX_DEPENDENCY_BUNDLE": "包 & dependency", "GX_PACKAGE_REF": "feature/package",
            "GX_PACKAGE_ALLOW_DIRTY": "1", "GX_ISCC": "C:/Build Tools/ISCC.exe",
            "GX_RUSTC": "C:/Rust Tools/rustc.exe",
        }
        argv = entry.commands(environment, "windows-x64", Path("output space"))
        self.assertIn("包 & dependency", argv[0])
        self.assertIn("feature/package", argv[0])
        self.assertIn("--allow-dirty", argv[0])
        self.assertEqual(argv[2][-2:], ["--iscc", "C:/Build Tools/ISCC.exe"])

    def test_invalid_development_flag_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be 0 or 1"):
            entry.commands({"GX_DEPENDENCY_BUNDLE": "bundle", "GX_PACKAGE_ALLOW_DIRTY": "yes"},
                           "ubuntu-amd64", Path("output"))

    def test_dry_run_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {
            "GX_PACKAGE_PLATFORM": "ubuntu-amd64", "GX_PACKAGE_OUTPUT": temp,
            "GX_DEPENDENCY_BUNDLE": "not-yet-assembled",
        }, clear=True), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(entry.main(["--dry-run"]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(len(result["commands"]), 3)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_failed_stage_does_not_invoke_build(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {
            "GX_PACKAGE_PLATFORM": "ubuntu-amd64", "GX_PACKAGE_OUTPUT": temp,
            "GX_DEPENDENCY_BUNDLE": "bundle",
        }, clear=True), mock.patch.object(entry.subprocess, "run", return_value=subprocess.CompletedProcess([], 7)) as run:
            self.assertEqual(entry.main([]), 7)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][2], "stage")
            self.assertNotIn("shell", run.call_args.kwargs)


class LifecycleEntry(unittest.TestCase):
    def test_default_refusal_has_no_subprocess(self):
        import gx_lifecycle_entry as lifecycle
        for environment in ({}, {"GX_PACKAGE_MANIFEST": "real.manifest.json"}, {
            "GX_PACKAGE_MANIFEST": "real.manifest.json", "GITHUB_ACTIONS": "true",
            "RUNNER_ENVIRONMENT": "self-hosted", "GITHUB_REPOSITORY": "gx0404/ohmyzsh",
        }):
            with self.subTest(environment=environment), mock.patch.dict(os.environ, environment, clear=True), \
                    mock.patch.object(lifecycle.subprocess, "run") as run, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(lifecycle.main(), 2)
                run.assert_not_called()

    def test_ci_dispatch_keeps_native_exit_code(self):
        import gx_lifecycle_entry as lifecycle
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {
            "GX_PACKAGE_MANIFEST": "package.manifest.json", "GITHUB_ACTIONS": "true",
            "RUNNER_ENVIRONMENT": "github-hosted", "GITHUB_REPOSITORY": "gx0404/ohmyzsh",
            "GX_LIFECYCLE_EVIDENCE": str(Path(temp) / "run"), "GX_LIFECYCLE_USER": "gx-test",
        }, clear=True), mock.patch.object(lifecycle.subprocess, "run", return_value=subprocess.CompletedProcess([], 3)) as run:
            self.assertEqual(lifecycle.main(), 3)
            self.assertIn("--run-as-user", run.call_args.args[0])
            self.assertIn("gx-test", run.call_args.args[0])
            self.assertNotIn("shell", run.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
