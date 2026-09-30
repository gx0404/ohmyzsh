"""历史导出的隐私边界与 Zsh 只读导入回归（不使用真实 HOME）。"""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gx_history", ROOT / "scripts/gx_history.py")
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


class HistoryExport(unittest.TestCase):
    def test_private_arguments_and_multiline_never_exported(self):
        data = (": 1:0;git status\n: 2:0;curl -H 'Authorization: PRIVATE_VALUE' https://private.invalid\n"
                ": 3:0;echo PRIVATE_VALUE\\\nls\n: 4:0;codex --prompt PRIVATE_VALUE\n"
                ": 5:0;git status; echo PRIVATE_VALUE\n: 6:0;ls\n: 7:0;ls\n")
        result = history.summarize(data)
        self.assertEqual(result["events"], 7)
        self.assertEqual(result["seed_counts"], {"ls": 2, "git status": 1})
        self.assertEqual(result["command_counts"]["curl"], 1)
        self.assertNotIn("PRIVATE_VALUE", json.dumps(result))
        self.assertNotIn("private.invalid", json.dumps(result))

    def test_reject_unknown_format(self):
        for data in ("", "ls\n", "private\n: 1:0;ls\n"):
            with self.assertRaises(ValueError):
                history.summarize(data)

    def test_cli_and_zsh_import(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "input"
            source.write_text(": 1:0;ls\n: 2:0;git status\n", encoding="utf-8")
            before = source.read_bytes()
            seed = subprocess.run(["python3", str(ROOT / "scripts/gx_history.py"), str(source),
                                   "--format", "zsh"], check=True, capture_output=True, text=True)
            (base / "seed").write_text(seed.stdout, encoding="utf-8")
            result = subprocess.run(["zsh", "-f", "-c",
                                     'HISTSIZE=100; fc -R "$HOME/seed"; fc -l -n 1'],
                                    env={"HOME": directory, "ZDOTDIR": directory, "PATH": "/usr/bin:/bin"},
                                    check=True, capture_output=True, text=True)
            self.assertIn("git status", result.stdout)
            self.assertIn("ls", result.stdout)
            self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
