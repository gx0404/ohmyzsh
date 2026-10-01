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

## 构建边界

所有编译、构建、打包与项目专用工具链环境只写 `.build/`（gitignored）——工作
目录、缓存、输出与解包产物不得散到项目外；本地 herdr 构建的
`GX_LOCAL_BUILD_ROOT` 指向 `.build/` 子目录。测试与 smoke 的临时数据同样落
`.build/tmp/`（run_tests/check_syntax/dev_shell/ui_smoke 已默认重定向
`TMPDIR`/`TEMP`/`TMP`），不留项目外残留。

Windows 本机补齐 POSIX 测试层用项目内 MSYS2 宿主（bash/python3/zsh/git 同根，
不装系统级 MSYS2/WSL）：

```bash
# 一次性搭建：msys2-base sfx 解压到 .build/msys64 → 首次 bash -l 初始化 →
# pacman -S git diffutils mingw-w64-ucrt-x86_64-fzf
./.build/msys64/usr/bin/bash -lc 'cd <仓库 POSIX 路径> && bash scripts/run_tests.sh'
```

外层 Git Bash 只跑 `zsh -n` 语法层时，把 `.build/msys64/usr/bin` 追加到 PATH
**末尾**即可（前置会遮蔽 Git 自带 cygpath 等，曾导致探针误报）。

经验边界（msys 宿主 ≠ 真 Linux）：本机 msys 宿主稳定覆盖 syntax / unit-cli /
config-shapes / smoke 与 `test_gx_*` 打包单元；gx 的 Linux 部署套件
（gx-terminal Deployed* / Wezterm、gx-install-smoke、gx-package-profile）及
DrvFS 无 POSIX 符号链接、真 cygpath 干扰 shim 用例等差异，仍以真 Linux 宿主
（协调仓 CI 或 WSL）为准。

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
