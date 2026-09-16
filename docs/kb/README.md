# AI 知识库（chunks.json）

把仓库知识切块为可检索语料，供 AI 工具与人工快速定位。**chunks.json 是受控
生成物，勿手改**——语料变化后 `make kb` 再生并审 diff；`make kb-check`
（已接入 ci-check）校验一致性，漂移即红。

## 构建与检查

```bash
make kb          # 重建 docs/kb/chunks.json（scripts/build_agent_kb.py --confirm）
make kb-check    # 校验与语料一致（corpus_hash + content_hash 双判定）
```

## 检索

```bash
python3 scripts/agent_kb.py search "git 插件 checkout 别名" --top 8
python3 scripts/agent_kb.py search "compinit insecure" --layer doc
python3 scripts/agent_kb.py search "alias dbl" --layer code
python3 scripts/agent_kb.py stats
```

命中携带 chunk id、来源路径、锚点（`路径#标题 slug`）与层；BM25-lite 打分
（ASCII 词 + CJK 单字/二元组，标题命中温和加权）。

## 语料三层

1. **文档层**：根 AGENTS/CLAUDE/CHANGELOG/CONTRIBUTING/README + docs/**/*.md
   （排除本目录），按标题切块（≤1500 字符，超长按空行二次切分）。
2. **插件层**：plugins/*/README.md 全量（367 份，本仓最大知识源）。
3. **代码结构层**：shell 源文件（oh-my-zsh.sh、lib/、plugins/ 的 plugin.zsh
   与 _补全、themes/*.zsh-theme、tools/、tests/）提取函数/别名/compdef 符号表。
   graphify 本地 AST 不识别 zsh 扩展名，zsh 结构检索由本层承担（与图谱互补）。

## 与图谱的分工

- 图谱（`make graph`）：源码结构关系查询（graphify query/path/explain），
  覆盖 bash/python/json 面。
- 知识库（本目录）：全语料关键词检索，覆盖 zsh 主战场。
优先图谱定位结构、KB 定位内容；两者都命中时双证据互证。
