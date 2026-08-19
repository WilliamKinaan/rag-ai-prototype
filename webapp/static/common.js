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
  if (!res.ok) {
    // FastAPI's default error body is {"detail": "..."} - surface that
    // (e.g. the rate limiter's "Rate limit reached — try again in 8s")
    // instead of just the bare status code, when it's there to read.
    let message = `${url} -> ${res.status}`;
    try {
      const data = await res.json();
      if (data && typeof data.detail === "string") message = data.detail;
    } catch {
      // no JSON body — keep the generic message
    }
    throw new Error(message);
  }
  return res.json();
}

function showError(container, err) {
  container.innerHTML = "";
  container.appendChild(el("p", "error", `Something went wrong: ${err.message}`));
}

// Small, dependency-free Markdown -> HTML renderer for LLM chat replies and
// the raw .md corpus documents shown in the corpus viewer — both arrive as
// plain Markdown text that was previously being dropped into the DOM as
// literal text (visible "**bold**" asterisks, etc.) instead of rendered.
// Escapes HTML first so this is safe against a model reply or document
// that happens to contain "<", ">", or "&" — only the markdown syntax this
// function recognizes itself produces real tags.
function escapeHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Applies inline formatting to a single already-escaped line: code spans
// first (so bold/italic markers inside a code span aren't touched), then
// bold, then italic — bold before italic so "**x**" isn't misread as
// italic-wrapped-in-italic by the single-asterisk pattern.
//
// Underscore variants require a non-word character (or string boundary) on
// both sides of the delimiter pair — real Markdown's "intraword emphasis"
// rule for underscores, unlike asterisks, which are allowed mid-word. This
// matters here specifically because the model cites source filenames like
// `uae_labour_working_hours_leave.md` inline in its replies: without the
// boundary check, every underscore in a filename reads as an emphasis
// marker and fragments it into nonsense italics.
function renderInlineMarkdown(line) {
  return line
    .replace(/`([^`]+?)`/g, "<code>$1</code>")
    // [text](url) -> plain "text": the model sometimes cites a source doc
    // as a markdown link, but "url" here is just the bare filename again
    // (not a route this site actually serves), so a real <a> would either
    // duplicate the text or 404 — showing the link text alone reads best.
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\*\*([^*]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(?<!\w)__([^_\s][^_]*?)__(?!\w)/g, "<strong>$1</strong>")
    .replace(/\*([^*]+?)\*/g, "<em>$1</em>")
    .replace(/(?<!\w)_([^_\s][^_]*?)_(?!\w)/g, "<em>$1</em>");
}

// Block-level: splits on blank lines into paragraphs/lists, recognizing
// "# Heading" lines and "-"/"*"/"1." list items — the subset actually used
// by this app's corpus docs and the LLM's replies. Anything else renders
// as an ordinary paragraph with single newlines becoming <br>.
function renderMarkdown(raw) {
  const blocks = escapeHtml(raw).split(/\n{2,}/);
  return blocks
    .map((block) => {
      const lines = block.split("\n").filter((l) => l.length > 0);
      if (lines.length === 0) return "";

      const heading = lines.length === 1 && lines[0].match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        const level = Math.min(heading[1].length + 1, 6); // h1 reserved for page title
        return `<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`;
      }

      if (lines.every((l) => /^[-*]\s+/.test(l))) {
        const items = lines.map((l) => `<li>${renderInlineMarkdown(l.replace(/^[-*]\s+/, ""))}</li>`);
        return `<ul>${items.join("")}</ul>`;
      }
      if (lines.every((l) => /^\d+\.\s+/.test(l))) {
        const items = lines.map((l) => `<li>${renderInlineMarkdown(l.replace(/^\d+\.\s+/, ""))}</li>`);
        return `<ol>${items.join("")}</ol>`;
      }

      // Apply inline formatting across the whole paragraph, not line by
      // line, then turn remaining newlines into <br> — an emphasis span
      // that wraps across a line break within one paragraph (several of
      // this app's own corpus docs do this for their multi-line "Sourced
      // from ..." disclaimer sentences) needs the full text in one string
      // to be recognized, since the opening/closing markers land on
      // different lines.
      return `<p>${renderInlineMarkdown(lines.join("\n")).replace(/\n/g, "<br>")}</p>`;
    })
    .join("");
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

// --- Rate-limit badge -------------------------------------------------
// Every response carries X-RateLimit-{Limit,Window-Seconds,Remaining,Reset}
// headers (see webapp/app.py's middleware) - read them off responses this
// page was already making, and reflect them in a small fixed badge. No
// dedicated polling: the only extra request is a one-shot GET on page
// load, to have a number on screen before the visitor's first action.
//
// Patches window.fetch once, globally, rather than editing postJSON (some
// pages here - e.g. the document/corpus viewers - fetch directly, not
// through postJSON) so every call site is covered without changes.

let _rateLimitResetTimer = null;

function _rateLimitBadgeText(remaining, secondsLeft) {
  const left = `${remaining} request${remaining === 1 ? "" : "s"} left`;
  return secondsLeft > 0 ? `${left} · resets in ${secondsLeft}s` : left;
}

function _renderRateLimitBadge(remaining, limit, resetSeconds, windowSeconds) {
  const badge = document.getElementById("rate-limit-badge");
  if (!badge) return;

  const known = remaining !== null && limit !== null && !Number.isNaN(remaining) && !Number.isNaN(limit);
  // Nothing's been spent yet (a fresh window, or right after one just
  // reset) - a countdown here would just be ticking down to reset a budget
  // that's already full, which reads as a bug rather than information.
  const nothingToReset = known && remaining >= limit;
  badge.textContent = known ? _rateLimitBadgeText(remaining, nothingToReset ? 0 : resetSeconds) : "";
  badge.title =
    known && windowSeconds
      ? `Simple demo rate limit (not Mistral's own) — up to ${limit} requests per ${windowSeconds}s`
      : "";
  badge.hidden = !known;

  if (_rateLimitResetTimer) clearInterval(_rateLimitResetTimer);
  if (!known || nothingToReset) return;

  let secondsLeft = resetSeconds;
  _rateLimitResetTimer = setInterval(() => {
    secondsLeft -= 1;
    if (secondsLeft <= 0) {
      clearInterval(_rateLimitResetTimer);
      // The limiter's fixed window always resets fully once it elapses
      // (see _FixedWindowLimiter._reset_if_elapsed in rate_limiter.py) -
      // apply that same rule here instead of leaving the last-known
      // `remaining` stale until the next real request refreshes it.
      badge.textContent = _rateLimitBadgeText(limit, 0);
      return;
    }
    badge.textContent = _rateLimitBadgeText(remaining, secondsLeft);
  }, 1000);
}

function _updateRateLimitBadgeFromHeaders(headers) {
  const remaining = headers.get("X-RateLimit-Remaining");
  const limit = headers.get("X-RateLimit-Limit");
  const reset = headers.get("X-RateLimit-Reset");
  const window = headers.get("X-RateLimit-Window-Seconds");
  if (remaining === null || limit === null || reset === null) return;
  _renderRateLimitBadge(Number(remaining), Number(limit), Number(reset), Number(window));
}

function _injectRateLimitBadge() {
  const badge = el("div", "rate-limit-badge");
  badge.id = "rate-limit-badge";
  badge.hidden = true;
  document.body.appendChild(badge);
}

const _nativeFetch = window.fetch.bind(window);
window.fetch = async (...args) => {
  const response = await _nativeFetch(...args);
  _updateRateLimitBadgeFromHeaders(response.headers);
  return response;
};

_injectRateLimitBadge();
// One-shot seed so the badge shows a real number before the visitor's
// first action - not a poll, this fires once per page load only.
_nativeFetch("/api/rate-limit/status")
  .then((response) => response.json())
  .then((data) =>
    _renderRateLimitBadge(data.remaining, data.limit, data.reset_in, data.window_seconds)
  )
  .catch(() => {
    /* leave the badge hidden if this one-shot call fails */
  });
