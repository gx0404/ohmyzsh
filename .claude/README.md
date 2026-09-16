# .claude/ 目录角色

| 条目 | 角色 | Git |
|---|---|---|
| settings.json | 权限三段（allow/ask/deny）+ PreToolUse/Stop hooks | 入仓 |
| hooks/pretooluse-safety-gate.sh | 安全门策略真源（Claude/ZCode/Codex 共用）：拒绝写 custom/cache/log/.git 与历史重写命令 | 入仓 |
| hooks/notify_review.sh | Stop 复审提醒（不阻断） | 入仓 |
| rules/*.md | 带 `paths:` 的薄路由提醒：只提醒执行同一 resolver，不复制领域正文 | 入仓 |
| 其余（会话、缓存、个人设置） | 本机状态，不是项目规则真源 | 忽略 |

规则加载协议见根 `AGENTS.md`；配置差异手册见 `docs/AI_TOOLS.md`。
