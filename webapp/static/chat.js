// Interactive chat page (index.html). Requires common.js loaded first.
// Default below must match DEFAULT_MAX_DISTANCE in webapp/app.py — see
// search.js for the same convention.
const FALLBACK_MAX_DISTANCE = 0.6;

// Plain in-memory history, cleared on reload — no persistence, matches the
// rest of this app. Only {role, content} pairs go to the server; sources
// are UI-only and never sent back.
const history = [];

const log = $("chat-log");

function addMessage(role, text, { noContext = false, pending = false } = {}) {
  const classes = ["chat-msg", role];
  if (noContext) classes.push("no-context");
  if (pending) classes.push("pending");
  const msg = el("div", classes.join(" "));
  // Assistant replies are Markdown from the model (bold/italic/lists) and
  // get rendered as such; the user's own typed message and the "thinking…"
  // placeholder are plain text, shown as-is.
  if (role === "assistant" && !pending) {
    msg.innerHTML = renderMarkdown(text);
  } else {
    msg.textContent = text;
  }
  log.appendChild(msg);
  log.scrollTop = log.scrollHeight;
  return msg;
}

async function send() {
  const input = $("chat-input");
  const btn = $("chat-btn");
  const errorBox = $("chat-error");
  const message = input.value.trim();
  if (!message) return;

  const maxDistance = parseFloat($("max-distance").value);
  const threshold = Number.isFinite(maxDistance) ? maxDistance : FALLBACK_MAX_DISTANCE;

  errorBox.innerHTML = "";
  addMessage("user", message);
  input.value = "";
  input.disabled = true;
  btn.disabled = true;
  const pending = addMessage("assistant", "Mistral is thinking…", { pending: true });

  try {
    const data = await postJSON("/api/chat", {
      message,
      history,
      max_distance: threshold,
    });

    pending.remove();
    addMessage("assistant", data.reply, { noContext: data.no_context });
    if (!data.no_context) renderSources(log, data.sources);
    log.scrollTop = log.scrollHeight;

    history.push({ role: "user", content: message });
    history.push({ role: "assistant", content: data.reply });
  } catch (err) {
    pending.remove();
    showError(errorBox, err);
  } finally {
    input.disabled = false;
    btn.disabled = false;
    input.focus();
  }
}

$("chat-btn").addEventListener("click", send);
$("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") send();
});

$("new-chat-btn").addEventListener("click", () => {
  history.length = 0; // history is const — clear in place, don't reassign
  log.innerHTML = "";
  $("chat-error").innerHTML = "";
  $("chat-input").value = "";
  $("chat-input").focus();
});
