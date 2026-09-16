# .zcode/ 目录角色（ZCode）

- `config.json`：只挂 hooks——PreToolUse 复用 `.claude/hooks/pretooluse-safety-gate.sh`
  （策略真源共用，协议各自适配），Stop 复用 `notify_review.sh`。超时单位是毫秒
  `timeoutMs`，不能粘贴其他客户端的秒值。
- ZCode 只读根 `AGENTS.md` 启动协议，不展开 `CLAUDE.md`；领域规则按
  `python3 scripts/resolve_agent_rules.py <路径>` 显式加载。
- 会话 plan、临时态、认证不入仓；本目录白名单外文件全部 Git 忽略。
