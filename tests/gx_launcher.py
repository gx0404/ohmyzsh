#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/gx-launcher/main.rs"


class NativeLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rustc = os.environ.get("GX_RUSTC") or shutil.which("rustc")
        if not cls.rustc:
            raise RuntimeError("rustc is required; launcher tests were not run")
        cls.sandbox = tempfile.TemporaryDirectory(prefix="gx-launcher-")
        cls.addClassCleanup(cls.sandbox.cleanup)
        cls.root = Path(cls.sandbox.name)
        cls.suffix = ".exe" if os.name == "nt" else ""
        cls.env = os.environ.copy()
        for key in list(cls.env):
            if key.upper().startswith(("HERDR_", "GX_")):
                cls.env.pop(key)
        for name, relative in {
            "HOME": "home", "USERPROFILE": "home", "APPDATA": "roaming",
            "LOCALAPPDATA": "local", "XDG_CONFIG_HOME": "config",
            "XDG_CACHE_HOME": "cache", "XDG_DATA_HOME": "data",
            "XDG_STATE_HOME": "state", "TMP": "tmp", "TEMP": "tmp", "TMPDIR": "tmp",
        }.items():
            directory = cls.root / relative
            directory.mkdir(exist_ok=True)
            cls.env[name] = str(directory)
        cls.env["GIT_CONFIG_GLOBAL"] = os.devnull
        cls.env["GIT_CONFIG_NOSYSTEM"] = "1"
        cls.commands = {}
        for name, flags in {
            "unit": ["--test"], "gx-zsh": [], "herdr": ["--cfg", "gx_herdr"],
        }.items():
            output = cls.root / (name + cls.suffix)
            command = [cls.rustc, "--edition=2021", "-D", "warnings"]
            if os.name == "nt":
                command.extend(["-C", "target-feature=+crt-static"])
            command.extend([*flags, str(SOURCE), "-o", str(output)])
            subprocess.run(command, check=True, env=cls.env, cwd=ROOT, timeout=180)
            cls.commands[name] = output

    def invoke(self, name, *args):
        return subprocess.run(
            [str(self.commands[name]), *args], env=self.env, cwd=self.root,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def test_native_unit_suite(self):
        result = self.invoke("unit")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 failed", result.stdout)
        self.assertIn("0 ignored", result.stdout)

    def test_update_is_blocked_before_any_initialization(self):
        before = sorted(path.relative_to(self.root) for path in self.root.rglob("*"))
        for command in [
            ["update"], ["--session", "test", "update", "--handoff"],
            ["channel", "set", "preview"],
        ]:
            result = self.invoke("herdr", *command)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("managed by Oh My Zsh GX", result.stderr)
        self.assertEqual(before, sorted(path.relative_to(self.root) for path in self.root.rglob("*")))

    def test_missing_payload_is_a_visible_failure(self):
        for name in ("gx-zsh", "herdr"):
            result = self.invoke(name, "--help")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Incomplete GX installation", result.stderr)
        self.assertFalse((self.root / "local/ohmyzsh-gx").exists())
        self.assertFalse((self.root / "config/ohmyzsh-gx").exists())

    def test_successful_native_child_keeps_argv_home_and_exit_code(self):
        case = self.root / "success-case"
        case.mkdir()
        prefix = case / "prefix"
        install = prefix if os.name == "nt" else prefix / "lib/ohmyzsh-gx"
        resources = prefix / "share/ohmyzsh-gx"
        (install / "bin").mkdir(parents=True)
        (install / "lib/herdr").mkdir(parents=True)
        (resources / "gx/config").mkdir(parents=True)
        (resources / "gx/omz-custom/themes/powerlevel10k").mkdir(parents=True)
        (resources / "p10k-runtime-id").write_text("a" * 64, encoding="ascii")
        for name in ("oh-my-zsh.sh", "gx/config/zshrc", "gx/config/package.zsh"):
            (resources / name).write_text("\n", encoding="utf-8")
        source = case / "child.rs"
        source.write_text(r'''
use std::{env,process};
fn main() {
    if env::current_exe().unwrap().file_stem().unwrap() == "cygpath" {
        println!("/converted/{}", env::args().last().unwrap().replace('\\', "/"));
        return;
    }
    println!("HOME={}", env::var("HOME").unwrap());
    for (index, arg) in env::args().skip(1).enumerate() {
        println!("ARG{index}={arg}");
    }
    process::exit(17);
}
''', encoding="utf-8")
        child = install / "lib/herdr" / ("herdr" + self.suffix)
        subprocess.run([self.rustc, "--edition=2021", str(source), "-o", str(child)],
                       env=self.env, check=True, timeout=180)
        if os.name == "nt":
            runtime = install / "runtime/msys64/usr/bin"
            runtime.mkdir(parents=True)
            shutil.copyfile(child, runtime / "zsh.exe")
            shutil.copyfile(child, runtime / "cygpath.exe")
            functions = install / "runtime/msys64/share/zsh/functions"
        else:
            (install / "libexec/zsh").mkdir(parents=True)
            shutil.copyfile(child, install / "libexec/zsh/zsh")
            functions = install / "share/zsh/functions"
        functions.mkdir(parents=True)
        (functions / "compinit").write_text("\n", encoding="utf-8")
        launcher = install / "bin" / ("herdr" + self.suffix)
        shutil.copyfile(self.commands["herdr"], launcher)
        launcher.chmod(0o755)
        environment = dict(self.env)
        for name in ("HOME", "USERPROFILE", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
            folder = case / name
            folder.mkdir()
            environment[name] = str(folder)
        values = ["agent", "prompt", "worker", "中文 space", "literal;$(exit 99)", "update"]
        result = subprocess.run([str(launcher), *values], env=environment, cwd=case,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
        expected_home = environment["USERPROFILE"] if os.name == "nt" else environment["HOME"]
        self.assertEqual(result.stdout.splitlines(), [f"HOME={expected_home}"]
                         + [f"ARG{index}={value}" for index, value in enumerate(values)])
        self.assertEqual(result.stderr, "")

    def test_nested_update_word_is_not_mistaken_for_self_update(self):
        result = self.invoke("herdr", "agent", "prompt", "worker", "update")
        self.assertNotIn("upstream self-update", result.stderr)
        self.assertIn("Incomplete GX installation", result.stderr)


if __name__ == "__main__":
    unittest.main()
