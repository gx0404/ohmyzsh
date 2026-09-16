#!/usr/bin/env python3
"""知识库构建器：三层语料 → docs/kb/chunks.json（受控入库的生成物，禁手改）。

语料分层：
  1. 文档层   根 AGENTS/CLAUDE/CHANGELOG/CONTRIBUTING/README + docs/**/*.md（排除 docs/kb/）
  2. 插件层   plugins/*/README.md（367 份，本仓最大知识源）
  3. 代码结构层 shell 文件（oh-my-zsh.sh、lib/、plugins/ 的 plugin.zsh 与 _补全、
     themes/*.zsh-theme、tools/、tests/）提取函数/别名/compdef 符号表——
     graphify 本地 AST 不识别 zsh 扩展名，zsh 结构检索由本层承担。

用法：
  python3 scripts/build_agent_kb.py --confirm   # 重建并写入
  python3 scripts/build_agent_kb.py --check     # 校验一致性（漂移即红，接入 ci-check）

一致性判定：corpus_hash（语料输入）与 content_hash（切块内容）都一致才算 PASS，
built_at 时间戳不参与比较。仅标准库；Python 3.10 兼容。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "docs" / "kb" / "chunks.json"
MAX_CHUNK_CHARS = 1500

FUNC_RE = re.compile(r"^(?:function\s+)?([A-Za-z_][A-Za-z0-9_:]*)\s*\(\)\s*\{", re.M)
ALIAS_RE = re.compile(r"^alias\s+([A-Za-z_][A-Za-z0-9_.:-]+)=(.{0,80})", re.M)
COMPDEF_RE = re.compile(r"^compdef\s+(\S+)", re.M)
HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.M)

ROOT_DOCS = {"AGENTS.md", "CLAUDE.md", "CHANGELOG.md", "CONTRIBUTING.md", "README.md"}
PLUGIN_README_RE = re.compile(r"plugins/[^/]+/README\.md")
PLUGIN_ZSH_RE = re.compile(r"plugins/[^/]+/[^/]*\.(plugin\.)?zsh")
PLUGIN_COMPLETION_RE = re.compile(r"plugins/[^/]+/_[^/]+")


def git_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit("FAIL: 无法枚举 Git 可见文件")
    return sorted(item.decode("utf-8") for item in result.stdout.split(b"\0") if item)


def is_shell_source(rel: str) -> bool:
    """代码结构层收录范围：zsh/sh 源与补全文件。"""
    if rel == "oh-my-zsh.sh":
        return True
    name = rel.rsplit("/", 1)[-1]
    if rel.startswith("lib/tests/") or rel.startswith("tests/"):
        return rel.endswith(".zsh")
    if rel.startswith("lib/"):
        return rel.endswith(".zsh")
    if rel.startswith("tools/"):
        return rel.endswith((".sh", ".zsh"))
    if rel.startswith("plugins/"):
        return bool(PLUGIN_ZSH_RE.fullmatch(rel) or PLUGIN_COMPLETION_RE.fullmatch(rel))
    if rel.startswith("themes/"):
        return rel.endswith(".zsh-theme")
    return False


def corpus_inputs(files: list[str]) -> list[tuple[str, str]]:
    """返回 (relpath, layer)；layer ∈ doc / plugin / code。"""
    inputs: list[tuple[str, str]] = []
    for rel in files:
        if rel in ROOT_DOCS:
            inputs.append((rel, "doc"))
        elif rel.startswith("docs/") and rel.endswith(".md") and not rel.startswith("docs/kb/"):
            inputs.append((rel, "doc"))
        elif PLUGIN_README_RE.fullmatch(rel):
            inputs.append((rel, "plugin"))
        elif is_shell_source(rel):
            inputs.append((rel, "code"))
    return inputs


def slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", text).strip("-").lower()
    return slug[:48] or "section"


def markdown_sections(text: str) -> list[tuple[str, str, str]]:
    """按标题切块，返回 (slug, title, body)；首段无标题时 slug 为空。"""
    matches = list(HEADING_RE.finditer(text))
    sections: list[tuple[str, str, str]] = []
    if not matches:
        return [("", "", text)] if text.strip() else []
    if matches[0].start() > 0:
        sections.append(("", "", text[: matches[0].start()]))
    for index, match in enumerate(matches):
        title = match.group(2)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((slugify(title), title, text[start:end]))
    return sections


def split_long(body: str) -> list[str]:
    if len(body) <= MAX_CHUNK_CHARS:
        return [body]
    parts, current = [], ""
    for block in re.split(r"\n\s*\n", body):
        candidate = (current + "\n\n" + block) if current else block
        if len(candidate) > MAX_CHUNK_CHARS and current:
            parts.append(current)
            current = block[:MAX_CHUNK_CHARS]
        else:
            current = candidate
    if current.strip():
        parts.append(current)
    return parts


def shell_symbols(text: str) -> str:
    lines = []
    funcs = FUNC_RE.findall(text)
    if funcs:
        lines.append("函数: " + ", ".join(dict.fromkeys(funcs))[:1200])
    aliases = ALIAS_RE.findall(text)
    if aliases:
        rendered = [f"{name}={value.strip()[:40]}" for name, value in aliases]
        lines.append("别名: " + ", ".join(rendered)[:1200])
    compdefs = COMPDEF_RE.findall(text)
    if compdefs:
        lines.append("compdef: " + ", ".join(dict.fromkeys(compdefs))[:400])
    return "\n".join(lines)


def make_chunk(source: str, anchor: str, title: str, text: str, layer: str) -> dict:
    digest = hashlib.sha1(f"{source}::{anchor}::{title}::{text}".encode("utf-8")).hexdigest()[:12]
    return {"id": digest, "source": source, "anchor": anchor, "title": title,
            "text": text[:4000], "layer": layer}


def build_chunks() -> tuple[list[dict], dict]:
    inputs = corpus_inputs(git_files())
    chunks: list[dict] = []
    corpus_hasher = hashlib.sha256()
    corpus_file_count = 0
    missing: list[str] = []
    for rel, layer in inputs:
        path = ROOT / rel
        if not path.is_file():
            missing.append(rel)
            continue
        raw = path.read_bytes()
        corpus_hasher.update(rel.encode("utf-8"))
        corpus_hasher.update(hashlib.sha256(raw).digest())
        corpus_file_count += 1
        text = raw.decode("utf-8", errors="replace")
        if layer in ("doc", "plugin"):
            for slug, title, body in markdown_sections(text):
                for piece in split_long(body.strip()):
                    if not piece.strip():
                        continue
                    anchor = f"{rel}#{slug}" if slug else rel
                    chunks.append(make_chunk(rel, anchor, title or rel, piece, layer))
        else:
            symbols = shell_symbols(text)
            if symbols:
                chunks.append(make_chunk(rel, rel, f"符号表 {rel}", symbols, "code"))
    if missing:
        raise SystemExit(f"FAIL: 语料文件缺失: {missing}")
    chunks.sort(key=lambda item: (item["source"], item["anchor"], item["id"]))
    content_hash = hashlib.sha256(json.dumps(
        [{k: c[k] for k in ("id", "source", "anchor", "title", "text", "layer")} for c in chunks],
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    meta = {
        "corpus_files": corpus_file_count,
        "corpus_hash": corpus_hasher.hexdigest(),
        "content_hash": content_hash,
        "chunk_count": len(chunks),
    }
    return chunks, meta


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库构建器（三层语料 → docs/kb/chunks.json）")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--confirm", action="store_true", help="重建并写入")
    mode.add_argument("--check", action="store_true", help="校验一致性，漂移退出 1")
    args = parser.parse_args()

    chunks, meta = build_chunks()
    if args.check:
        if not OUT_PATH.is_file():
            print("FAIL: docs/kb/chunks.json 不存在，先运行 make kb", file=sys.stderr)
            return 1
        try:
            existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FAIL: chunks.json 无法读取: {exc}", file=sys.stderr)
            return 1
        problems = []
        if existing.get("content_hash") != meta["content_hash"]:
            problems.append(f"content_hash 现值 {existing.get('content_hash')} 期望 {meta['content_hash']}")
        if existing.get("corpus_hash") != meta["corpus_hash"]:
            problems.append(f"corpus_hash 现值 {existing.get('corpus_hash')} 期望 {meta['corpus_hash']}")
        if problems:
            print("FAIL: 知识库与语料漂移（" + "; ".join(problems) + "）；运行 make kb 再生并审 diff",
                  file=sys.stderr)
            return 1
        print(f"kb-check: PASS（{meta['chunk_count']} chunks，{meta['corpus_files']} 语料文件）")
        return 0

    payload = {
        "schema": 1,
        "generator": "scripts/build_agent_kb.py",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **meta,
        "chunks": chunks,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(OUT_PATH.parent), prefix=".chunks-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=1)
            stream.write("\n")
        os.replace(tmp_name, OUT_PATH)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    print(f"kb: 写入 {OUT_PATH.relative_to(ROOT)}（{meta['chunk_count']} chunks，"
          f"{meta['corpus_files']} 语料文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
