"""Plant knowledge base: markdown sections as chunks, ranked with BM25.

Each ``## <ID> — <title>`` section of a ``knowledge/*.md`` file is one chunk.
Retrieval is plain Okapi BM25 (k1 = 1.5, b = 0.75) over lowercase word tokens
of title plus text, so it needs no dependency and no network.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

K1 = 1.5
B = 0.75

_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
_TOKEN = re.compile(r"\w+")
_SEPARATOR = " — "


@dataclass(frozen=True)
class Chunk:
    id: str
    title: str
    text: str
    source_file: str


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _parse(path: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    heading: str | None = None
    body: list[str] = []

    def flush() -> None:
        if heading is None:
            return
        cid, sep, title = heading.partition(_SEPARATOR)
        if not sep:
            raise ValueError(f"{path.name}: heading without an em dash: {heading!r}")
        chunks.append(Chunk(cid.strip(), title.strip(), "\n".join(body).strip(), path.name))

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            flush()
            heading, body = line[3:].strip(), []
        elif heading is not None:
            body.append(line)
    flush()
    return chunks


def load_chunks(directory: Path | None = None) -> list[Chunk]:
    """Every section of every ``*.md`` file in ``directory`` (default: the package's)."""
    root = Path(directory) if directory is not None else _KNOWLEDGE_DIR
    chunks: list[Chunk] = []
    seen: dict[str, str] = {}
    for path in sorted(root.glob("*.md")):
        for chunk in _parse(path):
            if chunk.id in seen:
                raise ValueError(
                    f"duplicate chunk id {chunk.id!r} in {path.name} and {seen[chunk.id]}"
                )
            seen[chunk.id] = path.name
            chunks.append(chunk)
    return chunks


def search(query: str, chunks: list[Chunk], k: int = 4) -> list[Chunk]:
    """Up to ``k`` chunks with a BM25 score above zero, best first, ties in chunk order."""
    terms = set(_tokens(query))
    if not terms or not chunks or k <= 0:
        return []
    docs = [Counter(_tokens(f"{c.title} {c.text}")) for c in chunks]
    lengths = [sum(d.values()) for d in docs]
    n = len(chunks)
    avg = (sum(lengths) / n) or 1.0
    idf = {}
    for term in terms:
        df = sum(1 for d in docs if term in d)
        idf[term] = math.log(1 + (n - df + 0.5) / (df + 0.5))
    scored: list[tuple[float, int]] = []
    for i, tf in enumerate(docs):
        score = 0.0
        for term in terms:
            f = tf.get(term, 0)
            if f:
                score += idf[term] * f * (K1 + 1) / (f + K1 * (1 - B + B * lengths[i] / avg))
        if score > 0:
            scored.append((score, i))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [chunks[i] for _, i in scored[:k]]
