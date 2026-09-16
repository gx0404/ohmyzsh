# ohmyzsh fork 文档索引

本目录是 fork 侧（gx0404/ohmyzsh）的框架与工程文档；上游用户文档在根 README.md
与各插件 README。AI 协作规则见根 `AGENTS.md` 与 `docs/AGENT_RULES/`。

| 文档 | 内容 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 加载流程、custom 覆盖机制、git prompt 引擎、omz CLI |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 开发交付闭环与日常流程 |
| [MAKE_COMMANDS.md](MAKE_COMMANDS.md) | make 目标语义与 15 个业务命令 |
| [TESTING.md](TESTING.md) | 测试分层、证据与终端截图流程 |
| [AI_TOOLS.md](AI_TOOLS.md) | 多工具（ZCode/Claude/Codex）配置与验证记录 |
| [RELEASE.md](RELEASE.md) | 版本双体系与 upstream 同步流程 |
| [kb/README.md](kb/README.md) | 知识库（chunks.json）构建与检索 |
| [dev-framework.json](dev-framework.json) | 15 命令状态真源（机器可读） |
| [AGENT_RULES/](AGENT_RULES/) | 领域规则闭集 + routes.toml 路由 |

代码图谱：`make graph` 生成 `graphify-out/`（本地产物，不入库）；
已知限制见 `scripts/graphify.sh` 头注释（zsh 扩展名不在 graphify AST 支持内，
zsh 语料检索靠知识库）。
