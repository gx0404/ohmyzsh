# 测试与证据

## 分层

| 层 | 入口 | 能证明 / 不能证明 |
|---|---|---|
| 语法 | `make lint`（check_syntax.sh） | 全部 shell 文件可解析（zsh -n / sh -n / bash -n 按 shebang 分派）+ 框架 Python 过 ast；与上游 CI 目标集一致并扩展到 tools/scripts/tests/hooks。不能证明行为正确 |
| 单元 | `lib/tests/cli.test.zsh`（自包含）；zunit 族（alias-finder、dotenv，本机 zunit 未装 → 可选层） | 独立单元逻辑。zunit 缺失时 ai-doctor 报 MISSING，不假绿 |
| 配置形状 | `tests/check_tool_configs.py`（make test 的 config-shapes 步） | 三工具配置结构未漂移（Codex 数组表 hooks、ZCode 毫秒字段、适配器语言一致）+ 安全门经注册入口的允许/拒绝双向探针 |
| 加载 smoke | `zsh tests/smoke_load.zsh [--plugins a,b]` | 隔离 ZDOTDIR/HOME 下主入口可加载、核心函数/别名就位、omz version 可用、退出码 0 |
| 集成 | `--plugins git,docker` 变体 | 多插件组合不互相破坏（环境相关插件如 kubectl 受命令守卫约束，不纳入固定集） |
| 终端证据 | `make ui-smoke` | 主题渲染（robbyrussell/agnoster 的分支段）、omz 子命令输出的真实捕获与断言 |
| gx 模块单元 | `python3 tests/gx_terminal.py`（TerminalIntegration，make test 的 gx-terminal 步） | `zsh -f -i` + PTY 只加载 terminal.zsh：守卫（含 fd 重定向、只认小写 `TERM_PROGRAM=ghostty` 或 `HERDR_ENV=1`、Ghostty 自带集成在位时只摘上游钩子不安装）、`file://localhost/` 主机字段、编码/缓存、上游钩子替换 |
| gx 真实链路 | 同上（DeployedZshrc / DeployedInteractive） | install.sh 落地 mktemp HOME 后走真实 .zshenv/.zshrc（不加 -f）：fzf 版本分支、skip_global_compinit；真 PTY 起 `zsh -i` 覆盖 p10k instant prompt 形态下的 precmd 链、一次 cd 一条 `file://localhost/` OSC 7、HERDR_ENV/TERM_PROGRAM 守卫、仿 Ghostty ZDOTDIR 注入（定义 `_ghostty_state`）时 p10k 不开 OSC 133 且整个会话没有 gx/上游 OSC 7、autosuggestions 首个提示符后不再重绑且后定义 widget 已包裹、灰色建议可见、4401 字符粘贴行每击键中位 <5 ms（高亮/建议长度上限生效）、越界后高亮停在旧帧不再重新解析（去掉 `ZSH_HIGHLIGHT_MAXLENGTH` 则会重新解析的对照）、p10k Lean 提示符在 Ghostty 与 herdr 窗格下都不含背景色和 powerline 分隔符（目录 `#89b4fa`、git 分支 `#a6e3a1` 前景，保留 `╭─` 与 `╰─❯` 框线）。缺 zsh/sh/PTY 或 instant prompt 缓存未生成即失败，不 skip |
| gx 安装演练 | `zsh tests/gx_install_smoke.zsh`（make test 的 gx-install-smoke 步） | 隔离 HOME 部署/加载/幂等重装（custom 层保全、同名以用户为准、符号链接 custom 原样保留、只清无后缀与异主机/版本 compdump（含残留 `.lock` 目录）而当前一族保留且下次启动不重建、快照指纹变化时连当前 dump 一起清、无中转残留）/备份恢复/`.pre-gx-*` 按 `GX_KEEP_BACKUPS` 留「第一代 + 最新 N 份」、uninstall 后留「第一代 + N-1 份」、`all` 不回收、非法份数拒绝、外来 `$ZSH` 整树备份固定「第一代 + 1 份」/不部署终端配置（旧版带 `.gx-managed` 的 `~/.config/wezterm` 重装不动、卸载移除，用户自有的始终不动，`--skip-wezterm` 只提示无作用）、快照不含项目内 `.build/`/自定义 ZSH 路径/`--home` 忽略环境 ZSH、环境 ZSH 越界 unattended 拒绝/上级不可写时中止且旧树不变。TMPDIR 与 fontconfig 缓存都落在沙箱 |
| GX 包 profile | `python3 tests/gx_package_profile.py`（make test 的 gx-package-profile 步） | 只读资源与独立 profile、中文配置/缓存、herdr 补全（含打包 `_herdr` 时不后台生成、覆盖插件与上游同步）、fzf 新旧入口及真 PTY；盘符/非绝对 `ZSH_CUSTOM` 与 `POWERLEVEL9K_INSTALLATION_DIR`、资源树内任意主题须走 profile 副本、被污染的 FPATH 不重建 compdump、启动器给出的 `_ZO_DATA_DIR` 不再 fork、`SHELL` 只在 MSYS/Cygwin 指向正在运行的 zsh（Linux 保持登录值）、fzf/zoxide 初始化缓存命中与失效（键不同各留一份带哈希的缓存文件）、`_gx_init_cache` 单元（哈希文件名、命中、超过一天的同名旧键文件清理且不误删前缀相同的其他名称、生成失败或无输出返回 1 且不写文件、缓存目录不存在时直接返回脚本、二进制取不到信息时不走缓存）、强制 MSYS 时的 p10k SSH 预置/无 sudo/dircolors 缓存；当前中文运行时问题必须修复，不能跳过红项 |
| GX Windows 层 | `python3 tests/gx_windows.py`（make test 的 gx-windows 步） | Linux 上 `windows.zsh` 不生效；强制 OSTYPE=msys/cygwin 时用 pwsh.exe/powershell.exe/cygpath shim 验证 `-NoProfile -ExecutionPolicy Bypass -Command` 外壳（脚本的 Windows 路径作单引号字面量，目录名里的 `'` 写两遍；退出码按 `-File` 语义由外壳里的 `$?`/`$LASTEXITCODE` 决定）、`MSYS2_ARG_CONV_EXCL=*`、临时脚本只有 BOM 加原文（`param(`/`[CmdletBinding()]`/`using` 开头的脚本首行不变）、退出码透传、空脚本（含 `irm` 失败后的 `\| iex`）不启动 PowerShell 并返回 1、成功/失败/SIGINT 都删临时脚本、irm/iwr 引用（`&`、`'` 与 `‘ ’ ‚ ‛`、`-x;…`、`--%` 都成字面量，UTF-8 与 C locale）、irm/iwr 末尾的失败状态行、iwr 缺 `-UseBasicParsing` 时补上（`-useb…` 不分大小写识别，不重复）、pwsh 优先与 `GX_POWERSHELL`、无 PowerShell 返回 127、注册表 PATH 合并、提示处理器从不执行且逐参数加引号、运行时已带 unzip/vi 时不定义 shim、原生 zoxide 钩子对盘符目录不再调用 cygpath 且在后台记录（非原生 zoxide 不改）；另验 terminal.zsh 的 `file://localhost/C:/…`。不运行真实 PowerShell；Windows 上的真实桥接只能在装好的 GX Zsh 里手测或由根冒烟覆盖 |
| 打包与发布单元 | `python3 -m unittest discover -s tests -p 'test_gx_*.py'` | 来源/归档/摘要/权限与发布 API 契约；synthetic fixture 不代表真实安装成功 |
| 原生启动器 | `python3 tests/gx_launcher.py` 或 `make typecheck` | 用实际 rustc 编译两个入口和 Rust 单元，执行隔离初始化/自更新拒绝、单次 `cygpath -f -` 标准输入批量转换及逐个回退、嵌套 GX 环境清理、herdr `config.toml` 迁移（只收编一次、非普通文件与托管路径的 `HERDR_CONFIG_PATH`）、`--gx-set-default-shell` 与 reload 报告（failed 退出 1、partial 告警）、Windows Ctrl+C 标志继承测试；缺编译器即失败。测试会改写 HOME/USERPROFILE，rustup 代理因此找不到工具链，用 `GX_RUSTC` 指向工具链内的 rustc 本体 |
| 包模块聚合 | `make package-test` | Python 包单元 + 原生启动器；不安装包，不替代生命周期验收 |
| herdr 基础 PTY | `scripts/gx_probe_herdr.py --herdr … --zsh … --output …`，Windows 另传 `--msys-root` | 唯一隔离 session 的真实 Zsh 窗格、中文输出、Ctrl+C、app-local ConPTY；Windows 另用 `send-keys ctrl+c` 与 win32-input-mode 按键记录中断原生 `PING.EXE` 和 `sleep`，每例都要求 `$?` 为 130。不是 TUI attach/detach 或安装器测试 |
| 原生包生命周期 | 协调仓根 `release.yml` 的冒烟（`scripts/gx_shell_smoke_windows.ps1`、`scripts/gx_shell_smoke_linux.sh`）；独立仓库为手动 `gx-release` | 必须对真实 EXE/DEB 验证安装/升级/卸载、PATH 所有权、中文 HOME/profile、P10k/补全缓存和 TUI。协调仓中冒烟只在一次性 Windows runner 与 Ubuntu 20.04/24.04 容器里跑合并安装包（Windows 能下载到 0.1.0 时含升级），本目录的 `gx-release` 不执行；未在这些环境跑过前保持 PENDING |
| 生成物 | `make generated-check`（kb-check） | docs/kb/chunks.json 与语料一致 |

上游 CI（`main.yml`，GX 分支已原样归档到 `.github/workflows-archive/main.yml`）只有
zsh -n 且被 `if: github.repository == 'ohmyzsh/ohmyzsh'` 守卫——**fork 上不运行**
（镜像分支 `master` 推送时只留下 skipped 记录）；`make ci-check` 是本仓真实质量门。
CI 列表只含 lint/test/generated-check，未列入的层不能宣称 CI 已覆盖。
协调仓根 `.github/workflows/release.yml` 只运行其中几层：prepare job
跑 `test_gx_*.py`，`ohmyzsh-posix` job（Ubuntu 24.04，等 `shell-linux` 产出 stage 后以其中打包的
GX Zsh 为 `GX_TEST_ZSH`——包装脚本不调外部命令、保留调用方已设的 FPATH；apt 另装 zsh 与 fzf）跑
`gx_package_profile.py`、`gx_windows.py` 与
`gx_launcher.py`——系统 Zsh 5.9 的 zcompile、zf_mv 会把中文路径按 metafied 字节处理，GX 补丁修复了
这一点，用例的中文 profile 路径正依赖它；`shell-windows` job 在 Windows runner 上跑 `gx_launcher.py`；
`gx_terminal.py`、安装演练与加载 smoke 等其余层仍只在本地 `make test` 里运行。

## 执行纪律

- 测试只写 mktemp 临时目录（隔离 HOME/ZDOTDIR），不写仓库目录、custom/、真实 $HOME。
- 失败必须非零退出并保留输出；验收命令禁接吞退出码管道。
- 工具配置（.zcode/.claude/.codex）改动后必跑 `python3 tests/check_tool_configs.py`
  （已接入 `make test` 的 config-shapes 步）：Codex hooks 数组表形状、ZCode 毫秒
  timeoutMs、Claude hook 脚本引用、适配器语言一致性（.py 必须是真 Python）、
  以及按各工具配置**原样 command** 走注册入口的允许/拒绝探针（危险字面量拆分
  构造，防宿主会话被同一安全门拦截造成「无输出」假象）。
- 已实测的环境陷阱（写测试前先读）：
  - heredoc 内 `${(s:,:)var}` **不拆分**（zsh 5.8 实测，与双引号上下文不同），
    先拆成空格分隔字符串再写入 .zshrc。
  - `git init -b <分支>` 需 git ≥2.28；兼容旧 git 用 `git init` + `symbolic-ref HEAD`。
  - async prompt（zsh≥5.0.6 默认开）下 `git_prompt_info` 读异步缓存，
    非真实终端中断言渲染需 `zstyle ':omz:alpha:lib:git' async-prompt no`。
  - 环境相关插件（kubectl 等以 `$+commands[...]` 守卫）的别名在二进制缺失时
    不存在，断言要选无条件定义的符号（git:gco、docker:dbl）。
  - 单行输出下 `${${(f)"$(cmd)"}[1]}` 退化为标量取首字符（多行才是数组），
    取首行/首字段用两步 `${var%%$'\n'*}`、`${var%% *}` 截断。
  - p10k instant prompt 缓存要到第二个提示符之后才由 `zle -F` 回调写出：PTY
    驱动必须等每条命令输出空闲后再发下一条，纯 typeahead 会让会话在写出前退出。
  - PTY 会话里的标记用算术展开生成（`M$((1000+n))`），避免等待时被输入回显命中。
  - `gx/config/terminal.zsh` 的守卫是「fd 1 是 TTY 或 `$TTY` 非空」：有 pty 但 stdout
    被重定向的交互 shell（`zsh -i > out.txt`）仍会把 `\e]7;file://localhost/…` 写进捕获文件，
    文本捕获类断言要先过滤 OSC 7；`SSH_*`/`INSIDE_EMACS` 存在时模块不接管，经 ssh
    跑测试须像 `gx_terminal.py::REMOTE_ENV` 那样剥离。
  - 任何调用 `gx/install.sh` 的测试都传 `--home <mktemp>`（安装器据此忽略继承的
    `ZSH`）并把 `TMPDIR` 指进沙箱；模拟「环境 ZSH 指向别处」只能用沙箱内假树。
  - `capture_output=True` 不会移除控制终端；测试无 TTY 场景应使用
    `start_new_session=True`。不能因 stdout 是管道就断言 `$TTY` 为空。
  - `zsh -c '…'` 先解析整段脚本再执行：同一段里刚定义的别名不会展开，要经 `eval`。
  - 没有 WSL 的 Windows 开发机可在私有 MSYS2 运行时的**副本**里 `pacman -S python` 后用它跑
    `gx_windows.py`；MSYS2 的符号链接默认是复制，复制出的 exe 找不到自己的 DLL，所以
    `gx_windows.py` 的系统工具用 `exec` 包装而不是符号链接。`gx_package_profile.py` 按 Linux
    编写（`gx/bin` 是 Linux 二进制、依赖真符号链接与权限位），在 MSYS 下的失败不代表 Linux 结果。
  - WSL 的 DrvFS 目录可能固定显示 0777；compaudit 拒绝时将测试快照放入原生 Linux
    临时目录，不能关闭 compfix。Windows CRLF 工作树不能直接作为 Linux 发布资源，
    正式包从 Git blob 提取 LF；只在测试快照规范行尾，不批量重写上游文件。

## 证据与截图流程

1. `python3 scripts/dev_framework.py evidence <task>`（`make evidence` 等价于任务名
   ui）分配批次目录（gitignored，按
   `<分支>/<任务>/<时间戳-uuid>/` 隔离；dev_framework.py 校验证据根确被
   gitignore 且拒绝路径穿越）。
2. 执行操作、捕获（文本捕获为主：重定向/`script`；有 tmux 时补
   `capture-pane`）、断言关键内容。
3. **读回**：人工或 agent 实际查看捕获文件内容后才在 result.json 置
   `images_reviewed: true` 并更新 status。只保存不算通过。
4. 失败批次保留待修复对照；修复后另开批次复测，不覆盖旧批次。

runner 只清理自己批次的 `results/`；`.playwright-mcp/` 整体不入库。
