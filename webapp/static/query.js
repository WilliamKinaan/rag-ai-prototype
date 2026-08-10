// Query-only landing page (index.html). Requires common.js loaded first.
// Default below must match DEFAULT_MAX_DISTANCE in webapp/app.py — the
// input's value="0.5" in index.html is the actual default; this is just
// the fallback if that value is somehow missing/unparseable.
const FALLBACK_MAX_DISTANCE = 0.5;

$("query-btn").addEventListener("click", async () => {
  const output = $("query-output");
  const btn = $("query-btn");
  const query = $("query-input").value.trim();
  if (!query) return;

  const maxDistance = parseFloat($("max-distance").value);
  const threshold = Number.isFinite(maxDistance) ? maxDistance : FALLBACK_MAX_DISTANCE;

  btn.disabled = true;
  output.innerHTML = "Searching…";
  try {
    const data = await postJSON("/api/query", { query, k: 3, max_distance: threshold });

    output.innerHTML = "";
    output.appendChild(
      el("p", "meta", `Lower distance = more similar. Showing matches with distance ≤ ${threshold}.`)
    );
    if (data.corpus_results.length === 0) {
      output.appendChild(el("p", "meta", "No matches within that distance threshold. Try raising it."));
    } else {
      renderResultGroup(output, "Sample corpus (indexed)", data.corpus_results);
    }
  } catch (err) {
    showError(output, err);
  } finally {
    btn.disabled = false;
  }
});

$("query-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("query-btn").click();
});
