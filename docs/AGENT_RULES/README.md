# 领域规则索引

路由真源是 [routes.toml](routes.toml)；本目录的 `*.md`（README 除外）构成领域文档
闭集，与 routes.toml 声明一一对应。开始任务先跑 resolver，不要凭本表猜：

```bash
python3 scripts/resolve_agent_rules.py <本轮触及的路径...>   # 列出必读规则
python3 scripts/resolve_agent_rules.py --task review <路径>   # 审核任务
python3 scripts/resolve_agent_rules.py --check                # 路由闭集校验
```

| id | 文档 | scope |
|---|---|---|
| code-review | code-review.md | 任务 `review`（只读审核） |
| core-loader | core-loader.md | oh-my-zsh.sh、lib/*.zsh、custom/ 模板 |
| development | development.md | 框架自身：docs/、scripts/、Makefile、CHANGELOG、.github/、根门面 |
| plugins | plugins.md | plugins/**（367 插件） |
| testing | testing.md | tests/**、lib/tests/** |
| themes | themes.md | themes/**（143 主题） |
| tools-installer | tools-installer.md | tools/**、templates/** |

## 维护

- 新增顶层文件/目录、调整领域边界：改 routes.toml → 补/拆领域文档（每份 ≤16 KiB）
  → `--check` 通过 → 更新本表。
- 领域正文写不变量、源码符号与验证命令；解释"为什么"的长文放 docs/ 手册。
- 单份规则超过 16 KiB 说明该拆分领域，而不是压缩措辞。
