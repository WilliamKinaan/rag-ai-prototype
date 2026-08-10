// Full pipeline demo (explore.html). Requires common.js loaded first.

const SAMPLE_TEXT = `Dutch employment contracts are generally either permanent (vast contract)
or temporary (tijdelijk contract), and it's common for a relationship to
start with one or more temporary contracts before converting to a
permanent one. Contracts usually include a short trial period (proeftijd)
at the very start, during which either the employer or the employee can
end the relationship immediately, without notice and without needing
anyone else's approval.

Outside that initial trial period, an employer generally cannot simply
dismiss an employee on their own decision.`;

let currentChunks = []; // texts from the most recent /api/chunk call
let playgroundTexts = []; // texts from the most recent /api/embed call

// --- 1. Chunking ---------------------------------------------------------

$("chunk-input").value = SAMPLE_TEXT;

$("chunk-btn").addEventListener("click", async () => {
  const output = $("chunk-output");
  const btn = $("chunk-btn");
  btn.disabled = true;
  output.innerHTML = "Chunking…";
  try {
    const text = $("chunk-input").value;
    const { chunks } = await postJSON("/api/chunk", { text });
    currentChunks = chunks.map((c) => c.text);

    output.innerHTML = "";
    output.appendChild(el("p", "meta", `${text.length} chars in -> ${chunks.length} chunk(s) out`));
    for (const c of chunks) {
      const card = el("div", "card");
      card.appendChild(el("div", "meta", `chunk ${c.index} — ${c.char_count} chars`));
      card.appendChild(el("div", null, c.text));
      output.appendChild(card);
    }
    $("embed-btn").disabled = chunks.length === 0;
  } catch (err) {
    showError(output, err);
  } finally {
    btn.disabled = false;
  }
});

// --- 2. Embedding ----------------------------------------------------------

$("embed-btn").addEventListener("click", async () => {
  const output = $("embed-output");
  const btn = $("embed-btn");
  btn.disabled = true;
  output.innerHTML = "Embedding… (first call loads the model, can take a while)";
  try {
    const { embeddings } = await postJSON("/api/embed", { texts: currentChunks });
    playgroundTexts = currentChunks.slice();

    output.innerHTML = "";
    for (const [i, e] of embeddings.entries()) {
      const card = el("div", "card");
      card.appendChild(el("div", "meta", `chunk ${i} — ${e.dim} dimensions`));
      card.appendChild(
        el("div", "vec-preview", `[${e.preview.map((v) => v.toFixed(4)).join(", ")}, ...]`)
      );
      output.appendChild(card);
    }
  } catch (err) {
    showError(output, err);
  } finally {
    btn.disabled = false;
  }
});

// --- 3. Storage -----------------------------------------------------------

async function loadStorageStats() {
  const output = $("storage-output");
  try {
    const res = await fetch("/api/index-stats");
    if (!res.ok) throw new Error(`/api/index-stats -> ${res.status}`);
    const stats = await res.json();

    const grid = el("div", "stats-grid");
    const items = [
      ["doc_count", "Documents"],
      ["chunk_count", "Chunks"],
      ["embedding_dim", "Dimensions"],
      ["chunk_size", "Chunk size (chars)"],
      ["overlap", "Overlap (chars)"],
    ];
    for (const [key, label] of items) {
      const stat = el("div", "stat");
      stat.appendChild(el("div", "value", String(stats[key])));
      stat.appendChild(el("div", "label", label));
      grid.appendChild(stat);
    }
    output.innerHTML = "";
    output.appendChild(grid);
    output.appendChild(el("p", "meta", `Model: ${stats.model_name}`));
  } catch (err) {
    showError(output, err);
  }
}

loadStorageStats();

// --- 4. Query --------------------------------------------------------------

$("query-btn").addEventListener("click", async () => {
  const output = $("query-output");
  const btn = $("query-btn");
  const query = $("query-input").value.trim();
  if (!query) return;

  const maxDistance = parseFloat($("max-distance").value);
  const threshold = Number.isFinite(maxDistance) ? maxDistance : 0.5;

  btn.disabled = true;
  output.innerHTML = "Searching…";
  try {
    const data = await postJSON("/api/query", {
      query,
      k: 3,
      playground_texts: playgroundTexts,
      max_distance: threshold,
    });

    output.innerHTML = "";
    output.appendChild(
      el(
        "p",
        "vec-preview",
        `query embedding (${data.embedding_dim}-dim): [${data.embedding_preview
          .map((v) => v.toFixed(4))
          .join(", ")}, ...]`
      )
    );
    output.appendChild(
      el("p", "meta", `Lower distance = more similar. Showing matches with distance ≤ ${threshold}.`)
    );

    if (playgroundTexts.length > 0) {
      renderResultGroup(output, "Your text (not indexed)", data.playground_results);
    }
    if (data.corpus_results.length === 0) {
      output.appendChild(el("p", "meta", "No corpus matches within that distance threshold. Try raising it."));
    } else {
      renderResultGroup(output, "Sample corpus (indexed)", data.corpus_results);
    }
  } catch (err) {
    showError(output, err);
  } finally {
    btn.disabled = false;
  }
});
