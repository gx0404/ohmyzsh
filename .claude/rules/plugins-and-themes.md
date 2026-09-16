---
description: 插件与主题改动提醒
paths: ["plugins/**", "themes/**"]
---

触及插件/主题时先运行 `python3 scripts/resolve_agent_rules.py <本轮路径>` 并完整读取
返回的 `docs/AGENT_RULES/plugins.md` / `themes.md`（标准构成、别名五准则、全局命名
空间查重、Conventional Commits scope=插件名）。本提醒不复制领域正文。
