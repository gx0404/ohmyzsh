# 开发流程

## 交付闭环（每次任务按序执行）

1. **验收点**：先明确本次改动的可观察行为与通过条件。
2. **规则**：列本轮触及路径 → `python3 scripts/resolve_agent_rules.py <paths...>`
   → 完整读返回的领域规则；审核任务加 `--task review`。
3. **实现/文档**：小步可逆修改；upstream 只增不改（唯一例外 .gitignore 标记块）。
4. **针对性检查**：`make lint`（语法层）→ `make test`（单元+smoke）；
   插件行为改动跑 `zsh tests/smoke_load.zsh --plugins <涉及插件>`。
5. **终端证据**（触及主题/渲染/CLI 交互时）：`make ui-smoke`，读回捕获文件后
   在批次 result.json 置 `images_reviewed: true`。
6. **修复复测**：失败证据批次保留；修复后另开批次。
7. **生成物/版本**：语料变了 `make kb` 再生并审 diff；`make version-check`；
   CHANGELOG.md 记已实现行为（fork 侧）。
8. **复审**：独立只读轮次（`--task review`），输出 严重/中/轻/结论。

## 日常命令速查

```bash
make help                # 全部入口与状态
make framework-check     # 路由闭集（改过规则/路由后必跑）
make ci-check            # lint + test + generated-check（fork 的真实质量门）
make ai-doctor           # 命令入口盘点（FOUND/MISSING，不安装）
python3 scripts/agent_kb.py search "关键词"   # 仓库知识检索
```

## 提交纪律

- Conventional Commits：`type(scope)!: subject`；scope = 插件/主题名或
  framework/ci/docs。breaking 用 `!` + `BREAKING CHANGE:` 正文。
- PR 描述按 CONTRIBUTING.md 披露 AI 参与程度。
- 不 `git add -A`；按文件清单 add；没有要求不 commit/push。

## upstream 同步

```bash
git fetch upstream
git merge upstream/master        # 框架文件应为纯新增，无冲突预期
make framework-check             # 新上游文件若未路由会红 → 补 routes.toml
make ci-check && make kb         # 全量复验 + 语料再生
```

冲突仅可能出现在 .gitignore（标记块内合并即可）与 fork 对上游文件的定制
（应当不存在；出现即说明违反了只增不改纪律）。
