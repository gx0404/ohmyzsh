use std::collections::HashMap;
use std::env;
use std::ffi::{OsStr, OsString};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{SystemTime, UNIX_EPOCH};

const HERDR_MARKER: &str = "# gx-shell: manages [terminal] default_shell and shell_mode; delete this line to manage them yourself";
const HERDR_MARKER_PREFIX: &str = "# gx-shell: manages";
const HERDR_KEYS: [&str; 2] = ["default_shell", "shell_mode"];
// 0.1.0 与 OhMyZshGX 以 root.join("runtime/msys64/usr/bin/zsh.exe") 生成，分隔符混用即为 GX 生成的指纹。
#[cfg(windows)]
const LEGACY_SHELL_SUFFIX: &str = "\\runtime/msys64/usr/bin/zsh.exe";
// 父 GX Zsh 导出的派生变量：MSYS2 交给原生进程时已转成 Windows 形式，由子 Zsh 的 package.zsh 重新计算。
const GX_DERIVED_VARIABLES: [&str; 10] = [
    "ZSH",
    "ZSH_CACHE_DIR",
    "ZSH_COMPDUMP",
    "HISTFILE",
    "NVM_DIR",
    "GITSTATUS_AUTO_INSTALL",
    "P9K_TTY",
    "_P9K_TTY",
    "P9K_SSH",
    "_P9K_SSH_TTY",
];

enum CygpathInput<'a> {
    Lines(&'a str),
    Path(&'a OsStr),
}

type Cygpath<'a> = dyn FnMut(CygpathInput<'_>) -> io::Result<Option<Vec<u8>>> + 'a;
type Environment<'a> = dyn Fn(&str) -> Option<OsString> + 'a;

fn invalid(message: impl std::fmt::Display) -> io::Error {
    io::Error::other(message.to_string())
}

fn absolute(value: OsString, name: &str) -> io::Result<PathBuf> {
    let path = PathBuf::from(value);
    if !path.is_absolute() {
        return Err(invalid(format!("{name} must be an absolute path")));
    }
    Ok(path)
}

fn required_path(name: &str) -> io::Result<PathBuf> {
    absolute(
        env::var_os(name).ok_or_else(|| invalid(format!("{name} is not set")))?,
        name,
    )
}

fn subpath(base: &Path, relative: &str) -> PathBuf {
    let mut path = base.to_path_buf();
    path.extend(relative.split('/'));
    path
}

#[cfg(windows)]
fn native(path: PathBuf) -> PathBuf {
    path.components().collect()
}

#[derive(Debug)]
struct Layout {
    root: PathBuf,
    resources: PathBuf,
    profile: PathBuf,
    home: PathBuf,
    shell: PathBuf,
}

impl Layout {
    fn discover() -> io::Result<Self> {
        let executable = env::current_exe()?;
        let root = executable
            .parent()
            .and_then(Path::parent)
            .ok_or_else(|| invalid("Cannot determine the GX installation directory"))?
            .to_path_buf();
        #[cfg(windows)]
        let (resources, profile, home, shell) = (
            subpath(&root, "share/ohmyzsh-gx"),
            subpath(
                &native(required_path("LOCALAPPDATA")?),
                "ohmyzsh-gx/profile",
            ),
            native(required_path("USERPROFILE")?),
            subpath(&root, "runtime/msys64/usr/bin/zsh.exe"),
        );
        #[cfg(unix)]
        let (resources, profile, home, shell) = {
            let home = required_path("HOME")?;
            let base = match env::var_os("XDG_CONFIG_HOME") {
                Some(path) => absolute(path, "XDG_CONFIG_HOME")?,
                None => home.join(".config"),
            };
            (
                subpath(&root, "../../share/ohmyzsh-gx"),
                subpath(&base, "ohmyzsh-gx/profile"),
                home,
                subpath(&root, "libexec/zsh/zsh"),
            )
        };
        Ok(Self {
            root,
            resources,
            profile,
            home,
            shell,
        })
    }

    fn real_herdr(&self) -> PathBuf {
        subpath(
            &self.root,
            &format!("lib/herdr/herdr{}", env::consts::EXE_SUFFIX),
        )
    }

    fn zsh_data(&self) -> PathBuf {
        #[cfg(windows)]
        {
            subpath(&self.root, "runtime/msys64/share/zsh")
        }
        #[cfg(unix)]
        {
            subpath(&self.root, "share/zsh")
        }
    }

    fn herdr_config(&self) -> PathBuf {
        subpath(&self.profile, "herdr/config.toml")
    }

    fn herdr_adopted(&self) -> PathBuf {
        subpath(&self.profile, "herdr/.gx-config-adopted")
    }

    fn validate(&self, herdr: bool) -> io::Result<()> {
        for path in [
            self.resources.join("oh-my-zsh.sh"),
            subpath(&self.resources, "gx/config/zshrc"),
            subpath(&self.resources, "gx/config/package.zsh"),
            subpath(&self.zsh_data(), "functions/compinit"),
            self.shell.clone(),
        ] {
            if !path.is_file() {
                return Err(invalid(format!(
                    "Incomplete GX installation: {}",
                    path.display()
                )));
            }
        }
        if herdr && !self.real_herdr().is_file() {
            return Err(invalid("The packaged herdr binary is missing"));
        }
        Ok(())
    }
}

fn is_link(metadata: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_attributes() & 0x400 != 0
    }
    #[cfg(unix)]
    {
        metadata.file_type().is_symlink()
    }
}

fn regular_or_missing(path: &Path) -> io::Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.is_file() && !is_link(&metadata) => Ok(true),
        Ok(_) => Err(invalid(format!(
            "Not a regular configuration file: {}",
            path.display()
        ))),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

fn unique_suffix() -> io::Result<String> {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(invalid)?
        .as_nanos();
    Ok(format!("{}-{stamp}", std::process::id()))
}

fn create_once(path: &Path, content: &str) -> io::Result<()> {
    if regular_or_missing(path)? {
        return Ok(());
    }
    let parent = path
        .parent()
        .ok_or_else(|| invalid("Missing configuration parent"))?;
    fs::create_dir_all(parent)?;
    let temp = parent.join(format!(".gx-create-{}", unique_suffix()?));
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temp)?;
    let result = (|| {
        file.write_all(content.as_bytes())?;
        file.sync_all()?;
        drop(file);
        match fs::hard_link(&temp, path) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                regular_or_missing(path)?;
                Ok(())
            }
            Err(error) => Err(error),
        }
    })();
    let cleanup = fs::remove_file(&temp);
    result.and(cleanup)
}

fn regular_file(path: &Path) -> io::Result<Option<bool>> {
    match fs::symlink_metadata(path) {
        Ok(metadata) => Ok(Some(metadata.is_file() && !is_link(&metadata))),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error),
    }
}

// herdr 自己也会改写 config.toml：rename 前复读，内容已变则放弃本次写入，由调用方重新判断。
fn replace_unchanged(path: &Path, original: &str, content: &str) -> io::Result<bool> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("Missing configuration parent"))?;
    let temp = parent.join(format!(".gx-update-{}", unique_suffix()?));
    let result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)?;
        file.write_all(content.as_bytes())?;
        file.sync_all()?;
        drop(file);
        #[cfg(unix)]
        fs::set_permissions(&temp, fs::metadata(path)?.permissions())?;
        if fs::read(path)? != original.as_bytes() {
            return Ok(false);
        }
        fs::rename(&temp, path).map(|()| true)
    })();
    if !matches!(result, Ok(true)) {
        let _ = fs::remove_file(&temp);
    }
    result
}

fn toml_string(value: &str) -> String {
    let mut quoted = String::from("\"");
    for ch in value.chars() {
        match ch {
            '\\' => quoted.push_str("\\\\"),
            '"' => quoted.push_str("\\\""),
            '\n' => quoted.push_str("\\n"),
            '\r' => quoted.push_str("\\r"),
            '\t' => quoted.push_str("\\t"),
            ch if ch.is_control() => quoted.push_str(&format!("\\u{:04X}", ch as u32)),
            ch => quoted.push(ch),
        }
    }
    quoted.push('"');
    quoted
}

fn unicode_escape(chars: &mut std::str::Chars, digits: usize) -> Option<char> {
    let hex: String = chars.by_ref().take(digits).collect();
    if hex.len() != digits || !hex.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return None;
    }
    char::from_u32(u32::from_str_radix(&hex, 16).ok()?)
}

// 解析开头的 TOML 字符串（也覆盖 JSON 字符串的转义），返回值与其后剩余的文本。
fn quoted(text: &str) -> Option<(String, &str)> {
    let mut chars = text.chars();
    let quote = chars.next().filter(|quote| matches!(quote, '"' | '\''))?;
    let mut value = String::new();
    loop {
        match chars.next()? {
            ch if ch == quote => return Some((value, chars.as_str())),
            '\\' if quote == '"' => value.push(match chars.next()? {
                'b' => '\u{8}',
                't' => '\t',
                'n' => '\n',
                'f' => '\u{c}',
                'r' => '\r',
                'e' => '\u{1b}',
                '"' => '"',
                '\\' => '\\',
                '/' => '/',
                'u' => unicode_escape(&mut chars, 4)?,
                'U' => unicode_escape(&mut chars, 8)?,
                _ => return None,
            }),
            ch => value.push(ch),
        }
    }
}

fn comment_only(text: &str) -> bool {
    let text = text.trim_start();
    text.is_empty() || text.starts_with('#')
}

fn toml_value(raw: &str) -> Option<String> {
    quoted(raw.trim_start())
        .filter(|(_, rest)| comment_only(rest))
        .map(|(value, _)| value)
}

fn toml_key(key: &str) -> &str {
    key.trim().trim_matches(['"', '\''])
}

fn toml_table(line: &str) -> Option<(bool, &str)> {
    let (array, (name, rest)) = match line.strip_prefix("[[") {
        Some(inner) => (true, inner.split_once("]]")?),
        None => (false, line.strip_prefix('[')?.split_once(']')?),
    };
    comment_only(rest).then_some((array, name.trim()))
}

fn terminal_key(key: &str) -> bool {
    key.split('.')
        .next()
        .is_some_and(|first| toml_key(first) == "terminal")
}

#[derive(Debug, Default)]
struct HerdrTerminal {
    marker: bool,
    default_shell: Option<String>,
    shell_mode: Option<String>,
}

fn herdr_terminal(content: &str) -> Option<HerdrTerminal> {
    let mut terminal = HerdrTerminal::default();
    let mut table = "";
    let mut sections = 0;
    for line in content.lines() {
        let line = line.trim_start_matches('\u{feff}').trim();
        if line.starts_with('#') {
            terminal.marker |= line.starts_with(HERDR_MARKER_PREFIX);
        } else if line.starts_with('[') {
            table = match toml_table(line)? {
                (false, "terminal") => "terminal",
                (_, name) if terminal_key(name) => return None,
                _ => "other",
            };
            sections += usize::from(table == "terminal");
        } else if let Some((key, value)) = line.split_once('=') {
            let key = toml_key(key);
            let slot = match table {
                "" if terminal_key(key) => return None,
                "terminal" if key == "default_shell" => &mut terminal.default_shell,
                "terminal" if key == "shell_mode" => &mut terminal.shell_mode,
                _ => continue,
            };
            let value = toml_value(value).unwrap_or_else(|| value.trim().to_owned());
            if slot.replace(value).is_some() {
                return None;
            }
        }
    }
    (sections <= 1).then_some(terminal)
}

fn set_herdr_shell(content: &str, shell: &str) -> String {
    let newline = if content.contains("\r\n") {
        "\r\n"
    } else {
        "\n"
    };
    let (bom, body) = match content.strip_prefix('\u{feff}') {
        Some(body) => ("\u{feff}", body),
        None => ("", content),
    };
    let values = [toml_string(shell), "\"login\"".to_owned()];
    let mut written = [false; 2];
    let mut lines = Vec::new();
    if !body
        .lines()
        .any(|line| line.trim().starts_with(HERDR_MARKER_PREFIX))
    {
        lines.push(HERDR_MARKER.to_owned());
    }
    let mut in_terminal = false;
    let mut header = None;
    for line in body.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('[') {
            in_terminal = toml_table(trimmed) == Some((false, "terminal"));
            if in_terminal {
                header = Some(lines.len());
            }
        } else if let Some((key, raw)) = line
            .split_once('=')
            .filter(|_| in_terminal && !trimmed.starts_with('#'))
        {
            if let Some(index) = HERDR_KEYS.iter().position(|name| toml_key(key) == *name) {
                if !written[index] {
                    let comment = quoted(raw.trim_start())
                        .map(|(_, rest)| rest.trim_end())
                        .filter(|rest| comment_only(rest))
                        .unwrap_or_default();
                    let indent = &line[..line.len() - line.trim_start().len()];
                    lines.push(format!(
                        "{indent}{} = {}{comment}",
                        HERDR_KEYS[index], values[index]
                    ));
                    written[index] = true;
                }
                continue;
            }
        }
        lines.push(line.to_owned());
    }
    let missing = HERDR_KEYS
        .iter()
        .zip(values)
        .zip(written)
        .filter(|(_, written)| !written)
        .map(|((key, value), _)| format!("{key} = {value}"));
    match header {
        Some(index) => {
            let rest = lines.split_off(index + 1);
            lines.extend(missing);
            lines.extend(rest);
        }
        None => {
            if lines.last().is_some_and(|line| !line.trim().is_empty()) {
                lines.push(String::new());
            }
            lines.push("[terminal]".to_owned());
            lines.extend(missing);
        }
    }
    format!("{bom}{}{newline}", lines.join(newline))
}

fn new_herdr_config(shell: &str) -> String {
    format!(
        "{HERDR_MARKER}\n[terminal]\ndefault_shell = {}\nshell_mode = \"login\"\n\n[update]\nversion_check = false\nmanifest_check = false\n",
        toml_string(shell),
    )
}

fn shell_text(layout: &Layout) -> io::Result<&str> {
    layout
        .shell
        .to_str()
        .ok_or_else(|| invalid("Zsh path is not UTF-8"))
}

fn legacy_shell(layout: &Layout, shell: &str) -> bool {
    #[cfg(windows)]
    {
        let _ = layout;
        shell
            .strip_suffix(LEGACY_SHELL_SUFFIX)
            .is_some_and(|root| Path::new(root).is_absolute())
    }
    #[cfg(unix)]
    {
        layout.shell.to_str() == Some(shell)
    }
}

fn stale_shell(shell: &str) -> bool {
    let path = Path::new(shell);
    path.is_absolute() && !path.is_file()
}

#[derive(Debug, PartialEq)]
enum HerdrConfigChange {
    Keep,
    Write(String),
    Custom,
}

// adopted：本 profile 的 config.toml 曾由 GX 创建或收编；此后删掉标记行即归用户，不再按旧版值收编。
fn herdr_config_change(
    layout: &Layout,
    content: &str,
    requested: Option<&str>,
    adopted: bool,
) -> io::Result<HerdrConfigChange> {
    let Some(terminal) = herdr_terminal(content) else {
        return Ok(HerdrConfigChange::Custom);
    };
    let current = terminal.default_shell.as_deref();
    let legacy = current.is_some_and(|shell| legacy_shell(layout, shell));
    if !terminal.marker && (adopted || !legacy || terminal.shell_mode.as_deref() != Some("login")) {
        return Ok(HerdrConfigChange::Custom);
    }
    let shell = match requested {
        Some(shell) => shell,
        None if legacy || current.is_none_or(stale_shell) => shell_text(layout)?,
        None => return Ok(HerdrConfigChange::Keep),
    };
    let updated = set_herdr_shell(content, shell);
    Ok(if updated == content {
        HerdrConfigChange::Keep
    } else {
        HerdrConfigChange::Write(updated)
    })
}

fn mark_adopted(layout: &Layout) -> io::Result<()> {
    create_once(
        &layout.herdr_adopted(),
        "GX Shell created or adopted config.toml; once its marker line is removed the file belongs to the user.\n",
    )
}

fn update_herdr_config(layout: &Layout, requested: Option<&str>) -> io::Result<bool> {
    let path = layout.herdr_config();
    let adopted = regular_file(&layout.herdr_adopted())?.is_some();
    for _ in 0..3 {
        let content = match fs::read_to_string(&path) {
            Ok(content) => content,
            Err(error) if error.kind() == io::ErrorKind::InvalidData => return Ok(false),
            Err(error) => return Err(error),
        };
        match herdr_config_change(layout, &content, requested, adopted)? {
            HerdrConfigChange::Custom => return Ok(false),
            HerdrConfigChange::Write(updated) => {
                if !replace_unchanged(&path, &content, &updated)? {
                    continue;
                }
            }
            HerdrConfigChange::Keep => {}
        }
        mark_adopted(layout)?;
        return Ok(true);
    }
    Err(invalid(format!(
        "{} kept changing while it was being updated",
        path.display()
    )))
}

fn ensure_herdr_config(layout: &Layout) -> io::Result<()> {
    let path = layout.herdr_config();
    match regular_file(&path)? {
        None => {
            create_once(&path, &new_herdr_config(shell_text(layout)?))?;
            mark_adopted(layout)
        }
        Some(false) => Ok(()),
        Some(true) => {
            if let Err(error) = update_herdr_config(layout, None) {
                eprintln!("Oh My Zsh GX: cannot migrate {}: {error}", path.display());
            }
            Ok(())
        }
    }
}

fn same_file(path: &Path, other: &Path) -> bool {
    match (resolve_destination(path), resolve_destination(other)) {
        (Ok(path), Ok(other)) => {
            path == other
                || (cfg!(windows) && path.as_os_str().eq_ignore_ascii_case(other.as_os_str()))
        }
        _ => false,
    }
}

// 启动器会把托管文件作为 HERDR_CONFIG_PATH 传给子进程；只有指向别处才算自定义配置。
fn custom_herdr_config(layout: &Layout, parent: &Environment<'_>) -> Option<OsString> {
    parent("HERDR_CONFIG_PATH").filter(|path| !same_file(Path::new(path), &layout.herdr_config()))
}

fn report_custom_herdr_config(location: &str) {
    eprintln!("Oh My Zsh GX: herdr uses a custom configuration ({location}); default_shell was not changed");
}

fn store_default_shell(
    layout: &Layout,
    shell: &OsStr,
    parent: &Environment<'_>,
) -> io::Result<bool> {
    if let Some(config) = custom_herdr_config(layout, parent) {
        report_custom_herdr_config(&format!(
            "HERDR_CONFIG_PATH={}",
            Path::new(&config).display()
        ));
        return Ok(false);
    }
    let shell = PathBuf::from(shell);
    #[cfg(windows)]
    let shell = native(shell);
    if !shell.is_absolute() || !shell.is_file() {
        return Err(invalid(format!(
            "Not an absolute path to a shell executable: {}",
            shell.display()
        )));
    }
    let shell = shell
        .to_str()
        .ok_or_else(|| invalid("Shell path is not UTF-8"))?;
    let _lock = lock_profile(layout)?;
    let path = layout.herdr_config();
    let managed = match regular_file(&path)? {
        None => {
            create_once(&path, &new_herdr_config(shell))?;
            mark_adopted(layout)?;
            true
        }
        Some(false) => false,
        Some(true) => update_herdr_config(layout, Some(shell))?,
    };
    if !managed {
        report_custom_herdr_config(&path.display().to_string());
    }
    Ok(managed)
}

fn json_value<'a>(text: &'a str, key: &str) -> Option<&'a str> {
    let key = format!("\"{key}\"");
    let start = text.find(&key)? + key.len();
    Some(text[start..].trim_start().strip_prefix(':')?.trim_start())
}

fn reload_report(text: &str) -> Option<(String, Vec<String>)> {
    let (status, _) = quoted(json_value(text, "status")?)?;
    let mut rest = json_value(text, "diagnostics")?
        .strip_prefix('[')?
        .trim_start();
    let mut diagnostics = Vec::new();
    while !rest.starts_with(']') {
        let (diagnostic, tail) = quoted(rest)?;
        diagnostics.push(diagnostic);
        let tail = tail.trim_start();
        rest = tail.strip_prefix(',').unwrap_or(tail).trim_start();
    }
    Some((status, diagnostics))
}

fn server_running(status: &[u8]) -> bool {
    let compact: Vec<u8> = status
        .iter()
        .copied()
        .filter(|byte| !byte.is_ascii_whitespace())
        .collect();
    compact
        .windows(b"\"running\":true".len())
        .any(|window| window == b"\"running\":true")
}

fn reload_herdr(layout: &Layout) -> io::Result<()> {
    let herdr = |args: &[&str]| {
        let mut command = Command::new(layout.real_herdr());
        command
            .args(args)
            .env("HERDR_CONFIG_PATH", layout.herdr_config());
        default_session(&mut command, &|name| env::var_os(name));
        command.output()
    };
    let status = herdr(&["status", "server", "--json"])?;
    if !status.status.success() {
        return Err(invalid(format!(
            "Cannot query the herdr server: {}",
            String::from_utf8_lossy(&status.stderr).trim()
        )));
    }
    if !server_running(&status.stdout) {
        return Ok(());
    }
    let reload = herdr(&["server", "reload-config"])?;
    let output = String::from_utf8_lossy(&reload.stdout);
    match reload_report(&output) {
        Some((status, diagnostics))
            if reload.status.success() && matches!(status.as_str(), "applied" | "partial") =>
        {
            for diagnostic in diagnostics {
                eprintln!("Oh My Zsh GX: herdr config warning: {diagnostic}");
            }
            Ok(())
        }
        Some((status, diagnostics)) if reload.status.success() => Err(invalid(format!(
            "herdr config was updated, but the running herdr server did not apply it ({status}): {}",
            diagnostics.join("; ")
        ))),
        _ => {
            let stderr = String::from_utf8_lossy(&reload.stderr);
            let detail = if stderr.trim().is_empty() {
                output.trim()
            } else {
                stderr.trim()
            };
            Err(invalid(format!(
                "herdr config was updated, but the running herdr server did not reload it: {detail}"
            )))
        }
    }
}

fn set_default_shell(layout: &Layout, shell: &OsStr) -> io::Result<i32> {
    if !store_default_shell(layout, shell, &|name| env::var_os(name))? {
        return Ok(3);
    }
    reload_herdr(layout)?;
    Ok(0)
}

fn resolve_destination(path: &Path) -> io::Result<PathBuf> {
    let mut ancestor = path.to_path_buf();
    let mut suffix = Vec::new();
    loop {
        match ancestor.canonicalize() {
            Ok(mut resolved) => {
                for name in suffix.iter().rev() {
                    resolved.push(name);
                }
                return Ok(resolved);
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                if fs::symlink_metadata(&ancestor).is_ok() {
                    return Err(invalid(format!(
                        "Unresolved path link: {}",
                        ancestor.display()
                    )));
                }
                suffix.push(
                    ancestor
                        .file_name()
                        .ok_or_else(|| invalid("Invalid profile ancestor"))?
                        .to_owned(),
                );
                if !ancestor.pop() {
                    return Err(error);
                }
            }
            Err(error) => return Err(error),
        }
    }
}

fn check_profile_location(layout: &Layout) -> io::Result<()> {
    for path in [&layout.profile, &layout.profile.join("herdr")] {
        match fs::symlink_metadata(path) {
            Ok(metadata) if metadata.is_dir() && !is_link(&metadata) => {}
            Ok(_) => {
                return Err(invalid(format!(
                    "Unsafe GX profile directory: {}",
                    path.display()
                )))
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(error),
        }
    }
    let profile = resolve_destination(&layout.profile)?;
    let home = resolve_destination(&layout.home)?;
    let resources = resolve_destination(&layout.resources)?;
    if profile == home || profile.starts_with(&resources) || resources.starts_with(&profile) {
        return Err(invalid(
            "GX profile must be separate from HOME and packaged resources",
        ));
    }
    Ok(())
}

fn p10k_identity(layout: &Layout) -> io::Result<String> {
    let identity = fs::read_to_string(layout.resources.join("p10k-runtime-id"))?;
    let identity = identity.trim();
    if identity.len() != 64 || !identity.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(invalid("Invalid P10k runtime identity"));
    }
    Ok(identity.to_owned())
}

fn regular_tree(source: &Path, destination: &Path, copy: bool) -> io::Result<()> {
    let metadata = fs::symlink_metadata(source)?;
    if is_link(&metadata) {
        return Err(invalid(format!(
            "Theme source contains a link: {}",
            source.display()
        )));
    }
    if metadata.is_dir() {
        if copy {
            fs::create_dir(destination)?;
        }
        let target = fs::symlink_metadata(destination)?;
        if !target.is_dir() || is_link(&target) {
            return Err(invalid("Unsafe P10k runtime directory"));
        }
        for entry in fs::read_dir(source)? {
            let entry = entry?;
            regular_tree(&entry.path(), &destination.join(entry.file_name()), copy)?;
        }
    } else if metadata.is_file() {
        if copy {
            fs::copy(source, destination)?;
            let mut permissions = fs::metadata(destination)?.permissions();
            #[cfg(windows)]
            permissions.set_readonly(false);
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                permissions.set_mode((permissions.mode() & 0o777) | 0o600);
            }
            fs::set_permissions(destination, permissions)?;
        }
        if !regular_or_missing(destination)? || fs::read(source)? != fs::read(destination)? {
            return Err(invalid(format!(
                "P10k runtime source changed: {}",
                destination.display()
            )));
        }
    } else {
        return Err(invalid("Theme source contains a special file"));
    }
    Ok(())
}

fn prepare_profile(layout: &Layout) -> io::Result<()> {
    let profile = layout.profile.canonicalize()?;
    let windows: &[&str] = if cfg!(windows) {
        &[
            ".cache/oh-my-zsh",
            ".cache/oh-my-zsh/completions",
            ".local",
            ".local/share",
            ".local/share/zoxide",
        ]
    } else {
        &[]
    };
    for relative in [".cache", ".cache/themes", ".cache/tmp"]
        .iter()
        .chain(windows)
    {
        let directory = subpath(&layout.profile, relative);
        match fs::symlink_metadata(&directory) {
            Ok(metadata) if metadata.is_dir() && !is_link(&metadata) => {}
            Ok(_) => {
                return Err(invalid(format!(
                    "GX profile directories cannot be links or files: {}",
                    directory.display()
                )))
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(error),
        }
        if !resolve_destination(&directory)?.starts_with(&profile) {
            return Err(invalid(format!(
                "GX profile directory escapes the profile: {}",
                directory.display()
            )));
        }
        fs::create_dir_all(directory)?;
    }
    Ok(())
}

fn prepare_p10k(layout: &Layout) -> io::Result<()> {
    let identity = p10k_identity(layout)?;
    let parent = subpath(&layout.profile, ".cache/themes");
    let destination = parent.join(&identity);
    let source = subpath(&layout.resources, "gx/omz-custom/themes/powerlevel10k");
    if destination.exists() || fs::symlink_metadata(&destination).is_ok() {
        let metadata = fs::symlink_metadata(&destination)?;
        if !metadata.is_dir()
            || is_link(&metadata)
            || !regular_or_missing(&destination.join(".gx-complete"))?
            || fs::read_to_string(destination.join(".gx-complete"))? != identity
        {
            return Err(invalid(
                "Incomplete or unowned P10k cache; preserve it and inspect manually",
            ));
        }
        return regular_tree(&source, &destination.join("powerlevel10k"), false);
    }
    let staging = parent.join(format!(".gx-stage-{}", unique_suffix()?));
    fs::create_dir(&staging)?;
    let result = (|| {
        regular_tree(&source, &staging.join("powerlevel10k"), true)?;
        fs::write(staging.join(".gx-complete"), &identity)?;
        fs::rename(&staging, destination)
    })();
    if result.is_err() {
        let _ = fs::remove_dir_all(&staging);
    }
    result
}

fn lock_profile(layout: &Layout) -> io::Result<File> {
    check_profile_location(layout)?;
    fs::create_dir_all(&layout.profile)?;
    let lock_path = layout.profile.join(".initialize.lock");
    regular_or_missing(&lock_path)?;
    let lock = File::options()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(lock_path)?;
    lock.lock()?;
    Ok(lock)
}

fn initialize(layout: &Layout, own_herdr_config: bool) -> io::Result<()> {
    let _lock = lock_profile(layout)?;
    prepare_profile(layout)?;
    prepare_p10k(layout)?;
    create_once(&layout.profile.join(".zshenv"), "skip_global_compinit=1\n")?;
    create_once(
        &layout.profile.join(".zshrc"),
        "source \"$GX_PACKAGE_ROOT/gx/config/zshrc\"\n",
    )?;
    if own_herdr_config {
        ensure_herdr_config(layout)?;
    }
    Ok(())
}

fn blocked_update(args: &[OsString]) -> bool {
    let mut cleaned = Vec::new();
    let mut index = 0;
    while index < args.len() {
        let arg = args[index].to_str().unwrap_or("");
        if arg == "--" {
            cleaned.extend_from_slice(&args[index..]);
            break;
        }
        if matches!(arg, "--session" | "--remote" | "--remote-keybindings") {
            index += 2;
            continue;
        }
        if ["--session=", "--remote=", "--remote-keybindings="]
            .iter()
            .any(|prefix| arg.starts_with(prefix))
        {
            index += 1;
            continue;
        }
        cleaned.push(args[index].clone());
        index += 1;
    }
    cleaned.first().is_some_and(|arg| arg == "update")
        || (cleaned.first().is_some_and(|arg| arg == "channel")
            && cleaned.get(1).is_some_and(|arg| arg == "set"))
}

fn informational(args: &[OsString]) -> bool {
    matches!(args, [arg] if [
        "--version",
        "-V",
        "--help",
        "-h",
        "--default-config",
        "--skill",
    ]
    .iter()
    .any(|value| arg == value))
}

fn windows_path(value: &OsStr) -> bool {
    let value = value.as_encoded_bytes();
    cfg!(windows)
        && (matches!(value, [drive, b':', b'\\' | b'/', ..] if drive.is_ascii_alphabetic())
            || value.starts_with(b"\\\\")
            || value.starts_with(b"//"))
}

fn fpath_entries(value: &OsStr) -> Vec<OsString> {
    #[cfg(windows)]
    if let Some(text) = value.to_str() {
        let separator = if text.contains(';') || windows_path(value) {
            ';'
        } else {
            ':'
        };
        return text
            .split(separator)
            .filter(|entry| !entry.is_empty())
            .map(OsString::from)
            .collect();
    }
    env::split_paths(value)
        .map(PathBuf::into_os_string)
        .filter(|entry| !entry.is_empty())
        .collect()
}

fn cygpath_lines(output: &[u8], count: usize) -> Option<Vec<OsString>> {
    let output = std::str::from_utf8(output)
        .ok()?
        .trim_end_matches(['\r', '\n']);
    let lines: Vec<&str> = output
        .split('\n')
        .map(|line| line.strip_suffix('\r').unwrap_or(line))
        .collect();
    (lines.len() == count
        && lines
            .iter()
            .all(|line| !line.is_empty() && !line.contains('\r')))
    .then(|| lines.into_iter().map(OsString::from).collect())
}

// 路径经标准输入逐行交给 cygpath，避开 MSYS2 对命令行的引号、通配与花括号展开；
// 无法按行传递或结果对不上时逐个用参数转换。
fn posix_paths(cygpath: &mut Cygpath<'_>, paths: &[OsString]) -> Vec<io::Result<OsString>> {
    let lines: Option<String> = paths
        .iter()
        .map(|path| {
            path.to_str()
                .filter(|path| !path.is_empty() && !path.contains(['\r', '\n']))
                .map(|path| format!("{path}\n"))
        })
        .collect();
    if let Some(Ok(Some(output))) = lines.map(|lines| cygpath(CygpathInput::Lines(&lines))) {
        if let Some(lines) = cygpath_lines(&output, paths.len()) {
            return lines.into_iter().map(Ok).collect();
        }
    }
    paths
        .iter()
        .map(|path| {
            let output = cygpath(CygpathInput::Path(path))?.ok_or_else(|| {
                invalid(format!(
                    "Cannot convert MSYS2 path: {}",
                    Path::new(path).display()
                ))
            })?;
            cygpath_lines(&output, 1)
                .and_then(|mut lines| lines.pop())
                .ok_or_else(|| invalid("cygpath returned an invalid path"))
        })
        .collect()
}

struct PosixPaths(HashMap<OsString, OsString>);

impl PosixPaths {
    fn convert(
        cygpath: &mut Cygpath<'_>,
        required: &[&Path],
        optional: &[&OsStr],
    ) -> io::Result<Self> {
        let mut inputs: Vec<OsString> = required
            .iter()
            .map(|path| path.as_os_str().to_owned())
            .collect();
        inputs.extend(
            optional
                .iter()
                .filter(|value| windows_path(value))
                .map(|value| value.to_os_string()),
        );
        let results = if cfg!(windows) {
            posix_paths(cygpath, &inputs)
        } else {
            inputs.iter().cloned().map(Ok).collect()
        };
        let mut paths = HashMap::new();
        for (index, (input, result)) in inputs.into_iter().zip(results).enumerate() {
            match result {
                Ok(path) => {
                    paths.insert(input, path);
                }
                Err(error) if index < required.len() => return Err(error),
                Err(_) => {}
            }
        }
        Ok(Self(paths))
    }

    fn path(&self, path: &Path) -> io::Result<OsString> {
        self.0
            .get(path.as_os_str())
            .cloned()
            .ok_or_else(|| invalid(format!("Cannot convert MSYS2 path: {}", path.display())))
    }

    fn value(&self, value: &OsStr) -> Option<OsString> {
        if windows_path(value) {
            self.0.get(value).cloned()
        } else {
            Some(value.to_owned())
        }
    }
}

fn posix_join(base: &OsStr, relative: &str) -> OsString {
    let mut path = base.to_owned();
    if !path.as_encoded_bytes().ends_with(b"/") {
        path.push("/");
    }
    path.push(relative);
    path
}

fn posix_key(path: &OsStr) -> Option<String> {
    let path = path.to_str()?;
    let path = match path.strip_prefix("/cygdrive") {
        Some(rest)
            if matches!(rest.as_bytes(), [b'/', drive, ..] if drive.is_ascii_alphabetic())
                && matches!(rest.as_bytes().get(2), None | Some(b'/')) =>
        {
            rest
        }
        _ => path,
    };
    let (root, rest) = match path.strip_prefix("//") {
        Some(rest) => ("//", rest),
        None => ("/", path.strip_prefix('/')?),
    };
    let mut parts = Vec::new();
    for part in rest.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            part => parts.push(part),
        }
    }
    let key = format!("{root}{}", parts.join("/"));
    Some(if cfg!(windows) {
        key.to_ascii_lowercase()
    } else {
        key
    })
}

fn same_posix(path: &OsStr, other: &OsStr) -> bool {
    posix_key(path).is_some_and(|path| Some(path) == posix_key(other))
}

fn posix_inside(path: &OsStr, base: &OsStr) -> bool {
    match (posix_key(path), posix_key(base)) {
        (Some(path), Some(base)) => {
            path == base
                || path
                    .strip_prefix(&base)
                    .is_some_and(|rest| rest.starts_with('/'))
        }
        _ => false,
    }
}

fn msys_cygpath(layout: &Layout) -> impl FnMut(CygpathInput<'_>) -> io::Result<Option<Vec<u8>>> {
    let program = subpath(&layout.root, "runtime/msys64/usr/bin/cygpath.exe");
    move |input: CygpathInput<'_>| {
        let mut command = Command::new(&program);
        command.arg("-u").env("LC_ALL", "C.UTF-8");
        let output = match input {
            CygpathInput::Path(path) => command.arg("--").arg(path).output()?,
            CygpathInput::Lines(lines) => {
                let mut child = command
                    .args(["-f", "-"])
                    .stdin(Stdio::piped())
                    .stdout(Stdio::piped())
                    .stderr(Stdio::null())
                    .spawn()?;
                let mut stdin = child
                    .stdin
                    .take()
                    .ok_or_else(|| invalid("cygpath input is unavailable"))?;
                let lines = lines.to_owned();
                let writer = thread::spawn(move || stdin.write_all(lines.as_bytes()));
                let output = child.wait_with_output()?;
                writer
                    .join()
                    .map_err(|_| invalid("cygpath input writer failed"))??;
                output
            }
        };
        Ok(output.status.success().then_some(output.stdout))
    }
}

fn default_session(command: &mut Command, parent: &Environment<'_>) {
    if parent("HERDR_SESSION").is_none() && parent("HERDR_SOCKET_PATH").is_none() {
        command.env("HERDR_SESSION", "ohmyzsh-gx");
    }
}

fn package_environment(
    command: &mut Command,
    layout: &Layout,
    herdr: bool,
    parent: &Environment<'_>,
    cygpath: &mut Cygpath<'_>,
) -> io::Result<()> {
    let gx_parent = parent("GX_PACKAGE_ROOT").is_some() || parent("GX_PROFILE_DIR").is_some();
    let inherited: Vec<(&str, OsString)> = if gx_parent {
        [
            "ZSH_CUSTOM",
            "POWERLEVEL9K_INSTALLATION_DIR",
            "XDG_CACHE_HOME",
        ]
        .into_iter()
        .filter_map(|name| Some((name, parent(name)?)))
        .collect()
    } else {
        Vec::new()
    };
    let fpath = match parent("FPATH") {
        Some(value) if !gx_parent => fpath_entries(&value),
        _ => Vec::new(),
    };
    let bin = subpath(&layout.root, "bin");
    let zsh_data = layout.zsh_data();
    let gitstatus = subpath(&layout.root, "lib/gitstatus");
    let mut required: Vec<&Path> = vec![
        &layout.resources,
        &bin,
        &layout.profile,
        &zsh_data,
        &gitstatus,
    ];
    if !herdr {
        required.push(&layout.home);
    }
    let optional: Vec<&OsStr> = inherited
        .iter()
        .map(|(_, value)| value.as_os_str())
        .chain(fpath.iter().map(OsString::as_os_str))
        .collect();
    let posix = PosixPaths::convert(cygpath, &required, &optional)?;
    let resources = posix.path(&layout.resources)?;
    let profile = posix.path(&layout.profile)?;
    let functions = posix.path(&zsh_data)?;
    command.env("GX_PACKAGE_ROOT", &resources);
    command.env("GX_PACKAGE_BIN", posix.path(&bin)?);
    command.env("GX_PROFILE_DIR", &profile);
    command.env(
        "GX_P10K_RUNTIME_DIR",
        posix_join(
            &profile,
            &format!(".cache/themes/{}/powerlevel10k", p10k_identity(layout)?),
        ),
    );
    command.env("ZDOTDIR", &profile);
    command.env("TMPDIR", posix_join(&profile, ".cache/tmp"));
    command.env("TMPPREFIX", posix_join(&profile, ".cache/tmp/zsh"));
    let mut search = posix_join(&functions, "functions");
    search.push(":");
    search.push(posix_join(&functions, "site-functions"));
    for entry in fpath.iter().filter_map(|entry| posix.value(entry)) {
        if entry.as_encoded_bytes().starts_with(b"/") {
            search.push(":");
            search.push(entry);
        }
    }
    command.env("FPATH", search);
    if !herdr {
        command.env("HOME", posix.path(&layout.home)?);
    }
    command.env("GITSTATUS_CACHE_DIR", posix.path(&gitstatus)?);
    if gx_parent {
        for name in GX_DERIVED_VARIABLES {
            command.env_remove(name);
        }
        let custom = posix_join(&resources, "gx/omz-custom");
        let theme = posix_join(&custom, "themes/powerlevel10k");
        for (name, value) in &inherited {
            let Some(value) = posix.value(value) else {
                continue;
            };
            match *name {
                "XDG_CACHE_HOME" => {
                    if posix_inside(&value, &profile) {
                        command.env_remove(name);
                    }
                }
                "ZSH_CUSTOM" if same_posix(&value, &custom) => {
                    command.env_remove(name);
                }
                "POWERLEVEL9K_INSTALLATION_DIR" if same_posix(&value, &theme) => {
                    command.env_remove(name);
                }
                _ => {
                    command.env(name, value);
                }
            }
        }
    }
    #[cfg(windows)]
    if parent("_ZO_DATA_DIR").is_none_or(|value| value.is_empty()) {
        command.env(
            "_ZO_DATA_DIR",
            subpath(&layout.profile, ".local/share/zoxide"),
        );
    }
    Ok(())
}

fn configured_command(
    layout: &Layout,
    herdr: bool,
    args: &[OsString],
    parent: &Environment<'_>,
    cygpath: &mut Cygpath<'_>,
) -> io::Result<Command> {
    let mut command = Command::new(if herdr {
        layout.real_herdr()
    } else {
        layout.shell.clone()
    });
    if !herdr {
        command.arg("-il");
    }
    command.args(args);
    if herdr {
        command.env("HOME", &layout.home);
    }
    if !(herdr && informational(args)) {
        package_environment(&mut command, layout, herdr, parent, cygpath)?;
    }
    let mut paths = vec![subpath(&layout.root, "bin")];
    #[cfg(windows)]
    {
        paths.push(subpath(&layout.root, "runtime/msys64/usr/bin"));
        paths.push(subpath(&layout.root, "runtime/msys64/ucrt64/bin"));
        command.env("MSYSTEM", "MSYS");
        command.env("MSYS2_PATH_TYPE", "inherit");
        command.env("CHERE_INVOKING", "1");
        command.env("LANG", "C.UTF-8");
    }
    if let Some(path) = parent("PATH") {
        paths.extend(env::split_paths(&path));
    }
    command.env("PATH", env::join_paths(paths).map_err(invalid)?);
    if parent("HERDR_CONFIG_PATH").is_none() {
        command.env("HERDR_CONFIG_PATH", layout.herdr_config());
    }
    default_session(&mut command, parent);
    Ok(command)
}

#[cfg(windows)]
#[link(name = "kernel32")]
unsafe extern "system" {
    fn SetConsoleCtrlHandler(
        handler: Option<unsafe extern "system" fn(u32) -> i32>,
        add: i32,
    ) -> i32;
}

#[cfg(windows)]
unsafe extern "system" fn console_control(event: u32) -> i32 {
    i32::from(event == 0 || event == 1)
}

fn launch(mut command: Command, herdr: bool) -> io::Result<i32> {
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        let _ = herdr;
        Err(command.exec())
    }
    #[cfg(windows)]
    {
        unsafe {
            // 清除继承的「忽略 Ctrl+C」标志，让 Zsh 及其前台作业能被中断；herdr 变体保持原状。
            if !herdr {
                SetConsoleCtrlHandler(None, 0);
            }
            SetConsoleCtrlHandler(Some(console_control), 1);
        }
        Ok(command.status()?.code().unwrap_or(1))
    }
}

fn run() -> io::Result<i32> {
    let args: Vec<_> = env::args_os().skip(1).collect();
    let herdr = cfg!(gx_herdr);
    if herdr && blocked_update(&args) {
        return Err(invalid("herdr is managed by Oh My Zsh GX. Install a new GX EXE/DEB to update; upstream self-update and channel switching are disabled by this entry point."));
    }
    let layout = Layout::discover()?;
    layout.validate(herdr)?;
    if herdr
        && args
            .first()
            .is_some_and(|arg| arg == "--gx-set-default-shell")
    {
        return match args.as_slice() {
            [_, shell] => set_default_shell(&layout, shell),
            _ => Err(invalid(
                "Usage: herdr --gx-set-default-shell <absolute path to a shell executable>",
            )),
        };
    }
    if !(herdr && informational(&args)) {
        initialize(
            &layout,
            custom_herdr_config(&layout, &|name| env::var_os(name)).is_none(),
        )?;
    }
    if args.as_slice() == [OsStr::new("--gx-initialize-only")] {
        return Ok(0);
    }
    let command = configured_command(
        &layout,
        herdr,
        &args,
        &|name| env::var_os(name),
        &mut msys_cygpath(&layout),
    )?;
    launch(command, herdr)
}

fn main() {
    let code = run().unwrap_or_else(|error| {
        eprintln!("Oh My Zsh GX: {error}");
        1
    });
    std::process::exit(code);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct Temp(PathBuf);
    impl Temp {
        fn new() -> Self {
            static COUNT: AtomicUsize = AtomicUsize::new(0);
            let path = env::temp_dir().join(format!(
                "gx-launcher-{}-{}",
                unique_suffix().unwrap(),
                COUNT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }
    }
    impl Drop for Temp {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }
    fn args(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }
    fn p10k_runtime(layout: &Layout) -> io::Result<PathBuf> {
        Ok(subpath(&layout.profile, ".cache/themes")
            .join(p10k_identity(layout)?)
            .join("powerlevel10k"))
    }
    fn fake_posix(path: &OsStr) -> String {
        let path = path.to_str().unwrap();
        match path.as_bytes() {
            [drive, b':', ..] => format!(
                "/{}{}",
                char::from(*drive).to_ascii_lowercase(),
                path[2..].replace('\\', "/")
            ),
            _ => path.replace('\\', "/"),
        }
    }
    fn input_paths(input: CygpathInput<'_>) -> Vec<OsString> {
        match input {
            CygpathInput::Lines(lines) => lines.lines().map(OsString::from).collect(),
            CygpathInput::Path(path) => vec![path.to_owned()],
        }
    }
    fn fake_cygpath(
        calls: &mut Vec<usize>,
    ) -> impl FnMut(CygpathInput<'_>) -> io::Result<Option<Vec<u8>>> + '_ {
        move |input: CygpathInput<'_>| {
            let paths = input_paths(input);
            calls.push(paths.len());
            Ok(Some(
                paths
                    .iter()
                    .map(|path| fake_posix(path) + "\n")
                    .collect::<String>()
                    .into_bytes(),
            ))
        }
    }
    fn change(layout: &Layout, content: &str, requested: Option<&str>) -> HerdrConfigChange {
        herdr_config_change(layout, content, requested, false).unwrap()
    }
    fn posix(path: &Path) -> String {
        if cfg!(windows) {
            fake_posix(path.as_os_str())
        } else {
            path.to_str().unwrap().to_owned()
        }
    }
    fn msys_form(path: &Path) -> OsString {
        if cfg!(windows) {
            path.to_str().unwrap().replace('\\', "/").into()
        } else {
            path.as_os_str().to_owned()
        }
    }
    fn envs(command: &Command) -> HashMap<String, Option<String>> {
        command
            .get_envs()
            .map(|(key, value)| {
                (
                    key.to_str().unwrap().to_owned(),
                    value.map(|value| value.to_str().unwrap().to_owned()),
                )
            })
            .collect()
    }
    fn package_layout(temp: &Temp) -> Layout {
        let root = temp.0.join("install");
        let layout = Layout {
            resources: subpath(&root, "share/ohmyzsh-gx"),
            profile: temp.0.join("profile 中文"),
            home: temp.0.join("home"),
            shell: subpath(
                &root,
                if cfg!(windows) {
                    "runtime/msys64/usr/bin/zsh.exe"
                } else {
                    "libexec/zsh/zsh"
                },
            ),
            root,
        };
        let theme = subpath(&layout.resources, "gx/omz-custom/themes/powerlevel10k");
        fs::create_dir_all(&theme).unwrap();
        fs::write(theme.join("powerlevel10k.zsh-theme"), "theme source").unwrap();
        fs::write(layout.resources.join("p10k-runtime-id"), "a".repeat(64)).unwrap();
        layout
    }
    fn released_shell(root: &Path) -> String {
        root.join(if cfg!(windows) {
            "runtime/msys64/usr/bin/zsh.exe"
        } else {
            "libexec/zsh/zsh"
        })
        .to_str()
        .unwrap()
        .to_owned()
    }
    fn legacy_config(shell: &str) -> String {
        format!(
            "[terminal]\ndefault_shell = {}\nshell_mode = \"login\"\n\n[update]\nversion_check = false\nmanifest_check = false\n",
            toml_string(shell)
        )
    }
    #[test]
    fn update_gate_matches_top_level_after_session_selection() {
        for values in [
            vec!["update"],
            vec!["--session", "work", "update", "--handoff"],
            vec!["--session=work", "channel", "set", "preview"],
            vec!["channel", "--session", "work", "set", "stable"],
        ] {
            assert!(blocked_update(&args(&values)), "{values:?}");
        }
        for values in [
            vec!["agent", "prompt", "worker", "update"],
            vec!["--session", "update"],
            vec!["channel", "show"],
            vec!["--", "update"],
            vec!["completion", "zsh"],
        ] {
            assert!(!blocked_update(&args(&values)), "{values:?}");
        }
    }
    #[test]
    fn toml_quotes_windows_and_unicode_paths() {
        assert_eq!(
            toml_string("C:\\中文 space\\zsh.exe"),
            "\"C:\\\\中文 space\\\\zsh.exe\""
        );
        assert_eq!(toml_string("a\"b\n\t"), "\"a\\\"b\\n\\t\"");
    }
    #[test]
    fn toml_strings_round_trip() {
        for value in ["C:\\中文 space\\zsh.exe", "a\"b\n\t\u{1}", "/usr/bin/zsh"] {
            assert_eq!(toml_value(&toml_string(value)).as_deref(), Some(value));
        }
        assert_eq!(toml_value(" 'C:\\x' # note").as_deref(), Some("C:\\x"));
        assert_eq!(
            toml_value("\"\\u4E2D\\U00006587\"").as_deref(),
            Some("中文")
        );
        for raw in ["\"open", "\"x\" trailing", "true", "\"\\q\"", "\"\\u12\""] {
            assert_eq!(toml_value(raw), None, "{raw}");
        }
    }
    #[test]
    fn existing_configuration_is_never_replaced() {
        let temp = Temp::new();
        let file = temp.0.join("profile 中文/.zshrc");
        create_once(&file, "first\n").unwrap();
        fs::write(&file, "user edits\n").unwrap();
        create_once(&file, "upgrade\n").unwrap();
        assert_eq!(fs::read_to_string(&file).unwrap(), "user edits\n");
        assert_eq!(fs::read_dir(file.parent().unwrap()).unwrap().count(), 1);
    }
    #[test]
    fn directory_in_place_of_configuration_is_rejected() {
        let temp = Temp::new();
        assert!(create_once(&temp.0, "must not write").is_err());
    }
    #[cfg(unix)]
    #[test]
    fn configuration_symlink_is_rejected() {
        let temp = Temp::new();
        let dest = temp.0.join("outside");
        fs::write(&dest, "original").unwrap();
        let link = temp.0.join(".zshrc");
        std::os::unix::fs::symlink(&dest, &link).unwrap();
        assert!(create_once(&link, "replacement").is_err());
        assert_eq!(fs::read_to_string(&dest).unwrap(), "original");
    }
    #[test]
    fn relative_profile_paths_are_rejected() {
        assert!(absolute(OsString::from("relative/path"), "HOME").is_err());
        assert!(absolute(env::temp_dir().into_os_string(), "HOME").is_ok());
    }
    #[test]
    fn profile_cannot_alias_home_or_resources() {
        let temp = Temp::new();
        let mut layout = Layout {
            root: temp.0.join("install"),
            resources: temp.0.join("resources"),
            profile: temp.0.join("home"),
            home: temp.0.join("home"),
            shell: PathBuf::from("/usr/bin/zsh"),
        };
        assert!(initialize(&layout, true).is_err());
        assert!(!layout.home.exists());
        layout.profile = layout.resources.join("profile");
        assert!(initialize(&layout, true).is_err());
        assert!(!layout.resources.exists());
    }
    #[cfg(unix)]
    #[test]
    fn linked_ancestor_cannot_redirect_new_profile_into_resources() {
        let temp = Temp::new();
        let resources = temp.0.join("resources");
        fs::create_dir(&resources).unwrap();
        let alias = temp.0.join("xdg-config");
        std::os::unix::fs::symlink(&resources, &alias).unwrap();
        let layout = Layout {
            root: temp.0.join("install"),
            resources: resources.clone(),
            profile: alias.join("ohmyzsh-gx/profile"),
            home: temp.0.join("home"),
            shell: PathBuf::from("/usr/bin/zsh"),
        };
        assert!(initialize(&layout, true).is_err());
        assert_eq!(fs::read_dir(resources).unwrap().count(), 0);
    }
    #[cfg(unix)]
    #[test]
    fn linked_herdr_directory_cannot_redirect_initialization() {
        let temp = Temp::new();
        let layout = Layout {
            root: temp.0.join("install"),
            resources: temp.0.join("resources"),
            profile: temp.0.join("profile"),
            home: temp.0.join("home"),
            shell: PathBuf::from("/usr/bin/zsh"),
        };
        fs::create_dir(&layout.profile).unwrap();
        fs::create_dir(&layout.home).unwrap();
        std::os::unix::fs::symlink(&layout.home, layout.profile.join("herdr")).unwrap();
        assert!(initialize(&layout, true).is_err());
        assert_eq!(fs::read_dir(&layout.home).unwrap().count(), 0);
        assert!(!layout.profile.join(".zshrc").exists());
    }
    #[test]
    fn initialize_is_idempotent_and_keeps_separate_profile() {
        let temp = Temp::new();
        let layout = Layout {
            root: temp.0.join("install"),
            resources: temp.0.join("resources"),
            profile: temp.0.join("profile 中文"),
            home: temp.0.join("untouched-home"),
            shell: PathBuf::from("/usr/bin/zsh"),
        };
        let theme = layout.resources.join("gx/omz-custom/themes/powerlevel10k");
        fs::create_dir_all(&theme).unwrap();
        fs::write(theme.join("powerlevel10k.zsh-theme"), "theme source").unwrap();
        fs::write(layout.resources.join("p10k-runtime-id"), "a".repeat(64)).unwrap();
        initialize(&layout, true).unwrap();
        let first = p10k_runtime(&layout).unwrap();
        fs::write(first.join("powerlevel10k.zsh-theme.zwc"), "compiled cache").unwrap();
        initialize(&layout, true).unwrap();
        assert!(!theme.join("powerlevel10k.zsh-theme.zwc").exists());
        fs::write(layout.resources.join("p10k-runtime-id"), "b".repeat(64)).unwrap();
        initialize(&layout, true).unwrap();
        assert_ne!(first, p10k_runtime(&layout).unwrap());
        assert_eq!(
            fs::read_to_string(first.join("powerlevel10k.zsh-theme.zwc")).unwrap(),
            "compiled cache"
        );
        fs::write(layout.resources.join("p10k-runtime-id"), "a".repeat(64)).unwrap();
        initialize(&layout, true).unwrap();
        assert_eq!(p10k_runtime(&layout).unwrap(), first);
        let config = layout.profile.join("herdr/config.toml");
        assert_eq!(
            fs::read_to_string(&config).unwrap(),
            new_herdr_config("/usr/bin/zsh")
        );
        fs::write(&config, "user config").unwrap();
        initialize(&layout, true).unwrap();
        assert_eq!(fs::read_to_string(&config).unwrap(), "user config");
        assert!(!layout.home.exists());
    }
    #[test]
    fn paths_are_converted_in_one_cygpath_call_on_stdin() {
        let paths = args(&[
            "C:\\GX Shell\\share",
            "D:\\项目\\profile",
            "\\\\server\\my share\\a b",
            "C:\\a{b,c}",
            "C:\\Users\\O'Brien",
        ]);
        let mut inputs = Vec::new();
        let mut cygpath = |input: CygpathInput<'_>| -> io::Result<Option<Vec<u8>>> {
            let CygpathInput::Lines(lines) = input else {
                panic!("paths must be sent as lines");
            };
            inputs.push(lines.to_owned());
            Ok(Some(
                lines
                    .lines()
                    .map(|path| fake_posix(OsStr::new(path)) + "\n")
                    .collect::<String>()
                    .into_bytes(),
            ))
        };
        let converted: Vec<_> = posix_paths(&mut cygpath, &paths)
            .into_iter()
            .map(Result::unwrap)
            .collect();
        assert_eq!(
            inputs,
            ["C:\\GX Shell\\share\nD:\\项目\\profile\n\\\\server\\my share\\a b\nC:\\a{b,c}\nC:\\Users\\O'Brien\n"]
        );
        assert_eq!(
            converted,
            args(&[
                "/c/GX Shell/share",
                "/d/项目/profile",
                "//server/my share/a b",
                "/c/a{b,c}",
                "/c/Users/O'Brien",
            ])
        );
    }
    #[test]
    fn unusable_batch_output_falls_back_to_single_paths() {
        let paths = args(&["C:\\a", "C:\\d", "C:\\fails"]);
        for batch in [None, Some("/c/a\n/c/d\n")] {
            let mut calls = Vec::new();
            let mut cygpath = |input: CygpathInput<'_>| -> io::Result<Option<Vec<u8>>> {
                if let CygpathInput::Lines(_) = input {
                    calls.push("lines".to_owned());
                    return Ok(batch.map(|output| output.as_bytes().to_vec()));
                }
                let path = input_paths(input).remove(0);
                calls.push(path.to_str().unwrap().to_owned());
                Ok((path != "C:\\fails").then(|| (fake_posix(&path) + "\n").into_bytes()))
            };
            let converted = posix_paths(&mut cygpath, &paths);
            assert_eq!(calls, ["lines", "C:\\a", "C:\\d", "C:\\fails"]);
            assert_eq!(converted[0].as_ref().unwrap(), &OsString::from("/c/a"));
            assert_eq!(converted[1].as_ref().unwrap(), &OsString::from("/c/d"));
            assert!(converted[2].is_err());
        }
        assert_eq!(cygpath_lines(b"/a\r\n/b\r\n", 2), Some(args(&["/a", "/b"])));
        assert_eq!(cygpath_lines(b"/a\n\n/b\n", 2), None);
    }
    #[test]
    fn paths_that_cannot_be_sent_as_lines_are_converted_one_by_one() {
        let paths = args(&["C:\\a", "C:\\line\nbreak"]);
        let mut calls = Vec::new();
        let converted = posix_paths(&mut fake_cygpath(&mut calls), &paths);
        assert_eq!(calls, [1, 1]);
        assert_eq!(converted[0].as_ref().unwrap(), &OsString::from("/c/a"));
        assert!(converted[1].is_err());
    }
    #[test]
    fn posix_comparisons_accept_both_drive_prefixes() {
        assert!(same_posix(
            OsStr::new("/cygdrive/c/GX/"),
            OsStr::new("/c/GX")
        ));
        assert!(posix_inside(
            OsStr::new("/c/p/.cache"),
            OsStr::new("/cygdrive/c/p")
        ));
        assert!(!posix_inside(OsStr::new("/c/p-other"), OsStr::new("/c/p")));
        assert!(!same_posix(OsStr::new("/cygdrivex/c"), OsStr::new("/c")));
        assert!(same_posix(
            OsStr::new("/usr/lib/ohmyzsh-gx/../../share/ohmyzsh-gx/./gx"),
            OsStr::new("/usr/share/ohmyzsh-gx/gx")
        ));
        assert!(!same_posix(
            OsStr::new("//server/x"),
            OsStr::new("/server/x")
        ));
        assert!(!same_posix(OsStr::new("relative"), OsStr::new("relative")));
        assert_eq!(posix_join(OsStr::new("/"), "share/zsh"), "/share/zsh");
        assert_eq!(
            posix_join(OsStr::new("/c/p"), ".cache/tmp"),
            "/c/p/.cache/tmp"
        );
    }
    #[cfg(windows)]
    #[test]
    fn windows_paths_use_native_separators() {
        assert_eq!(
            subpath(Path::new(r"C:\GX Shell"), "runtime/msys64/usr/bin/zsh.exe").to_str(),
            Some(r"C:\GX Shell\runtime\msys64\usr\bin\zsh.exe")
        );
        assert_eq!(
            native(PathBuf::from("C:/Users/中文/AppData/Local/")).to_str(),
            Some(r"C:\Users\中文\AppData\Local")
        );
        assert_eq!(
            native(PathBuf::from(r"\\server\share/x")).to_str(),
            Some(r"\\server\share\x")
        );
        let temp = Temp::new();
        let layout = package_layout(&temp);
        for path in [
            layout.shell.clone(),
            layout.herdr_config(),
            layout.real_herdr(),
        ] {
            assert!(!path.to_str().unwrap().contains('/'), "{}", path.display());
        }
    }
    #[test]
    fn nested_gx_environment_is_rebuilt_from_the_layout() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let custom = subpath(&layout.resources, "gx/omz-custom");
        let mut parent = HashMap::from([
            ("GX_PACKAGE_ROOT", msys_form(&layout.resources)),
            ("ZSH_CUSTOM", msys_form(&custom)),
            (
                "POWERLEVEL9K_INSTALLATION_DIR",
                msys_form(&subpath(&custom, "themes/powerlevel10k")),
            ),
            (
                "XDG_CACHE_HOME",
                msys_form(&subpath(&layout.profile, ".cache")),
            ),
            (
                "FPATH",
                OsString::from(if cfg!(windows) {
                    "C:\\junk;D:\\more"
                } else {
                    "/junk:/more"
                }),
            ),
            ("_ZO_DATA_DIR", OsString::from("kept")),
        ]);
        for name in GX_DERIVED_VARIABLES {
            parent.insert(name, msys_form(&layout.profile));
        }
        let mut calls = Vec::new();
        let command = configured_command(
            &layout,
            false,
            &[],
            &|name| parent.get(name).cloned(),
            &mut fake_cygpath(&mut calls),
        )
        .unwrap();
        let envs = envs(&command);
        for name in [
            "ZSH_CUSTOM",
            "POWERLEVEL9K_INSTALLATION_DIR",
            "XDG_CACHE_HOME",
        ]
        .into_iter()
        .chain(GX_DERIVED_VARIABLES)
        {
            assert_eq!(envs.get(name), Some(&None), "{name}");
        }
        let profile = posix(&layout.profile);
        let data = posix(&layout.zsh_data());
        for (name, value) in [
            ("FPATH", format!("{data}/functions:{data}/site-functions")),
            ("GX_PACKAGE_ROOT", posix(&layout.resources)),
            ("GX_PROFILE_DIR", profile.clone()),
            ("ZDOTDIR", profile.clone()),
            ("HOME", posix(&layout.home)),
            ("TMPDIR", format!("{profile}/.cache/tmp")),
            ("TMPPREFIX", format!("{profile}/.cache/tmp/zsh")),
            (
                "GX_P10K_RUNTIME_DIR",
                format!("{profile}/.cache/themes/{}/powerlevel10k", "a".repeat(64)),
            ),
        ] {
            assert_eq!(envs[name].as_deref(), Some(value.as_str()), "{name}");
        }
        for name in ["TEMP", "TMP", "_ZO_DATA_DIR"] {
            assert!(!envs.contains_key(name), "{name}");
        }
        assert_eq!(calls.len(), usize::from(cfg!(windows)));
    }
    #[test]
    fn custom_values_from_a_gx_parent_become_posix_paths() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let custom = temp.0.join("my custom");
        let parent = HashMap::from([
            ("GX_PROFILE_DIR", msys_form(&layout.profile)),
            ("ZSH_CUSTOM", msys_form(&custom)),
            ("XDG_CACHE_HOME", msys_form(&temp.0.join("cache"))),
        ]);
        let command = configured_command(
            &layout,
            true,
            &args(&["agent", "list"]),
            &|name| parent.get(name).cloned(),
            &mut fake_cygpath(&mut Vec::new()),
        )
        .unwrap();
        let envs = envs(&command);
        assert_eq!(envs["ZSH_CUSTOM"].as_deref(), Some(posix(&custom).as_str()));
        assert_eq!(envs["ZSH"], None);
        assert_eq!(envs["HOME"].as_deref(), layout.home.to_str());
        assert!(!envs.contains_key("XDG_CACHE_HOME"));
        assert!(!envs.contains_key("POWERLEVEL9K_INSTALLATION_DIR"));
    }
    #[test]
    fn inherited_fpath_keeps_only_absolute_posix_entries() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let data = posix(&layout.zsh_data());
        let lists: &[(&str, &str)] = if cfg!(windows) {
            &[
                ("C:\\a;relative;D:\\b c", ":/c/a:/d/b c"),
                ("/usr/share/zsh:rel:/c/x", ":/usr/share/zsh:/c/x"),
            ]
        } else {
            &[("/a:relative:/b c", ":/a:/b c")]
        };
        for (inherited, kept) in lists {
            let parent = HashMap::from([
                ("FPATH", OsString::from(inherited)),
                ("ZSH", OsString::from("/elsewhere")),
            ]);
            let mut calls = Vec::new();
            let command = configured_command(
                &layout,
                false,
                &[],
                &|name| parent.get(name).cloned(),
                &mut fake_cygpath(&mut calls),
            )
            .unwrap();
            let envs = envs(&command);
            assert_eq!(
                envs["FPATH"].as_deref(),
                Some(format!("{data}/functions:{data}/site-functions{kept}").as_str())
            );
            assert!(!envs.contains_key("ZSH"));
            assert_eq!(calls.len(), usize::from(cfg!(windows)));
        }
    }
    #[test]
    fn informational_herdr_commands_skip_path_conversion() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        for flag in [
            "--version",
            "-V",
            "--help",
            "-h",
            "--default-config",
            "--skill",
        ] {
            let command = configured_command(
                &layout,
                true,
                &args(&[flag]),
                &|_| None,
                &mut |_: CygpathInput<'_>| -> io::Result<Option<Vec<u8>>> {
                    panic!("{flag} must not convert paths")
                },
            )
            .unwrap();
            let envs = envs(&command);
            for name in ["GX_PACKAGE_ROOT", "FPATH", "ZDOTDIR", "TMPDIR"] {
                assert!(!envs.contains_key(name), "{flag} {name}");
            }
            assert_eq!(envs["HOME"].as_deref(), layout.home.to_str());
            assert_eq!(envs["HERDR_SESSION"].as_deref(), Some("ohmyzsh-gx"));
            assert!(envs.contains_key("HERDR_CONFIG_PATH"));
        }
        let mut calls = Vec::new();
        configured_command(
            &layout,
            true,
            &args(&["--version", "extra"]),
            &|_| None,
            &mut fake_cygpath(&mut calls),
        )
        .unwrap();
        assert_eq!(calls.len(), usize::from(cfg!(windows)));
    }
    #[cfg(windows)]
    #[test]
    fn launcher_prepares_native_zoxide_data_directory() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        initialize(&layout, true).unwrap();
        for relative in [
            ".cache/oh-my-zsh/completions",
            ".cache/tmp",
            ".local/share/zoxide",
        ] {
            assert!(subpath(&layout.profile, relative).is_dir(), "{relative}");
        }
        let zoxide = subpath(&layout.profile, ".local/share/zoxide");
        assert!(!zoxide.to_str().unwrap().contains('/'));
        for inherited in [None, Some(OsString::new())] {
            let command = configured_command(
                &layout,
                true,
                &[],
                &|name| inherited.clone().filter(|_| name == "_ZO_DATA_DIR"),
                &mut fake_cygpath(&mut Vec::new()),
            )
            .unwrap();
            assert_eq!(envs(&command)["_ZO_DATA_DIR"].as_deref(), zoxide.to_str());
        }
        let command = configured_command(
            &layout,
            false,
            &[],
            &|name| (name == "_ZO_DATA_DIR").then(|| OsString::from(r"D:\zoxide")),
            &mut fake_cygpath(&mut Vec::new()),
        )
        .unwrap();
        assert!(!envs(&command).contains_key("_ZO_DATA_DIR"));
    }
    #[test]
    fn released_herdr_configs_are_migrated_once() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let released = legacy_config(&released_shell(&layout.root));
        let migrated = new_herdr_config(shell_text(&layout).unwrap());
        let body = migrated.strip_prefix(HERDR_MARKER).unwrap();
        for (content, expected) in [
            (released.clone(), migrated.clone()),
            (
                format!("onboarding = false\n{released}"),
                format!("{HERDR_MARKER}\nonboarding = false{body}"),
            ),
            (
                released.replace('\n', "\r\n"),
                migrated.replace('\n', "\r\n"),
            ),
            (
                format!("{released}\n[keys]\nprefix = \"ctrl+a\"\n"),
                format!("{migrated}\n[keys]\nprefix = \"ctrl+a\"\n"),
            ),
        ] {
            assert_eq!(
                change(&layout, &content, None),
                HerdrConfigChange::Write(expected.clone())
            );
            assert_eq!(change(&layout, &expected, None), HerdrConfigChange::Keep);
            for requested in [None, Some(shell_text(&layout).unwrap())] {
                assert_eq!(
                    herdr_config_change(&layout, &content, requested, true).unwrap(),
                    HerdrConfigChange::Custom
                );
            }
        }
    }
    #[cfg(windows)]
    #[test]
    fn herdr_configs_from_older_gx_roots_are_recognized() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let migrated = new_herdr_config(shell_text(&layout).unwrap());
        for root in [
            r"C:\Users\x\AppData\Local\Programs\OhMyZshGX",
            r"D:\gone\GXShell",
            r"\\server\apps\GX Shell",
        ] {
            let released = legacy_config(&released_shell(Path::new(root)));
            assert_eq!(
                change(&layout, &released, None),
                HerdrConfigChange::Write(migrated.clone()),
                "{root}"
            );
        }
        let normalized = legacy_config(r"C:\GX\runtime\msys64\usr\bin\zsh.exe");
        assert_eq!(
            change(&layout, &normalized, None),
            HerdrConfigChange::Custom
        );
    }
    #[test]
    fn customized_herdr_configs_are_left_alone() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let released = legacy_config(&released_shell(&layout.root));
        let shell = shell_text(&layout).unwrap();
        for content in [
            String::new(),
            "user config".to_owned(),
            "[terminal]\ndefault_shell = \"/bin/fish\"\nshell_mode = \"login\"\n".to_owned(),
            released.replace("\"login\"", "\"non-login\""),
            released.replace("shell_mode = \"login\"\n", ""),
            format!("terminal.default_shell = \"x\"\n{released}"),
            format!("{HERDR_MARKER}\n{released}[terminal]\n"),
            format!("{HERDR_MARKER}\n[terminal]\ndefault_shell = \"a\"\ndefault_shell = \"b\"\n"),
            format!("{HERDR_MARKER}\n[\"terminal\"]\ndefault_shell = \"a\"\n"),
            format!("{HERDR_MARKER}\n[ 'terminal' ]\nshell_mode = \"login\"\n"),
            format!("{HERDR_MARKER}\n[terminal.extra]\nx = 1\n"),
            format!("{HERDR_MARKER}\n[[terminal]]\ndefault_shell = \"a\"\n"),
            format!("{HERDR_MARKER}\n[terminal\n"),
        ] {
            for requested in [None, Some(shell)] {
                assert_eq!(
                    change(&layout, &content, requested),
                    HerdrConfigChange::Custom,
                    "{content}"
                );
            }
        }
    }
    #[test]
    fn managed_herdr_config_follows_the_chosen_shell() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let zsh = shell_text(&layout).unwrap();
        let created = new_herdr_config(zsh);
        let chosen = temp.0.join("pwsh 中文.exe");
        fs::write(&chosen, "").unwrap();
        let chosen = chosen.to_str().unwrap();
        let HerdrConfigChange::Write(updated) = change(&layout, &created, Some(chosen)) else {
            panic!("the chosen shell was not written");
        };
        assert_eq!(
            updated,
            created.replace(&toml_string(zsh), &toml_string(chosen))
        );
        for requested in [Some(chosen), None] {
            assert_eq!(
                change(&layout, &updated, requested),
                HerdrConfigChange::Keep
            );
        }
        fs::remove_file(chosen).unwrap();
        assert_eq!(
            change(&layout, &updated, None),
            HerdrConfigChange::Write(created)
        );
        let partial =
            format!("{HERDR_MARKER}\n[keys]\nprefix = \"ctrl+a\"\n[terminal] # shells\n# note\n");
        assert_eq!(
            change(&layout, &partial, None),
            HerdrConfigChange::Write(format!(
                "{HERDR_MARKER}\n[keys]\nprefix = \"ctrl+a\"\n[terminal] # shells\ndefault_shell = {}\nshell_mode = \"login\"\n# note\n",
                toml_string(zsh)
            ))
        );
        let missing = format!("{HERDR_MARKER}\nonboarding = false\n");
        assert_eq!(
            change(&layout, &missing, None),
            HerdrConfigChange::Write(format!(
                "{HERDR_MARKER}\nonboarding = false\n\n[terminal]\ndefault_shell = {}\nshell_mode = \"login\"\n",
                toml_string(zsh)
            ))
        );
        let commented = format!(
            "{HERDR_MARKER}\n[terminal]\n  default_shell = '{}'  # picked in WezTerm\nshell_mode=\"non-login\" # mine\n",
            temp.0.join("gone.exe").display()
        );
        assert_eq!(
            change(&layout, &commented, None),
            HerdrConfigChange::Write(format!(
                "{HERDR_MARKER}\n[terminal]\n  default_shell = {}  # picked in WezTerm\nshell_mode = \"login\" # mine\n",
                toml_string(zsh)
            ))
        );
    }
    #[test]
    fn initialize_adopts_a_released_herdr_config_only_once() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let config = layout.herdr_config();
        fs::create_dir_all(config.parent().unwrap()).unwrap();
        let released = format!(
            "onboarding = false\n{}",
            legacy_config(&released_shell(&layout.root))
        );
        fs::write(&config, &released).unwrap();
        initialize(&layout, false).unwrap();
        assert_eq!(fs::read_to_string(&config).unwrap(), released);
        assert!(!layout.herdr_adopted().exists());
        initialize(&layout, true).unwrap();
        let migrated = fs::read_to_string(&config).unwrap();
        assert!(migrated.starts_with(&format!(
            "{HERDR_MARKER}\nonboarding = false\n[terminal]\ndefault_shell = {}\n",
            toml_string(shell_text(&layout).unwrap())
        )));
        initialize(&layout, true).unwrap();
        assert_eq!(fs::read_to_string(&config).unwrap(), migrated);
        let mut names: Vec<_> = fs::read_dir(config.parent().unwrap())
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();
        names.sort();
        assert_eq!(names, [".gx-config-adopted", "config.toml"]);
        for owned_by_user in [
            released.clone(),
            migrated.replace(&format!("{HERDR_MARKER}\n"), ""),
        ] {
            fs::write(&config, &owned_by_user).unwrap();
            initialize(&layout, true).unwrap();
            assert_eq!(fs::read_to_string(&config).unwrap(), owned_by_user);
        }
    }
    #[test]
    fn non_regular_herdr_config_belongs_to_the_user() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let config = layout.herdr_config();
        fs::create_dir_all(&config).unwrap();
        initialize(&layout, true).unwrap();
        let chosen = temp.0.join("pwsh.exe");
        fs::write(&chosen, "").unwrap();
        assert!(!store_default_shell(&layout, chosen.as_os_str(), &|_| None).unwrap());
        assert!(config.is_dir());
        assert!(!layout.herdr_adopted().exists());
    }
    #[cfg(unix)]
    #[test]
    fn linked_herdr_config_belongs_to_the_user() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let outside = temp.0.join("dotfiles.toml");
        let released = legacy_config(&released_shell(&layout.root));
        fs::write(&outside, &released).unwrap();
        fs::create_dir_all(layout.herdr_config().parent().unwrap()).unwrap();
        std::os::unix::fs::symlink(&outside, layout.herdr_config()).unwrap();
        initialize(&layout, true).unwrap();
        let chosen = temp.0.join("fish");
        fs::write(&chosen, "").unwrap();
        assert!(!store_default_shell(&layout, chosen.as_os_str(), &|_| None).unwrap());
        assert_eq!(fs::read_to_string(&outside).unwrap(), released);
    }
    #[test]
    fn concurrent_herdr_config_changes_are_not_overwritten() {
        let temp = Temp::new();
        let path = temp.0.join("config.toml");
        fs::write(&path, "herdr wrote this\n").unwrap();
        assert!(!replace_unchanged(&path, "what GX read\n", "GX update\n").unwrap());
        assert_eq!(fs::read_to_string(&path).unwrap(), "herdr wrote this\n");
        assert!(replace_unchanged(&path, "herdr wrote this\n", "GX update\n").unwrap());
        assert_eq!(fs::read_to_string(&path).unwrap(), "GX update\n");
        assert_eq!(fs::read_dir(&temp.0).unwrap().count(), 1);
    }
    #[test]
    fn profile_directory_errors_name_the_offending_path() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let tmp = subpath(&layout.profile, ".cache/tmp");
        fs::create_dir_all(tmp.parent().unwrap()).unwrap();
        fs::write(&tmp, "not a directory").unwrap();
        let error = initialize(&layout, true).unwrap_err().to_string();
        assert!(error.contains(&tmp.display().to_string()), "{error}");
    }
    #[test]
    fn managed_herdr_config_path_is_not_custom() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let managed = layout.herdr_config();
        let mut forms = vec![managed.clone().into_os_string()];
        if cfg!(windows) {
            forms.push(managed.to_str().unwrap().replace('\\', "/").into());
            forms.push(managed.to_str().unwrap().to_uppercase().into());
        }
        for exists in [false, true] {
            if exists {
                fs::create_dir_all(managed.parent().unwrap()).unwrap();
                fs::write(&managed, "").unwrap();
            }
            for form in &forms {
                let parent = |name: &str| (name == "HERDR_CONFIG_PATH").then(|| form.clone());
                assert_eq!(custom_herdr_config(&layout, &parent), None, "{form:?}");
            }
        }
        let other = temp.0.join("other.toml").into_os_string();
        let parent = |name: &str| (name == "HERDR_CONFIG_PATH").then(|| other.clone());
        assert_eq!(custom_herdr_config(&layout, &parent), Some(other.clone()));
        let empty = |name: &str| (name == "HERDR_CONFIG_PATH").then(OsString::new);
        assert_eq!(custom_herdr_config(&layout, &empty), Some(OsString::new()));
        assert_eq!(custom_herdr_config(&layout, &|_| None), None);
    }
    #[test]
    fn default_shell_is_stored_only_in_gx_managed_configs() {
        let temp = Temp::new();
        let layout = package_layout(&temp);
        let chosen = temp.0.join("pwsh.exe");
        fs::write(&chosen, "").unwrap();
        let config = layout.herdr_config();
        let custom_path =
            |name: &str| (name == "HERDR_CONFIG_PATH").then(|| OsString::from("elsewhere.toml"));
        assert!(!store_default_shell(&layout, chosen.as_os_str(), &custom_path).unwrap());
        assert!(!config.exists());
        let managed_path =
            |name: &str| (name == "HERDR_CONFIG_PATH").then(|| config.clone().into_os_string());
        assert!(store_default_shell(&layout, chosen.as_os_str(), &managed_path).unwrap());
        assert_eq!(
            fs::read_to_string(&config).unwrap(),
            new_herdr_config(chosen.to_str().unwrap())
        );
        assert!(layout.herdr_adopted().is_file());
        let custom = "[terminal]\ndefault_shell = \"/bin/fish\"\n";
        fs::write(&config, custom).unwrap();
        assert!(!store_default_shell(&layout, chosen.as_os_str(), &|_| None).unwrap());
        for shell in [
            OsStr::new("pwsh.exe"),
            temp.0.join("missing.exe").as_os_str(),
        ] {
            assert!(store_default_shell(&layout, shell, &|_| None).is_err());
        }
        assert_eq!(fs::read_to_string(&config).unwrap(), custom);
    }
    #[test]
    fn running_server_is_read_from_status_json() {
        assert!(server_running(
            br#"{"status":"running","running":true,"version":"0.7.0"}"#
        ));
        assert!(server_running(b"{\n  \"running\": true\n}"));
        assert!(!server_running(
            br#"{"status":"not_running","running":false}"#
        ));
        assert!(!server_running(b""));
    }
    #[test]
    fn reload_reports_are_parsed() {
        assert_eq!(
            reload_report(
                r#"{"id":"cli:server:reload-config","result":{"type":"config_reload","status":"applied","diagnostics":[]}}"#
            ),
            Some(("applied".to_owned(), Vec::new()))
        );
        assert_eq!(
            reload_report(
                r#"{"id":"x","result":{"type":"config_reload","status":"failed","diagnostics":["config parse error: expected \"=\" at \\n\u4e2d","second"]}}"#
            ),
            Some((
                "failed".to_owned(),
                vec![
                    "config parse error: expected \"=\" at \\n中".to_owned(),
                    "second".to_owned()
                ]
            ))
        );
        assert_eq!(
            reload_report(
                "{\n \"status\" : \"partial\" ,\n \"diagnostics\" : [ \"a\" , \"b\" ]\n}"
            ),
            Some(("partial".to_owned(), vec!["a".to_owned(), "b".to_owned()]))
        );
        for broken in [
            "",
            "{}",
            r#"{"status":"failed"}"#,
            r#"{"status":"failed","diagnostics":["open"#,
        ] {
            assert_eq!(reload_report(broken), None, "{broken}");
        }
    }
}
