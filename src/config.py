"""Central configuration for the RAG V1 pipeline.

Every other module reads its constants from here, so changing a chunking
or model parameter only requires editing this one file.
"""

from pathlib import Path

# --- Paths -------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
EVAL_FILE = PROJECT_ROOT / "data" / "eval.json"
CHROMA_DIR = PROJECT_ROOT / "chroma_db"

# --- Embedding -----------------------------------------------------------
# BAAI/bge-m3: multilingual, 8k context, no query-instruction prefix needed
# (unlike earlier bge-v1.5 models). See https://huggingface.co/BAAI/bge-m3
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"
EMBEDDING_DIM = 1024

# --- Chunking ------------------------------------------------------------
CHUNK_SIZE_CHARS = 1000
CHUNK_OVERLAP_CHARS = 150

# --- Retrieval -------------------------------------------------------------
COLLECTION_NAME = "documents"
TOP_K = 3
