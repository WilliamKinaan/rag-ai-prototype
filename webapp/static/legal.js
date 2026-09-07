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
const toolbar = $("review-toolbar");
const downloadBtn = $("download-btn");

// Set alongside a successful renderReview() call so downloadReport() has
// something to serialize - the API response itself, plus the two bits of
// context (original filename, human-readable model label) that aren't
// part of it. Cleared whenever the output area is cleared so a stale
// download can't survive past a new upload or a failed re-run.
let lastData = null;
let lastFilename = null;
let lastProviderLabel = null;
let lastProviderValue = null;

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

// Plain-text rendering of the same data renderReview() puts on screen -
// kept as a separate function (rather than scraping output.textContent)
// so the file's structure doesn't depend on the DOM layout renderReview()
// happens to produce.
function buildReportText() {
  const lines = [
    "Legal Assistant — Contract Review",
    `Document: ${lastFilename}`,
    `Model: ${lastProviderLabel}`,
    `Generated: ${new Date().toLocaleString()}`,
    "",
    "Testing prototype output — not legal advice. Review with a qualified lawyer.",
    "",
  ];

  if (lastData.truncated) {
    lines.push(
      "Note: this document was longer than the demo's limit and was " +
        "truncated before review — results may miss sections near the end.",
      ""
    );
  }

  const sections = lastData.review.sections || [];
  if (sections.length === 0) {
    lines.push("No issues flagged in this document.");
  } else {
    for (const section of sections) {
      lines.push(`## ${section.section}`);
      for (const issue of section.issues || []) {
        lines.push(`- Flagged text: ${issue.text}`, `  Suggestion: ${issue.suggestion}`);
      }
      lines.push("");
    }
  }

  return lines.join("\n");
}

// Client-side-only download (no server round trip) via a throwaway object
// URL, following the standard Blob -> <a download> -> revoke pattern.
function downloadReport() {
  if (!lastData) return;

  const blob = new Blob([buildReportText()], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = el("a");
  link.href = url;
  // "original name + model name + suggestions", e.g.
  // "my-contract-mistral-suggestions.txt" - lastProviderValue is the
  // dropdown's value (mistral/openai/anthropic), already filename-safe,
  // as opposed to lastProviderLabel's display text ("Mistral
  // (ministral-8b)"), which isn't.
  const baseName = lastFilename.replace(/\.[^.]+$/, "");
  link.download = `${baseName}-${lastProviderValue}-suggestions.txt`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function analyze() {
  errorBox.innerHTML = "";
  output.innerHTML = "";
  toolbar.hidden = true;
  lastData = null;

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
    const data = await res.json();
    lastData = data;
    lastFilename = file.name;
    lastProviderValue = providerSelect.value;
    lastProviderLabel = providerSelect.options[providerSelect.selectedIndex].text;
    toolbar.hidden = false;
    renderReview(data);
  } catch (err) {
    showError(errorBox, err);
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
}

btn.addEventListener("click", analyze);
downloadBtn.addEventListener("click", downloadReport);
