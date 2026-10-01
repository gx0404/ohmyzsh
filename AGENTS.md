# ohmyzsh Agent 规则（fork：gx0404/ohmyzsh）

本仓库是 Oh My Zsh（纯 Zsh 框架：`oh-my-zsh.sh` 入口 + `lib/` 核心库 + 367 插件 +
143 主题 + `tools/` 安装运维脚本）的 fork；`upstream` 指向 ohmyzsh/ohmyzsh。
框架文件（本文件、docs/、scripts/、Makefile、.zcode/ 等）全部为 fork 新增，
上游不存在——这是 upstream 合并冲突面最小的保证。

## 规则加载协议

先列本轮将读取、修改、评审的相对路径，再运行：

```bash
python3 scripts/resolve_agent_rules.py <paths...>
```

完整阅读输出的全部领域规则；审核追加 `--task review`。scope 扩大后用完整新集合
重算。领域正文与路由在 docs/AGENT_RULES（routes.toml 是唯一机器真源），不在工具
目录复制，不依赖隐式 import。根与领域规则各不超过 16 KiB；禁止新增嵌套 AGENTS.md。
resolver 需 Python 3.11+ 或已装 tomli；不为检查安装依赖。

## 语言与协作

- 沟通、框架文档（docs/、规则）使用中文；变量/函数名与上游代码注释保持英文。
- 复杂任务有可验证计划；保留用户改动，小范围可逆修改；只对显著影响结果的歧义提问。
- 先诊断并安全修复失败；相同阻塞连续三次后说明证据与缺失条件。
- 没有要求不 commit/push，不重写历史；commit 标题 ≤72 字符、正文每行 ≤80 字符。

## 高风险与隐私

- 不删除/覆盖用户数据，不碰真实 `$HOME`（测试用 mktemp 隔离），不写 `custom/`
  （用户运行时层）、`cache/`、`log/`。
- 不读取、输出、迁移或硬编码 auth、密钥与生产凭据；认证经环境变量名或安全存储引用。
- tools/*.sh 会被 `curl | sh` 执行：任何改动按安全敏感处理。
- commit/PR/文档不写 AI 私人会话链接或身份 footer；PR 按 CONTRIBUTING.md 披露
  AI 参与程度。

## 项目模型

- 加载：`tools/check_for_upgrade.sh` → 插件 fpath 预注册 → `compinit`（compfix
  安全模式）→ `lib/*.zsh`（字典序）→ `$plugins` → `custom/*.zsh` → 主题；
  `_omz_source` 实现 `$ZSH_CUSTOM` 覆盖 `$ZSH` 的优先级。
- git 提示符统一走 `lib/git.zsh`（`GIT_OPTIONAL_LOCKS=0`）；`omz` CLI 在 `lib/cli.zsh`。
- GX 原生包在 `scripts/gx_package.py` / `scripts/packaging/`，原生入口在
  `scripts/gx-launcher/main.rs`，包配置在 `gx/config/package.zsh`；Windows 使用私有
  MSYS2，Ubuntu 使用 DEB。当前完整包验收未完成，状态与边界见 `docs/RELEASE.md`。
- `make package-test` 验证打包单元及原生启动器（需 Rust）；`make package` 读取显式
  `GX_DEPENDENCY_BUNDLE` 离线构建，不自动安装或发布。`gx-release` 仅手动触发，
  只允许发布到本 fork；源码、许可、中文配置和真实生命周期证据缺项即失败。
- 本 fork 在独立默认分支 `feature/gx_ohmyzsh` 维护；herdr 的来源为
  `gx0404/herdr` 默认分支 `feature/gx_herdr` 上的完整提交与校验过的 GitHub 源码归档。
  三仓 SHA 独立，禁止再解析 `monorepo_path` 或复用旧提交的构建回执。协调仓
  `gx0404/gx_shell` 的 `release.yml` 消费 `gx_package.py stage` 生成合并安装包。
  补充许可文本按 `.gitattributes` 保留原始字节，不能让 checkout 换行转换改变锁定摘要。
- 架构细节见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)；命令见
  [docs/MAKE_COMMANDS.md](docs/MAKE_COMMANDS.md)。
- 质量门：上游 CI 在 fork 上不运行（repository 守卫），本地 `make ci-check` 是
  真源（zsh -n 全量语法 + 加载 smoke + KB 一致性）。

## 常用命令

```bash
make help               # 全部入口
make framework-check    # 路由闭集校验（resolver --check）
make framework-ready    # 命令配置完整门
make ci-check           # lint + test + generated-check
make test               # 单元 + 隔离加载 smoke
make graph / kb         # 重建代码图谱 / 知识库（chunks.json 受控生成物）
make evidence <task>    # 分配 .playwright-mcp/<分支>/<任务>/<批次>/ 证据目录
```

## 跨域硬边界

- **upstream 只增不改**：框架文件全部新增；唯一可改的上游文件是 `.gitignore`
  （仅标记块内追加）。合并 upstream 后重跑 framework-check / ci-check / kb。
- **Conventional Commits**：`type(scope)!: subject`，scope = 插件/主题名或
  framework/ci/docs/gx；tools/changelog.sh 依赖该格式。
- **全局命名空间**：别名/函数先与全仓查重（367 插件共享一个命名空间）。
- **生成物**：`docs/kb/chunks.json` 只由 `make kb` 再生（kb-check 守门）；
  `graphify-out/` 本地产物。生成物先判意图再写入并审 diff。
- **测试纪律**：不因缺工具链（如 zunit）整族 skip 后报绿；验收命令不接吞退出码
  的管道；终端证据读回后才算通过。
- **版本双体系**：fork 版本真源是 CHANGELOG.md（`## X.Y.Z(日期|TBD)`，
  `make version-check` 守门）；上游 `omz changelog` 动态生成体系不受影响。

## 领域规则索引（人工预览，实际以 resolver 输出为准）

| 领域 | 文档 | 触及 |
|---|---|---|
| code-review | docs/AGENT_RULES/code-review.md | 任务 review |
| core-loader | docs/AGENT_RULES/core-loader.md | oh-my-zsh.sh、lib/、custom/ 模板 |
| development | docs/AGENT_RULES/development.md | 框架自身、docs/、scripts/、.github/ |
| gx-profile | docs/AGENT_RULES/gx-profile.md | gx/** 个人配置固化层与安装器 |
| plugins | docs/AGENT_RULES/plugins.md | plugins/** |
| testing | docs/AGENT_RULES/testing.md | tests/**、lib/tests/** |
| themes | docs/AGENT_RULES/themes.md | themes/** |
| tools-installer | docs/AGENT_RULES/tools-installer.md | tools/**、templates/** |

## 审核与完成

验收点 → resolver 规则 → 实现/文档 → 针对性测试 → 适用终端证据读回 → 修复复测 →
生成物/版本 → 复审。交付如实报告实际执行、未执行项、N/A 理由与剩余风险；配置或
文件存在不证明运行成功。审核输出固定格式：`## 严重 / ## 中 / ## 轻 / ## 结论`
（三态：通过 / 有条件通过 / 驳回）。

长期文档用 `路径::符号` 引用（如 `lib/git.zsh::__git_prompt_git`），不钉行号；
审核发现可用当前准确行号。规则/路由改动后运行
`python3 scripts/resolve_agent_rules.py --check`。
