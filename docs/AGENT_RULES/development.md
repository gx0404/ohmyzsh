# 框架自身与仓库卫生规则（docs/、scripts/、Makefile、.github/、根门面）

适用 scope：`docs/**`、`scripts/**`、`Makefile`、`CHANGELOG.md`、`README.md`、
`CONTRIBUTING.md`、`.github/**`、`.gitignore`。本文件约束 AI 协作框架自身的维护。

## 路由与配置真源

- `docs/AGENT_RULES/routes.toml` 是路径/任务 → 领域文档的唯一机器真源；根 AGENTS.md
  的索引表只是人工预览。改路由、增删领域文档、新增顶层文件后必须运行
  `python3 scripts/resolve_agent_rules.py --check`（闭集校验：全仓 Git 可见文件
  零遗漏、零重叠、每条 pattern 至少命中一个文件）。
- `docs/dev-framework.json` 是全部开发命令的状态真源（argv 数组 + 仓库相对 cwd；
  pending/not-applicable 必须写 reason；lint 与 test 不得 N/A）。改命令先改这里，
  Makefile 只是转发层。
- resolver 依赖 Python 3.11+ 的 tomllib，或已安装的 tomli（本机 Python 3.10 +
  tomli 2.4.1 已验证）；不因检查而安装依赖。

## upstream fork 合并纪律（本仓特有硬边界）

- 框架对上游采取**只增不改**策略：所有框架文件（AGENTS.md、CLAUDE.md、docs/、
  scripts/、Makefile、.zcode/、.claude/、.codex/、.agents/、tests/、CHANGELOG.md）
  均为上游不存在的新增文件，保证 `git merge upstream/master` 干净重放。
- 唯一允许改动的上游文件是 `.gitignore`，且只在 `# --- dev-framework (fork) ---`
  标记块内追加。README.md、CONTRIBUTING.md、plugins/、lib/、tools/ 的定制需求
  先评估移到 custom/ 或新插件。
- 合并 upstream 后重跑：`make framework-check`（新上游文件可能需补路由）、
  `make ci-check`、`make kb`（语料变化）。

## 生成物

- `docs/kb/chunks.json` 是受控入库的生成物：由 `make kb`（scripts/build_agent_kb.py）
  从文档层 + 367 份插件 README + 代码结构层生成。禁止手改；语料变化后再生并审 diff；
  `make kb-check`（纳入 ci-check）校验一致性，漂移即红。
- `graphify-out/` 是本地图谱产物（gitignored），`make graph` 随时重建；
  `make graph-check` 校验指纹新鲜度。

## 提交与版本

- Conventional Commmits：`type(scope)!: subject`，scope = 插件/主题名或
  `framework`/`ci`/`docs`/`gx`（与根 AGENTS.md 一致）；breaking change 用 `!` +
  `BREAKING CHANGE:` 正文。
  tools/changelog.sh 依赖该格式。
- `CHANGELOG.md` 是 **fork 侧**版本真源（`## X.Y.Z(日期|TBD)`，version.py 取最大
  数值 SemVer）；不替代上游 `omz changelog` 的动态生成体系。上游同步类改动记
  `chore(upstream)` 条目。
- 不 `git add -A`；只 add 明确清单。没有用户要求不 commit/push，不重写历史。

## GX 原生打包与发布

- `scripts/gx_dependencies.py` + `scripts/packaging/` 锁定来源、摘要、许可和对应源码；
  缺项硬失败。实验运行时里的 HOME、keyring、缓存和私钥不能进入发行负载。
- `scripts/gx_package.py` 从干净 Git SHA 白名单读取 LF 资源；开发包显式允许 dirty
  后永远不可发布。Windows EXE 与 Ubuntu DEB 不得混入另一平台二进制。
- `scripts/gx-launcher/main.rs` 用锁定 Rust 编译，无额外 Cargo 依赖；测试编译并实际
  调用入口。原生包维护脚本不写用户 HOME，不自动 chsh，不安装新的系统依赖。
- `scripts/gx_release.py` / `gx-release.yml` 只允许手动发布到本 fork。controller 使用
  可信工作流 SHA，构建 job 只读，写 token 只交给发布步骤。不得移动 tag 或覆盖公开版。
- 公开 Release 前要求两平台同 SHA、完整资产摘要、再分发材料和真实生命周期/PTY
  证据。fixture、文件存在、编译成功、仅 `--version` 均不是安装/TUI 验收证据。
- `.iss` 模板需要真实 Inno 编译；`/O-` 只能证明模板编译，不证明安装/注册表回滚。
  真安装/卸载只在可丢弃环境，不能把宿主当前用户作为 CI fixture。

## 并行会话与探针纪律（skill 2026-09 增补）

- **写入前复查并行信号**：untracked/修改清单短间隔增长、出现新生成目录
  （graphify-out、kb、.playwright-mcp 之外的陌生产物）即可能是并行会话在推进
  同一任务；检测用 ctime（`find -newerct`）或文件清单快照，不信任 mtime
  （并行会话常以保留 mtime 的拷贝落盘）。发现并行推进**不双写**：转只读验收，
  确需收尾只做逐项声明的外科修复，交付报告列明自己改动的文件供对账。
- **门探针纪律**：hook/安全门探针必须用工具真实协议形状（Claude/ZCode 的
  `file_path` 嵌在 `tool_input` 且常为绝对路径，判定前先相对化到组件根——gx_shell 单仓
  里即 `ohmyzsh/`，由脚本自身位置推导，而非 git 顶层）；
  探针中的危险命令字面量拆分构造（`"git pu" + "sh --force"`），防止宿主会话
  挂着同一安全门把探针命令拦掉、表现为「无输出」而非探针失败。
- **注册入口复验**：探针除直调 gate 脚本外，必须按各工具配置里的原样
  command 再走一次（含适配器与解释器）；工具配置形状锁在
  `tests/check_tool_configs.py`（已接入 `make test`），改 .zcode/.claude/.codex
  配置后必跑。
- 用户转述「命令没有输出」时先按产物存在性判断是否真的执行过（权限弹窗
  卡住即此形态），不按提示文本诊断。

## 文档与代码卫生

- 上游门面（README/CONTRIBUTING/plugins/themes/lib/tools）保持英文；
  框架文档（docs/、AGENTS.md、规则）使用中文。markdown 遵循 .prettierrc
  （110 列、proseWrap always）与 .editorconfig（LF、2 空格缩进）。
- 长期文档引用用 `路径::符号`（如 `oh-my-zsh.sh::_omz_source`），不钉行号；
  审核发现可用当时行号。
- scripts/ 下框架脚本（Python）用中文注释说明约束与原因；shell 脚本头部注明
  用途与退出码语义。
- 不读取、不迁移、不硬编码凭据；.env/auth/session 类文件不入仓（.gitignore
  已挡）。PR 描述按 CONTRIBUTING.md 披露 AI 参与。
