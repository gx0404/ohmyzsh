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
│   ├── zshenv         skip_global_compinit + cargo 环境
│   ├── zshrc.local    机器差异层参照（CUDA/TensorRT、Photoneo、海康 MVS 等；
│   │                  不入安装器部署对，换机不带走，目标机已有文件原样保留）
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
后迁移，可随时回退。重装（目标带 `.gx-managed` 标记）时新快照先在 `$ZSH` 同级
完整就位并合并 `$ZSH/custom/` 用户层（同名文件以用户版本为准；`custom` 是符号链接
时原样保留，不展开成拷贝），再原子替换目录——任何失败都发生在旧安装原样在位时，
没有「暂存后回填」的中间态；上次中断留下的 `.gx-new-*`/`.gx-old-*`/旧版
`.gx-custom.*` 只提示不清理。补全缓存：无后缀的全局 compinit 残留 `.zcompdump` 与其他
主机名/zsh 版本的 `.zcompdump-*`（含残留的 `.lock` 锁目录）总是清掉；当前
`<host>-<ver>` 一族只在**源快照指纹与上次部署一致**时保留（指纹写在
`$ZSH/.gx-managed` 的 `snapshot:` 行），指纹变了就一并清掉、下次启动重建。这条兜底
不能交给 omz 自己：它的失效判据只有 `#omz fpath:`（fpath 目录集）与 compinit 的
「补全文件总数 + zsh 版本」，已存在补全文件的内容/`#compdef` 标签改动检不出，而
`#omz revision:` 在本安装器的无 `.git` 快照部署下恒为空。未改动的重装因此仍省下
约 121 ms（20 轮中位实测重装后首启 369.5 ms → 248.3 ms）。

`.pre-gx-*` 备份回收：**时间戳最小的「第一代」永久保留**（那是唯一一份 gx 之前
用户自己的配置，删掉就再也回不去），其余只留最新 `GX_KEEP_BACKUPS` 份（默认 2；
须 ≥1，`all` 关闭回收），中间世代回收；只认本安装器的 `.pre-gx-<14 位时间戳>`
后缀，手工改名的备份不碰。两个例外：`$ZSH` 整树因体积固定只留「第一代 + 1 份」，
不受 `GX_KEEP_BACKUPS` 影响；`$ZSH/custom/themes/powerlevel10k.pre-gx-*` 在用户
运行时层里，一律不回收。

常用选项：`--online`（强制拉取最新分支）、`--skip-apt/--skip-fonts/
--skip-wezterm/--skip-chsh`、`--unattended`（无交互）、`--uninstall`（恢复最新
一份 `.pre-gx-*` 备份并移除带 `.gx-managed` 标记的产物，其余备份留「第一代 +
`GX_KEEP_BACKUPS-1` 份」；注意它恢复的是**最新**一份，即最后一次重装前的状态，
要回到 gx 之前的原版请手动取第一代那份）、`--home <dir>`/`--zsh <dir>`
（重定向部署目标，测试用）。
`--home` 显式给出时忽略继承的环境变量 `ZSH`（gx 会话里它指向真实
`~/.oh-my-zsh`，否则隔离演练会重装真实目录）；环境 `ZSH` 不在部署 home 之下且未传
`--zsh` 时，unattended 直接拒绝、交互模式要求确认。`--home` 重定向时 fc-cache 的
缓存也落在部署 HOME。完整契约见 `gx/install.sh` 头部注释。

## 更新流程

1. 本机改 `~/.zshrc`（或其他配置）并验证；
2. 回填 `gx/config/` 对应文件（保持 `$HOME` 参数化，勿写死绝对路径）；
3. 跑 `make test`（含 gx 安装演练）后提交；
4. 目标机重跑安装器即获得新配置（本地模式 `sh ~/.oh-my-zsh/gx/install.sh`
   或在线模式）。

## WezTerm 壁纸快捷键（Leader 层）

壁纸键位统一挂在宿主 leader（`Ctrl+Shift+Space`，1 秒超时）之下，不再占用裸
`Alt` 组合——裸 `Alt+.` / `Alt+b` 是 readline 标准键（末参数插入、退词），被
GUI 截获后 shell 不可用（GX-10）。

| 快捷键 | 功能 |
|---|---|
| `Leader .` / `Leader ,` | 下一张 / 上一张壁纸 |
| `Leader /` | 随机壁纸 |
| `Leader i` | 打开壁纸选择器（不用 `Leader Shift+/`：X11 把 Shift+/ 解成 `?`，物理不可达） |
| `Leader b` | 切换纯色专注模式与壁纸 |
| `Leader k` / `m` / `s` | 快捷键速查 / 主菜单 / 设置浮层 |

标签直达 `Leader 1..9`（Linux）；分屏为 `Ctrl+Shift+\`（垂直）与
`Ctrl+Alt+Shift+\`（水平）；`Alt+w` 仍关闭当前 pane 但改为先弹确认（防误毁
运行中 agent 的 pane）。本机调整键位后，同步 `gx/wezterm/config/bindings.lua`
与 WezTerm 仓库的 `dotfiles/wezterm-config/config/bindings.lua`，再验证配置
可加载。

## vendored 组件清单

| 组件 | 来源 | 版本 | 复刻命令 |
|---|---|---|---|
| powerlevel10k | github.com/romkatv/powerlevel10k | 9253fb1c（master） | `git archive HEAD` 导出提交树（gitstatus 守护进程不含在内，单独 vendor） |
| gitstatusd | 本机 `~/.cache/gitstatus/` | v1.5.4 linux-x86_64 | 从 romkatv/gitstatus releases 同版本下载 |
| zoxide | 本机 `~/.local/bin/zoxide` | 0.9.9 linux-x86_64 | github.com/ajeetdsouza/zoxide releases v0.9.9 |
| Nerd Font | 本机 `~/.local/share/fonts/JetBrainsMonoNerd/` | v3.4.0 JetBrainsMono ×4 字重 | nerd-fonts release v3.4.0 |
| wezterm 配置 | 本机 `~/.config/wezterm`（上游 gx0404/wezterm） | 工作树快照 9b60228；2026-09-21 壁纸/标签直达键迁入 leader（GX-10） | 排除 `.git`/`backups`/`*.bak` 后拷贝 |

二进制仅携带 linux-x86_64：其他架构时 gitstatus 由 p10k 联网自下载，zoxide
提示手动安装（见安装器警告）。

## 范围外（有意不迁移）

`~/.zsh_history` 与 zoxide 数据库（隐私）、nvm/cargo/bun/go 等 SDK（PATH 守卫
静默跳过）、`.gitconfig`、任何 token/密钥文件。atuin 在 zshrc 中留有守卫集成，
未安装则自动跳过。

## 交互性能开关（有意的取舍）

- `ZSH_AUTOSUGGEST_MANUAL_REBIND=1`：zsh-autosuggestions 在首个提示符统一包裹全部
  widget（此时整份 `.zshrc` 含 `~/.zshrc.local` 已执行完），默认之后每个提示符都
  再整体重绑一次；关掉后真 PTY 原位实测 precmd 链 5.5 ms → 0.05 ms/提示符。代价：
  首个提示符之后才 `zle -N` 的新 widget 不会被包裹——需要包裹的 widget 一律放在
  `.zshrc`/`.zshrc.local` 的 source 阶段内定义，交互期临时定义的不在此列。
- `ZSH_HIGHLIGHT_MAXLENGTH=512` / `ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE=512`：超过 512
  字符的命令行不再重新解析语法、不再取历史建议。两者每击键都按整个 buffer 重算；
  4401 字符的粘贴行在部署 HOME 真 PTY 里 20 键取中位，四种组合实测：两项都不设
  25.5 ms、只设建议上限 24.5 ms（≈无效）、只设高亮上限 1.0 ms、两者同设 0.65 ms。
  即 **`ZSH_HIGHLIGHT_MAXLENGTH` 是主因**（粘贴首帧也从「40 s 内仍未静默」降到
  1.5 s），`ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE` 是补足项（1.0 → 0.65 ms，并让越界时
  不再查历史）；粘贴首帧的那 1.5 s 由逐字节回显主导，与建议上限无关。
- 越界后的高亮不是「没有颜色」：zsh-syntax-highlighting 在清空 `region_highlight`
  **之前**就返回，越界前那一帧的区间原样留下并随编辑平移，于是颜色可能与实际语法
  不符（行首插入一个不存在的命令，它仍显示为命令绿）。**超长行只保证可编辑，不保证
  配色正确**；灰色建议则确实会消失。512 以内实测 <3 ms/击键，带长路径的
  rsync/ffmpeg 这类真实长命令仍正常高亮。

## Herdr 与 WezTerm 联动

`gx/wezterm` 与 WezTerm fork 的 `dotfiles/wezterm-config` 对应。宿主 leader 为
`Ctrl+Shift+Space`，Herdr 保留 `Ctrl+B`；普通拖选由应用处理，Shift 拖选交给宿主。
正文使用 Regular 字重，标题和选择由 TUI 自行强调。Windows 优先 PowerShell 7，
未安装时回退 5.1；WSL 使用实际发行版默认用户与登录 shell。

`gx/config/terminal.zsh` 只在交互 shell 且 fd 1 是 TTY 或 `$TTY` 非空（对 p10k
instant prompt 的 fd 重定向免疫）时上报 OSC 7 工作目录：主机名字段留空
（`file:///...`，herdr 与 WezTerm 都接受），编码中文、空格和控制字符，只在目录
变化时发送，并摘掉上游 `omz_termsupport_cwd` 避免同一提示符双发（摘钩子在重复
source 守卫之前执行，`source ~/.zshrc` 后仍只有一个上报函数）。ssh / emacs 会话
（`SSH_CONNECTION`/`SSH_CLIENT`/`SSH_TTY`/`INSIDE_EMACS`）不接管，与上游一致；
已有 WezTerm CWD 集成时跳过。已知副作用：fd 1 被重定向但 `$TTY` 非空（如
`zsh -i > log`）时 OSC 7 仍写到 stdout，捕获类测试需过滤 `\e]7;`。P10k 使用自身
的 OSC 133 支持，不叠加 PS1 包装。`.zshenv` 首行 `skip_global_compinit=1` 跳过
Ubuntu 全局 compinit，缺少 Cargo 环境文件时静默继续。验证：
`python3 tests/gx_terminal.py` 和隔离安装 smoke。
