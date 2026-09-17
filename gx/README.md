# gx 个人配置层

把一台机器的完整 zsh 工作环境（Oh My Zsh fork 分支 + p10k 主题 + 补全/高亮 +
zoxide + Nerd 字体 + WezTerm 终端配置）固化进仓库，一条命令在全新 Linux
工控机上部署，实现跨机无缝迁移。领域规则见
[docs/AGENT_RULES/gx-profile.md](../docs/AGENT_RULES/gx-profile.md)。

## 目录结构

```
gx/
├── config/            配置真源（改动在本机验证后回填到这里）
│   ├── zshrc          主配置（p10k、plugins、按键/历史/补全定制、第三方集成）
│   ├── zshenv         cargo 环境
│   ├── zshrc.local    机器差异层（CUDA/TensorRT、Photoneo、海康 MVS 等，缺路径不报错）
│   └── p10k.zsh       Powerlevel10k Lean 精简配置
├── omz-custom/themes/powerlevel10k/   主题提交树快照（无 .git）
├── bin/               linux-x86_64 二进制：gitstatusd v1.5.4、zoxide 0.9.9
├── fonts/JetBrainsMonoNerd/           Nerd Fonts v3.4.0 四字重 ttf
├── wezterm/           ~/.config/wezterm 工作树快照（含背景图）
├── install.sh         一键安装器（POSIX sh，双模式）
└── bundle.sh          工作树打 tar.gz 离线安装包
```

## 安装（全新工控机）

```bash
# 方式一：在线一键（需能访问 GitHub）
sh -c "$(curl -fsSL https://raw.githubusercontent.com/gx0404/ohmyzsh/feature/gx_ohmyzsh/gx/install.sh)"

# 方式二：离线（U 盘拷仓库或解包 make gx-bundle 的 tar.gz 后）
sh gx/install.sh

# 方式三：仓库内
make gx-install
```

安装器自动完成：apt 包（zsh/git/fzf/zsh-autosuggestions/zsh-syntax-highlighting，
需 root 或 sudo）→ Oh My Zsh 工作树到 `~/.oh-my-zsh` → 四个配置文件 → p10k
主题 + gitstatusd → `~/.local/bin/zoxide` → 字体 + fc-cache → WezTerm 配置 →
chsh（交互确认）。已有官方 Oh My Zsh 或旧配置时自动备份为 `*.pre-gx-<时间戳>`
后迁移，可随时回退。

常用选项：`--online`（强制拉取最新分支）、`--skip-apt/--skip-fonts/
--skip-wezterm/--skip-chsh`、`--unattended`（无交互）、`--uninstall`（恢复备份
并移除带 `.gx-managed` 标记的产物）、`--home <dir>`/`--zsh <dir>`（重定向部署
目标，测试用）。完整契约见 `gx/install.sh` 头部注释。

## 更新流程

1. 本机改 `~/.zshrc`（或其他配置）并验证；
2. 回填 `gx/config/` 对应文件（保持 `$HOME` 参数化，勿写死绝对路径）；
3. 跑 `make test`（含 gx 安装演练）后提交；
4. 目标机重跑安装器即获得新配置（本地模式 `sh ~/.oh-my-zsh/gx/install.sh`
   或在线模式）。

## WezTerm 壁纸快捷键（Linux / Windows）

| 快捷键 | 功能 |
|---|---|
| `Alt+.` / `Alt+,` | 下一张 / 上一张壁纸 |
| `Alt+/` | 随机壁纸 |
| `Ctrl+Alt+/` | 打开壁纸选择器 |
| `Alt+b` | 切换纯色专注模式与壁纸 |

macOS 对应使用 `Super` / `Ctrl+Super`。Linux 常用终端功能继续使用 `Ctrl+Shift`。
本机调整壁纸键位后，同步 `gx/wezterm/config/bindings.lua` 与 WezTerm 仓库的
`dotfiles/wezterm-config/config/bindings.lua`，再验证配置可加载。

## vendored 组件清单

| 组件 | 来源 | 版本 | 复刻命令 |
|---|---|---|---|
| powerlevel10k | github.com/romkatv/powerlevel10k | 9253fb1c（master） | `git archive HEAD` 导出提交树（gitstatus 守护进程不含在内，单独 vendor） |
| gitstatusd | 本机 `~/.cache/gitstatus/` | v1.5.4 linux-x86_64 | 从 romkatv/gitstatus releases 同版本下载 |
| zoxide | 本机 `~/.local/bin/zoxide` | 0.9.9 linux-x86_64 | github.com/ajeetdsouza/zoxide releases v0.9.9 |
| Nerd Font | 本机 `~/.local/share/fonts/JetBrainsMonoNerd/` | v3.4.0 JetBrainsMono ×4 字重 | nerd-fonts release v3.4.0 |
| wezterm 配置 | 本机 `~/.config/wezterm`（上游 gx0404/wezterm） | 工作树快照 9b60228；2026-09-16 恢复壁纸 Alt 快捷键 | 排除 `.git`/`backups`/`*.bak` 后拷贝 |

二进制仅携带 linux-x86_64：其他架构时 gitstatus 由 p10k 联网自下载，zoxide
提示手动安装（见安装器警告）。

## 范围外（有意不迁移）

`~/.zsh_history` 与 zoxide 数据库（隐私）、nvm/cargo/bun/go 等 SDK（PATH 守卫
静默跳过）、`.gitconfig`、任何 token/密钥文件。atuin 在 zshrc 中留有守卫集成，
未安装则自动跳过。

## Herdr 与 WezTerm 联动

`gx/wezterm` 与 WezTerm fork 的 `dotfiles/wezterm-config` 对应。宿主 leader 为
`Ctrl+Shift+Space`，Herdr 保留 `Ctrl+B`；普通拖选由应用处理，Shift 拖选交给宿主。
正文使用 Regular 字重，标题和选择由 TUI 自行强调。Windows 优先 PowerShell 7，
未安装时回退 5.1；WSL 使用实际发行版默认用户与登录 shell。

`gx/config/terminal.zsh` 只在交互 TTY 中上报 OSC 7 工作目录，编码中文、空格和
控制字符，只在目录变化时发送。已有 WezTerm CWD 集成时跳过，重复 source 不增加
hook。P10k 使用自身的 OSC 133 支持，不叠加 PS1 包装。缺少 Cargo 环境文件时
`.zshenv` 静默继续。验证：`python3 tests/gx_terminal.py` 和隔离安装 smoke。
