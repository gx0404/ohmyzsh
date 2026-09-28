import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("gx_probe_herdr", Path(__file__).resolve().parents[1] / "scripts/gx_probe_herdr.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class HerdrProbeCleanup(unittest.TestCase):
    def test_stop_timeout_still_reaps_own_server_and_writes_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exe, zsh = root / "herdr", root / "zsh"
            exe.write_bytes(b"fixture")
            zsh.write_bytes(b"fixture")
            server = mock.Mock(pid=123)
            server.wait.side_effect = [subprocess.TimeoutExpired("server", 20), 0]

            def call(argv, **kwargs):
                if argv[1:] == ["server", "stop"]:
                    raise subprocess.TimeoutExpired(argv, 20)
                if argv[1:] == ["status"]:
                    return subprocess.CompletedProcess(argv, 0, "{}", "")
                if argv[1] == "workspace":
                    return subprocess.CompletedProcess(argv, 1, "", "intentional fixture failure")
                return subprocess.CompletedProcess(argv, 0, "herdr fixture", "")

            with mock.patch.object(probe.os, "name", "posix"), \
                    mock.patch.object(probe.subprocess, "Popen", return_value=server), \
                    mock.patch.object(probe.subprocess, "run", side_effect=call):
                with self.assertRaisesRegex(RuntimeError, "intentional fixture failure"):
                    probe.run_probe(exe, zsh, root / "evidence", None)
            server.terminate.assert_called_once()
            self.assertEqual(server.wait.call_count, 2)
            result = json.loads((root / "evidence/result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("cleanup_error", result)
            self.assertTrue((root / "evidence/commands.json").is_file())


if __name__ == "__main__":
    unittest.main()
