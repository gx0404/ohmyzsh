# 架构（从源码研读提炼；符号引用用 `路径::符号`）

Oh My Zsh 是纯 Zsh 框架：一个被用户 `.zshrc` source 的主入口 + 核心库 + 367 插件 +
143 主题 + 安装运维脚本。无后台进程、无持久化服务；全部"状态"是 shell 会话内变量
与 `$ZSH_CACHE_DIR` 下的缓存文件。

## 加载流程（oh-my-zsh.sh）

```
.zshrc（用户）
  └─ source $ZSH/oh-my-zsh.sh
       1. 守卫：非 zsh / emulation 非 zsh → 拒绝加载
       2. ZSH / ZSH_CUSTOM / ZSH_CACHE_DIR 解析（缓存不可写→XDG 回退）
       3. source tools/check_for_upgrade.sh     ← 更新检查先于一切
       4. is_plugin() 预注册插件到 fpath         ← 必须先于 compinit
       5. compinit（compfix 安全模式 -i / ZSH_DISABLE_COMPFIX 时 -u）
          + compdump 元数据（#omz revision / #omz fpath）失效即重建
          + zrecompile 编译 .zwc
       6. _omz_source：lib/*.zsh（全部、字典序）
       7. _omz_source：$plugins 数组逐个 plugins/<n>/<n>.plugin.zsh
       8. _omz_source：custom/*.zsh
       9. 主题：$ZSH_CUSTOM/$ZSH_THEME.zsh-theme > $ZSH_CUSTOM/themes/ > $ZSH/themes/
```

关键机制：

- **custom 覆盖**（`oh-my-zsh.sh::_omz_source`）：`$ZSH_CUSTOM/<path>` 优先于
  `$ZSH/<path>`。用户不改上游文件即可覆盖任何 lib/插件/主题。
- **插件判定**（`oh-my-zsh.sh::is_plugin`）：存在 `<name>.plugin.zsh` 或 `_<name>`
  补全即算插件，两种形态都预注册进 fpath。
- **别名回滚**：`zstyle ':omz:... aliases` 支持按插件禁用别名，`_omz_source`
  基于 grep 回查插件源实现，加载前自动卸载被禁别名。

## lib/ 核心库（22 个文件）

| 文件 | 职责 |
|---|---|
| lib/git.zsh | git prompt 引擎：`__git_prompt_git`（`GIT_OPTIONAL_LOCKS=0` 避免索引锁）、`_omz_git_prompt_info`、async 变体（`':omz:alpha:lib:git' async-prompt` 开关，zsh≥5.0.6 默认开） |
| lib/cli.zsh | `omz` CLI：plugin/theme/update/changelog/pr/version 子命令 + `_omz` 补全；`omz version` 从 git describe/分支派生 |
| lib/theme-and-appearance.zsh | `colors`、`prompt_subst`、`ZSH_THEME_GIT_PROMPT_*` 默认值、ls/diff 颜色 |
| lib/prompt_info_functions.zsh | `git_prompt_info` 等主题入口 + 未加载插件的 dummy 实现 |
| lib/compfix.zsh | 不安全补全目录检测（compinit 前置） |
| lib/termsupport.zsh | 窗口/标签标题 precmd-preexec 钩子 |
| lib/async_prompt.zsh | 异步 prompt 池（`_omz_register_handler`） |
| lib/functions.zsh | `env_default`、`omz_source` 等通用函数 |
| lib/history.zsh / completion.zsh / key-bindings.zsh / directories.zsh / clipboard.zsh / diagnostics.zsh / nvm.zsh / ... | 历史、补全样式、键绑定、cd 增强、剪贴板、诊断、惰性 nvm 等 |

依赖方向：后加载者可依赖先加载者（字典序），`lib/misc.zsh` 的 setopt 组与
`theme-and-appearance.zsh` 是后续文件的隐式前置。

## 插件与主题

- 标准插件 = `plugins/<n>/<n>.plugin.zsh` + `README.md`（+ 可选 `_<n>` 补全 /
  `completions/` 子目录 / `tests/*.zunit`）。93 个插件根目录有 `_<n>` 补全；
  docker、gem 用 completions/ 子目录。
- 补全缓存模式：`kubectl completion zsh > $ZSH_CACHE_DIR/completions/_kubectl` 后台
  执行（plugins/kubectl 先例）。
- 主题定义 prompt 变量/函数，git 段统一经 `git_prompt_info`；agnoster 类主题自带
  `build_prompt` 组装器。

## tools/ 运维面

install.sh（POSIX sh，`curl | sh` 执行面）、uninstall.sh（依 `.zshrc.pre-oh-my-zsh`
备份恢复）、upgrade.sh（-v default|minimal|silent）、check_for_upgrade.sh
（zstyle ':omz:update' mode 闭集 + epoch 节流，写 `$ZSH_CACHE_DIR/.zsh-update`）、
changelog.sh（从 Conventional Commits 生成变更日志）、require_tool.sh
（awk 版 strverscmp）、theme_chooser.sh。

## fork 框架层（本仓新增）

- 规则路由：`docs/AGENT_RULES/routes.toml` + `scripts/resolve_agent_rules.py`
  （scope → 必读领域规则；--check 闭集校验）。
- 命令面：`Makefile` → `scripts/dev_framework.py` → `docs/dev-framework.json`。
- 知识库：`scripts/build_agent_kb.py` 三层语料 → `docs/kb/chunks.json`；
  `scripts/agent_kb.py` 检索。
- 图谱：`scripts/graphify.sh`（graphify --code-only；zsh 扩展名不受 AST 支持，
  覆盖 bash/python/json 面，zsh 结构检索由 KB 代码层承担）。

## GX 原生启动器（scripts/gx-launcher/main.rs）

- 两个变体：`gx-zsh` 以 `-il` 启动私有 Zsh；`herdr`（`--cfg gx_herdr`）启动 `lib/herdr` 下的
  真实 herdr。资源按自身可执行文件定位，Windows 路径逐段拼接，只用 `\`。
- `main.rs::initialize` 在 profile 锁内准备目录（Windows 另建 `.cache/oh-my-zsh/completions`、
  `.local/share/zoxide`）、P10k 运行副本、`.zshenv`/`.zshrc` 与 herdr `config.toml`。
  herdr 信息类参数（`--version`、`--help` 等）跳过初始化和路径转换。
- `main.rs::package_environment` 把全部路径逐行写入一次 `cygpath -u -f -` 的标准输入（不经 MSYS2
  命令行解析，含空格的 UNC、`{a,b}`、`'` 原样转换），行数不符或无法按行传递时逐个用参数回退；
  profile 下的派生路径直接拼接。`TMPDIR`/`TMPPREFIX` 指向 profile，`TEMP`/`TMP` 不改；
  Windows 下 `_ZO_DATA_DIR` 未设置时导出 profile 内的原生路径。
- 入参环境含 `GX_PACKAGE_ROOT` 或 `GX_PROFILE_DIR` 时视为 GX 父环境：不继承 `FPATH`；
  `ZSH_CUSTOM`、`POWERLEVEL9K_INSTALLATION_DIR` 转成 POSIX，等于包内默认值时移除；移除
  `ZSH`、`ZSH_CACHE_DIR`、`ZSH_COMPDUMP`、`HISTFILE`、`NVM_DIR`、`GITSTATUS_AUTO_INSTALL`、
  `P9K_TTY`、`_P9K_TTY`、`P9K_SSH`、`_P9K_SSH_TTY` 这 10 个变量，以及指向 profile 的
  `XDG_CACHE_HOME`。其他父环境只保留 `FPATH` 里的绝对 POSIX 项。
- herdr 变体给 server 的环境与 `gx-zsh` 相同（`ZDOTDIR`、`FPATH`、`GX_*`、`MSYSTEM`、
  `_ZO_DATA_DIR` 等），只有 `HOME` 是原生 Windows 路径（`gx-zsh` 给的是 POSIX 形式）。默认 Shell
  换成 pwsh、cmd 等时窗格仍继承这些变量；这是有意保留的，运行中的 server 切回 GX Zsh 后新窗格
  才能直接用。
- herdr `config.toml` 由标记行 `# gx-shell: manages ...` 声明 GX 管理 `[terminal]` 的
  `default_shell`、`shell_mode`。GX 创建或收编该文件时在旁边写 `.gx-config-adopted`。
  无标记且没有这个印记时，`default_shell` 是旧版生成值、`shell_mode = "login"` 才收编一次：
  Windows 的旧值是 0.1.0/OhMyZshGX 的混合分隔符路径（`…\runtime/msys64/usr/bin/zsh.exe`）；
  Linux 的旧值与现值相同（`/usr/lib/ohmyzsh-gx/libexec/zsh/zsh`），只靠印记区分。
  用户删掉标记行后永不再收编。
- 以下情况都不动文件：`HERDR_CONFIG_PATH` 指向托管文件以外的位置（指向托管文件本身不算，
  Windows 比较不区分大小写）；`config.toml` 是链接、目录等非普通文件；`[terminal]` 以带引号、
  点号子表或数组表等形式出现。启动时只修复旧版值与已不存在的路径；写入先写临时文件，rename 前
  复读，内容被 herdr 改过就重读重判；替换的两行保留缩进与行尾注释，其余内容与 CRLF 不变。
- `herdr --gx-set-default-shell <绝对路径>`（仅 herdr 变体）写入托管配置；会话（默认
  `ohmyzsh-gx`）的 server 已在运行时再执行 `server reload-config`，从不启动 server，并解析
  其报告：`failed` 按错误返回并在 stderr 给出诊断（配置保持已写入），`partial` 的诊断作为警告。
  退出码：0 成功；3 配置不归 GX 管理（stderr 含 `custom configuration`）；其他为错误。
- Windows 的 `gx-zsh` 启动 Zsh 前清除继承的「忽略 Ctrl+C」标志；herdr 变体维持原状。
