# .codex/ 目录角色

| 条目 | 角色 | Git |
|---|---|---|
| config.toml | approval/sandbox、`project_doc_max_bytes`、数组表 hooks、环境变量排除 | 入仓 |
| hooks/pre_tool_use_policy.py | 协议桥接：透传 stdin 到 `.claude/hooks/pretooluse-safety-gate.sh`（策略真源共用） | 入仓 |
| hooks/stop_review_signal.py | Stop 复审提醒桥接 | 入仓 |
| 其余（state、会话） | 本机状态 | 忽略 |

Codex 只读根 `AGENTS.md`；`project_doc_max_bytes = 32768` 防常驻规则膨胀。
规则加载协议与验收记录见 `docs/AI_TOOLS.md`。
