// Single-document viewer page (document.html?source=<filename>). Requires
// common.js loaded first.

(async () => {
  const content = $("doc-content");
  const params = new URLSearchParams(window.location.search);
  const source = params.get("source");

  if (!source) {
    showError(content, new Error("No document specified (missing ?source=...)."));
    return;
  }

  try {
    const res = await fetch(`/api/corpus/${encodeURIComponent(source)}`);
    if (!res.ok) throw new Error(`/api/corpus/${source} -> ${res.status}`);
    const doc = await res.json();

    $("doc-title").textContent = doc.title;
    $("doc-filename").textContent = doc.source;
    document.title = `${doc.title} — RAG Search`;
    content.innerHTML = renderMarkdown(doc.text);
  } catch (err) {
    showError(content, err);
  }
})();
