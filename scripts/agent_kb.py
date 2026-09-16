#!/usr/bin/env python3
"""知识库检索 CLI（BM25-lite）：查询 docs/kb/chunks.json。

用法：
  python3 scripts/agent_kb.py search "git 插件有哪些别名" [--top 8] [--layer doc|plugin|code] [--source git]
  python3 scripts/agent_kb.py stats

分词：ASCII 词 + CJK 单字与二元组（中文查询可用）。命中携带 chunk id、来源、
锚点与层；无命中退出码仍为 0（探索性检索），参数错误退出 2。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB_PATH = ROOT / "docs" / "kb" / "chunks.json"
ASCII_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.+-]{1,}")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens = ASCII_TOKEN_RE.findall(lowered)
    cjk_chars = CJK_RE.findall(lowered)
    tokens.extend(cjk_chars)
    tokens.extend(a + b for a, b in zip(cjk_chars, cjk_chars[1:]))
    return tokens


def load_kb() -> dict:
    if not KB_PATH.is_file():
        print("FAIL: docs/kb/chunks.json 不存在，先运行 make kb", file=sys.stderr)
        raise SystemExit(1)
    return json.loads(KB_PATH.read_text(encoding="utf-8"))


def search(kb: dict, query: str, top: int, layer: str | None, source: str | None) -> list[tuple[float, dict]]:
    chunks = kb.get("chunks", [])
    if layer:
        chunks = [c for c in chunks if c.get("layer") == layer]
    if source:
        chunks = [c for c in chunks if source.lower() in c.get("source", "").lower()]
    if not chunks:
        return []
    term_freqs = [Counter(tokenize(f"{c.get('title', '')} {c.get('text', '')}")) for c in chunks]
    doc_freq = Counter()
    for freq in term_freqs:
        doc_freq.update(freq.keys())
    total = len(chunks)
    query_terms = set(tokenize(query))
    if not query_terms:
        return []
    scored = []
    for chunk, freq in zip(chunks, term_freqs):
        score = 0.0
        for term in query_terms:
            tf = freq.get(term, 0)
            if not tf:
                continue
            idf = math.log(1.0 + total / doc_freq[term])
            score += idf * (tf / (tf + 1.5))  # 饱和项：单 chunk 内重复词收益递减
        title_terms = set(tokenize(chunk.get("title", "")))
        if title_terms & query_terms:
            score *= 1.3  # 标题命中的温和加权
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["source"], pair[1]["anchor"]))
    return scored[:top]


def snippet(text: str, terms: set[str], width: int = 200) -> str:
    lowered = text.lower()
    position = len(text)
    for term in terms:
        index = lowered.find(term.lower())
        if index >= 0:
            position = min(position, index)
    if position >= len(text):
        position = 0
    start = max(0, position - 40)
    body = text[start:start + width].replace("\n", " ")
    return ("…" if start else "") + body + ("…" if start + width < len(text) else "")


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库检索（docs/kb/chunks.json）")
    sub = parser.add_subparsers(dest="command", required=True)
    search_parser = sub.add_parser("search", help="BM25-lite 检索")
    search_parser.add_argument("query")
    search_parser.add_argument("--top", type=int, default=8)
    search_parser.add_argument("--layer", choices=["doc", "plugin", "code"])
    search_parser.add_argument("--source", help="来源路径子串过滤，如 git")
    sub.add_parser("stats", help="知识库统计")
    args = parser.parse_args()

    kb = load_kb()
    if args.command == "stats":
        layers = Counter(c.get("layer") for c in kb.get("chunks", []))
        print(f"chunks={kb.get('chunk_count')} corpus_files={kb.get('corpus_files')}")
        print(f"layers={dict(sorted(layers.items()))}")
        print(f"corpus_hash={kb.get('corpus_hash')}")
        print(f"content_hash={kb.get('content_hash')}")
        return 0

    results = search(kb, args.query, args.top, args.layer, args.source)
    if not results:
        print("no hits")
        return 0
    terms = set(tokenize(args.query))
    for rank, (score, chunk) in enumerate(results, start=1):
        print(f"[{rank}] score={score:.3f} layer={chunk['layer']} {chunk['source']}  ({chunk['anchor']})")
        print(f"    {chunk.get('title', '')}")
        print(f"    {snippet(chunk['text'], terms)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
