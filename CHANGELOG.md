# ohmyzsh fork CHANGELOG

本文件是 **fork 侧**（gx0404/ohmyzsh）的版本真源，只记录 fork 引入的已实现行为；
不替代上游 `omz changelog` 从 Conventional Commits 动态生成的体系。版本取
`## X.Y.Z(日期|TBD)` 的最大数值 SemVer（scripts/version.py 维护）。

## 0.1.0(TBD)

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
    五键（随机 `/`、上一张 `,`、下一张 `.`、选择器 `Shift+/`、专注模式 `b`）从裸
    `Alt` 挂到 leader（`Ctrl+Shift+Space`），Linux 标签直达 `Alt+1..9` 改
    `Leader 1..9`，分屏 `Alt+\` 系改 `Ctrl+Shift(+Alt)+\`；裸 `Alt+.`/`Alt+b`/
    `Alt+1..9` 归还给 readline（末参数插入、退词、digit-argument）。`Alt+w` 关闭
    pane 改 `confirm=true`，误按不再不可逆销毁运行中 agent 的 pane。与 WezTerm
    仓库 `dotfiles/wezterm-config/config/bindings.lua` 逐字节一致（该侧为同一
    迁移的并行改动）；已用已装 wezterm `--config-file ... show-keys` 验证可加载，
    `LEADER` 组与 `Alt+w confirm:true` 生效。
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
