"""Build (or rebuild) the Chroma collection from data/raw/.

Usage:
    python ingest.py            # incremental: upsert, unchanged files are a no-op
    python ingest.py --rebuild  # drop the collection and re-embed everything
"""

import argparse

import sqlite_shim  # noqa: F401  (must precede `import chromadb` — see module docstring)
import chromadb
from chromadb.errors import NotFoundError

from chunking import chunk_document
from config import (
    CHROMA_DIR,
    CHUNK_OVERLAP_CHARS,
    CHUNK_SIZE_CHARS,
    COLLECTION_NAME,
    EMBEDDING_DIM,
    EMBEDDING_MODEL_NAME,
)
from embedding import embed
from loader import load_documents

INDEX_METADATA = {
    "model_name": EMBEDDING_MODEL_NAME,
    "embedding_dim": EMBEDDING_DIM,
    "chunk_size": CHUNK_SIZE_CHARS,
    "overlap": CHUNK_OVERLAP_CHARS,
    "hnsw:space": "cosine",
}


def get_collection(client: chromadb.ClientAPI, rebuild: bool):
    if rebuild:
        try:
            client.delete_collection(COLLECTION_NAME)
            print(f"Deleted existing collection '{COLLECTION_NAME}'.")
        except NotFoundError:
            pass
        return client.create_collection(
            COLLECTION_NAME, embedding_function=None, metadata=INDEX_METADATA
        )

    try:
        collection = client.get_collection(COLLECTION_NAME, embedding_function=None)
    except NotFoundError:
        return client.create_collection(
            COLLECTION_NAME, embedding_function=None, metadata=INDEX_METADATA
        )

    # Guard against silently appending chunks built with a different
    # model/chunking config than what's already indexed.
    stale = {
        k: v
        for k, v in INDEX_METADATA.items()
        if k != "hnsw:space" and collection.metadata.get(k) != v
    }
    if stale:
        raise SystemExit(
            f"Collection '{COLLECTION_NAME}' was built with different settings "
            f"({stale}). Run with --rebuild to re-embed everything, or revert "
            f"config.py to match the existing index."
        )
    return collection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete and recreate the collection instead of upserting into it.",
    )
    args = parser.parse_args()

    docs = load_documents()
    if not docs:
        raise SystemExit("No documents found in data/raw/.")

    records = [chunk for doc in docs for chunk in chunk_document(doc["source"], doc["text"])]
    print(f"Loaded {len(docs)} document(s), split into {len(records)} chunk(s).")

    print(f"Embedding with {EMBEDDING_MODEL_NAME} (first run downloads the model, be patient)...")
    embeddings = embed([r["text"] for r in records])

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = get_collection(client, args.rebuild)

    collection.upsert(
        ids=[f"{r['source']}::chunk{r['chunk_index']}" for r in records],
        embeddings=embeddings,
        documents=[r["text"] for r in records],
        metadatas=[{"source": r["source"], "chunk_index": r["chunk_index"]} for r in records],
    )

    print(f"Indexed. Collection now has {collection.count()} chunk(s) at {CHROMA_DIR}")


if __name__ == "__main__":
    main()
