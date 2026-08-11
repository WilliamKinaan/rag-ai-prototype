# Project Context

_Last updated: 2026-08-10_

## Corpus pivot (2026-08-10): legal-law demo, English only

The original 6-doc corpus (HR policies, a recipe, science, French/Spanish
docs) was replaced with a themed one: 6 English-language documents
summarizing French and Dutch law, 3 topics × 2 jurisdictions (employment,
residential tenancy, company formation) — see `data/raw/`. Every doc opens
with "_Illustrative simplified summary for a search demo — not legal
advice._" so the caveat travels with the text even when a chunk surfaces
out of context. The webapp additionally shows a persistent disclaimer
banner on both pages (`webapp/static/style.css` `.disclaimer`) — this
corpus is explicitly **not to be used for real legal advice or any real
decision**.

Consequence: the "multilingual" justification for `BAAI/bge-m3` (the
cross-lingual eval queries in the original `data/eval.json`) no longer
applies — the corpus is English-only now. Kept `bge-m3` anyway rather than
swapping models, since it still works fine and V1's other design choices
don't depend on multilinguality; just noting the original rationale for
picking it is now partly moot.

Eval queries were redesigned around **jurisdiction discrimination**: each
topic pair (e.g. `france_employment_law.md` vs
`netherlands_employment_law.md`) is deliberately hard to tell apart by
keyword, since a naive query like "notice period under French law" would
trivially win on the word "French" rather than on actual retrieval. Eval
queries instead describe a legal *scenario* using country-specific
institutions/terms of art present in the doc text (e.g. `kantonrechter`,
`huurcommissie`, `notariële akte`, `RCS`) without naming the country.

Original result (FR/NL only, 10 queries): hit@1 6/10, hit@3 10/10. The 4
misses were informative, not bugs — two were **negation-sensitivity
misses** (a query phrased "can X happen, rather than needing Y" surfaces
the doc describing Y instead of X, because embeddings match
bag-of-meaning proximity, not logical structure), two were genuine close
calls between adjacent-topic docs. No fix was applied at the time — see
git history / below for the current (post-UAE-expansion) numbers, which
supersede this.

## UAE corpus expansion (2026-08-10)

Added UAE as a **third jurisdiction** alongside France/Netherlands, plus
UAE-only topics with no FR/NL equivalent (the user's actual goal is a UAE
legal-content prototype; FR/NL were kept as the retrieval-comparison
baseline rather than removed). 6 new docs in `data/raw/`, same
"illustrative simplified summary — not legal advice" style and length as
the existing 6, each sourced from and citing official government
material (not scraped verbatim — hand-summarized from primary sources):

- `uae_employment_law.md` — Federal Decree-Law No. 33 of 2021 (MOHRE /
  uaelegislation.gov.ae): fixed-term-only contracts, MOHRE conciliation
  before Labour Court referral, end-of-service gratuity, DIFC/ADGM carve-out.
- `uae_tenant_law.md` — Dubai Law No. 26 of 2007 as amended (Dubai Land
  Department / RERA): tenancy is regulated **per emirate, not federally**
  (this doc covers Dubai only); Ejari registration, RERA rental-index
  increase cap, Rental Dispute Settlement Centre.
- `uae_company_formation.md` — Federal Decree-Law No. 32 of 2021 (u.ae):
  100% foreign ownership onshore since 2022, Cabinet Resolution No. 55 of
  2021 strategic-sector carve-out, per-emirate Department of Economy
  licensing.
- `uae_data_protection_law.md` — Federal Decree-Law No. 45 of 2021 PDPL
  (u.ae): first federal cross-sector data protection law; does not apply
  in DIFC/ADGM, which run their own GDPR-like regimes.
- `uae_free_zone_vs_mainland.md` — mainland vs free-zone licensing,
  ownership, tax, and March-2025 dual-licensing reform (u.ae).
- `uae_inheritance_wills_expats.md` — Federal Personal Status Law No. 41
  of 2022 default Sharia-based succession vs. electing home-country law
  via the DIFC Wills Service (Dubai Law No. 15 of 2017).

Sources were fetched live via web search/fetch during this session, not
recalled from model memory, given how easily UAE company/labour-law
specifics change. Sources are cited inline in each doc's header rather
than in a separate bibliography.

`data/eval.json` grew from 10 to 16 queries: 3 new UAE-vs-FR/NL
jurisdiction-discrimination queries (MOHRE conciliation, Ejari
registration, strategic-sector foreign-ownership carve-out) plus 3 plain
paraphrase queries for the UAE-only topics (PDPL scope, free-zone vs
mainland, DIFC wills). `loader.py` discovers all files in `data/raw/`
automatically (no hardcoded doc list), so no ingest code changes were
needed — just `python src/ingest.py --rebuild`.

Result at that point (16 queries, 12 docs / 30 chunks): hit@1 11/16,
hit@3 16/16 — superseded by the broader expansion below.

## UAE corpus broadening (2026-08-10, same day): 19 more topics

User's actual goal clarified: this is a demo for a **UAE-based client**
who "can't know in advance what they will test it with" — so breadth
across UAE legal domains matters more than depth on a handful of topics.
Added 19 more UAE docs (25 UAE docs total, 31 docs overall), each still
hand-summarized (not scraped verbatim) in the same disclaimer-first
style, sourced from official government/regulator sites
(uaelegislation.gov.ae, u.ae, tax.gov.ae, MOHRE, Dubai Land Department,
Ministry of Economy & Tourism) fetched live via WebSearch this session,
covering:

- **Criminal/regulatory:** `uae_criminal_law_overview.md` (Penal Code,
  Federal Decree-Law No. 31/2021), `uae_cybercrime_law.md` (No. 34/2021),
  `uae_traffic_law.md` (black-points system), `uae_aml_law.md` (No.
  20/2018).
- **Tax:** `uae_vat_law.md` (No. 8/2017, 5%), `uae_corporate_tax_law.md`
  (No. 47/2022, 9% above AED 375k, free-zone qualifying-income carve-out).
- **Commercial/consumer:** `uae_consumer_protection_law.md` (No.
  15/2020), `uae_bounced_cheque_law.md` (No. 14/2020 decriminalization),
  `uae_bankruptcy_law.md` (No. 51/2023).
- **IP:** `uae_trademark_law.md` (No. 36/2021), `uae_copyright_law.md`
  (No. 38/2021), `uae_patent_law.md` (No. 11/2021).
- **Dispute resolution:** `uae_arbitration_law.md` (No. 6/2018),
  `uae_court_system_litigation.md` (First Instance/Appeal/Cassation
  structure).
- **Family/immigration/labour:** `uae_marriage_divorce_law.md` (Civil
  Personal Status, No. 41/2022), `uae_golden_visa_immigration.md` (No.
  29/2021), `uae_domestic_workers_law.md` (No. 9/2022).
- **Real estate:** `uae_real_estate_foreign_ownership.md` (Dubai
  freehold designated areas, Law No. 7/2006), `uae_real_estate_escrow_law.md`
  (off-plan buyer protection, Dubai Law No. 8/2007).

`data/eval.json` grew again, 16 → 35 queries (one plain-paraphrase query
added per new doc, plus the original jurisdiction-discrimination and
FR/NL/UAE-3-way set kept as-is). No ingest code changes needed — same
`loader.py` auto-discovery as before, just `--rebuild`.

**Current result (35 queries, 31 docs / 80 chunks): hit@1 28/35, hit@3
35/35.** Every one of the 19 new queries lands in the top 3, and 18/19
hit@1 on the first try — the sole new-topic miss is the AML query
("convicted of laundering money even if never charged with the [predicate]
crime") surfacing `uae_bounced_cheque_law.md` first instead of
`uae_aml_law.md`, plausibly because both docs discuss financial-crime/
fraud-adjacent criminal liability in similar language. All other misses
are the same pre-existing FR/NL negation-sensitivity/close-call pattern
from before — the corpus growth didn't regress anything. Left as-is per
the same standing guidance: don't reword queries just to inflate the
score.

## Corpus goes UAE-only (2026-08-11): France/Netherlands removed, 18 more UAE topics

User asked to remove the France/Netherlands docs entirely (they'd been
kept as a retrieval-comparison baseline through the two UAE expansions
above) and add "much more" UAE data — the corpus is now **UAE-only**,
43 docs. Both changes landed together:

- **Removed:** all 6 `france_*.md`/`netherlands_*.md` docs and every
  `data/eval.json` entry that referenced them (the jurisdiction-
  discrimination query design doesn't apply once there's only one
  jurisdiction — the two surviving queries whose notes had compared UAE
  to FR/NL had their notes reworded, expected_source unchanged).
- **Added 18 more UAE docs**, same sourced-and-cited style as before,
  filling gaps the first 25 didn't cover: `uae_wage_protection_system.md`,
  `uae_unemployment_insurance_iloe.md` (Federal Decree-Law No. 13/2022),
  `uae_emiratisation_quotas.md`, `uae_sharia_inheritance_muslims.md`
  (Federal Decree-Law No. 41/2024 — the *Muslim* personal status law;
  note this is a **different** No. 41 law than the 2022 civil/non-Muslim
  one `uae_inheritance_wills_expats.md` already covered — same number,
  different year, easy to conflate), `uae_child_custody_law.md`,
  `uae_insurance_law.md` and `uae_banking_law.md` (originally Federal
  Decree-Law No. 48/2023 and No. 14/2018 respectively, both now
  consolidated under Federal Decree-Law No. 6/2025 — cross-referenced as
  companion docs since they're the same current law's two halves),
  `uae_maritime_law.md` (No. 43/2023), `uae_media_law.md` (No. 55/2023),
  `uae_climate_environmental_law.md` (No. 11/2024),
  `uae_electronic_transactions_law.md` (No. 46/2021),
  `uae_medical_liability_law.md` (No. 4/2016), `uae_anti_discrimination_law.md`
  (current law is No. 34/2023, superseding the older 2015/2019 one — flagged
  in the doc itself since this area of UAE law has moved unusually fast),
  `uae_mortgage_law_dubai.md` (Dubai Law No. 14/2008),
  `uae_difc_overview.md` and `uae_adgm_overview.md` (the two common-law
  financial free zones, previously only mentioned in passing by other
  docs), `uae_off_plan_property_registration_oqood.md` (Dubai Law No.
  13/2008 — deliberately close in topic to `uae_real_estate_escrow_law.md`,
  same off-plan purchase but a different protection mechanism), and
  `uae_labour_working_hours_leave.md` (working hours/overtime/leave
  detail, complementing the original `uae_employment_law.md`). All
  sourced live via WebSearch this session, not recalled from memory.

`data/eval.json`: 35 → 43 queries (10 FR/NL entries removed, 18 new
plain-paraphrase queries added, 2 notes reworded as above).

**Current result (43 queries, 43 docs / 118 chunks): hit@1 38/43, hit@3
43/43.** All 5 misses are informative close calls between genuinely
adjacent UAE topics (e.g. the Ejari-registration query landing on
`uae_off_plan_property_registration_oqood.md` — both are "which system
registers this contract" scenarios; the AML query still lands on
`uae_bounced_cheque_law.md` first, same pattern as the prior expansion) —
none are regressions, and 3 of the 5 misses were deliberately designed as
close-call pairs in the query notes rather than accidents. Not tuned
toward 10/10 for the same standing reason as before.

**Not yet done as of this note:** the live Oracle deployment still has
the old FR/NL corpus and old CSS — this corpus change and the earlier
light-theme CSS change are committed and pushed to `main` but **not
deployed**, per the user's standing instruction to always confirm before
running `deploy-oracle.sh` (see `CONTEXT-deploy-oracle.md`).

## Goal

Learn how RAG works by building it from scratch (no LangChain/LlamaIndex),
in stages:
- **V1 (done):** semantic search only — ingest, chunk, embed, store,
  retrieve. No LLM.
- **V2 (in progress):** wrap `retrieve()` with a generation layer to
  produce grounded answers. See below — the local-model assumption was
  superseded.
- **Later:** turn the chatbot into an agent.

## Status: V1 complete and verified

Ingestion + retrieval pipeline works end-to-end. Current eval harness
score (UAE-only legal corpus, see notes above): **hit@1: 38/43, hit@3:
43/43**.

## Decisions locked in (V1)

- **Vector store:** Chroma, `PersistentClient`, persisted to `./chroma_db/`
  (gitignored), collection `documents`, `hnsw:space: cosine`.
- **Embedding model:** `BAAI/bge-m3` via `sentence-transformers`, fully
  local/offline. No query-instruction prefix needed (unlike bge-v1.5).
  `normalize_embeddings=True` used for hygiene, though not strictly
  required for correctness under Chroma's cosine space.
- **Chunking:** dependency-free, paragraph-aware packing to ~1000 chars
  with ~150 char overlap; word-boundary fallback for any single paragraph
  too long to fit in one chunk. See `src/chunking.py`.
- **Interface:** CLI scripts (`ingest.py`, `query.py`), no notebook/web UI.
- Single `embed(texts, is_query=False)` function (`src/embedding.py`) used
  identically by both ingest and query, so normalization/prefix handling
  can't silently diverge between the two paths.
- Collection metadata stores `model_name`/`embedding_dim`/`chunk_size`/
  `overlap` at creation; both `ingest.py` and `query.py` assert current
  `config.py` still matches before writing/reading — prevents silently
  garbage rankings after a config change without `--rebuild`. Verified
  this actually fires on mismatch.

## Environment gotcha (important if reinstalling)

This machine is an **Intel Mac (Homebrew `/usr/local`), Python 3.12**, so
PyTorch is capped at **2.2.2** (no newer wheel exists for this
platform/arch) and runs **CPU-only** (no MPS/GPU). Recent
`transformers`/`sentence-transformers` require `torch>=2.4` and break the
import chain on this box. Fix already applied and pinned in
`requirements.txt`:

```
sentence-transformers==3.3.1
transformers==4.46.3
numpy<2
```

This combination was verified to reproduce cleanly from a **fresh venv**
installing only from `requirements.txt` (not just patched by hand in the
working venv) — see `rag-env/`. First run downloads ~2GB of model weights;
expect seconds-per-batch encoding, not instant, since there's no GPU.

**Superseded:** this used to say V2 would run Mistral locally via
llama.cpp/Ollama, since this box is CPU-only. Decision reversed — V2
instead calls the **hosted Mistral AI API** (`ministral-8b-latest`,
free tier via console.mistral.ai), which needs no local model weights
and no GPU. See `CONTEXT-webapp.md`'s "V2 interactive chat" section for
the implementation.

## Project layout

data/raw/          43 sample docs, UAE-only (English — see the corpus-pivot
                    and UAE-expansion notes above for how it got here and
                    the France/Netherlands docs it replaced): employment,
                    tenancy, company formation, data protection, free zone
                    vs mainland, inheritance/wills (non-Muslim + Sharia),
                    criminal law, cybercrime, traffic, consumer protection,
                    VAT, corporate tax, marriage/divorce, child custody,
                    real estate (foreign ownership, escrow, off-plan/Oqood,
                    mortgages), bounced cheques, AML, trademarks, copyright,
                    patents, bankruptcy, arbitration, golden visa/immigration,
                    domestic workers, working hours/leave, wage protection,
                    unemployment insurance, Emiratisation, insurance,
                    banking, maritime, media, climate, e-transactions,
                    medical liability, anti-discrimination, DIFC, ADGM, and
                    the court system — see the corpus-pivot note above for
                    the full list and sources
data/eval.json      43 hand-built (query, expected_source) pairs, all
                    plain-paraphrase queries designed backwards from the
                    corpus per topic (see corpus-pivot note for why the
                    earlier jurisdiction-discrimination query design was
                    dropped along with the FR/NL docs)
src/config.py       all tunables (paths, model name, chunk size/overlap, k)
src/embedding.py     embed(texts, is_query=False) — shared by ingest+query
src/chunking.py      paragraph-pack chunker + word-boundary fallback
src/loader.py        reads .txt/.md from data/raw/
src/ingest.py        builds/upserts the Chroma collection; --rebuild flag
src/query.py         retrieve(query, k) -> ranked chunks; --eval mode
requirements.txt     pinned versions (see gotcha above)
README.md            usage instructions
chroma_db/          persisted index (gitignored, generated by ingest.py)
rag-env/            python venv (gitignored)
```

## How to resume / verify it still works

```bash
source rag-env/bin/activate
python src/ingest.py          # builds chroma_db/ if missing
python src/query.py --eval    # should print hit@1: 38/43  hit@3: 43/43
```

## Known caveats / non-blocking notes

- The eval set is a smoke test, not a statistically meaningful benchmark.
  With 118 chunks (as of the UAE-only pivot) it's a more meaningful signal
  than the original 13-chunk version, but still hand-built and
  backwards-designed from the corpus rather than an independent benchmark.
- The 5 current eval misses are expected/documented (see the corpus-pivot
  note above) — don't "fix" them by rewording the queries; if hit@1
  changes on a future run, check whether the corpus or config changed
  first.
- `_split_by_words` (the long-paragraph fallback in `chunking.py`) rejoins
  words with a single space, so if it ever fires on text that still
  contains a `\n\n` paragraph separator, that separator gets flattened to
  a space in the output chunk. Harmless for retrieval, just not exact
  whitespace round-tripping. Documented in the module docstring.

## V2 status: interactive chat built (2026-08-10)

Generation layer added: `webapp/llm.py` + `POST /api/chat` (see
`CONTEXT-webapp.md`'s "V2 interactive chat" section for the full
design). Reuses `search()`/`embed()` from `src/query.py` unchanged —
`retrieve(query, k)` itself wasn't touched, only wrapped. Not yet
user-verified end-to-end with a real `MISTRAL_API_KEY` (needs the
user's own free-tier key from console.mistral.ai) — the retrieval
path, no-context short-circuit, and missing-key error path were all
smoke-tested locally without one.
