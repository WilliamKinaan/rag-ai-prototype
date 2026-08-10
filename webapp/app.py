"""FastAPI backend for the interactive RAG pipeline demo.

Thin wrapper around the existing src/ pipeline — no chunking/embedding/
retrieval logic is reimplemented here, only exposed over HTTP. Run with:

    uvicorn webapp.app:app --reload --port 8000
"""

import sys
from pathlib import Path

WEBAPP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEBAPP_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import chromadb  # noqa: E402
import numpy as np  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from chunking import chunk_document, chunk_text  # noqa: E402
from config import CHROMA_DIR, EMBEDDING_DIM, EMBEDDING_MODEL_NAME  # noqa: E402
from config import CHUNK_OVERLAP_CHARS, CHUNK_SIZE_CHARS, TOP_K  # noqa: E402
from embedding import embed  # noqa: E402
from ingest import get_collection  # noqa: E402
from loader import load_documents  # noqa: E402
from query import search  # noqa: E402

app = FastAPI(title="RAG Prototype Demo")

# Default cosine-distance cutoff for the "hide weak matches" filter. Kept
# here as the single source of truth; the frontend's default input value
# (query.js / explore.js) is hardcoded to match — see comments there.
DEFAULT_MAX_DISTANCE = 0.5

# Populated at startup; holds the live Chroma collection + a couple of
# stats that aren't cheap to recompute on every /api/index-stats call.
state: dict = {}


@app.on_event("startup")
def build_index() -> None:
    docs = load_documents()
    records = [chunk for doc in docs for chunk in chunk_document(doc["source"], doc["text"])]
    embeddings = embed([r["text"] for r in records])

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = get_collection(client, rebuild=True)
    collection.upsert(
        ids=[f"{r['source']}::chunk{r['chunk_index']}" for r in records],
        embeddings=embeddings,
        documents=[r["text"] for r in records],
        metadatas=[{"source": r["source"], "chunk_index": r["chunk_index"]} for r in records],
    )

    state["collection"] = collection
    state["docs"] = {d["source"]: d["text"] for d in docs}
    state["doc_count"] = len(docs)
    print(f"[startup] indexed {len(docs)} doc(s), {collection.count()} chunk(s)")


# --- request/response models ------------------------------------------

class ChunkRequest(BaseModel):
    text: str


class EmbedRequest(BaseModel):
    texts: list[str]


class QueryRequest(BaseModel):
    query: str
    k: int = TOP_K
    playground_texts: list[str] = []
    max_distance: float = DEFAULT_MAX_DISTANCE


# --- endpoints -----------------------------------------------------------

@app.get("/api/index-stats")
def index_stats():
    collection = state["collection"]
    return {
        "model_name": EMBEDDING_MODEL_NAME,
        "chunk_size": CHUNK_SIZE_CHARS,
        "overlap": CHUNK_OVERLAP_CHARS,
        "embedding_dim": EMBEDDING_DIM,
        "doc_count": state["doc_count"],
        "chunk_count": collection.count(),
    }


@app.post("/api/chunk")
def api_chunk(req: ChunkRequest):
    chunks = chunk_text(req.text)
    return {"chunks": [{"index": i, "text": c, "char_count": len(c)} for i, c in enumerate(chunks)]}


@app.post("/api/embed")
def api_embed(req: EmbedRequest):
    if not req.texts:
        return {"embeddings": []}
    vectors = embed(req.texts)
    return {
        "embeddings": [
            {"text": t, "dim": len(v), "preview": v[:8]} for t, v in zip(req.texts, vectors)
        ]
    }


@app.post("/api/query")
def api_query(req: QueryRequest):
    collection = state["collection"]

    query_vec = embed([req.query], is_query=True)[0]
    corpus_results = search(collection, query_vec, req.k)
    corpus_results = [r for r in corpus_results if r["distance"] <= req.max_distance]

    playground_results = None
    if req.playground_texts:
        q = np.array(query_vec)
        p_vecs = embed(req.playground_texts)
        playground_results = [
            {"index": i, "text": t, "distance": 1.0 - float(np.dot(q, np.array(v)))}
            for i, (t, v) in enumerate(zip(req.playground_texts, p_vecs))
        ]
        playground_results.sort(key=lambda r: r["distance"])
        playground_results = [r for r in playground_results if r["distance"] <= req.max_distance]

    return {
        "query": req.query,
        "embedding_dim": len(query_vec),
        "embedding_preview": query_vec[:8],
        "max_distance": req.max_distance,
        "corpus_results": corpus_results,
        "playground_results": playground_results,
    }


def _doc_title(text: str) -> str:
    """First markdown H1 line, if present, else empty."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


@app.get("/api/corpus")
def api_corpus():
    return {
        "documents": [
            {"source": source, "title": _doc_title(text) or source}
            for source, text in sorted(state["docs"].items())
        ]
    }


@app.get("/api/corpus/{source}")
def api_corpus_document(source: str):
    docs = state["docs"]
    if source not in docs:
        raise HTTPException(status_code=404, detail=f"No such document: {source}")
    text = docs[source]
    return {"source": source, "title": _doc_title(text) or source, "text": text}


# Serve the frontend. Mounted last so it doesn't shadow the /api/* routes
# above (Starlette tries routes in registration order).
app.mount("/", StaticFiles(directory=str(WEBAPP_DIR / "static"), html=True), name="static")
