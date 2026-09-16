# 插件规则（plugins/）

适用 scope：`plugins/**`（367 个插件目录，含各插件自带 tests/）。
插件是本仓库最高频的改动面；规范来自 CONTRIBUTING.md 与既有插件先例。

## 标准构成

一个标准插件 = `plugins/<name>/<name>.plugin.zsh` + `plugins/<name>/README.md`。
当前 367 个插件全部有 README.md，两者缺一不可：

- `<name>.plugin.zsh`：插件入口，由 `_omz_source` 在 lib 之后按 `$plugins` 数组加载。
- `README.md`：说明插件做什么、如何启用；含别名的插件必须列出全部别名及其作用
  （先例：plugins/git/README.md 的 200+ 别名表格）。
- 可选补全：`_<name>` 放插件根目录（93 个先例），或 `completions/_<name>` 子目录
  （docker、gem 两个先例）。`is_plugin` 两种都认。
- 可选测试：`tests/*.zunit` + `_support/`（先例：alias-finder、dotenv）。
- 可选附加资源：配置片段、LICENSE（先例：gradle、tmux）。

## 别名准入（CONTRIBUTING.md 五条准则）

新别名必须同时满足：受众广、面向高频通用任务、宁少勿多、说明所服务的工作流、
避开与常用命令同名。合并前自查仓库内是否已有同名别名或函数——插件共享一个全局
命名空间，`alias gco=...` 在两个插件中定义即产生静默覆盖。

## 行为约束

- 不得假设其他插件的加载顺序；可以依赖 lib/（插件总在 lib 之后加载）。
- 运行期产物（下载的补全、缓存）写 `$ZSH_CACHE_DIR/completions/`，不得写仓库目录、
  `$HOME` 散落文件或 `custom/`。缓存式补全下载先例见 plugins/kubectl（后台 `&|`
  执行 `kubectl completion zsh` 到缓存目录）。
- 惰性加载重型工具（先例：lib/nvm.zsh 模式）；插件加载不得阻塞交互启动可感知时长。
- 检测外部命令存在再用（`(( $+commands[foo] ))` 或 `command -v`），缺失时静默降级，
  不向 stderr 刷警告。
- 不改全局 `setopt`/`bindkey`；键盘与选项归 lib/ 与用户。

## 提交与披露

- Conventional Commits：`type(<插件名>): subject`，scope 用插件名本身
  （`feat(shopify): ...` 而非 `feat(plugin/shopify): ...`）——tools/changelog.sh 按
  该格式生成变更日志。
- 上游要求 PR 披露 AI 参与程度（CONTRIBUTING.md「A note on AI-assisted
  contributions」）；fork 侧改动同样在 PR/commit 正文中披露，且作者须能解释每行。
- 新插件 README 用英文（上游门面语言），遵循 .prettierrc（110 列、proseWrap always）
  与 .editorconfig（LF、2 空格缩进、文件末尾空行）。

## 验证

- `bash scripts/check_syntax.sh` 覆盖 `plugins/*/*.plugin.zsh` 与 `plugins/*/_*`。
- 行为改动跑 `zsh tests/smoke_load.zsh --plugins <name>[,<name>]`（隔离环境加载断言）。
- 涉及补全缓存的改动清理 `$ZSH_CACHE_DIR/completions/` 后复跑，确认可重建。
