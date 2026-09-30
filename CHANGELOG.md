# ohmyzsh fork CHANGELOG

本文件是 **fork 侧**（gx0404/ohmyzsh）的版本真源，只记录 fork 引入的已实现行为；
不替代上游 `omz changelog` 从 Conventional Commits 动态生成的体系。版本取
`## X.Y.Z(日期|TBD)` 的最大数值 SemVer（scripts/version.py 维护）。

## 0.2.0(TBD)

- 增加本机 Zsh 历史白名单导出、通用命令精选与操作习惯说明；仅保存固定命令和
  计数，支持手动导入历史检索，不复制原始参数或自动改写用户历史。
- 新增 Windows x64 EXE 与 Ubuntu amd64 DEB 构建入口、依赖及对应源码/许可锁、
  manifest 和校验值；GitHub Actions 仅手动触发，默认只构建验证，不自动公开 Release。
- 提供 `gx-zsh` 与托管 `herdr` 入口。Windows 使用私有 MSYS2，Ubuntu 使用独立
  Zsh 运行时；固定 herdr 来源包含 Windows 命名管道握手修复，不覆盖既有用户配置。
- 修复 Zsh 5.9.2 中文启动文件、进程替换、sysopen 和 zcompile 的路径编码；
  Linux 运行时通过 Ubuntu 20.04/24.04 用户态验证，保留源码补丁与构建记录。
- 将 P10k 运行副本和编译缓存移到独立 profile，修复暖缓存无 TTY 初始化及
  Windows zoxide 数据目录适配；长粘贴按长度选择逐键处理或一次字面插入。
- 安装器遇到同秒备份/中转目标碰撞时安全拒绝，不再覆盖旧备份或删除同名残留。
- 新增真实 PTY/ConPTY、中文路径、原生入口、打包、发布安全与生命周期测试。
  开发候选包已在 Windows 和 WSL Ubuntu 24.04 实际安装并通过核心 TUI 验证；
  原生包升级/卸载及完整发布验收仍未完成，不能据此宣称可正式发布。
- 知识库构建统一文本换行并处理 Git 符号链接，避免 Windows/Linux checkout 形态
  导致语料指纹漂移；同步 Make 入口、领域规则和发布/测试文档。
- 并入 `gx0404/gx_shell` 单仓：herdr 改为从同一提交的 `herdr/` 子目录构建，
  锁只声明 `monorepo_path`，revision、版本和源码归档摘要由提交推导，对应源码与
  编译输入是同一归档；herdr 以包身份编译，二进制内关闭自更新。打包脚本的脏检查与
  CHANGELOG 读取限定在本目录，herdr 构建器接受 gx_shell 的 GitHub 托管 runner。
- AI 工具安全门在单仓中按本组件根（脚本自身位置）相对化路径，注册命令指向
  `ohmyzsh/` 下的脚本；修复并入单仓后 `custom/` 等保护规则静默失效，以及 Windows
  反斜杠路径从未命中的问题，注册入口探针补充绝对路径与 Stop 钩子用例。
- herdr 探针在 Windows 上改为经 Win32（OpenProcess + K32EnumProcessModulesEx）
  直接枚举自有 herdr server 的已加载模块来证明 app-local ConPTY，不再启动
  PowerShell：托管 windows-2025 runner 上 PowerShell 冷启动超过 20 秒，导致单仓
  冒烟在该步超时。模块表刚启动时可能不完整，限时 10 秒重试；失败时报告所见模块
  或 Win32 错误。Ctrl+C 后先等新提示符出现（至多 20 秒）再输入下一条命令：MSYS2
  Zsh 处理中断时会丢弃提前到达的键入，原先该步成败取决于时序。探针自有 server
  停止后删除隔离 TMP，证据目录不再带 herdr 放入的 Codex 垫片（herdr 本体的
  硬链接、副本或符号链接，Windows 证据因此多出约 37 MB）。
  server 就绪改以 `herdr status server --json` 的 running 为准，提前退出时报错附 server.log 末 20 行。
- **破坏性变化**：Windows 私有 MSYS2 运行时改为随包提供上游的 `etc/fstab`，盘符路径由
  `/cygdrive/c/…` 变为 `/c/…`（与 Git Bash 一致），`/cygdrive` 不再存在。写在 `~/.zshrc.local`、
  脚本或历史命令里的 `/cygdrive/c/…` 要改成 `/c/…` 或 `C:/…`；GX 自带的 OSC 7 上报与 zoxide
  钩子两种写法都认。升级后第一次启动会按新路径重建一次补全缓存。
- 修复在 GX Zsh 里运行 herdr（或再启动一层 `gx-zsh`）时新窗格报
  `(anon):source:27: no such file or directory: …/powerlevel10k/internal/p10k.zsh`、提示符退化成
  `GX%`：MSYS2 把 `ZSH_CUSTOM` 等路径转成 `C:/…` 交给原生程序，`package.zsh` 又把它当成相对路径
  拼到当前目录后面。启动器现在丢弃从上一层 GX 进程继承的内部变量、按安装布局重新计算；
  `package.zsh` 把盘符/UNC 形式的 `ZSH_CUSTOM`、`POWERLEVEL9K_INSTALLATION_DIR` 转回 POSIX 路径，
  清掉混进 FPATH 的 Windows 路径碎片，补全缓存不再每次启动都重建。
- 修复运行 winget、应用商店版 pwsh/python 等「应用执行别名」后 GX Zsh 永久挂死、Ctrl+C 也无法
  恢复：私有运行时的 msys2-runtime 由 3.6.10-5 升级到修复该回归的 3.6.10-6（上游
  msys2/msys2-runtime#372）。`gx-zsh` 启动 Zsh 前还会清除从父进程继承的「忽略 Ctrl+C」标志，
  Zsh 及其前台程序不再沿用它。
- Windows 新增 PowerShell 桥接，`irm https://…/install.ps1 | iex` 这类安装命令可直接在 GX Zsh 里
  运行：`iex`/`Invoke-Expression` 与新命令 `gx-pwsh '脚本'`（或 `… | gx-pwsh`）把脚本原样写入带
  BOM 的临时 `.ps1` 交给 PowerShell 7（没有时用 5.1，`GX_POWERSHELL` 可指定），以 `param()` 开头的
  安装脚本照常可用，退出码与 `pwsh -File` 一致；`irm`/`iwr`/`Invoke-RestMethod`/`Invoke-WebRequest`
  拼成一条 PowerShell 命令，参数名以外的参数一律按字面量传递（含中文与各种单引号）。PowerShell
  里的 tar、find、sort、curl、cmd 优先用 Windows 自带版本；脚本结束后重新读取注册表 PATH，刚装好
  的命令当场可用。已有同名命令、函数或别名时不覆盖。
- 桥接的出错处理：`irm` 请求失败时返回 1，随后的 `| iex` 收到空脚本时不启动 PowerShell、提示后
  返回 1；`iwr` 没写 `-UseBasicParsing` 时自动补上（Windows PowerShell 5.1 不带它会报错或卡住），
  输出进管道时只输出正文，`iwr … | iex` 同样可用。
- Windows 上找不到命令时只给提示、从不代为执行：`Get-ChildItem` 这类 PowerShell 命令提示可原样
  复制运行的 `gx-pwsh …` 写法，`man` 提示改用 `--help`，`tmux`/`screen` 提示随附的 herdr，rg、fd、
  htop 等给出 winget 包名。另补 `open`/`xdg-open`、`pbcopy`/`pbpaste`，有 vim 没有 vi 时 `vi` 调用
  vim，运行时没有 `unzip` 时转交 `bsdunzip`。
- 启动提速：启动器把全部路径经标准输入一次交给 `cygpath`（此前每条路径各起一次进程，用户目录
  含 `'`、花括号时还会转错），`gx-zsh -f -c exit` 约 580 ms → 123 ms，`herdr --version` 等信息类
  命令不再做路径转换（571 ms → 38 ms）；配置侧省掉 `uname`、`mkdir`、`who -m` 等外部进程，fzf 与
  zoxide（Windows 上还有 `dircolors`）的初始化输出缓存到 `$ZSH_CACHE_DIR` 并 zcompile，Windows
  热启动到第一个提示符约 2.65 s → 1.87 s；herdr 补全改为打包时生成，新 profile 不再连续两次
  重建补全缓存。
- Windows 上 `cd` 不再等待 zoxide：原生 zoxide 的目录记录改为纯 zsh 换算盘符路径并放到后台，
  每次 `cd` 约 200 ms 以上 → 约 62 ms，`z`/`zi` 用法不变。
- Windows 上输入不再卡顿：zsh-autosuggestions 在 zsh ≥ 5.0.8 上默认异步取建议，每击键 fork 一个
  子 shell，MSYS2 上每次约 30 ms，整行输入时 ZLE 跟不上；MSYS/Cygwin 改为进程内同步查历史，每击键
  约 0.8 ms（zprof 实测），执行 `true` 回车到下一个提示符的中位数约 195 → 33 ms。Linux 不变。
- 私有运行时有了 `/tmp`（0.1.0 没有），指向 Windows 用户临时目录；从 GX Zsh 启动的原生程序不再
  被改写 `TEMP`/`TMP`（此前指向 profile 内的目录）。ssh、scp 等取 home 时先看 `HOME`（GX Zsh 里即
  `%USERPROFILE%`），与 Windows OpenSSH 共用 `%USERPROFILE%\.ssh` 的配置、密钥与 known_hosts，
  只有 Windows OpenSSH 认识的配置项可能在这里告警。
- 私有运行时新增 diffutils、patch、unzip、zip、tree、bc、procps-ng（top、pgrep、pkill、watch、
  free 等）、vim（含 xxd）、rsync、jq 及其依赖，附对应源码与许可再分发材料。
- WezTerm/herdr 新开的标签与分屏沿用当前目录：MSYS 上盘符目录的 OSC 7 上报改为 `file:///C:/…`
  （此前的 `/cygdrive/c/…` 原生程序用不了），运行时内部的非盘符目录不上报。
- Windows 上不再加载 `sudo` 插件（系统 sudo.exe 提升不了 MSYS 命令的权限，双击 Esc 补 sudo 的
  快捷键随之取消）；没有 `man` 时不加载 `colored-man-pages`；Windows 包模式把 `SHELL` 设为正在
  运行的 zsh，fzf 等经 `$SHELL` 起子进程的程序不再落到 cmd。
- herdr 配置改由 GX 托管：`config.toml` 里的 `# gx-shell: manages …` 标记行声明 GX 只管 `[terminal]`
  的 `default_shell` 与 `shell_mode`。0.1.0 生成的旧配置（Windows 上是 `…\runtime/msys64/…` 这种
  混合分隔符路径）在首次启动时收编一次；用户改过的配置、链接或目录形式的 `config.toml`、指向别处的
  `HERDR_CONFIG_PATH` 都保持不动，删掉标记行后不再被改回。
- 新增 `herdr --gx-set-default-shell <Shell 可执行文件的绝对路径>`：WezTerm 设置页切换默认 Shell
  时用它让 herdr 新窗格跟随，正在运行的 herdr server 随即重新加载配置（不会为此启动 server）；
  重载失败时报错并给出诊断（配置已写入），部分生效时输出警告，配置不归 GX 管时返回 3。
- 启动器的其他修正：Windows 上路径统一使用 `\`，预建补全与 zoxide 目录并直接给出 zoxide 的原生
  数据目录 `_ZO_DATA_DIR`；profile 目录校验失败时错误信息给出具体路径。
- `gx/wezterm/` 与 WezTerm GX 的 `dotfiles/wezterm-config/` 重新逐字节一致：默认 Shell 设置、
  Windows 与 Linux 统一的 `Ctrl+Shift` 键位（Windows 不再用 `Alt` 组合；关闭窗格改为
  `Ctrl+Shift+W`，仍先确认；调整窗口大小改为 `Leader -`/`Leader =`；Windows 翻页滚动改为
  `Shift+PageUp/PageDown`）、配置求值与状态栏提速，以及等比缩小的壁纸；`gx/README.md` 同步
  键位、默认 Shell、`/c/` 盘符和新附带工具的说明。
- 打包：只有 herdr 构建记录（receipt）写 `builder=github-actions` 的 stage 可以发布。设
  `GX_LOCAL_BUILD_ROOT` 可在本机完整构建 herdr（记 `builder=local`），这类 stage 恒为不可发布，
  `verify --require-release` 拒绝；Windows 目标的 herdr 与启动器编译显式使用
  `1.96.1-x86_64-pc-windows-msvc` 工具链，缺少时直接失败，不自动下载安装。
- 打包：stage 时用包内 herdr 在隔离环境生成 `_herdr` 补全（说明文字固定为 zh-CN，超时即报错），
  放进 GX 的 herdr 插件覆盖目录 `gx/omz-custom/plugins/herdr`（与上游插件只差「已有 `_herdr` 时
  不再后台生成」）；`gx/config/windows.zsh` 纳入打包资源；stage manifest 记录 MSYS2 覆盖文件，
  `verify-stage` 核对载荷与记录一致。
- 依赖工具：签名包可用 `upgrades_base` 整体替换 base 快照里的旧版本（先按 pacman 文件清单与 mtree
  摘要核对全部旧文件），依赖 manifest 记录替换、`verify-bundle` 复核；新增 MSYS2 覆盖层，GX 改过的
  包内文件（`etc/fstab`、`etc/nsswitch.conf`）钉住原/新摘要、作为对应源码随再分发材料发布，上游
  原文件变了就组装失败；再分发锁里 herdr 组件的版本必须与 herdr 实际版本一致。
- herdr 许可收集：没有自带许可文本、license 表达式又与 herdr 根 crate 相同的 workspace 成员
  （上游新增的 `crates/ghostty-vt`）沿用根目录 `LICENSE` 并在清单里记录来源；表达式不同仍拒绝。
- herdr 探针在 Windows 上新增原生 `PING.EXE`，以及 WezTerm win32-input-mode 按键记录形式的
  Ctrl+C 中断用例，每例都要求退出码 130。
- 测试：新增 `tests/gx_windows.py`，在强制 MSYS 的 Zsh 里用 PowerShell/cygpath 替身验证 Windows 层
  （接入 `make test`）；`gx_package_profile.py`、`gx_launcher.py` 覆盖本轮修复，单仓发版流程在
  Ubuntu 24.04 上运行这三组测试、在 Windows runner 上运行启动器测试（Linux 结果与两平台安装冒烟
  以该流程为准）；`check_syntax.sh` 覆盖 `gx/omz-custom/plugins` 下的覆盖插件；`test_gx_lifecycle`
  调用 PowerShell 时加 `-ExecutionPolicy Bypass`。

## 0.1.0(2026-09-21)

- PreToolUse 安全门改为只在命令位置拦截强推/`git clean -f`/历史重写：heredoc
  正文、搜索关键字、commit message 里的文本提及不再误拦；真执行（含链式、
  `bash -c` 包装、环境变量前缀、`git -C`）仍拒绝，并补成对回归探针。
- Herdr 终端协作：统一 WezTerm 前缀与 Shift 选择，按已安装 shell 提供 Windows
  启动项，使用 WSL 自动发现；补齐 zsh 幂等目录上报与隔离 PTY 回归。

0. 初始化 AI 协作开发框架（update-ai-settings skill，参考 xyz-csm/xyz-hmi3 体系）：
   根 `AGENTS.md` 启动协议 + `CLAUDE.md` 薄入口；`docs/AGENT_RULES/` 七份领域规则
   与 `routes.toml` 路由闭集（全仓 Git 可见文件零遗漏、零重叠）；
   `scripts/resolve_agent_rules.py` 按路径/任务解析必读规则（`--check` 校验）。
1. 命令面：`Makefile` + `scripts/dev_framework.py` + `docs/dev-framework.json`
   （15 命令真源）；lint=全量 zsh -n 语法检查（与上游 CI 对等）、test=单元 +
   隔离加载 smoke、generated-check=KB 一致性；graph/kb/evidence/version 门就位。
2. 测试流程：`scripts/check_syntax.sh`（语法层）、`tests/smoke_load.zsh`
   （隔离 ZDOTDIR/HOME 加载断言，支持 `--plugins` 多插件集成变体）、
   `scripts/run_tests.sh` 编排；zunit 族登记为可选层（doctor 报 MISSING 不假绿）。
3. 终端证据与截图流程：`make evidence <task>` 批次目录
   （`.playwright-mcp/<分支>/<任务>/<批次>/`，gitignored）；
   `scripts/ui_smoke.sh` 渲染默认/指定主题并断言关键段（临时 git 仓库分支名），
   文本捕获读回后置 `images_reviewed`。
4. 代码图谱：`scripts/graphify.sh` wrapper（graphify 0.9.20）索引 lib/plugins/
   themes/tools/oh-my-zsh.sh/docs，产物 `graphify-out/`（gitignored）+
   指纹 manifest，`graph-check` 校验新鲜度。
5. 知识库：`scripts/build_agent_kb.py` 三层语料（框架文档 + 367 份插件 README +
   shell 符号结构）生成受控 `docs/kb/chunks.json`；`scripts/agent_kb.py`
   BM25-lite 检索 CLI（search/stats）；`kb-check` 接入 ci-check，漂移即红。
6. 多工具执行面（shared 无凭据基线）：`.zcode/config.json`（hooks 桥接）、
   `.claude/`（settings.json 权限三段 + rules 薄提醒 + hooks 安全门/复审提醒）、
   `.codex/config.toml`（sandbox + 数组表 hooks）；`.agents/README.md`。
7. 文档：`docs/` 手册（README 索引、ARCHITECTURE、DEVELOPMENT、MAKE_COMMANDS、
   TESTING、AI_TOOLS、RELEASE）；upstream 只增不改纪律与 .gitignore 标记块。
8. 随 update-ai-settings skill 2026-09 更新增补（增量维护，脚本与资产模板未变
   无需重装）：新增 `tests/check_tool_configs.py` 形状回归锁（Codex 数组表
   hooks/Stop 无 matcher/秒制 timeout、ZCode 毫秒 timeoutMs、Claude hook 引用与
   custom/ deny 防线、.py 适配器真 Python 校验）并接入 `make test` 的
   config-shapes 步与 check_syntax.sh 的 Python ast 层；安全门探针改为按各工具
   配置原样 command 走注册入口、危险字面量拆分构造（防宿主会话同门拦截假象）；
   领域规则 development.md 增补并行会话检测（ctime/清单快照、发现并行不双写）
   与探针纪律；`check_syntax.sh` 扩展覆盖 tests/*.py 与 .codex/hooks/*.py。
9. gx 个人配置层与一键迁移：`gx/` 固化本机 zsh 配置链（zshrc/zshenv/
   zshrc.local/p10k.zsh + powerlevel10k 提交树快照 + gitstatusd v1.5.4 与
   zoxide 0.9.9 二进制 + Nerd Fonts v3.4.0 四字重 + WezTerm 配置快照）；
   `gx/install.sh` POSIX sh 双模式安装器（本地工作树离线部署 / 在线浅拉
   fork 分支；幂等、时间戳备份、`.gx-managed` 标记管理、`--uninstall` 恢复、
   `--home/--zsh` 重定向测试钩子）；`gx/bundle.sh` 离线分发打包；
   `tests/gx_install_smoke.zsh` 隔离演练（部署/加载/幂等/备份恢复/自定义
   路径）接入 `make test`；新增 gx-install/gx-bundle 命令与 gx-profile
   领域规则路由。
10. 恢复 WezTerm 配置快照的 Linux 壁纸快捷键：`Alt+.` / `Alt+,` 切换
    下一张 / 上一张，`Alt+/` 随机、`Ctrl+Alt+/` 选择、`Alt+b` 切换纯色
    专注模式；与本机及 WezTerm 仓库 `dotfiles/wezterm-config/` 同步，
    常用终端功能继续使用 `Ctrl+Shift`。
11. 安装演练清除继承的 `ZSH`、`ZSH_CUSTOM`、缓存及 `GX_HOME` 等环境变量，
    避免 `--home` 指向临时目录时仍更新当前 Shell 的 Oh My Zsh 与 gitstatus 缓存。
12. 终端 OSC 7 上报兼容 p10k instant prompt：`gx/config/terminal.zsh` 守卫改以
    `$TTY` 判定（instant prompt 重定向 fd 1 后 `-t 1` 恒假，模块此前在部署形态
    下从未安装）；主机名字段留空输出 `file:///<cwd>`（herdr 只接受空或
    localhost）；接管后摘掉上游 `omz_termsupport_cwd`，同一提示符不再双发
    （摘钩子在重复 source 守卫之前，`source ~/.zshrc` 后不回归）；ssh / emacs
    会话（`SSH_CONNECTION`/`SSH_CLIENT`/`SSH_TTY`/`INSIDE_EMACS`）不接管，与上游
    一致，避免远端 cwd 被当成本地目录。
13. fzf 选项按版本探测拼装：`gx/config/zshrc` 用 `is-at-least 0.24` 判定
    `fzf --version` 首字段后才追加 `--border=rounded/--pointer/--marker`
    （Ubuntu 20.04 的 0.20.0 退化为 `--border`，此前所有 fzf 入口启动即退出）；
    fzf 缺失时不导出；首字段不是 `<数字>.<数字>` 形态（包装脚本打印
    `fzf 0.20.0`、`v0.44.1`）时退化为老选项，不把未知当新版；
    `FZF_DEFAULT_COMMAND` 依次优先 fd/fdfind/rg --files。
14. 重装保留 custom 层：`gx/install.sh::deploy_omz_repo` 先把新快照解包到
    `$ZSH.gx-new-<ts>`，用 `merge_custom_layer` 把旧 `$ZSH/custom` 合并进新树
    （同名以用户为准；`custom` 是符号链接时整体复刻、不展开成拷贝），再两次
    rename 原子替换，旧树随后删除——任何失败都在旧安装原样在位时中止，没有
    暂存回填的中间态；此前重装会静默抹掉用户自装插件。`cleanup_zcompdump`
    明确覆盖无后缀 `.zcompdump`；smoke 幂等场景补 custom 保全、同名以用户为准、
    符号链接保留、上级不可写中止与 compdump 清理断言。
15. `gx/config/zshenv` 首行 `skip_global_compinit=1`：跳过 Ubuntu `/etc/zsh/zshrc`
    在 `~/.zshrc` 之前额外执行的全局 compinit（双 compinit/compaudit 与多一份无
    后缀 `.zcompdump`）；smoke 与部署链路测试断言交互加载后只存在
    `.zcompdump-<host>-<ver>` 一族。
16. 真实链路测试类：`tests/gx_terminal.py` 新增 DeployedInteractive——install.sh
    落地 mktemp HOME 后用真 PTY 起 `zsh -i`（不加 `-f`），预热一次让 p10k 写出
    instant prompt 缓存，再断言 precmd 链含 `_gx_terminal_report_cwd`、不含
    `omz_termsupport_cwd`、一次 cd 只发一条 `file:///` OSC 7、`HERDR_ENV=1`
    与无宿主身份两种守卫形态、FZF_DEFAULT_OPTS 与宿主 fzf 版本匹配且
    `fzf --filter` 可用；缺 zsh/sh/PTY 或缓存未生成即失败不 skip。
17. 安装器 `--home` 与环境 `ZSH` 互锁：`--home` 显式给出时忽略继承的 `ZSH`
    （gx 会话 `export ZSH=~/.oh-my-zsh`，此前隔离演练会把重装打到真实目录）；
    环境 `ZSH` 不在部署 home 之下且未传 `--zsh` 时 unattended 以退出码 1 拒绝、
    交互须确认；启动时提示上次中断残留（`.gx-new-*`/`.gx-old-*`/`.gx-custom.*`）；
    `--home` 重定向时 fc-cache 缓存落在部署 HOME。smoke 场景 G/H 与
    `gx_terminal.py::InstallerZshInterlock` 用沙箱内假树验证，测试不再依赖
    `unset ZSH` 掩盖。
18. autosuggestions 一次绑定：`gx/config/zshrc` 设 `ZSH_AUTOSUGGEST_MANUAL_REBIND=1`，
    插件仍在首个 precmd 统一包裹全部 widget（含 zshrc 后半段的 `zle -N` 与
    `.zshrc.local`），只去掉此后每个提示符的整体重绑；部署 HOME 真 PTY 原位实测
    precmd 链 5.57 ms → 0.06 ms/提示符（§3 循环法 6.69 → 0.94 ms）。加载块位置
    不变（实测下移对包裹无增益）。DeployedInteractive 断言首个提示符后
    `_zsh_autosuggest_start` 已离开 `precmd_functions`、三个自定义 widget 均以
    `_zsh_autosuggest_bound_` 包裹、输入历史前缀仍弹出灰色建议。
19. 长命令行可编辑：`gx/config/zshrc` 设 `ZSH_HIGHLIGHT_MAXLENGTH=512` 与
    `ZSH_AUTOSUGGEST_BUFFER_MAX_SIZE=512`，超过该长度不再重新解析语法、不再取历史
    建议（有意的降级）。4401 字符粘贴行在部署 HOME 真 PTY 里 20 键取中位，四种组合
    实测：都不设 25.5 ms、只设建议上限 24.5 ms（≈无效）、只设高亮上限 1.0 ms、两者
    同设 0.65 ms —— `ZSH_HIGHLIGHT_MAXLENGTH` 是主因（粘贴首帧从「40 s 内仍未静默」
    降到 1.5 s），建议上限是补足项；1.5 s 首帧由逐字节回显主导，与建议上限无关。
    越界后的形态是「高亮停在越界前那一帧」而非失去颜色：z-sy-h 在 `region_highlight=()`
    之前就 return，旧区间随编辑平移，颜色可能与实际语法不符（灰色建议则确实消失）。
    DeployedInteractive 用括号粘贴投入 4401 字符行再 20 次单键，断言两个变量在
    部署形态非空、输出 10 s 内静默、每击键中位 <5 ms；另加一条断言钉住「越界不再
    重新解析」与去掉高亮上限后的对照。
20. 安装器按源快照指纹决定是否保留 zcompdump：`gx/install.sh::cleanup_zcompdump`
    始终清无后缀 `.zcompdump` 与其他主机名/zsh 版本的 `.zcompdump-*`（含 omz
    zrecompile 残留的 `.lock` 锁**目录**，清理循环对目录与失败都容错，不再可能以
    `set -eu` 打断安装器）；当前 `<host>-<ver>{,.zwc,.lock}` 一族只在本次源快照指纹
    与上次部署相同时保留。指纹是部署用中转 tar 的 CRC + 字节数，由
    `deploy_omz_repo` 写进 `$ZSH/.gx-managed` 的 `snapshot:` 行 —— 不能靠 omz 自己
    兜底：它的判据只有 `#omz fpath:`（fpath 目录集）与 compinit 的「补全文件总数 +
    zsh 版本」，已存在补全文件的内容/`#compdef` 标签改动检不出，而 `#omz revision:`
    在本安装器排除了 `./.git` 的快照部署下恒为空（真实 HOME 的 dump 首行即
    `#omz revision: ` 空值）。未改动的重装仍省下约 121 ms：隔离部署 HOME 内 20 轮
    「重装 → 首启 → 二启」中位 369.5 ms → 248.3 ms，二启 33.9 → 34.0 ms 不变，稳定
    启动 33.3 ms；剩余 215 ms 是 p10k 重编自身 `.zwc`，与 dump 无关。指纹变化时首启
    回到全新安装的 372.8 ms（该重建是有意的正确性代价）。
21. 安装器备份回收：新增 `gx/install.sh::list_backups`/`prune_backups`，
    `deploy_configs`、`replace_dir`（wezterm）与 `$ZSH` 备份按 `GX_KEEP_BACKUPS`
    （默认 2，须 ≥1，`all` 关闭回收）保留最新几份，只认 `.pre-gx-<14 位时间戳>`
    后缀（用户手工改名的备份不碰），回收失败只告警不中止。**时间戳最小的「第一代」
    永久保留**：它是唯一一份 gx 之前用户自己的配置，后面每份都是 gx 部署物被改过的
    派生物，而 `--uninstall` 只恢复最新一份，删掉第一代就永久失去「回到 gx 之前」的
    能力（真实 HOME 的 `.zshrc.pre-gx-20260916135406` 即那一份）。两个例外：`$ZSH`
    整树因体积固定「第一代 + 1 份」，`$ZSH/custom/themes/powerlevel10k` 在用户运行
    时层里不回收（`replace_dir` 新增 keep 参数，`deploy_p10k` 传 `all`）。
    `--uninstall` 按时间戳后缀（不再靠 mv 保留的旧 mtime）恢复最新一份，其余留
    「第一代 + N-1 份」。此前「改过配置再重装」每次 +1 且永不回收（真实 HOME 已累积
    6 份）。smoke 场景 B 断言当前 dump 与其 `.lock` 保留、下次启动 mtime 不变、篡改
    `#omz fpath:` 后 omz 仍会重建、异版本 `.lock` 目录被清掉且安装器仍打印摘要、
    篡改 `snapshot:` 指纹后当前 dump 被清；场景 J 覆盖回收上界、第一代在多轮重装与
    两种 `--uninstall` 之后仍在、`all` 不回收、`GX_KEEP_BACKUPS=0` 拒绝。
22. WezTerm 键位迁入 leader 层（GX-10）：`gx/wezterm/config/bindings.lua` 的壁纸
    五键（随机 `/`、上一张 `,`、下一张 `.`、选择器 `i`、专注模式 `b`）从裸
    `Alt` 挂到 leader（`Ctrl+Shift+Space`），Linux 标签直达 `Alt+1..9` 改
    `Leader 1..9`，分屏 `Alt+\` 系改 `Ctrl+Shift(+Alt)+\`；裸 `Alt+.`/`Alt+b`/
    `Alt+1..9` 归还给 readline（末参数插入、退词、digit-argument）。`Alt+w` 关闭
    pane 改 `confirm=true`，误按不再不可逆销毁运行中 agent 的 pane。选择器不用
    `Leader Shift+/`：X11 会把 Shift+/ 解成 `?`、用户绑定没有 shifted 变体合成
    （上游 #1906），物理不可达。同文件回灌 wezterm 批 8 新增的浮层入口
    `Leader k/m/s`（键位速查/主菜单/设置，herdr 抓鼠标时键盘仍可达）。与 WezTerm
    仓库 `dotfiles/wezterm-config/config/bindings.lua` 逐字节一致（含其未提交的
    Leader i 改动）；已用已装 wezterm `--config-file ... show-keys` 验证可加载
    （rc=0），新键位在册、无重复绑定。
23. `~/.zshrc` 归 gx 层真源 + zshrc.local 不再强制部署（GX-14）：wezterm 安装器
    历史追加的 `# >>> wezterm-gx >>>` cursor-mode 键位块（up/down-line-or-beginning-
    search 双光标模式绑定）在 `gx/config/zshrc` 中前移到规范位置——全部
    `zle -N`/bindkey（含 fzf 源内绑定）之后、autosuggestions 与 syntax-highlighting
    source 之前；`install.sh::deploy_configs` 检测到历史标记块时打印剥离提示
    （.zshrc 本就备份+整体替换，原块留在 .pre-gx 备份可回查）。`zshrc.local`
    移出部署对：CUDA/SDK 等机器差异路径属单机所有，换机不再带走；目标机已有同名
    文件原样保留、不再备份覆盖，缺失由 zshrc 的 `[[ -r ... ]]` 守卫静默跳过。
    `tests/gx_terminal.py` 新增 WeztermLegacyBlock 类（预置标记块部署后断言剥离、
    备份忠实、真 PTY 三键位输出正确）与 DeployedZshrc 三条（zshrc.local 缺席、
    source 顺序、zstyle/widget 生效）；smoke 场景 A 翻转缺席断言、场景 B 预置
    标记块与机器差异文件断言剥离与保留。
24. 非 tty 交互调用关闭 gitstatus（GX-15）：`gx/config/zshrc` 在加载 omz 前对
    `$TTY` 为空的 shell（agent 工具的 `zsh -i -c` 形态）设
    `POWERLEVEL9K_DISABLE_GITSTATUS=true`——这种形态永远画不出提示符，不再白拉起
    gitstatusd 守护进程，启动失败时也不会把 `gitstatus failed to initialize` 横幅
    打进工具输出（横幅触发点：`gitstatus.plugin.zsh` `gitstatus_start` 失败的
    无守卫兜底打印；真 PTY 形态不变）。DeployedZshrc 断言非 tty 下开关置位、
    无守护进程 PID、stderr 全静默；DeployedInteractive 断言真 PTY 里守护进程
    照常拉起。
25. atuin 段与现实对齐（GX-16）：本机未装 atuin，`path` 列表不再加不存在的
    `$HOME/.atuin/bin`；注释改述真实归属——Ctrl+R 由 fzf key-bindings 的
    fzf-history-widget 提供，atuin 段保留 `$+commands` 存在性守卫（装了的机器仍由
    atuin 接管、`--disable-up-arrow` 不动上下键），经官方脚本装到 ~/.atuin/bin 的
    机器把 PATH 与 init 放 `~/.zshrc.local` 机器差异层。DeployedZshrc 断言 path
    列表无该条目（洗 PATH 重跑排除宿主继承干扰）、`^R` 实绑 fzf-history-widget、
    守卫健在。
26. 每提示符光标形状复位（GX-17）：`gx/config/terminal.zsh` 新增
    `_gx_terminal_reset_cursor` precmd 钩子，每提示符发 `\e[0 q`（DECSCUSR 0 =
    终端默认形状）——TUI（vim、herdr 等）改光标后异常退出不再把 bar/beam 遗留给
    shell。与 OSC 7 同守卫（仅交互终端、WezTerm/herdr、非远端）；cwd 缓存早退
    不影响复位（独立钩子）；成本一次 builtin printf、无 fork。测试：模块级断言
    发射恰好一次、重复 source 不重复挂钩、守卫拒绝时不注册；真 PTY 断言遗留
    beam 后连续两个提示符各复位一次。
27. `^B` 替代绑定（GX-20）：herdr 默认 prefix 是 ctrl+b，pane 内 zsh 的 `^B`
    （backward-char）需双击 prefix 透传（ctrl+b ctrl+b；help 默认在 `prefix+?`）。
    `gx/config/zshrc` 补绑 `Alt+Ctrl+B` → backward-char 作单键直达（zsh
    emacs/viins 默认空闲、WezTerm GX-10 迁移后无 Alt+Ctrl+B、herdr 默认键无
    ctrl+alt+b，三侧零冲突），并在注释说明来龙去脉（逐字符左移也可用左方向键）。
    DeployedZshrc 断言两 keymap 的 `^[^B` 与 emacs `^B` 均绑到 backward-char。
28. OSC 133 语义标记核验收口（WEZ-UX-02 zsh 侧）：核验证实 gx 守卫
    （`TERM_PROGRAM=WezTerm` 或 `HERDR_ENV=1`）下 p10k 的
    `POWERLEVEL9K_TERM_SHELL_INTEGRATION` 已发全 133 A/B/C/D——zsh 侧无需叠加
    第二套 PS1 包装（双发会让终端看到重复标记），配置改动驳回；herdr 上送宿主由
    herdr 轨道负责。DeployedInteractive 钉回归：两种守卫环境四标记齐全且开关
    置位，守卫外（未知终端）不发 C/D。
29. 同步点 1 回灌 wezterm 轨 C 全部 Lua 变更：`gx/wezterm/` 与 wezterm 仓
    `dotfiles/wezterm-config/` 恢复逐字节一致（`diff -rq` 为空）。内容：
    `config/bindings.lua`——WEZ-CFG-04 Shift+PageUp/Down 在 alt-screen 应用
    （herdr/vim/Claude Code）里透传 `\x1b[5;2~`/`\x1b[6;2~` 而非宿主静默空滚；
    `Leader w` 壁纸管理浮层入口（批 13）；WEZ-CFG-03 插件缺失时
    workspace_switcher/resurrect 键位降级 Nop。`config/general.lua` 补
    `language='zh-CN'`（GX-11 闭环，WEZTERM_LANG 优先）。`config/plugins.lua`
    pcall 兜底并删死 stub。`utils/backdrops.lua` glob 加 pcall、空目录纯色回退、
    新增 `set_default_from_sidecar()`（`wezterm.lua` 链上随调）。`events/
    right-status.lua` 无电池早退与窗口表回收。删除死模块 `events/left-status.lua`
    与 `utils/gpu-adapter.lua`（与轨 C 同步；WEZ-HYG-01 快照卫生）。验证：wezterm
    仓 `target/debug/wezterm`（20260921 构建，含 ShowWallpaperOverlay）
    `--config-file gx/wezterm/wezterm.lua show-keys` rc=0，20 个 LEADER 键在册
    含 `Leader w`；注意已装二进制（20260920）尚无该 action，用它验证会静默回退
    默认键表——本仓镜像的加载验证以 wezterm 仓构建为准。
