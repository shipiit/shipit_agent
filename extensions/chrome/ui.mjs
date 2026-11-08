// Stateless panel helpers: element lookup, status line, message cards, busy state.
import { renderMarkdown } from "./render.mjs";

export const $ = (id) => document.getElementById(id);
export function status(text, error = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", error);
}
export function message(turn) {
  const article = document.createElement("article");
  article.className = `message ${turn.role}`;
  const label = document.createElement("div");
  label.className = "label";
  label.textContent = turn.role === "user" ? "YOU" : "SHIPIT";
  const body = document.createElement("div");
  body.className = "body";
  if (turn.role === "assistant") renderMarkdown(body, turn.text);
  else body.textContent = turn.text;
  article.append(label, body);
  if (turn.source) {
    const note = document.createElement("div");
    note.className = "message-note";
    note.textContent = `◫ ${turn.source}`;
    article.append(note);
  }
  if (turn.role === "assistant") {
    const copy = document.createElement("button");
    copy.className = "copy";
    copy.textContent = "Copy response";
    copy.onclick = async () => {
      try {
        await navigator.clipboard.writeText(turn.text);
        copy.textContent = "Copied";
      } catch {
        status("Could not copy. Select the response text instead.", true);
      }
    };
    article.append(copy);
  }
  $("messages").append(article);
  $("welcome").hidden = true;
  return body;
}
export function busy(value) {
  for (const id of [
    "send",
    "attach",
    "new",
    "settings",
    "upload",
    "screenshot",
    "model",
  ])
    $(id).disabled = value;
  $("stop").hidden = !value;
  $("send").hidden = value;
}
