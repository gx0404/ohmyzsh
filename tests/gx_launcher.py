#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/gx-launcher/main.rs"
MARKER = "# gx-shell: manages [terminal] default_shell and shell_mode"
# 同一个假程序按文件名扮演 cygpath、真实 herdr 与 zsh：cygpath 从标准输入（-f -）或参数逐行回显
# 转换结果并记录调用方式；herdr 的 status/server 子命令写日志，reload-config 按 GX_TEST_RELOAD
# 返回报告；其余情况打印 HOME、参数与 GX_TEST_PRINT 列出的变量。
CHILD = r'''
use std::{env, fs, io::Write, process};

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    fn GenerateConsoleCtrlEvent(event: u32, group: u32) -> i32;
}

fn log(name: &str, line: &str) {
    let path = env::current_exe().unwrap().with_file_name(name);
    let mut file = fs::OpenOptions::new().create(true).append(true).open(path).unwrap();
    writeln!(file, "{line}").unwrap();
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    if env::current_exe().unwrap().file_stem().unwrap() == "cygpath" {
        let paths: Vec<String> = if args.iter().any(|arg| arg == "-f") {
            log("cygpath.log", "stdin");
            std::io::stdin().lines().map(Result::unwrap).collect()
        } else {
            log("cygpath.log", &args.join(" "));
            args.iter().skip_while(|arg| *arg != "--").skip(1).cloned().collect()
        };
        for path in paths {
            println!("/converted/{}", path.replace('\\', "/"));
        }
        return;
    }
    if matches!(args.first().map(String::as_str), Some("status" | "server")) {
        log("herdr.log", &args.join(" "));
        if args[0] == "status" {
            println!("{{\"status\":\"x\",\"running\":{}}}", env::var_os("GX_TEST_RUNNING").is_some());
        } else if args.get(1).map(String::as_str) == Some("reload-config") {
            let status = env::var("GX_TEST_RELOAD").unwrap_or_else(|_| "applied".to_owned());
            let diagnostics = if status == "applied" { "" } else { "\"config parse error: bad value\"" };
            println!("{{\"id\":\"cli:server:reload-config\",\"result\":{{\"type\":\"config_reload\",\"status\":\"{status}\",\"diagnostics\":[{diagnostics}]}}}}");
        }
        return;
    }
    #[cfg(windows)]
    if env::var_os("GX_TEST_CTRL_C").is_some() {
        unsafe { GenerateConsoleCtrlEvent(0, 0) };
        std::thread::sleep(std::time::Duration::from_secs(5));
        return;
    }
    for name in env::var("GX_TEST_PRINT").unwrap_or_default().split(',').filter(|name| !name.is_empty()) {
        println!("{name}={}", env::var(name).unwrap_or_else(|_| "<unset>".to_owned()));
    }
    println!("HOME={}", env::var("HOME").unwrap());
    for (index, arg) in args.iter().enumerate() {
        println!("ARG{index}={arg}");
    }
    process::exit(17);
}
'''
# 先设置可继承的「忽略 Ctrl+C」标志，再启动参数里的程序并打印其退出码。
CTRL = r'''
use std::{env, process::Command};

#[link(name = "kernel32")]
extern "system" {
    fn SetConsoleCtrlHandler(handler: usize, add: i32) -> i32;
}

fn main() {
    let args: Vec<_> = env::args_os().skip(1).collect();
    unsafe { SetConsoleCtrlHandler(0, 1) };
    let status = Command::new(&args[0]).args(&args[1..]).status().unwrap();
    println!("{}", status.code().unwrap());
}
'''


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
            if key.upper().startswith(("HERDR_", "GX_", "ZSH", "FPATH", "_ZO_")):
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
        cls.child = cls.compile("child", CHILD)

    @classmethod
    def compile(cls, name, source):
        path = cls.root / f"{name}.rs"
        path.write_text(source, encoding="utf-8")
        output = cls.root / (name + cls.suffix)
        subprocess.run([cls.rustc, "--edition=2021", str(path), "-o", str(output)],
                       env=cls.env, check=True, timeout=180)
        return output

    def invoke(self, name, *args):
        return subprocess.run(
            [str(self.commands[name]), *args], env=self.env, cwd=self.root,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def fake_install(self, name):
        case = self.root / name
        case.mkdir()
        prefix = case / "prefix"
        install = prefix if os.name == "nt" else prefix / "lib/ohmyzsh-gx"
        resources = prefix / "share/ohmyzsh-gx"
        (install / "bin").mkdir(parents=True)
        (install / "lib/herdr").mkdir(parents=True)
        (resources / "gx/config").mkdir(parents=True)
        (resources / "gx/omz-custom/themes/powerlevel10k").mkdir(parents=True)
        (resources / "p10k-runtime-id").write_text("a" * 64, encoding="ascii")
        for relative in ("oh-my-zsh.sh", "gx/config/zshrc", "gx/config/package.zsh"):
            (resources / relative).write_text("\n", encoding="utf-8")
        shutil.copyfile(self.child, install / "lib/herdr" / ("herdr" + self.suffix))
        if os.name == "nt":
            runtime = install / "runtime/msys64/usr/bin"
            runtime.mkdir(parents=True)
            shutil.copyfile(self.child, runtime / "zsh.exe")
            shutil.copyfile(self.child, runtime / "cygpath.exe")
            data = install / "runtime/msys64/share/zsh"
        else:
            (install / "libexec/zsh").mkdir(parents=True)
            shutil.copyfile(self.child, install / "libexec/zsh/zsh")
            data = install / "share/zsh"
        (data / "functions").mkdir(parents=True)
        (data / "functions/compinit").write_text("\n", encoding="utf-8")
        for launcher in ("gx-zsh", "herdr"):
            target = install / "bin" / (launcher + self.suffix)
            shutil.copyfile(self.commands[launcher], target)
            target.chmod(0o755)
        for path in (install / "lib/herdr").iterdir():
            path.chmod(0o755)
        if os.name != "nt":
            (install / "libexec/zsh/zsh").chmod(0o755)
        environment = dict(self.env)
        for variable in ("HOME", "USERPROFILE", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
            folder = case / variable
            folder.mkdir()
            environment[variable] = str(folder)
        profile = Path(environment["LOCALAPPDATA" if os.name == "nt" else "XDG_CONFIG_HOME"]) / "ohmyzsh-gx/profile"
        return {"case": case, "install": install, "resources": resources, "data": data,
                "profile": profile, "env": environment}

    def launch(self, fixture, launcher, *args, **extra):
        return subprocess.run(
            [str(fixture["install"] / "bin" / (launcher + self.suffix)), *args],
            env={**fixture["env"], **extra}, cwd=fixture["case"],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def cygpath_calls(self, fixture):
        log = fixture["install"] / "runtime/msys64/usr/bin/cygpath.log"
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

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
        fixture = self.fake_install("success-case")
        values = ["agent", "prompt", "worker", "中文 space", "literal;$(exit 99)", "update"]
        result = self.launch(fixture, "herdr", *values)
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
        environment = fixture["env"]
        expected_home = environment["USERPROFILE"] if os.name == "nt" else environment["HOME"]
        self.assertEqual(result.stdout.splitlines(), [f"HOME={expected_home}"]
                         + [f"ARG{index}={value}" for index, value in enumerate(values)])
        self.assertEqual(result.stderr, "")
        config = (fixture["profile"] / "herdr/config.toml").read_text(encoding="utf-8")
        self.assertTrue(config.startswith(MARKER), config)

    def test_nested_launch_rebuilds_gx_environment_with_one_path_conversion(self):
        fixture = self.fake_install("nested-case")
        resources, data, profile = fixture["resources"], fixture["data"], fixture["profile"]
        native = str if os.name != "nt" else (lambda path: str(path).replace("\\", "/"))
        converted = str if os.name != "nt" else (lambda path: "/converted/" + str(path).replace("\\", "/"))
        printed = "ZSH_CUSTOM,ZSH,FPATH,TEMP,TMP,TMPDIR,_ZO_DATA_DIR,GX_PACKAGE_ROOT"
        result = self.launch(
            fixture, "gx-zsh",
            GX_PACKAGE_ROOT=native(resources), ZSH_CUSTOM=native(resources / "gx/omz-custom"),
            ZSH=native(resources), FPATH="C:\\junk;D:\\more" if os.name == "nt" else "/junk:/more",
            HERDR_CONFIG_PATH=str(profile / "herdr/config.toml"), GX_TEST_PRINT=printed,
        )
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines())
        self.assertEqual(values["ZSH_CUSTOM"], "<unset>")
        self.assertEqual(values["ZSH"], "<unset>")
        self.assertEqual(values["FPATH"], f"{converted(data)}/functions:{converted(data)}/site-functions")
        self.assertEqual(values["GX_PACKAGE_ROOT"] if os.name == "nt" else os.path.normpath(values["GX_PACKAGE_ROOT"]),
                         converted(resources))
        self.assertEqual(values["TMPDIR"], f"{converted(profile)}/.cache/tmp")
        self.assertEqual(values["TEMP"], fixture["env"]["TEMP"])
        self.assertEqual(values["TMP"], fixture["env"]["TMP"])
        config = (profile / "herdr/config.toml").read_text(encoding="utf-8")
        self.assertTrue(config.startswith(MARKER), config)
        if os.name == "nt":
            self.assertEqual(values["_ZO_DATA_DIR"], str(profile / ".local/share/zoxide"))
            self.assertTrue((profile / ".cache/oh-my-zsh/completions").is_dir())
            self.assertEqual(self.cygpath_calls(fixture), ["stdin"])
            before = self.cygpath_calls(fixture)
            result = self.launch(fixture, "herdr", "--version")
            self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
            self.assertEqual(self.cygpath_calls(fixture), before)
        else:
            self.assertEqual(values["_ZO_DATA_DIR"], "<unset>")

    def test_default_shell_command_changes_only_gx_managed_herdr_config(self):
        fixture = self.fake_install("default-shell")
        config = fixture["profile"] / "herdr/config.toml"
        shell = fixture["install"] / "lib/herdr" / ("herdr" + self.suffix)
        log = fixture["install"] / "lib/herdr/herdr.log"

        def set_shell(*args, **extra):
            before = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
            result = self.launch(fixture, "herdr", "--gx-set-default-shell", *args, **extra)
            after = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
            return result, after[len(before):]

        # 从 GX Shell 里启动的 WezTerm 会继承启动器导出的托管路径，这不算自定义配置。
        managed = str(config).replace("\\", "/") if os.name == "nt" else str(config)
        result, calls = set_shell(str(shell), HERDR_CONFIG_PATH=managed)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = config.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(MARKER), text)
        self.assertIn("default_shell = " + json.dumps(str(shell), ensure_ascii=False) + "\n", text)
        self.assertIn('shell_mode = "login"\n', text)
        self.assertEqual(calls, ["status server --json"])
        result, calls = set_shell(str(shell), GX_TEST_RUNNING="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(calls, ["status server --json", "server reload-config"])
        self.assertEqual(result.stderr, "")
        result, _ = set_shell(str(shell), GX_TEST_RUNNING="1", GX_TEST_RELOAD="partial")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("herdr config warning: config parse error: bad value", result.stderr)
        result, _ = set_shell(str(shell), GX_TEST_RUNNING="1", GX_TEST_RELOAD="failed")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("did not apply it (failed): config parse error: bad value", result.stderr)
        self.assertEqual(config.read_text(encoding="utf-8"), text)
        custom = '[terminal]\ndefault_shell = "custom"\n'
        config.write_text(custom, encoding="utf-8")
        for extra in ({}, {"HERDR_CONFIG_PATH": str(fixture["case"] / "other.toml")}):
            result, calls = set_shell(str(shell), **extra)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn("custom configuration", result.stderr)
            self.assertEqual(calls, [])
        for args in (["relative-shell"], [str(fixture["case"] / "missing" / shell.name)], []):
            result, calls = set_shell(*args)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(calls, [])
        self.assertEqual(config.read_text(encoding="utf-8"), custom)
        config.unlink()
        config.mkdir()
        result, calls = set_shell(str(shell))
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(calls, [])
        self.assertTrue(config.is_dir())

    @unittest.skipUnless(os.name == "nt", "console Ctrl+C inheritance is Windows-specific")
    def test_gx_zsh_restores_ctrl_c_for_its_shell(self):
        fixture = self.fake_install("ctrl-c")
        helper = self.compile("ctrl", CTRL)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        codes = {}
        for launcher in ("gx-zsh", "herdr"):
            result = subprocess.run(
                [str(helper), str(fixture["install"] / "bin" / (launcher + ".exe")), "ctrl-c"],
                env={**fixture["env"], "GX_TEST_CTRL_C": "1"}, cwd=fixture["case"],
                capture_output=True, text=True, timeout=60,
                creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            codes[launcher] = int(result.stdout.strip())
        self.assertEqual(codes, {"gx-zsh": -1073741510, "herdr": 0})

    def test_nested_update_word_is_not_mistaken_for_self_update(self):
        result = self.invoke("herdr", "agent", "prompt", "worker", "update")
        self.assertNotIn("upstream self-update", result.stderr)
        self.assertIn("Incomplete GX installation", result.stderr)


if __name__ == "__main__":
    unittest.main()
