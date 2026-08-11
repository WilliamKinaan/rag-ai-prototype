"""Thin wrapper around the hosted Mistral AI chat completions API.

V2's generation layer: takes retrieved chunks (from src/query.py's
search()) and a conversation, and produces a grounded answer. No SDK —
one endpoint, plain httpx, matches this project's "no framework
wrappers" style. See CONTEXT.md's V2 section for why this is the
*hosted* API (free tier) rather than a local llama.cpp/Ollama model:
the dev machine is CPU-only, and running an 8B model locally there
would be impractically slow for an interactive demo.
"""

import os

import httpx
from dotenv import load_dotenv

load_dotenv()

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

# "ministral-8b-latest" — Mistral's edge/latency-tier 8B model, available
# on the free "Experiment" tier (console.mistral.ai). If this ever 400s
# as an unknown model, GET https://api.mistral.ai/v1/models with a valid
# key to see the current live model IDs rather than guessing a variant.
MISTRAL_MODEL_NAME = "ministral-8b-latest"

SYSTEM_PROMPT = """You are a legal-research demo assistant answering questions over a sample \
corpus of illustrative, simplified summaries of UAE law, spanning many areas \
— employment, tenancy, company formation, tax, criminal law, family law, \
real estate, intellectual property, financial regulation, and more. This is \
a testing prototype, not legal advice.

Rules:
- Answer ONLY using the context chunks provided for this turn. Do not use \
outside/general knowledge to fill gaps.
- If the provided context does not contain enough information to answer, say \
so plainly rather than guessing.
- The corpus spans many distinct areas of UAE law, and adjacent topics can \
sometimes surface together (e.g. banking vs. insurance regulation, or \
off-plan property registration vs. escrow protection). If the retrieved \
context appears to be about a different specific law or topic than what was \
asked, say that explicitly instead of answering as if it matched.
- Briefly note which source document(s) (by filename) the answer is drawn \
from.
- Keep in mind, and if relevant restate, that this is a demo and not a \
substitute for advice from a qualified lawyer.
"""

NO_CONTEXT_REPLY = (
    "I couldn't find anything relevant to that in the sample corpus at the "
    "current distance threshold. Try rephrasing, raising the threshold, or "
    "browse the full list of UAE law topics this demo covers via the "
    '"View the corpus used" link on this page.'
)


def build_context_block(results: list[dict]) -> str:
    """Format retrieved chunks into the context text injected for this turn."""
    parts = []
    for r in results:
        parts.append(f"[{r['source']} #chunk{r['chunk_index']}]\n{r['text']}")
    return "\n\n".join(parts)


def call_mistral(history: list[dict], message: str, context_block: str) -> str:
    """Send one chat-completions request and return the reply text.

    `history` is prior {role, content} turns only (no retrieved context
    from earlier turns — each turn gets its own fresh context block).
    Raises RuntimeError with a clear message on missing key or API failure.
    """
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError(
            "MISTRAL_API_KEY is not set. Create a free key at "
            "console.mistral.ai and put it in a .env file at the project "
            "root (see .env.example)."
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "system", "content": f"Context for this turn:\n\n{context_block}"},
        {"role": "user", "content": message},
    ]

    try:
        resp = httpx.post(
            MISTRAL_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": MISTRAL_MODEL_NAME, "messages": messages},
            timeout=30.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Mistral API error {e.response.status_code}: {e.response.text}") from e
    except httpx.HTTPError as e:
        raise RuntimeError(f"Mistral API request failed: {e}") from e

    data = resp.json()
    return data["choices"][0]["message"]["content"]
