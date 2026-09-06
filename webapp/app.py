"""FastAPI backend for the interactive RAG pipeline demo.

Thin wrapper around the existing src/ pipeline — no chunking/embedding/
retrieval logic is reimplemented here, only exposed over HTTP. Run with:

    uvicorn webapp.app:app --reload --port 8000

Local-only fast path: building the RAG index at startup loads the ~2GB
bge-m3 embedding model and encodes the whole corpus, which takes a while on
a CPU-only dev machine. If you only want to work on the Legal Assistant
page (which doesn't use the RAG index at all), skip that with:

    SKIP_RAG_INDEX=1 uvicorn webapp.app:app --reload --port 8000

This must never be set in the real deploy (see CONTEXT-webapp.md) — it's
not read from .env on purpose, so it can't leak into the deployed
environment by copying/reusing that file; pass it inline on the command
line each time instead. With it set, the RAG demo/search/explore/corpus
pages return a clean 503 instead of working.
"""

import os
import sys
from pathlib import Path

WEBAPP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEBAPP_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(WEBAPP_DIR))  # so `import llm` (webapp/llm.py) resolves

import sqlite_shim  # noqa: E402,F401  (must precede `import chromadb` — see module docstring)
import chromadb  # noqa: E402
import numpy as np  # noqa: E402
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from chunking import chunk_document, chunk_text  # noqa: E402
from config import CHROMA_DIR, EMBEDDING_DIM, EMBEDDING_MODEL_NAME  # noqa: E402
from config import CHUNK_OVERLAP_CHARS, CHUNK_SIZE_CHARS, TOP_K  # noqa: E402
from embedding import embed  # noqa: E402
from ingest import get_collection  # noqa: E402
from loader import load_documents  # noqa: E402
from query import search  # noqa: E402

import legal_review  # noqa: E402
import llm  # noqa: E402
import rate_limiter  # noqa: E402

app = FastAPI(title="RAG Prototype Demo")

# See the module docstring - local dev only, never set on the real deploy.
SKIP_RAG_INDEX = os.environ.get("SKIP_RAG_INDEX", "").strip().lower() in ("1", "true", "yes")


@app.get("/api/rate-limit/status")
def rate_limit_status():
    """Read-only snapshot of the in-memory rate limiter (rate_limiter.py) -
    doesn't consume any budget. Called once by the page's badge on load to
    show a real number before the visitor's first message.
    """
    remaining, reset_in = rate_limiter.status()
    return {
        "remaining": remaining,
        "reset_in": max(0, round(reset_in)),
        "limit": rate_limiter.MAX_REQUESTS,
        "window_seconds": rate_limiter.WINDOW_SECONDS,
    }


@app.exception_handler(rate_limiter.RateLimitExceeded)
def handle_rate_limit_exceeded(request: Request, exc: rate_limiter.RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": str(exc)})


@app.middleware("http")
async def add_rate_limit_headers(request: Request, call_next):
    """Stamp the current rate-limit snapshot onto every response (success or
    429 alike - the exception handler above runs before this middleware sees
    the response), so the badge updates off requests the page was already
    making, no separate polling needed.
    """
    response = await call_next(request)
    remaining, reset_in = rate_limiter.status()
    reset_seconds = max(0, round(reset_in))
    response.headers["X-RateLimit-Limit"] = str(rate_limiter.MAX_REQUESTS)
    response.headers["X-RateLimit-Window-Seconds"] = str(rate_limiter.WINDOW_SECONDS)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset_seconds)
    if response.status_code == 429:
        response.headers["Retry-After"] = str(max(1, reset_seconds))
    return response


# Default cosine-distance cutoff for the "hide weak matches" filter. Kept
# here as the single source of truth; the frontend's default input value
# (query.js / explore.js) is hardcoded to match — see comments there.
DEFAULT_MAX_DISTANCE = 0.6

# Populated at startup; holds the live Chroma collection + a couple of
# stats that aren't cheap to recompute on every /api/index-stats call.
state: dict = {}


def build_index_state() -> dict:
    """Build/rebuild the Chroma index and return the shared state dict.

    Split out from the startup event (below) so callers that can't rely on
    a mounted sub-app's startup event actually firing — notably the
    Hugging Face Space entrypoint, which mounts this app under Gradio's
    `gr.Server` — can call it directly at module scope instead. See
    `app.py` at the project root.
    """
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

    print(f"[startup] indexed {len(docs)} doc(s), {collection.count()} chunk(s)")
    return {
        "collection": collection,
        "docs": {d["source"]: d["text"] for d in docs},
        "doc_count": len(docs),
    }


@app.on_event("startup")
def _on_startup() -> None:
    if SKIP_RAG_INDEX:
        print("[startup] SKIP_RAG_INDEX set - skipping RAG index build. "
              "The RAG demo, search, explore, and corpus pages will return "
              "a 503 until the server is restarted without that flag.")
        return
    if "collection" not in state:  # idempotent: harmless if already populated
        state.update(build_index_state())


def _require_rag_index() -> None:
    """Raise a clean 503 instead of a bare KeyError on `state["collection"]`
    when the index wasn't built - i.e. the server was started with
    SKIP_RAG_INDEX set for fast local iteration on the Legal Assistant page
    alone. Never set in the real deploy - see the module docstring above.
    """
    if "collection" not in state:
        raise HTTPException(
            status_code=503,
            detail=(
                "The RAG index wasn't built (server started with "
                "SKIP_RAG_INDEX set). Restart without that flag to use "
                "this page."
            ),
        )


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


class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []
    k: int = TOP_K
    max_distance: float = DEFAULT_MAX_DISTANCE


# --- endpoints -----------------------------------------------------------

@app.get("/api/index-stats")
def index_stats():
    _require_rag_index()
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
    _require_rag_index()
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


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    _require_rag_index()
    collection = state["collection"]

    # Retrieval query: fold in the last user turn for follow-ups ("what
    # about in the Netherlands?") so a short, pronoun-dependent message
    # still embeds close to the right chunks. The LLM still sees `message`
    # unmodified below — this concatenation is for retrieval only.
    last_user_turn = next(
        (t.content for t in reversed(req.history) if t.role == "user"), None
    )
    retrieval_query = f"{last_user_turn} {req.message}" if last_user_turn else req.message

    query_vec = embed([retrieval_query], is_query=True)[0]
    results = search(collection, query_vec, req.k)
    results = [r for r in results if r["distance"] <= req.max_distance]

    if not results:
        return {"reply": llm.NO_CONTEXT_REPLY, "sources": [], "no_context": True}

    context_block = llm.build_context_block(results)
    history = [{"role": t.role, "content": t.content} for t in req.history]
    # Reserve right before the one real Mistral call this turn makes - not
    # earlier, so a turn that never reaches Mistral (the no-context return
    # above) doesn't spend any budget. Left to raise RateLimitExceeded
    # uncaught: the except below only wraps llm.call_mistral's own
    # RuntimeError, so this propagates to the global exception handler as a
    # clean 429 instead of being folded into that 500/502 path.
    rate_limiter.reserve(1)
    try:
        reply = llm.call_mistral(history, req.message, context_block)
    except RuntimeError as e:
        # Missing key is a local config problem (500); anything else is the
        # Mistral API itself failing (502 — this server, talking upstream).
        status = 500 if "MISTRAL_API_KEY" in str(e) else 502
        raise HTTPException(status_code=status, detail=str(e))

    return {"reply": reply, "sources": results, "no_context": False}


@app.post("/api/legal-review")
async def api_legal_review(file: UploadFile = File(...), provider: str = Form(...)):
    """Legal Assistant: upload a contract, get back a structured review.
    See webapp/legal_review.py for the model-agnostic review logic - this
    endpoint is just upload handling + error-status mapping.
    """
    if provider not in legal_review.PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"'{provider}' is not yet supported. Choose one of: {', '.join(legal_review.PROVIDERS)}.",
        )

    content = await file.read()
    try:
        text = legal_review.extract_text(file.filename or "", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    text, truncated = legal_review.truncate(text)

    # Only the Mistral call spends from the shared-key rate limiter (see
    # .env.example / rate_limiter.py) - that budget is specifically this
    # app's share of a Mistral key shared with two other apps, unrelated to
    # OpenAI/Anthropic quota. Reserving it for every provider would reject a
    # Claude/GPT review because someone used the RAG chat on Mistral seconds
    # earlier, with a confusing Mistral-flavored error. OpenAI/Anthropic
    # calls go out unmetered for now - a known phase-1 gap, not an oversight
    # (see plans/phase1-legal-assistant.md).
    if provider == "mistral":
        rate_limiter.reserve(1)

    try:
        review = legal_review.review_contract(provider, text)
    except legal_review.ReviewConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except legal_review.ReviewUpstreamError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except legal_review.ReviewParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"provider": provider, "truncated": truncated, "review": review.model_dump()}


def _doc_title(text: str) -> str:
    """First markdown H1 line, if present, else empty."""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


@app.get("/api/corpus")
def api_corpus():
    _require_rag_index()
    return {
        "documents": [
            {"source": source, "title": _doc_title(text) or source}
            for source, text in sorted(state["docs"].items())
        ]
    }


@app.get("/api/corpus/{source}")
def api_corpus_document(source: str):
    _require_rag_index()
    docs = state["docs"]
    if source not in docs:
        raise HTTPException(status_code=404, detail=f"No such document: {source}")
    text = docs[source]
    return {"source": source, "title": _doc_title(text) or source, "text": text}


# Serve the frontend. Mounted last so it doesn't shadow the /api/* routes
# above (Starlette tries routes in registration order).
app.mount("/", StaticFiles(directory=str(WEBAPP_DIR / "static"), html=True), name="static")
