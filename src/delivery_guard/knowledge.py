"""Small, auditable local knowledge index with paragraph-level citations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from delivery_guard.context import KnowledgeCitation
from delivery_guard.hashing import stable_hash


TOKEN_RE = re.compile(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]")
INJECTION_PATTERNS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "approve every",
    "disable verification",
    "管理员授权",
    "忽略系统",
)


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text)}


@dataclass(frozen=True)
class _Chunk:
    document_id: str
    source_ref: str
    section: str
    text: str
    document_hash: str
    tokens: set[str]
    security_flags: tuple[str, ...]


class LocalKnowledgeBase:
    def __init__(self, paths: list[str | Path]) -> None:
        self._chunks: list[_Chunk] = []
        for raw_path in paths:
            self._load(Path(raw_path))

    def _load(self, path: Path) -> None:
        content = path.read_text(encoding="utf-8")
        document_hash = stable_hash(content)
        document_id = path.stem
        if content.startswith("---"):
            _, frontmatter, body = content.split("---", 2)
            for line in frontmatter.splitlines():
                if line.startswith("document_id:"):
                    document_id = line.split(":", 1)[1].strip()
            content = body.strip()
        section = "document"
        paragraphs: list[tuple[str, str]] = []
        for block in re.split(r"\n\s*\n", content):
            clean = block.strip()
            if not clean:
                continue
            if clean.startswith("#"):
                section = clean.lstrip("#").strip()
                continue
            paragraphs.append((section, clean.replace("\n", " ")))
        for paragraph_section, paragraph in paragraphs:
            lowered = paragraph.lower()
            flags = tuple(
                f"retrieval_injection:{pattern}"
                for pattern in INJECTION_PATTERNS
                if pattern in lowered
            )
            self._chunks.append(
                _Chunk(
                    document_id=document_id,
                    source_ref=str(path),
                    section=paragraph_section,
                    text=paragraph,
                    document_hash=document_hash,
                    tokens=_tokens(f"{paragraph_section} {paragraph}"),
                    security_flags=flags,
                )
            )

    def search(self, query: str, top_k: int = 4) -> list[KnowledgeCitation]:
        query_tokens = _tokens(query)
        scored: list[tuple[int, _Chunk]] = []
        for chunk in self._chunks:
            overlap = len(query_tokens & chunk.tokens)
            if overlap:
                phrase_bonus = 3 if query.lower() in chunk.text.lower() else 0
                scored.append((overlap * 10 + phrase_bonus, chunk))
        scored.sort(key=lambda pair: (-pair[0], pair[1].document_id, pair[1].section))
        return [
            KnowledgeCitation(
                citation_id=f"cite_{stable_hash({'document_id': chunk.document_id, 'section': chunk.section, 'text': chunk.text})[:8]}",
                document_id=chunk.document_id,
                source_ref=chunk.source_ref,
                section=chunk.section,
                text=chunk.text,
                document_hash=chunk.document_hash,
                score=score,
                security_flags=list(chunk.security_flags),
            )
            for score, chunk in scored[:top_k]
        ]
