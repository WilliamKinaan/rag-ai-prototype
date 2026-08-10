"""The single place embeddings get computed.

ingest.py and query.py both call `embed()` from here so that whatever
normalization/prefix choice we make can never silently diverge between the
two paths (a mismatch there would make retrieval quietly wrong, not error).
"""

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from config import EMBEDDING_MODEL_NAME


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    # Cached so repeated calls (e.g. many queries in one process) don't
    # reload ~2GB of weights each time.
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def embed(texts: list[str], is_query: bool = False) -> list[list[float]]:
    """Embed a list of strings.

    `is_query` is accepted for symmetry with how BGE-style models are
    normally called (some need a different prefix for queries vs.
    documents), but BGE-M3 specifically needs no query instruction prefix,
    so it's currently unused. Kept so a future model swap that *does* need
    one only requires editing this function.
    """
    model = _get_model()
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embeddings.tolist()
