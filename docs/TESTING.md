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
| gx 模块单元 | `python3 tests/gx_terminal.py`（TerminalIntegration，make test 的 gx-terminal 步） | `zsh -f -i` + PTY 只加载 terminal.zsh：守卫（含 fd 重定向）、编码/缓存、上游钩子替换 |
| gx 真实链路 | 同上（DeployedZshrc / DeployedInteractive） | install.sh 落地 mktemp HOME 后走真实 .zshenv/.zshrc（不加 -f）：fzf 版本分支、skip_global_compinit；真 PTY 起 `zsh -i` 覆盖 p10k instant prompt 形态下的 precmd 链、一次 cd 一条 `file:///` OSC 7、HERDR_ENV/TERM_PROGRAM 守卫、autosuggestions 首个提示符后不再重绑且后定义 widget 已包裹、灰色建议可见、4401 字符粘贴行每击键中位 <5 ms（高亮/建议长度上限生效）。缺 zsh/sh/PTY 或 instant prompt 缓存未生成即失败，不 skip |
| gx 安装演练 | `zsh tests/gx_install_smoke.zsh`（make test 的 gx-install-smoke 步） | 隔离 HOME 部署/加载/幂等重装（custom 层保全、同名以用户为准、符号链接 custom 原样保留、只清无后缀与异主机/版本 compdump（含残留 `.lock` 目录）而当前一族保留且下次启动不重建、快照指纹变化时连当前 dump 一起清、无中转残留）/备份恢复/`.pre-gx-*` 按 `GX_KEEP_BACKUPS` 留「第一代 + 最新 N 份」、uninstall 后留「第一代 + N-1 份」、`all` 不回收、非法份数拒绝/自定义 ZSH 路径/`--home` 忽略环境 ZSH、环境 ZSH 越界 unattended 拒绝/上级不可写时中止且旧树不变。TMPDIR 与 fontconfig 缓存都落在沙箱 |
| 生成物 | `make generated-check`（kb-check） | docs/kb/chunks.json 与语料一致 |

上游 CI（.github/workflows/main.yml）只有 zsh -n 且被
`if: github.repository == 'ohmyzsh/ohmyzsh'` 守卫——**fork 上不运行**；
`make ci-check` 是本仓真实质量门。CI 列表只含 lint/test/generated-check，
未列入的层不能宣称 CI 已覆盖。

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
    被重定向的交互 shell（`zsh -i > out.txt`）仍会把 `\e]7;file:///…` 写进捕获文件，
    文本捕获类断言要先过滤 OSC 7；`SSH_*`/`INSIDE_EMACS` 存在时模块不接管，经 ssh
    跑测试须像 `gx_terminal.py::REMOTE_ENV` 那样剥离。
  - 任何调用 `gx/install.sh` 的测试都传 `--home <mktemp>`（安装器据此忽略继承的
    `ZSH`）并把 `TMPDIR` 指进沙箱；模拟「环境 ZSH 指向别处」只能用沙箱内假树。

## 证据与截图流程

1. `make evidence <task>` 分配批次目录（gitignored，按
   `<分支>/<任务>/<时间戳-uuid>/` 隔离；dev_framework.py 校验证据根确被
   gitignore 且拒绝路径穿越）。
2. 执行操作、捕获（文本捕获为主：重定向/`script`；有 tmux 时补
   `capture-pane`）、断言关键内容。
3. **读回**：人工或 agent 实际查看捕获文件内容后才在 result.json 置
   `images_reviewed: true` 并更新 status。只保存不算通过。
4. 失败批次保留待修复对照；修复后另开批次复测，不覆盖旧批次。

runner 只清理自己批次的 `results/`；`.playwright-mcp/` 整体不入库。
