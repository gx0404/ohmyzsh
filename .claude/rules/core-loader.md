---
description: 核心加载器与 lib 库改动提醒
paths: ["lib/**", "oh-my-zsh.sh", "custom/**"]
---

触及加载器/lib 时先运行 `python3 scripts/resolve_agent_rules.py <本轮路径>` 并完整
读取返回的 `docs/AGENT_RULES/core-loader.md`（加载顺序不可重排、custom 覆盖机制、
compinit/compfix、`GIT_OPTIONAL_LOCKS`）。本提醒不复制领域正文。
