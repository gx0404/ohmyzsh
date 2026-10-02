# 已归档的工作流

这里原样保存 GX 默认分支撤下的上游工作流及其配套目录（`installer/`、`dependencies/`）。
GitHub 只从 `.github/workflows/` 加载工作流，本目录用于保留同步和查阅资料，不被 Actions 调度。

当前唯一的工作流入口为手动发布的 `gx-release`。分支安排、上游同步后的归档步骤见
[发布说明](../../docs/RELEASE.md#工作流目录与上游同步)；规则真源见
[development](../../docs/AGENT_RULES/development.md)。
