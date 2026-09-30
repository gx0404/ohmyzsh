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
│   ├── package.zsh    原生包模式的 profile 隔离（只在 GX_PACKAGE_ROOT/GX_PROFILE_DIR 下生效）
│   ├── terminal.zsh   WezTerm/herdr 的 OSC 7 工作目录上报
│   ├── windows.zsh    Windows（MSYS/Cygwin）交互层：PowerShell 桥接、缺失命令提示、shim
│   ├── zshrc.local    机器差异层参照（CUDA/TensorRT、Photoneo、海康 MVS 等；
│   │                  不入安装器部署对，换机不带走，目标机已有文件原样保留）
│   └── p10k.zsh       Powerlevel10k Lean 精简配置
├── omz-custom/themes/powerlevel10k/   主题提交树快照（无 .git）
├── omz-custom/plugins/herdr/          覆盖上游 herdr 插件（原生包自带 _herdr 时不再后台生成）
├── bin/               linux-x86_64 二进制：gitstatusd v1.5.4、zoxide 0.9.9
├── fonts/JetBrainsMonoNerd/           Nerd Fonts v3.4.0 四字重 ttf
├── wezterm/           ~/.config/wezterm 工作树快照（含背景图）
├── install.sh         一键安装器（POSIX sh，双模式）
└── bundle.sh          工作树打 tar.gz 离线安装包
```

## 原生安装包（开发中）

正在增加 Windows x64 EXE（私有 MSYS2 Zsh，非 WSL）与 Ubuntu amd64 DEB。
原生入口为 `gx-zsh` / `herdr`，herdr 来自 `gx0404/gx_shell` 单仓同一提交的 `herdr/`
目录。打包来源、工具版本、许可及对应源码见 `scripts/packaging/`；合并安装包
（含 WezTerm）由单仓根目录的发版流程生成。

**完整包尚未验收，不应把下述接口当作已发布下载。** 中文 HOME/独立 profile/缓存、
安装升级卸载与 TUI 均需真实通过后才能发布，详见 [发布手册](../docs/RELEASE.md)。

- `config/package.zsh`：显式包模式下，将 Zsh/P10k 缓存与历史归入独立 profile，
  不替换已有 HOME `.zshrc`；机器差异和 P10k 覆盖只从 profile 读取。
- P10k 内部主题副本和 `.zwc` 写入 profile 的版本化缓存，不修改包资源：主题或
  `POWERLEVEL9K_INSTALLATION_DIR` 位于资源树内任何位置（Windows 上不分大小写）都改用该副本；
  无控制终端的命令调用不初始化提示符主题，真实终端仍启用 instant prompt 和 gitstatus。
- herdr 窗格、嵌套 `gx-zsh` 继承到的 `ZSH_CUSTOM` / `POWERLEVEL9K_INSTALLATION_DIR` 可能已被
  MSYS 转成 `C:/…`：盘符/UNC 值用一次 `cygpath -u` 转回，其余非绝对值忽略并告警一次；
  `fpath` 只保留存在的绝对目录并去重，混进来的 Windows 路径碎片不再让 compdump 反复重建。
  Windows（MSYS/Cygwin）包模式还导出 `SHELL`（正在运行的 zsh；Linux 保持登录环境给的值），
  平台只看 `$OSTYPE`，目录已存在时不调用外部 `mkdir`。
- Windows 包模式的 zoxide 默认数据库放在 profile 的 `.local/share/zoxide`，以原生
  Win32 路径传给 `_ZO_DATA_DIR`：启动器已给出时原样使用，缺失时才用 `cygpath -w` 兜底；
  已有显式设置原样保留，不迁移或改写其他用户数据库。
- `config/zshrc`：启用既有 herdr 插件，命令缺失时静默降级；插件本身不安装 herdr。
  Windows 上不加载 `sudo` 插件（系统 sudo.exe 提不了 MSYS 命令的权限），没有 `man` 时不加载
  `colored-man-pages`；MSYS 包模式无 SSH 变量时预置 p10k 的 SSH 判定，省掉 `who -m`。
- fzf 0.48+ 使用自身 `--zsh`，旧版保留发行版脚本；键位集成要求真实 TTY/ZLE，
  无终端调用仍保留版本兼容选项和普通补全。`fzf --version`、`fzf --zsh`、`zoxide init zsh`
  （以及 MSYS 包模式的 `dircolors -b`）的输出缓存为 `$ZSH_CACHE_DIR/gx-init-<名称>-<哈希>.zsh`
  并 zcompile。首行记录生成命令、附加键、二进制路径/mtime/大小与 GX 包身份（`package-origin.json`），
  文件名里的 8 位十六进制哈希（FNV-1a）取自这一行：任一输入变化就换一个文件，键不同的并发 shell
  各写各的文件，脚本和 `.zwc` 不会来自不同的键；同名的旧键文件超过一天后在下次重新生成时清理。
  缓存目录写不进去时直接执行生成的脚本，生成命令失败或没有输出时跳过该集成。
- `omz-custom/plugins/herdr` 覆盖上游插件：别名、函数与提示符片段逐字同步上游；打包时在该目录
  生成的 `_herdr` 存在时直接由 compinit 加载，不再每次启动后台重新生成（否则新 profile 会连续
  两次重建 compdump）。上游插件更新后同步这里（`tests/gx_package_profile.py` 守门）。
- `config/windows.zsh`（仅 MSYS/Cygwin）：`gx-pwsh '脚本'` 或 `… | gx-pwsh` 把脚本原样写成带
  UTF-8 BOM 的临时 `.ps1`，不加任何前置行，以 `param(`、`[CmdletBinding()]` 或 `using` 开头的
  安装脚本照常可用；PowerShell（`GX_POWERSHELL` > pwsh.exe > powershell.exe）以
  `-NoProfile -ExecutionPolicy Bypass -Command` 运行一层外壳，设好 UTF-8 输出、关掉进度条后调用
  该脚本，退出码与 `-File` 相同（脚本 `exit N` 为 N，正常结束为 0，`throw` 为 1），
  `$ErrorActionPreference` 保持默认（与 `Invoke-Expression` 一致）。
  没有收到脚本内容时（如 `irm <错误地址> | iex` 里 irm 已失败）不启动 PowerShell，提示后返回 1。
  `iex`/`Invoke-Expression` 走 `gx-pwsh`；`irm`/`iwr`/`Invoke-RestMethod`/`Invoke-WebRequest`
  拼成一条 PowerShell 命令：只有 `-Name` 形式的参数名原样传，其余参数一律写成单引号字面量
  （`'` 与 `‘ ’ ‚ ‛` 这些同样会结束字符串的引号都写两遍），请求失败时返回 1。`iwr` 没写
  `-UseBasicParsing`（或 `-useb`）时自动补上：Windows PowerShell 5.1 不带它会用 IE 引擎解析页面，
  没有 IE 的系统上会报错或卡住，PowerShell 6+ 忽略这个参数。输出进管道时 `iwr` 只写正文，
  因此 `iwr https://… | iex` 与 `irm https://… | iex` 一样可用。PowerShell 子进程的 PATH 里，私有
  运行时的 `/usr/bin` 等目录排到最后，安装脚本调用的 tar、find、sort、curl、cmd 是 Windows 自带的
  版本。每次 `gx-pwsh`（含 `iex`）结束后把注册表 PATH 与用户 bin 目录里新出现的目录追加进
  `$path` 并 rehash，安装器装好的命令当场可用；已在 `$path` 的条目不再检查，不可达的网络路径
  不会每次都拖慢。缺失命令只提示不执行：`Verb-Noun` 提示改用 `gx-pwsh`
  （每个参数按 PowerShell 规则单独加引号，整行再按 zsh 规则加引号，可原样复制运行），`man` 提示
  `--help`，`tmux` 提示 herdr，rg/fd/htop 等给出 winget 包名。另补 `vi`→`vim`、
  `open`/`xdg-open`→`open_command`、`pbcopy`/`pbpaste`（`/dev/clipboard`），运行时缺 `unzip`
  时转交 `bsdunzip`；已有同名命令、函数或别名一律不覆盖。
  原生 zoxide 的 cd 钩子改为纯 zsh 换算盘符目录（`/c/…`、`/cygdrive/c/…`）并在后台记录，
  不再每次 cd 同步 fork 子 shell、cygpath 与 zoxide（实测每次 cd 约 0.2 s → 0.06 s），`z`/`zi` 不变。
- Windows 私有运行时（MSYS2）：盘符路径是 `/c/…`（与 Git Bash 一致），升级后 compdump 与
  `gx-init-*` 缓存按新路径自动重建。**0.1.0 的 `/cygdrive/c/…` 路径升级后不再存在**：GX 自带的
  OSC 7 上报与 zoxide 钩子两种写法都认，但运行时不再挂载 `/cygdrive`，用户自己写在
  `~/.zshrc.local`、脚本或历史命令里的 `/cygdrive/c/…` 会找不到文件，需要改成 `/c/…`（或
  `C:/…`）。`/tmp` 指向 Windows 用户临时目录，ssh 等按 `$HOME` 即 `%USERPROFILE%` 读取 `.ssh`；
  附带 diffutils、patch、unzip/zip、tree、bc、procps-ng（top/pgrep/pkill/watch/free）、vim、rsync、
  jq。仍没有 man、htop、rg、fd、tmux 等，缺失时由上面的提示给出替代或 winget 包名。
- 原生包不默认复制 `gx/wezterm` 或机器专属 `zshrc.local`，不覆盖既有 WezTerm/MSYS2。
- `make package-test` 验证模块，`make package` 需显式离线依赖 bundle；两者均不发布。
  legacy `install.sh` 和 `bundle.sh` 保持原有用途，工作树 tar.gz 不作为正式原生包输入。

## 安装（全新 Linux 工控机，legacy 脚本）

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

同一秒内连续操作若碰到已经占用的备份、中转或卸载移出名称，安装器会以退出码 2
拒绝并提示稍后重试，不覆盖旧备份、不删除同名残留或悬空链接。不要并发操作同一
安装目标；这项防覆盖检查不等同于完整的多进程事务锁。

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

## WezTerm 快捷键（Windows 与 Linux 相同）

两个平台用同一套键位：常用操作是 Ubuntu 终端习惯的 `Ctrl+Shift`（复制/粘贴 `Ctrl+Shift+C/V`、
新标签 `Ctrl+Shift+T`、搜索 `Ctrl+Shift+F`），`Ctrl+C`/`Ctrl+V` 不拦截（中断与图片粘贴留给应用）。
壁纸、标签直达与浮层挂在宿主 leader（`Ctrl+Shift+Space`，1 秒超时）之下，不占用裸 `Alt`
组合——裸 `Alt+.` / `Alt+b` / `Alt+f` 是 readline 标准键（末参数插入、按词移动），被 GUI 截获后
shell 不可用（GX-10）。

| 快捷键 | 功能 |
|---|---|
| `Leader .` / `Leader ,` | 下一张 / 上一张壁纸 |
| `Leader /` | 随机壁纸 |
| `Leader i` | 打开壁纸选择器（不用 `Leader Shift+/`：X11 把 Shift+/ 解成 `?`，物理不可达） |
| `Leader b` | 切换纯色专注模式与壁纸 |
| `Leader w` | 壁纸管理浮层（可视化列表/实时预览/添加/删除） |
| `Leader k` / `m` / `s` | 快捷键速查 / 主菜单 / 设置浮层 |

标签直达 `Leader 1..9`，`Ctrl+PageUp/PageDown` 切换标签，`Ctrl+=`/`Ctrl+-`/`Ctrl+0` 缩放字体，
`Leader -`/`Leader =` 把窗口缩小/放大 50 像素（`Ctrl+Shift+-` 就是 shell 撤销用的 `Ctrl+_`，不占用）；
分屏为 `Ctrl+Shift+\`（垂直）与 `Ctrl+Alt+Shift+\`（水平）；`Ctrl+Shift+W` 关闭当前 pane、
`Ctrl+Alt+Shift+W` 关闭当前标签，都先弹确认（防误毁运行中 agent 的 pane）。`Shift+PageUp/Down`
在前台是 alt-screen 应用（herdr/vim/Claude Code）时透传为应用内翻页，否则宿主滚动；不带修饰的
PageUp/PageDown 留给 less、vim 等程序。截图（flameshot）与 AI 图片粘贴（`Alt+Shift+S/V`）只在
Linux 绑定，Windows 用 `Win+Shift+S` 截图后直接 `Ctrl+V` 给 agent。插件缺失时相关键位静默
降级为 Nop（pcall 兜底）。本机调整键位后，同步 `gx/wezterm/config/bindings.lua`
与 WezTerm 仓库的 `dotfiles/wezterm-config/config/bindings.lua`，再验证配置
可加载。

## vendored 组件清单

| 组件 | 来源 | 版本 | 复刻命令 |
|---|---|---|---|
| powerlevel10k | github.com/romkatv/powerlevel10k | 9253fb1c（master） | `git archive HEAD` 导出提交树（gitstatus 守护进程不含在内，单独 vendor） |
| gitstatusd | 本机 `~/.cache/gitstatus/` | v1.5.4 linux-x86_64 | 从 romkatv/gitstatus releases 同版本下载 |
| zoxide | 本机 `~/.local/bin/zoxide` | 0.9.9 linux-x86_64 | github.com/ajeetdsouza/zoxide releases v0.9.9 |
| Nerd Font | 本机 `~/.local/share/fonts/JetBrainsMonoNerd/` | v3.4.0 JetBrainsMono ×4 字重 | nerd-fonts release v3.4.0 |
| wezterm 配置 | 本机 `~/.config/wezterm`（上游 gx0404/wezterm） | 工作树快照 9b60228；2026-09-21 壁纸/标签直达键迁入 leader（GX-10）；同日回灌轨 C 全部 Lua 变更（批 8/12/13 + 复审）；2026-09-30 回灌 0.2.0 的 Lua 配置：默认 Shell 注册表 `utils/shells.lua`（由 `config/launch.lua` 生成 launch_menu）、设置页 sidecar 定位 `utils/gui-settings.lua`、安装包入口探测 `utils/gx-shell.lua`，Windows 与 Linux 统一的 `Ctrl+Shift` 键位方案（leader 为 `Ctrl+Shift+Space`），以及性能调优（`animation_fps` 30→10 且光标闪烁改为 Constant 缓动，空闲窗口不再持续重绘；状态栏的电池信息缓存 60 秒、前台进程探测 2 秒内复用；WSL 发行版列表由 `utils/wsl.lua` 缓存、`wsl_domains` 始终赋值，不再每次查询都运行 wsl.exe；关闭只会提示上游版本的更新检查）；同日 backdrops/ 16 张壁纸等比缩小、去元数据（与 WezTerm dotfiles/wezterm-config/backdrops/ 逐字节相同，见其 PROVENANCE.md） | 排除 `.git`/`backups`/`*.bak` 后拷贝；backdrops/ 取 WezTerm 仓库版本，不回收本机原图 |

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
  不再查历史）。这些是原先仅限制高亮/建议时的测量，未包含下一项整段粘贴优化。
- `:bracketed-paste-magic` 的 `active-widgets` 动态样式：至多 512 字符保留默认
  `self-*` 钩子；超过 512 字符交给内建 bracketed paste 一次字面插入，避免逐字符
  重放。修复版 Zsh 真 PTY 三轮中，4401 字符粘贴从约 5.3 s 降到 13–17 ms，
  20 键中位约 1.1 ms。长粘贴不再逐字符执行自定义 `self-*` 处理，但保留上游
  paste-init/paste-finish、原始内容、单次 undo 和不自动执行多行的语义；机器层可覆盖。
- 越界后的高亮不是「没有颜色」：zsh-syntax-highlighting 在清空 `region_highlight`
  **之前**就返回，越界前那一帧的区间原样留下并随编辑平移，于是颜色可能与实际语法
  不符（行首插入一个不存在的命令，它仍显示为命令绿）。**超长行只保证可编辑，不保证
  配色正确**；灰色建议则确实会消失。512 以内实测 <3 ms/击键，带长路径的
  rsync/ffmpeg 这类真实长命令仍正常高亮。

## Herdr 与 WezTerm 联动

`gx/wezterm` 与 WezTerm fork 的 `dotfiles/wezterm-config` 对应。宿主 leader 为
`Ctrl+Shift+Space`，Herdr 保留 `Ctrl+B`；普通拖选由应用处理，Shift 拖选交给宿主。
正文使用 Regular 字重，标题和选择由 TUI 自行强调。默认 Shell 是 GX Zsh；设置浮层
（`Leader s`，或主菜单与标签栏右键的「默认 Shell…」）的 Shell 分区可改成本机探测到的 PowerShell 7/5.1、
cmd、Git Bash、MSYS2 UCRT64、Nushell 或 WSL 发行版（Linux 上为系统 zsh/bash）。选择写入
`gui-settings.json` 的 `default_shell`，新标签随之切换；安装包内 herdr 的新窗格也跟随（herdr 的
`config.toml` 被用户改过 Shell 时保持不变并提示）。herdr 只接受一个可执行文件：选 WSL 发行版时
herdr 窗格进入 WSL 默认发行版，选 MSYS2 UCRT64 时 herdr 里是 MSYS 环境的 bash，Linux 上选系统
zsh 时 herdr 用 GX Zsh；切换后的通知写明 herdr 实际使用的 Shell。WSL 使用实际发行版默认用户与
登录 shell。

`gx/config/terminal.zsh` 只在交互 shell 且 fd 1 是 TTY 或 `$TTY` 非空（对 p10k
instant prompt 的 fd 重定向免疫）时上报 OSC 7 工作目录：主机名字段留空
（`file:///...`，herdr 与 WezTerm 都接受），编码中文、空格和控制字符，只在目录
变化时发送。MSYS/Cygwin 上盘符目录（`/c/…` 或 `/cygdrive/c/…`）报成 `file:///C:/…`，
新标签/分屏才能沿用；运行时根下等非盘符目录不上报。上报时摘掉上游 `omz_termsupport_cwd`
避免同一提示符双发（摘钩子在重复 source 守卫之前执行，`source ~/.zshrc` 后仍只有一个
上报函数）。ssh / emacs 会话（`SSH_CONNECTION`/`SSH_CLIENT`/`SSH_TTY`/`INSIDE_EMACS`）
不接管，与上游一致；已有 WezTerm CWD 集成时跳过。已知副作用：fd 1 被重定向但 `$TTY`
非空（如 `zsh -i > log`）时 OSC 7 仍写到 stdout，捕获类测试需过滤 `\e]7;`。P10k 使用
自身的 OSC 133 支持，不叠加 PS1 包装。`.zshenv` 首行 `skip_global_compinit=1` 跳过
Ubuntu 全局 compinit，缺少 Cargo 环境文件时静默继续。验证：`python3 tests/gx_terminal.py`、
`python3 tests/gx_windows.py`（Windows 分支）和隔离安装 smoke。
