# 版本与发布

## 版本双体系（本仓特有）

| 体系 | 真源 | 消费者 | 说明 |
|---|---|---|---|
| 上游体系 | git tag + Conventional Commits | `omz version`（lib/cli.zsh）、`omz changelog`（tools/changelog.sh 动态生成） | 不落盘文件；fork 继续沿用，不受框架影响 |
| fork 体系 | `CHANGELOG.md`（`## X.Y.Z(日期|TBD)`） | `make version` / `version-check`（scripts/version.py 取最大数值 SemVer） | 只记 fork 侧已实现行为；上游同步类改动记 `chore(upstream)` 条目 |

两条规则：

1. CHANGELOG.md 只记录**已实现并通过验证**的行为；计划与承诺不写入。
2. 不引入与上游竞争的文件版本镜像（version_targets 为空）；若未来需要
   （如发布 fork 安装脚本版本），在 dev-framework.json 的 version_targets 登记
   并用 `make version-write` 同步，先全量校验后原子写入。

## fork 版本节奏

- 破坏性变更（规则契约、命令语义变更）：主版本位 + `BREAKING CHANGE`。
- 新能力（新规则域、新命令层）：次版本位。
- 修正与文档：补丁位。发布时把 `(TBD)` 改为 `(YYYYMMDD)`。

## 发布形态

fork 的"发布" = git 分支/tag + PR（到 origin 的分支）。无制品打包（package N/A）。
PR 遵循上游模板：描述改动、引用 issue、**披露 AI 参与程度**、能解释每行代码。

## upstream 同步（周期性维护）

```bash
git fetch upstream && git merge upstream/master
make framework-check   # 新文件未路由会红 → 补 routes.toml（bootstrap 闭集）
make ci-check          # 语法/加载/KB 全量复验
make kb                # 语料变化后再生 chunks.json 并审 diff
```

同步后在 CHANGELOG.md 的当前版本下补 `chore(upstream)` 条目（同步到哪个
commit、是否有冲突处理）。上游合并冲突只允许出现在 .gitignore 标记块；
出现在其他文件即违反只增不改纪律，需回查定制来源。
