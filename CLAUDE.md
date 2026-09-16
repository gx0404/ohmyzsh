@AGENTS.md

# Claude Code 项目入口

根 `AGENTS.md` 是跨工具启动协议。开始工作前按实际触及路径运行：

```bash
python3 scripts/resolve_agent_rules.py <paths...>
```

完整读取 resolver 返回的 `docs/AGENT_RULES/*.md`；审核追加 `--task review`，scope
扩大后重新解析并读取规则并集。

`.claude/rules/` 只放带 `paths:` 的薄路由提醒（提醒执行同一 resolver，不复制领域
正文）。`.claude/` 整体 Git 忽略，白名单（settings.json、hooks/、rules/、README.md）
之外的本机状态不是项目规则真源。

架构、测试、命令与 AI 工具说明分别见 `docs/ARCHITECTURE.md`、`docs/TESTING.md`、
`docs/MAKE_COMMANDS.md`、`docs/AI_TOOLS.md`。
