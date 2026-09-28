use std::env;
use std::ffi::{OsStr, OsString};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

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
            root.join("share/ohmyzsh-gx"),
            required_path("LOCALAPPDATA")?.join("ohmyzsh-gx/profile"),
            required_path("USERPROFILE")?,
            root.join("runtime/msys64/usr/bin/zsh.exe"),
        );
        #[cfg(unix)]
        let (resources, profile, home, shell) = {
            let home = required_path("HOME")?;
            let base = match env::var_os("XDG_CONFIG_HOME") {
                Some(path) => absolute(path, "XDG_CONFIG_HOME")?,
                None => home.join(".config"),
            };
            (
                root.join("../../share/ohmyzsh-gx"),
                base.join("ohmyzsh-gx/profile"),
                home,
                root.join("libexec/zsh/zsh"),
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
        self.root
            .join(format!("lib/herdr/herdr{}", env::consts::EXE_SUFFIX))
    }

    fn zsh_data(&self) -> PathBuf {
        #[cfg(windows)]
        {
            self.root.join("runtime/msys64/share/zsh")
        }
        #[cfg(unix)]
        {
            self.root.join("share/zsh")
        }
    }

    fn validate(&self, herdr: bool) -> io::Result<()> {
        for path in [
            self.resources.join("oh-my-zsh.sh"),
            self.resources.join("gx/config/zshrc"),
            self.resources.join("gx/config/package.zsh"),
            self.zsh_data().join("functions/compinit"),
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

fn create_once(path: &Path, content: &str) -> io::Result<()> {
    if regular_or_missing(path)? {
        return Ok(());
    }
    let parent = path
        .parent()
        .ok_or_else(|| invalid("Missing configuration parent"))?;
    fs::create_dir_all(parent)?;
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(invalid)?
        .as_nanos();
    let temp = parent.join(format!(".gx-create-{}-{stamp}", std::process::id()));
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

fn p10k_runtime(layout: &Layout) -> io::Result<PathBuf> {
    Ok(layout
        .profile
        .join(".cache/themes")
        .join(p10k_identity(layout)?)
        .join("powerlevel10k"))
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

fn prepare_p10k(layout: &Layout) -> io::Result<()> {
    let identity = p10k_identity(layout)?;
    let parent = layout.profile.join(".cache/themes");
    let profile = layout.profile.canonicalize()?;
    for directory in [
        layout.profile.join(".cache"),
        parent.clone(),
        layout.profile.join(".cache/tmp"),
    ] {
        match fs::symlink_metadata(&directory) {
            Ok(metadata) if metadata.is_dir() && !is_link(&metadata) => {}
            Ok(_) => return Err(invalid("P10k cache directories cannot be links or files")),
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(error),
        }
        if !resolve_destination(&directory)?.starts_with(&profile) {
            return Err(invalid("P10k cache escapes the profile"));
        }
        fs::create_dir_all(directory)?;
    }
    let destination = parent.join(&identity);
    let source = layout.resources.join("gx/omz-custom/themes/powerlevel10k");
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
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(invalid)?
        .as_nanos();
    let staging = parent.join(format!(".gx-stage-{}-{stamp}", std::process::id()));
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

fn initialize(layout: &Layout, own_herdr_config: bool) -> io::Result<()> {
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
    prepare_p10k(layout)?;
    create_once(&layout.profile.join(".zshenv"), "skip_global_compinit=1\n")?;
    create_once(
        &layout.profile.join(".zshrc"),
        "source \"$GX_PACKAGE_ROOT/gx/config/zshrc\"\n",
    )?;
    if own_herdr_config {
        let shell = layout
            .shell
            .to_str()
            .ok_or_else(|| invalid("Zsh path is not UTF-8"))?;
        let content = format!(
            "[terminal]\ndefault_shell = {}\nshell_mode = \"login\"\n\n[update]\nversion_check = false\nmanifest_check = false\n",
            toml_string(shell),
        );
        create_once(&layout.profile.join("herdr/config.toml"), &content)?;
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

#[cfg(windows)]
fn posix_path(layout: &Layout, path: &Path) -> io::Result<OsString> {
    let result = Command::new(layout.root.join("runtime/msys64/usr/bin/cygpath.exe"))
        .arg("-u")
        .arg("--")
        .arg(path)
        .output()?;
    if !result.status.success() {
        return Err(invalid(format!(
            "Cannot convert MSYS2 path: {}",
            path.display()
        )));
    }
    let output = String::from_utf8(result.stdout).map_err(invalid)?;
    let value = output.trim_end_matches(['\r', '\n']);
    if value.is_empty() || value.contains(['\r', '\n']) {
        return Err(invalid("cygpath returned an invalid path"));
    }
    Ok(OsString::from(value))
}

#[cfg(unix)]
fn posix_path(_layout: &Layout, path: &Path) -> io::Result<OsString> {
    Ok(path.as_os_str().to_owned())
}

fn configured_command(layout: &Layout, herdr: bool, args: &[OsString]) -> io::Result<Command> {
    let mut command = Command::new(if herdr {
        layout.real_herdr()
    } else {
        layout.shell.clone()
    });
    if !herdr {
        command.arg("-il");
    }
    command.args(args);
    command.env("GX_PACKAGE_ROOT", posix_path(layout, &layout.resources)?);
    command.env(
        "GX_PACKAGE_BIN",
        posix_path(layout, &layout.root.join("bin"))?,
    );
    command.env("GX_PROFILE_DIR", posix_path(layout, &layout.profile)?);
    command.env(
        "GX_P10K_RUNTIME_DIR",
        posix_path(layout, &p10k_runtime(layout)?)?,
    );
    command.env("ZDOTDIR", posix_path(layout, &layout.profile)?);
    let temporary = layout.profile.join(".cache/tmp");
    command.env("TMPDIR", posix_path(layout, &temporary)?);
    command.env("TMPPREFIX", posix_path(layout, &temporary.join("zsh"))?);
    #[cfg(windows)]
    {
        command.env("TEMP", &temporary);
        command.env("TMP", &temporary);
    }
    let mut fpath = posix_path(layout, &layout.zsh_data().join("functions"))?;
    fpath.push(":");
    fpath.push(posix_path(
        layout,
        &layout.zsh_data().join("site-functions"),
    )?);
    if let Some(previous) = env::var_os("FPATH").filter(|value| !value.is_empty()) {
        fpath.push(":");
        fpath.push(previous);
    }
    command.env("FPATH", fpath);
    command.env(
        "HOME",
        if herdr {
            layout.home.as_os_str().to_owned()
        } else {
            posix_path(layout, &layout.home)?
        },
    );
    let mut paths = vec![layout.root.join("bin")];
    #[cfg(windows)]
    {
        paths.push(layout.root.join("runtime/msys64/usr/bin"));
        paths.push(layout.root.join("runtime/msys64/ucrt64/bin"));
        command.env("MSYSTEM", "MSYS");
        command.env("MSYS2_PATH_TYPE", "inherit");
        command.env("CHERE_INVOKING", "1");
        command.env("LANG", "C.UTF-8");
    }
    if let Some(path) = env::var_os("PATH") {
        paths.extend(env::split_paths(&path));
    }
    command.env("PATH", env::join_paths(paths).map_err(invalid)?);
    if env::var_os("HERDR_CONFIG_PATH").is_none() {
        command.env(
            "HERDR_CONFIG_PATH",
            layout.profile.join("herdr/config.toml"),
        );
    }
    if env::var_os("HERDR_SESSION").is_none() && env::var_os("HERDR_SOCKET_PATH").is_none() {
        command.env("HERDR_SESSION", "ohmyzsh-gx");
    }
    command.env(
        "GITSTATUS_CACHE_DIR",
        posix_path(layout, &layout.root.join("lib/gitstatus"))?,
    );
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

fn launch(mut command: Command) -> io::Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        Err(command.exec())
    }
    #[cfg(windows)]
    {
        unsafe { SetConsoleCtrlHandler(Some(console_control), 1) };
        let status = command.status()?;
        std::process::exit(status.code().unwrap_or(1));
    }
}

fn run() -> io::Result<()> {
    let args: Vec<_> = env::args_os().skip(1).collect();
    let herdr = cfg!(gx_herdr);
    if herdr && blocked_update(&args) {
        return Err(invalid("herdr is managed by Oh My Zsh GX. Install a new GX EXE/DEB to update; upstream self-update and channel switching are disabled by this entry point."));
    }
    let layout = Layout::discover()?;
    layout.validate(herdr)?;
    let informational = herdr
        && args.len() == 1
        && [
            "--version",
            "-V",
            "--help",
            "-h",
            "--default-config",
            "--skill",
        ]
        .iter()
        .any(|value| args[0] == *value);
    if !informational {
        initialize(&layout, env::var_os("HERDR_CONFIG_PATH").is_none())?;
    }
    if args.as_slice() == [OsStr::new("--gx-initialize-only")] {
        return Ok(());
    }
    launch(configured_command(&layout, herdr, &args)?)
}

fn main() {
    if let Err(error) = run() {
        eprintln!("Oh My Zsh GX: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Temp(PathBuf);
    impl Temp {
        fn new() -> Self {
            let stamp = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let path = env::temp_dir().join(format!("gx-launcher-{}-{stamp}", std::process::id()));
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
        assert!(fs::read_to_string(&config)
            .unwrap()
            .contains("version_check = false"));
        fs::write(&config, "user config").unwrap();
        initialize(&layout, true).unwrap();
        assert_eq!(fs::read_to_string(&config).unwrap(), "user config");
        assert!(!layout.home.exists());
    }
}
