// Model Evaluation page (Phase 4 - see plans/phase4-model-evaluation.md).
// Public page: only fetches the baseline scorecard and lets a visitor
// trigger "Evaluate now", whose backend action is admin-gated
// independently (see webapp/app.py's admin_router).

async function loadResults() {
  const container = $("results-list");
  try {
    const res = await fetch("/api/legal-eval/results?approach=baseline");
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();

    container.innerHTML = "";
    for (const row of data.results) {
      const text = row.evaluated
        ? `${row.label}: ${row.correct} out of ${row.total}`
        : `${row.label}: not yet evaluated`;
      container.appendChild(el("div", "card", text));
    }
  } catch (e) {
    showError(container, e);
  }
}

// Points a visitor at /admin via a real page navigation (not fetch) so
// Cloudflare Access's login redirect can actually complete - see the
// note in onEvaluateNow() below for why a fetch can't do this itself.
function renderSignInPrompt(container) {
  container.innerHTML = "";
  container.appendChild(document.createTextNode("Admin sign-in required. "));
  const link = document.createElement("a");
  link.href = "/admin";
  link.textContent = "Sign in, then come back and try again";
  container.appendChild(link);
}

async function onEvaluateNow() {
  const status = $("evaluate-status");
  status.textContent = "…";
  try {
    // redirect: "manual" turns an unauthenticated hit on this
    // Cloudflare-Access-protected route into a *detectable* opaque
    // redirect instead of a bare network-error throw - this page is
    // public, so a visitor's first-ever click here may have no
    // CF_Authorization cookie yet (see CONTEXT-admin-auth.md §6a: an
    // unauthenticated request to /api/admin/* gets a cross-origin 302 to
    // Cloudflare's login, which a plain fetch can't follow usefully).
    const res = await fetch("/api/admin/legal-eval/run", {
      method: "POST",
      redirect: "manual",
    });

    if (res.type === "opaqueredirect" || res.status === 0) {
      renderSignInPrompt(status);
      return;
    }
    if (!res.ok) {
      // Reachable locally when CF_ACCESS_TEAM_DOMAIN/AUD are unset (every
      // admin route 401s by design - see cf_access.py), or in prod via
      // the documented raw-IP path that bypasses Cloudflare entirely.
      const data = await res.json().catch(() => ({}));
      showError(status, new Error(data.detail || `${res.status} ${res.statusText}`));
      return;
    }

    // Stub for now (see webapp/app.py's admin_run_legal_eval) - proves
    // the admin-gated round trip; no real evaluation has run yet.
    status.textContent = "Request succeeded, but evaluation logic isn't built yet.";
    loadResults();
  } catch (e) {
    // Cross-origin redirect with no CORS headers (browsers that don't
    // surface it as res.type === "opaqueredirect"), or any other network
    // failure not caught above.
    renderSignInPrompt(status);
  }
}

$("evaluate-btn").addEventListener("click", onEvaluateNow);
loadResults();
