import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_agent_kb.py"
SPEC = importlib.util.spec_from_file_location("gx_kb", SCRIPT)
kb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kb)


class KnowledgeBaseText(unittest.TestCase):
    def test_text_line_endings_do_not_change_chunks_or_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc = root / "example.md"
            source = root / "example.zsh"
            outputs = []
            with mock.patch.object(kb, "ROOT", root), mock.patch.object(kb, "git_files", return_value=[]), \
                    mock.patch.object(kb, "git_symlinks", return_value=set()), \
                    mock.patch.object(kb, "corpus_inputs", return_value=[("example.md", "doc"), ("example.zsh", "code")]):
                for ending in (b"\n", b"\r\n", b"\r"):
                    doc.write_bytes("# 示例\n\n正文\n".encode().replace(b"\n", ending))
                    source.write_bytes(b"function gx_sample() {\n  :\n}\nalias gs='git status'\n".replace(b"\n", ending))
                    outputs.append(kb.build_chunks())
                self.assertEqual(outputs[0], outputs[1])
                self.assertEqual(outputs[0], outputs[2])
                self.assertGreater(outputs[0][1]["chunk_count"], 0)
                doc.write_bytes("# 示例\n\n已修改正文\n".encode())
                changed = kb.build_chunks()
                self.assertNotEqual(changed[1]["corpus_hash"], outputs[0][1]["corpus_hash"])
                self.assertNotEqual(changed[1]["content_hash"], outputs[0][1]["content_hash"])

    def test_git_link_stub_reads_target_and_rejects_escape_or_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target.zsh").write_bytes(b"alias gx=git\r\n")
            stub = root / "link.zsh"
            stub.write_text("target.zsh", encoding="utf-8")
            with mock.patch.object(kb, "ROOT", root):
                self.assertEqual(kb.corpus_bytes("link.zsh", {"link.zsh"}), b"alias gx=git\n")
                stub.write_text("../outside.zsh", encoding="utf-8")
                with self.assertRaises(ValueError):
                    kb.corpus_bytes("link.zsh", {"link.zsh"})
                stub.write_text("link.zsh", encoding="utf-8")
                with self.assertRaises(ValueError):
                    kb.corpus_bytes("link.zsh", {"link.zsh"})


if __name__ == "__main__":
    unittest.main()
