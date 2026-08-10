// Corpus listing page (corpus.html). Requires common.js loaded first.

(async () => {
  const output = $("corpus-list");
  try {
    const res = await fetch("/api/corpus");
    if (!res.ok) throw new Error(`/api/corpus -> ${res.status}`);
    const { documents } = await res.json();

    output.innerHTML = "";
    for (const doc of documents) {
      const link = el("a");
      link.href = `/document.html?source=${encodeURIComponent(doc.source)}`;
      link.target = "_blank";
      link.rel = "noopener";
      const title = el("div", null, doc.title);
      const filename = el("div", "filename", doc.source);
      link.appendChild(title);
      link.appendChild(filename);
      output.appendChild(link);
    }
  } catch (err) {
    showError(output, err);
  }
})();
