import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from gx_p10k_metadata import runtime_identity


class P10kIdentity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.theme = self.root / "gx/omz-custom/themes/powerlevel10k"
        for name in ("powerlevel10k.zsh-theme", "internal/p10k.zsh", "gitstatus/gitstatus.plugin.zsh"):
            path = self.theme / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"source\n")

    def test_identity_tracks_source_platform_and_zsh_not_timestamps(self):
        initial = runtime_identity(self.root, "windows-x64", "a" * 64)
        source = self.theme / "internal/p10k.zsh"
        os.utime(source, (1700000000, 1700000000))
        self.assertEqual(runtime_identity(self.root, "windows-x64", "a" * 64), initial)
        self.assertNotEqual(runtime_identity(self.root, "ubuntu-amd64", "a" * 64), initial)
        self.assertNotEqual(runtime_identity(self.root, "windows-x64", "b" * 64), initial)
        source.write_bytes(b"changed\n")
        self.assertNotEqual(runtime_identity(self.root, "windows-x64", "a" * 64), initial)

    def test_missing_files_and_compiled_output_are_rejected(self):
        compiled = self.theme / "internal/p10k.zsh.zwc"
        compiled.write_bytes(b"runtime")
        with self.assertRaisesRegex(ValueError, "compilation output"):
            runtime_identity(self.root, "windows-x64", "a" * 64)
        compiled.unlink()
        (self.theme / "internal/p10k.zsh").unlink()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            runtime_identity(self.root, "windows-x64", "a" * 64)

    def test_invalid_binary_digest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "verified Zsh"):
            runtime_identity(self.root, "windows-x64", "unknown")


if __name__ == "__main__":
    unittest.main()
