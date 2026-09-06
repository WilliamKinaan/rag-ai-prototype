// Legal Assistant page (legal.html). Requires common.js loaded first.
//
// Uses a direct fetch() with FormData rather than common.js's postJSON()
// since this is a multipart file upload, not a JSON body - same reasoning
// document.js already follows for its own direct-fetch call (see the
// comment on postJSON in common.js).

const fileInput = $("contract-file");
const providerSelect = $("provider-select");
const btn = $("review-btn");
const errorBox = $("review-error");
const output = $("review-output");

function renderReview(data) {
  output.innerHTML = "";

  if (data.truncated) {
    output.appendChild(
      el(
        "div",
        "review-notice",
        "This document was longer than the demo's limit and was truncated " +
          "before review — results may miss sections near the end."
      )
    );
  }

  const sections = data.review.sections || [];
  if (sections.length === 0) {
    output.appendChild(el("p", "meta", "No issues flagged in this document."));
    return;
  }

  for (const section of sections) {
    const card = el("div", "review-section");
    card.appendChild(el("h3", null, section.section));
    for (const issue of section.issues || []) {
      const issueCard = el("div", "review-issue");
      issueCard.appendChild(el("span", "label", "Flagged text"));
      issueCard.appendChild(el("p", "flagged-text", issue.text));
      issueCard.appendChild(el("span", "label", "Suggestion"));
      issueCard.appendChild(el("p", "suggestion", issue.suggestion));
      card.appendChild(issueCard);
    }
    output.appendChild(card);
  }
}

async function analyze() {
  errorBox.innerHTML = "";
  output.innerHTML = "";

  const file = fileInput.files[0];
  if (!file) {
    showError(errorBox, new Error("Choose a file first."));
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  formData.append("provider", providerSelect.value);

  const originalLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Analyzing… (this can take up to 30s)";

  try {
    const res = await fetch("/api/legal-review", { method: "POST", body: formData });
    if (!res.ok) {
      // Mirrors postJSON's error handling (common.js) - FastAPI's default
      // error body is {"detail": "..."}.
      let message = `/api/legal-review -> ${res.status}`;
      try {
        const data = await res.json();
        if (data && typeof data.detail === "string") message = data.detail;
      } catch {
        // no JSON body — keep the generic message
      }
      throw new Error(message);
    }
    renderReview(await res.json());
  } catch (err) {
    showError(errorBox, err);
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
}

btn.addEventListener("click", analyze);
