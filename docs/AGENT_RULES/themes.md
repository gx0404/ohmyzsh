# 主题规则（themes/）

适用 scope：`themes/**`（143 个 `*.zsh-theme`）。

## 主题契约

- 主题文件定义提示符变量与函数；由 `oh-my-zsh.sh` 末段按 `ZSH_THEME` 解析加载，
  顺序为 `$ZSH_CUSTOM/$ZSH_THEME.zsh-theme` > `$ZSH_CUSTOM/themes/` > `$ZSH/themes/`。
- `lib/theme-and-appearance.zsh` 在主题之前加载：`colors` autoload、`prompt_subst`、
  `ZSH_THEME_GIT_PROMPT_*` 前后缀默认值都已就位。主题直接使用这些默认值，
  不必也不应重复定义。
- git 段一律经 `lib/prompt_info_functions.zsh::git_prompt_info` →
  `lib/git.zsh::_omz_git_prompt_info`；不要在主题内另起 git 进程或绕过
  `GIT_OPTIONAL_LOCKS=0` 约定，否则提示符渲染会与索引锁竞争。
- 使用 `%(...)` 条件、右提示符 `RPROMPT`、`async_prompt`（lib/async_prompt.zsh）时，
  确认所选转义与用户的 `prompt_subst` 环境兼容；主题不得自行 `setopt`。

## 修改纪律

- 上游**暂停接受新主题**（CONTRIBUTING.md）。fork 新增主题属于 fork 私有改动：
  commit 用 `feat(<主题名>): ...`，正文注明 fork-only、上游不收，并在 PR 描述披露
  AI 参与。
- 修主题 bug 保持最小 diff，兼容已有 `ZSH_THEME_*` 变量覆盖点；删除或改语义 =
  breaking change，需 `!` + `BREAKING CHANGE:` 正文。
- 主题文件保持英文注释、`#` 行注释风格。

## 验证

- `bash scripts/check_syntax.sh` 覆盖 `themes/*.zsh-theme`。
- 渲染类改动跑 `make ui-smoke`：脚本在隔离环境渲染默认主题与目标主题的提示符并
  断言关键段（如临时 git 仓库分支名出现），产物进证据批次目录，截图/文本捕获
  须读回检查后在 result.json 标记 `images_reviewed: true`。
