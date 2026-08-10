"""Query the Chroma collection built by ingest.py.

Usage:
    python query.py "some question"
    python query.py "some question" --k 5
    python query.py --eval
"""

import argparse
import json

import chromadb
from chromadb.errors import NotFoundError

from config import (
    CHROMA_DIR,
    CHUNK_OVERLAP_CHARS,
    CHUNK_SIZE_CHARS,
    COLLECTION_NAME,
    EMBEDDING_DIM,
    EMBEDDING_MODEL_NAME,
    EVAL_FILE,
    TOP_K,
)
from embedding import embed

EXPECTED_INDEX_METADATA = {
    "model_name": EMBEDDING_MODEL_NAME,
    "embedding_dim": EMBEDDING_DIM,
    "chunk_size": CHUNK_SIZE_CHARS,
    "overlap": CHUNK_OVERLAP_CHARS,
}


def load_collection():
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        collection = client.get_collection(COLLECTION_NAME, embedding_function=None)
    except NotFoundError:
        raise SystemExit("No index found. Run `python ingest.py` first.")

    stale = {
        k: v for k, v in EXPECTED_INDEX_METADATA.items() if collection.metadata.get(k) != v
    }
    if stale:
        raise SystemExit(
            f"Index was built with different settings than config.py currently "
            f"specifies ({stale}). Run `python ingest.py --rebuild` to fix."
        )
    return collection


def search(collection, query_embedding: list[float], k: int = TOP_K) -> list[dict]:
    """Search with an already-computed query embedding. Split out from
    retrieve() so callers that need the raw embedding too (e.g. the webapp,
    to show it in the UI) don't have to embed the query twice."""
    results = collection.query(query_embeddings=[query_embedding], n_results=k)
    return [
        {
            "source": meta["source"],
            "chunk_index": meta["chunk_index"],
            "text": doc,
            "distance": dist,  # cosine distance: lower = more similar
        }
        for doc, meta, dist in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        )
    ]


def retrieve(collection, query: str, k: int = TOP_K) -> list[dict]:
    """The V1 retrieval seam: text query in, ranked chunks out. A future
    generation layer wraps this same call."""
    query_embedding = embed([query], is_query=True)[0]
    return search(collection, query_embedding, k)


def print_results(results: list[dict]) -> None:
    for rank, r in enumerate(results, start=1):
        preview = r["text"].replace("\n", " ")
        if len(preview) > 160:
            preview = preview[:160] + "..."
        print(
            f"{rank}. distance={r['distance']:.4f}  "
            f"{r['source']}#chunk{r['chunk_index']}\n   {preview}"
        )


def run_eval(collection) -> None:
    pairs = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    hits_at_1 = 0
    hits_at_3 = 0

    for pair in pairs:
        results = retrieve(collection, pair["query"], k=3)
        sources = [r["source"] for r in results]
        hit1 = sources[:1] == [pair["expected_source"]]
        hit3 = pair["expected_source"] in sources
        hits_at_1 += hit1
        hits_at_3 += hit3
        mark = "OK" if hit1 else ("~ " if hit3 else "MISS")
        print(f"[{mark}] {pair['query']!r} -> expected {pair['expected_source']}, got {sources}")

    n = len(pairs)
    print(f"\nhit@1: {hits_at_1}/{n}   hit@3: {hits_at_3}/{n}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", help="Query text.")
    parser.add_argument("--k", type=int, default=TOP_K)
    parser.add_argument("--eval", action="store_true", help="Run data/eval.json and report hit@1/hit@3.")
    args = parser.parse_args()

    collection = load_collection()

    if args.eval:
        run_eval(collection)
        return

    if not args.query:
        raise SystemExit("Provide a query, or use --eval.")

    print_results(retrieve(collection, args.query, k=args.k))


if __name__ == "__main__":
    main()
