// Shared helpers used by both the query-only landing page (query.js) and
// the full pipeline demo (explore.js). Load this before either.

const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

function showError(container, err) {
  container.innerHTML = "";
  container.appendChild(el("p", "error", `Something went wrong: ${err.message}`));
}

// results: [{source, chunk_index, text, distance}] (corpus) or
// [{index, text, distance}] (playground) — the branch below tells them apart.
function renderResultGroup(container, title, results) {
  const group = el("div", "result-group");
  group.appendChild(el("h3", null, title));
  if (!results || results.length === 0) {
    group.appendChild(el("p", "meta", "(none)"));
  } else {
    for (const r of results) {
      const card = el("div", "card");
      const label = r.source ? `${r.source} #chunk${r.chunk_index}` : `your text #${r.index}`;
      const meta = el("div", "meta");
      meta.appendChild(document.createTextNode(label + " — distance: "));
      const dist = el("span", "distance", r.distance.toFixed(4));
      meta.appendChild(dist);
      card.appendChild(meta);
      card.appendChild(el("div", null, r.text));
      group.appendChild(card);
    }
  }
  container.appendChild(group);
}
