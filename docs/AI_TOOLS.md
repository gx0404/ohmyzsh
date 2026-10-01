# AI 工具配置（ZCode / Claude Code / Codex）

共享策略 **shared**：三工具的项目配置以无凭据基线入库（.gitignore 白名单外
全部本机）；模型、provider、认证归用户级配置，不入仓。规则真源单一：根
`AGENTS.md` + `docs/AGENT_RULES/routes.toml` + `scripts/resolve_agent_rules.py`，
工具目录只做协议适配，不复制领域正文。Kimi Code 未使用，不建目录。

## 各工具配置面

| 面 | ZCode | Claude Code | Codex |
|---|---|---|---|
| 入口 | 根 AGENTS.md（ZCode 不展开 CLAUDE.md） | CLAUDE.md（首行 `@AGENTS.md` 薄入口） | 根 AGENTS.md（`project_doc_max_bytes=32768`） |
| 项目配置 | .zcode/config.json | .claude/settings.json | .codex/config.toml |
| 路由提醒 | —（按 AGENTS.md 协议手动 resolver） | .claude/rules/*.md（带 paths 的薄提醒） | — |
| hooks | PreToolUse→安全门（毫秒 timeoutMs）；Stop→复审提醒 | 同左（秒 timeout） | 数组表 `[[hooks.PreToolUse]]` 桥接同一安全门（Python 透传） |
| 权限 | — | allow/ask/deny 三段（deny：强推、clean、写 custom/、写 cache/、写 .git/） | approval=never、sandbox=danger-full-access（2026-09 用户授权放开，破坏性操作仍由安全门真源拦截）；环境变量排除 *KEY*/*SECRET*/*TOKEN*/*PASSWORD* |

安全门策略真源：`.claude/hooks/pretooluse-safety-gate.sh`（拒绝写
custom/cache/log/.git 与历史重写命令；stdin JSON 宽容提取，绝对路径相对化后
判定）。三工具各自协议适配后指向它。

## 验证状态（2026-09-16 初始化会话；同日随 skill 更新增补形状锁）

| 验证项 | 状态 | 证据 |
|---|---|---|
| 配置文件可解析（JSON/TOML） | PASS | audit_ai_settings 0 ERROR |
| hook 脚本语法（bash -n / ast.parse） | PASS | check_syntax.sh 覆盖；audit 复核 |
| 配置形状回归锁 | PASS | tests/check_tool_configs.py 全过（Codex 数组表 hooks、Stop 无 matcher、秒制 timeout；Zcode enabled+毫秒 timeoutMs；Claude hook 引用与 custom/ deny 防线；.py 适配器 ast 可解析；命令位置/文本提及区分；组件根相对化） |
| 注册入口原样探针 | PASS | 按各工具配置里的原样 command 走 bash -c 执行（含 git rev-parse 与适配器），危险写入拒（exit 2）/合法写入放行（exit 0）双向 |
| resolver 规则加载（真实 scope 演练） | PASS | lib/git.zsh + plugins/docker + themes/agnoster --task review → 4 份规则正确返回 |
| ZCode hooks 实际触发 | PENDING | 需新会话实际写文件观察（本会话无法自证） |
| Claude Code / Codex 会话加载与调用 | PENDING | 未在本会话运行这两个客户端 |
| 模型读图（终端截图解读） | PENDING | tmux 未装；文本捕获已覆盖断言 |

PENDING 项不冒充 PASS；后续会话补验后更新本表。Codex 配置解析的真实 CLI 启动
验证（`codex --strict-config --version`）待目标机有 CLI 时补做，记入上表增行。

## 新会话自检清单

1. `make framework-check` 通过（规则闭集未被破坏）。
2. 触及路径跑 resolver 并完整读返回文档。
3. 工具 hooks 生效性：尝试写 `custom/tmp` 应被拒（安全门 exit 2）。
4. `make ai-doctor` 确认命令入口齐备。
