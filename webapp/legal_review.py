"""Contract review over hosted LLM APIs — the Phase 1 "Legal Assistant"
prototype (see /plans/phase1-legal-assistant.md and CONTEXT-legal-assistant.md).

No RAG here by design — this is the roadmap sheet's Phase 1 ("Baseline LLM
only"). Given a contract's extracted text, ask one of three hosted models
to return a structured review: section -> flagged passage -> suggested fix.
Contract-category classification (also on the sheet) is deliberately out of
scope for this pass.

Each provider gets its own call function so the dropdown in legal.html can
pick any of them; `review_contract()` is the single dispatch point the
FastAPI endpoint calls.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

# Cap on extracted contract text sent to any model - keeps prompt size (and
# cost/latency) bounded for this prototype. ~60k chars is roughly a
# 20-30 page contract; longer documents are truncated and the caller is
# told so via the `truncated` flag threaded through to the API response
# (never truncate silently - see the claude-api skill's guidance on this).
MAX_CHARS = 60_000

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


# --- structured output schema --------------------------------------------

class Issue(BaseModel):
    text: str
    suggestion: str


class ReviewSection(BaseModel):
    section: str
    issues: list[Issue]


class ContractReview(BaseModel):
    sections: list[ReviewSection]


REVIEW_SYSTEM_PROMPT = """You are a contract-review demo assistant. You are given the full text of a \
contract and must identify passages that need a lawyer's attention - unclear, \
one-sided, missing, or risky clauses - organized by the section of the \
contract they appear in.

Rules:
- Group findings under the contract's own section/clause headings (or a \
reasonable descriptive label if the document has none).
- For each flagged passage, quote or closely paraphrase the specific text \
that needs attention, and give one concrete, actionable suggestion for how \
to revise it.
- Only flag things a reviewing lawyer would actually want to look at - don't \
pad the output with routine, unremarkable boilerplate.
- If a section has no issues, omit it entirely rather than including it with \
an empty issue list.
- This is a testing prototype, not legal advice - do not claim certainty \
about jurisdiction-specific enforceability; phrase suggestions as things to \
review with a qualified lawyer.
- Respond with structured output only - no commentary outside the schema.
"""


def _build_user_message(contract_text: str) -> str:
    return f"Review this contract:\n\n{contract_text}"


# --- text extraction -------------------------------------------------------

def extract_text(filename: str, content: bytes) -> str:
    """Extract plain text from an uploaded contract file.

    Dispatches on the filename's extension (attacker-controlled but this is
    a prototype - worst case is a wrong parser, not a security issue).
    Raises ValueError for anything outside SUPPORTED_EXTENSIONS, so the
    caller can turn that into a clean 400 before doing any parsing work.
    """
    suffix = Path(filename).suffix.lower()

    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{suffix or filename}'. Upload a "
            ".txt, .md, .pdf, or .docx file."
        )

    if suffix in (".txt", ".md"):
        return content.decode("utf-8", errors="replace")

    if suffix == ".pdf":
        from pypdf import PdfReader
        import io

        reader = PdfReader(io.BytesIO(content))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)

    # .docx
    from docx import Document
    import io

    doc = Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs)


def truncate(text: str) -> tuple[str, bool]:
    """Returns (possibly-truncated text, whether it was truncated)."""
    if len(text) <= MAX_CHARS:
        return text, False
    return text[:MAX_CHARS], True


# --- provider calls ---------------------------------------------------------

class ReviewError(RuntimeError):
    """Base class for a provider/config problem; the endpoint maps
    subclasses to distinct, clean HTTP statuses instead of a raw 500 stack
    trace for every failure mode alike."""


class ReviewConfigError(ReviewError):
    """Missing/misconfigured API key - a local setup problem (-> 500)."""


class ReviewUpstreamError(ReviewError):
    """The provider's API itself failed (-> 502 - this server, talking
    upstream)."""


class ReviewParseError(ReviewError):
    """The model's reply didn't parse into the expected schema - a
    user-selectable outcome (wrong model choice), not a server bug (-> 422)."""


def call_mistral_review(text: str) -> ContractReview:
    """Reuses the same hosted Mistral endpoint/style as webapp/llm.py (raw
    httpx, no SDK - matches that file's convention). ministral-8b-latest has
    no guaranteed JSON-mode/structured-output support, so the schema is
    prompt-enforced and parsed leniently rather than relying on a
    provider-side guarantee.
    """
    import llm  # local import: avoids a hard dependency at module load time

    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise ReviewConfigError(
            "MISTRAL_API_KEY is not set. Create a free key at "
            "console.mistral.ai and put it in a .env file at the project "
            "root (see .env.example)."
        )

    schema_hint = ContractReview.model_json_schema()
    messages = [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                "Respond with ONLY a single JSON object that is a *direct "
                "instance* of this JSON Schema - i.e. your top-level object "
                "must itself have a \"sections\" key, exactly like the "
                "schema's \"properties\". Do not wrap it under a "
                "\"ContractReview\" key or any other key, do not include "
                "\"$schema\" or other schema-metadata keys in your answer, "
                f"no other text, no markdown code fences:\n{json.dumps(schema_hint)}"
            ),
        },
        {"role": "user", "content": _build_user_message(text)},
    ]

    try:
        resp = httpx.post(
            llm.MISTRAL_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": llm.MISTRAL_MODEL_NAME, "messages": messages},
            timeout=60.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise ReviewUpstreamError(f"Mistral API error {e.response.status_code}: {e.response.text}") from e
    except httpx.HTTPError as e:
        raise ReviewUpstreamError(f"Mistral API request failed: {e}") from e

    raw = resp.json()["choices"][0]["message"]["content"]
    return _parse_lenient_json(raw)


def _unwrap_sections(data):
    """A schema-following model occasionally nests the actual instance one
    level deeper than asked - e.g. {"ContractReview": {"sections": [...]}}
    or {"$schema": ..., "ContractReview": {...}} instead of a flat
    {"sections": [...]} - observed in practice with Mistral's smaller model
    despite an explicit instruction not to. Cheap, safe unwrap: if the
    top level already has "sections", use it as-is; otherwise, if exactly
    one of its values is itself a dict with a "sections" key, use that.
    Anything else falls through unchanged and still fails validation below
    with a clear error - this only rescues the one shape actually seen.
    """
    if isinstance(data, dict) and "sections" in data:
        return data
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, dict) and "sections" in value:
                return value
    return data


def _parse_lenient_json(raw: str) -> ContractReview:
    """Strips ```json fences a chat-style model sometimes wraps its answer
    in, then validates against ContractReview. Raises ReviewError with a
    message meant to be shown to the user (the dropdown makes "this model's
    output didn't parse" a user-selectable outcome, not a 500).
    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        data = _unwrap_sections(data)
        return ContractReview.model_validate(data)
    except Exception as e:
        raise ReviewParseError(
            "The selected model didn't return a valid structured review. "
            "Try a different model from the dropdown."
        ) from e


def call_qwen_review(text: str) -> ContractReview:
    """Alibaba Cloud's Qwen models, via DashScope's OpenAI-compatible endpoint
    (https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope).
    Reuses the official `openai` SDK already installed for call_openai_review()
    rather than adding a separate `dashscope` dependency for one provider -
    same client class, just pointed at a different base_url.

    Uses the same prompt-enforced-schema + lenient-parse approach as
    call_mistral_review() rather than OpenAI's .parse()/strict response_format:
    DashScope's json_object mode (https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output)
    guarantees valid JSON, not a specific schema, and only newer Qwen model
    versions support it at all - prompt-enforced + lenient parsing degrades
    gracefully either way. json_object mode also requires the literal word
    "json" somewhere in the prompt (DashScope 400s otherwise), which the
    schema-hint system message below already satisfies.
    """
    import openai

    api_key = os.environ.get("QWEN_API_KEY")
    if not api_key:
        raise ReviewConfigError(
            "QWEN_API_KEY is not set. Create a key on the Model Studio "
            "console's API Key page (bailian.console.alibabacloud.com) and "
            "put it in a .env file at the project root (see .env.example)."
        )

    # Unlike OpenAI/Anthropic/Mistral, DashScope's compatible-mode endpoint
    # is workspace- and region-scoped, not one fixed public URL - the
    # console's model-service page shows the exact host for your account
    # (observed shape: https://<workspace-id>.<region>.maas.aliyuncs.com/compatible-mode/v1,
    # e.g. Germany/eu-central-1). QWEN_BASE_URL carries that per-account
    # value; the generic international host below is a fallback for
    # whichever account setup it does work for, not something to rely on.
    base_url = os.environ.get("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    client = openai.OpenAI(api_key=api_key, base_url=base_url)

    schema_hint = ContractReview.model_json_schema()
    messages = [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                "Respond with ONLY a single JSON object that is a *direct "
                "instance* of this JSON Schema - i.e. your top-level object "
                "must itself have a \"sections\" key, exactly like the "
                "schema's \"properties\". Do not wrap it under a "
                "\"ContractReview\" key or any other key, do not include "
                "\"$schema\" or other schema-metadata keys in your answer, "
                f"no other text, no markdown code fences:\n{json.dumps(schema_hint)}"
            ),
        },
        {"role": "user", "content": _build_user_message(text)},
    ]

    try:
        response = client.chat.completions.create(
            # Unversioned "-plus" alias - a general-purpose Qwen model. Qwen
            # model names/versions move fast; if this 400s, check
            # help.aliyun.com/en/model-studio for current model IDs.
            model="qwen-plus",
            messages=messages,
            response_format={"type": "json_object"},
        )
    except openai.APIError as e:
        raise ReviewUpstreamError(f"Qwen API error: {e}") from e

    raw = response.choices[0].message.content
    return _parse_lenient_json(raw)


def call_openai_review(text: str) -> ContractReview:
    """Official `openai` SDK (this repo's house style is raw httpx for
    Mistral, but there's no prior OpenAI integration to match, and both the
    project's own defaults and general practice favor the official SDK when
    one exists - it gives real JSON-schema-constrained structured output
    instead of prompt-and-hope). Verified against the installed SDK version
    (client.chat.completions.parse(..., response_format=PydanticModel) ->
    response.choices[0].message.parsed) before wiring this in.
    """
    import openai

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ReviewConfigError(
            "OPENAI_API_KEY is not set. Create a key at "
            "platform.openai.com and put it in a .env file at the project "
            "root (see .env.example)."
        )

    client = openai.OpenAI(api_key=api_key)
    try:
        response = client.chat.completions.parse(
            # Unversioned alias, not a dated snapshot - if this 400s as
            # decommissioned, check platform.openai.com/docs/models for the
            # current live model IDs rather than guessing a variant.
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(text)},
            ],
            response_format=ContractReview,
        )
    except openai.APIError as e:
        raise ReviewUpstreamError(f"OpenAI API error: {e}") from e

    message = response.choices[0].message
    if message.refusal:
        raise ReviewParseError(f"OpenAI declined to review this document: {message.refusal}")
    if message.parsed is None:
        raise ReviewParseError(
            "OpenAI didn't return a valid structured review. Try a "
            "different model from the dropdown."
        )
    return message.parsed


def call_anthropic_review(text: str) -> ContractReview:
    """Official `anthropic` SDK. Verified against the installed SDK version:
    client.messages.parse(..., output_format=PydanticModel) ->
    response.parsed_output, which internally builds the same
    output_config={"format": {"type": "json_schema", ...}} structured-output
    request documented for raw-schema use.
    """
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ReviewConfigError(
            "ANTHROPIC_API_KEY is not set. Create a key at "
            "console.anthropic.com and put it in a .env file at the "
            "project root (see .env.example)."
        )

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.parse(
            model="claude-sonnet-5",
            max_tokens=16000,
            system=REVIEW_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_message(text)}],
            output_format=ContractReview,
        )
    except anthropic.APIError as e:
        raise ReviewUpstreamError(f"Anthropic API error: {e}") from e

    if response.stop_reason == "refusal":
        raise ReviewParseError("Anthropic declined to review this document.")
    if response.parsed_output is None:
        raise ReviewParseError(
            "Anthropic didn't return a valid structured review. Try a "
            "different model from the dropdown."
        )
    return response.parsed_output


# --- dispatch ---------------------------------------------------------------

PROVIDERS = {
    "mistral": call_mistral_review,
    "openai": call_openai_review,
    "anthropic": call_anthropic_review,
    "qwen": call_qwen_review,
}


def review_contract(provider: str, text: str) -> ContractReview:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}")
    return PROVIDERS[provider](text)
