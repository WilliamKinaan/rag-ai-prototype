"""Dependency-free, paragraph-aware chunking.

Strategy: split on blank lines into paragraphs, then greedily pack
paragraphs into ~CHUNK_SIZE_CHARS chunks. A paragraph long enough to
exceed the chunk size on its own is split on word boundaries instead
(never mid-word). Each chunk after the first carries a bit of the
previous chunk's tail as overlap, so a sentence near a chunk boundary
still shows up whole in at least one chunk.

Note: the word-boundary fallback (_split_by_words) rejoins words with a
single space, so if it fires on text that still contains the "\n\n"
paragraph separator (i.e. the overlap-tail + next-paragraph combo was
itself too long), that separator gets flattened to a space in the output
chunk. Harmless for chunk content/retrieval, just don't expect exact
whitespace round-tripping through this path.
"""

import re

from config import CHUNK_OVERLAP_CHARS, CHUNK_SIZE_CHARS

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def _overlap_tail(text: str, overlap: int) -> str:
    """Last `overlap` chars of `text`, trimmed to start at a word boundary."""
    if len(text) <= overlap:
        return text
    tail = text[-overlap:]
    space_idx = tail.find(" ")
    return tail[space_idx + 1 :] if space_idx != -1 else tail


def _split_by_words(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Fallback for a single paragraph too long to fit in one chunk."""
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for word in words:
        added = len(word) + (1 if current else 0)
        if current and current_len + added > chunk_size:
            chunks.append(" ".join(current))
            # seed the next chunk with a word-boundary overlap tail
            tail: list[str] = []
            tail_len = 0
            for w in reversed(current):
                if tail_len + len(w) + 1 > overlap:
                    break
                tail.insert(0, w)
                tail_len += len(w) + 1
            current, current_len = tail, tail_len
            added = len(word) + (1 if current else 0)
        current.append(word)
        current_len += added

    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
) -> list[str]:
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para

        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = _overlap_tail(current, overlap)
            candidate = f"{current}\n\n{para}" if current else para

        if len(candidate) <= chunk_size:
            current = candidate
        else:
            # even current+para (or para alone) is too big: split on words
            word_chunks = _split_by_words(candidate, chunk_size, overlap)
            chunks.extend(word_chunks[:-1])
            current = word_chunks[-1] if word_chunks else ""

    if current:
        chunks.append(current)
    return chunks


def chunk_document(source: str, text: str) -> list[dict]:
    """Chunk one document's text into {text, source, chunk_index} records."""
    return [
        {"text": chunk, "source": source, "chunk_index": i}
        for i, chunk in enumerate(chunk_text(text))
    ]
