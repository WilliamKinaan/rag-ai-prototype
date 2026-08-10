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

// Single shared tooltip element for source-chunk previews, appended to
// <body> (not wherever renderSources() is called) and positioned with
// `fixed`, following the cursor. Deliberately *not* the native `title`
// attribute: chat sources live inside .chat-log (`overflow-y: auto`,
// scrolled to the bottom where new messages land), and the native
// tooltip's ~1s hover delay plus general low visibility made it easy to
// miss there. `position: fixed` also sidesteps any overflow-clipping
// concerns since it's anchored to the viewport, not to .chat-log.
let sourceTooltip = null;
function ensureSourceTooltip() {
  if (!sourceTooltip) {
    sourceTooltip = el("div", "source-tooltip");
    document.body.appendChild(sourceTooltip);
  }
  return sourceTooltip;
}

function positionSourceTooltip(e) {
  const tip = ensureSourceTooltip();
  const margin = 14;
  const maxLeft = window.innerWidth - tip.offsetWidth - margin;
  const maxTop = window.innerHeight - tip.offsetHeight - margin;
  tip.style.left = `${Math.max(margin, Math.min(e.clientX + margin, maxLeft))}px`;
  tip.style.top = `${Math.max(margin, Math.min(e.clientY + margin, maxTop))}px`;
}

// Compact inline citation list for a chat answer, distinct from
// renderResultGroup's full result cards (chat sources sit under a
// message bubble, not in their own labeled section). Hovering (or
// focusing, for keyboard users) a source tag shows the chunk's full text
// in the tooltip above.
// sources: [{source, chunk_index, text, distance}]
function renderSources(container, sources) {
  if (!sources || sources.length === 0) return;
  const wrap = el("div", "sources");
  wrap.appendChild(el("span", "sources-label", "Sources: "));
  sources.forEach((s, i) => {
    const tag = el("span", "source-tag", `${s.source} #chunk${s.chunk_index}`);
    tag.tabIndex = 0;
    tag.setAttribute("aria-label", s.text);
    tag.addEventListener("mouseenter", (e) => {
      const tip = ensureSourceTooltip();
      tip.textContent = s.text;
      tip.classList.add("visible");
      positionSourceTooltip(e);
    });
    tag.addEventListener("mousemove", positionSourceTooltip);
    tag.addEventListener("mouseleave", () => {
      if (sourceTooltip) sourceTooltip.classList.remove("visible");
    });
    wrap.appendChild(tag);
    if (i < sources.length - 1) wrap.appendChild(document.createTextNode(" "));
  });
  container.appendChild(wrap);
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
