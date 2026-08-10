"""Reads source documents from data/raw/."""

from pathlib import Path

from config import RAW_DATA_DIR

SUPPORTED_EXTENSIONS = {".txt", ".md"}


def load_documents(raw_dir: Path = RAW_DATA_DIR) -> list[dict]:
    """Return [{source: filename, text: contents}, ...] for every supported
    file in raw_dir, sorted by filename for deterministic ingest order."""
    docs = []
    for path in sorted(raw_dir.iterdir()):
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            docs.append({"source": path.name, "text": path.read_text(encoding="utf-8")})
    return docs
