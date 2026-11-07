import {
  BRIDGE,
  extractPage,
  consumeEvents,
  workspaceTarget,
} from "./core.mjs";
import { renderMarkdown } from "./render.mjs";

const $ = (id) => document.getElementById(id);
const extension = Boolean(globalThis.chrome?.storage?.session);
const sourceWindowId =
  Number(new URL(location.href).searchParams.get("sourceWindow")) || null;
async function currentTab() {
  const tabs = await chrome.tabs.query(
    sourceWindowId
      ? { active: true, windowId: sourceWindowId }
      : { active: true, currentWindow: true },
  );
  return tabs[0];
}
let token = "",
  sessionId = "",
  turns = [],
  page = null,
  controller = null;
let uploads = [],
  modelCatalog = [],
  proposals = [],
  workspaceConfigured = false,
  captureBusy = false;
const saved = extension
  ? await chrome.storage.session.get([
      "token",
      "sessionId",
      "turns",
      "model",
      "proposals",
    ])
  : {};
token = saved.token || "";
sessionId = saved.sessionId || "";
turns = saved.turns || [];
proposals = saved.proposals || [];
if (saved.model) $("model").value = saved.model;

function status(text, error = false) {
  $("status").textContent = text;
  $("status").classList.toggle("error", error);
}
function connection() {
  $("connection").textContent = token
    ? "Agent configured"
    : "Connect your agent";
  $("dot").classList.toggle("connected", Boolean(token));
}
async function persist() {
  if (extension)
    await chrome.storage.session.set({
      token,
      sessionId,
      turns,
      model: $("model").value,
      proposals,
    });
}
async function loadConfig() {
  if (!token) return;
  const response = await api("/config", {});
  const config = await response.json();
  workspaceConfigured = Boolean(config.workspace_connected);
  modelCatalog = config.models;
  const previous = $("model").value;
  $("model").replaceChildren(
    ...modelCatalog.map((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.label;
      return option;
    }),
  );
  $("model").value = modelCatalog.some((item) => item.id === previous)
    ? previous
    : config.default_model;
  $("vision-label").hidden = !modelCatalog.find(
    (item) => item.id === $("model").value,
  )?.vision;
  $("workspace-state").textContent = config.workspace_connected
    ? "GOOGLE CONFIGURED"
    : "GOOGLE NOT CONNECTED";
  $("connection").textContent = "Agent connected";
}
$("model").onchange = async () => {
  $("vision-label").hidden = !modelCatalog.find(
    (item) => item.id === $("model").value,
  )?.vision;
  await persist();
};
async function api(path, body, signal) {
  const response = await fetch(BRIDGE + path, {
    method: "POST",
    redirect: "error",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || `Bridge returned ${response.status}`);
  }
  return response;
}
function message(turn) {
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
function busy(value) {
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
function removePage() {
  page = null;
  $("page-card").hidden = true;
}
$("remove-page").onclick = removePage;
$("attach").onclick = async () => {
  if (!extension) {
    status(
      "Page capture is available when installed as a Chrome extension.",
      true,
    );
    return;
  }
  try {
    const tab = await currentTab();
    if (!tab?.id || !/^https?:/.test(tab.url || ""))
      throw new Error(
        "Open a webpage and click the Shipit toolbar icon on that tab first.",
      );
    const [snapshot] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractPage,
    });
    if (!snapshot?.result) throw new Error("Could not capture this page.");
    page = snapshot.result;
    if (!page.text && !workspaceTarget(page.url))
      throw new Error(
        "No readable text found. Select or paste the document content instead.",
      );
    $("page-card").hidden = false;
    $("page-title").textContent = page.title;
    $("page-source").textContent = page.url;
    $("page-summary").textContent =
      `Review ${page.mode} · ${page.text.length.toLocaleString()} characters${page.truncated ? " · truncated" : ""}`;
    $("page-limit").textContent = page.limitation;
    $("page-preview").textContent = page.text;
    status(
      "Snapshot ready. Review it before sending. It will be attached to your next message only.",
    );
    const target = workspaceTarget(page.url);
    if (target)
      status(
        workspaceConfigured
          ? `Page attached. The agent can read the actual ${target.service} file through your configured Google account.`
          : "Page attached. Connect Google Workspace in the backend to read this document; the snapshot may contain only editor controls.",
      );
  } catch (error) {
    status(
      `${error.message} If access was denied, click Shipit's toolbar icon on the page, then try again.`,
      true,
    );
  }
};
$("settings").onclick = () => {
  $("token").value = token;
  $("config-status").textContent = "";
  $("config").showModal();
};
$("cancel-config").onclick = () => $("config").close();
$("config-form").onsubmit = async (event) => {
  event.preventDefault();
  if ($("connect-button").disabled) return;
  const next = $("token").value.trim();
  const previous = token;
  $("connect-button").disabled = true;
  $("connect-button").textContent = "Connecting…";
  $("config-status").textContent = "";
  token = next;
  try {
    await loadConfig();
    if (next !== previous) {
      sessionId = "";
      turns = [];
      proposals = [];
      renderProposals();
      document.querySelectorAll(".message").forEach((el) => el.remove());
      $("welcome").hidden = false;
    }
    $("dot").classList.add("connected");
    await persist();
    $("config").close();
    status("Connected. Choose a model and ask your question.");
  } catch (error) {
    token = previous;
    $("config-status").textContent = error.message;
  } finally {
    $("connect-button").disabled = false;
    $("connect-button").textContent = "Connect agent ↗";
  }
};
$("new").onclick = async () => {
  try {
    if (sessionId) await api("/sessions/delete", { session_id: sessionId });
  } catch (error) {
    if (!error.message.includes("expired")) {
      status(error.message, true);
      return;
    }
  }
  sessionId = "";
  turns = [];
  uploads = [];
  proposals = [];
  renderUploads();
  renderProposals();
  removePage();
  document.querySelectorAll(".message").forEach((el) => el.remove());
  $("welcome").hidden = false;
  await persist();
  status("New chat. Previous chat history cleared from this bridge.");
};
for (const button of document.querySelectorAll("[data-prompt]"))
  button.onclick = () => {
    $("prompt").value = button.dataset.prompt;
    $("prompt").focus();
    if (!page)
      status(
        "Attach the current page, or paste the relevant context, before sending.",
      );
  };
$("stop").onclick = () => controller?.abort();
function renderUploads() {
  $("attachments").replaceChildren(
    ...uploads.map((item, index) => {
      const chip = document.createElement("div");
      chip.className = "attachment-chip";
      if (item.mime.startsWith("image/")) {
        const image = document.createElement("img");
        image.src = `data:${item.mime};base64,${item.data}`;
        image.alt = item.name;
        chip.append(image);
      }
      const name = document.createElement("span");
      name.textContent = item.name;
      chip.append(name);
      const remove = document.createElement("button");
      remove.textContent = "×";
      remove.ariaLabel = `Remove ${item.name}`;
      remove.onclick = () => {
        uploads.splice(index, 1);
        renderUploads();
      };
      chip.append(remove);
      return chip;
    }),
  );
}
async function addFiles(files) {
  if (captureBusy || controller) return;
  captureBusy = true;
  $("send").disabled = true;
  try {
    const pending = [];
    for (const file of files) {
      if (uploads.length + pending.length >= 8 || file.size > 4 * 1024 * 1024)
        throw new Error("Use at most eight files, each under 4 MB.");
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(",")[1]);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      pending.push({
        name: file.name,
        mime: file.type || "application/octet-stream",
        data,
        size: file.size,
      });
    }
    if (
      [...uploads, ...pending].reduce((sum, f) => sum + f.size, 0) >
      12 * 1024 * 1024
    )
      throw new Error("Attachments exceed 12 MB total.");
    uploads.push(...pending);
    renderUploads();
    status("Files attached to your next message.");
  } catch (error) {
    status(error.message || "Could not read attachment", true);
  } finally {
    captureBusy = false;
    $("send").disabled = Boolean(controller);
  }
}
$("upload").onclick = () => $("file-input").click();
$("file-input").onchange = async () => {
  await addFiles($("file-input").files);
  $("file-input").value = "";
};
document.addEventListener("dragover", (event) => {
  event.preventDefault();
});
document.addEventListener("drop", async (event) => {
  event.preventDefault();
  await addFiles(event.dataTransfer.files);
});
$("screenshot").onclick = async () => {
  if (!extension) {
    status("Screenshot capture requires the installed Chrome extension.", true);
    return;
  }
  try {
    const image = await chrome.tabs.captureVisibleTab(
      sourceWindowId || undefined,
      { format: "jpeg", quality: 75 },
    );
    const bytes = Uint8Array.from(atob(image.split(",")[1]), (value) =>
      value.charCodeAt(0),
    );
    const file = new File([bytes], "Current page.jpg", { type: "image/jpeg" });
    await addFiles([file]);
    status("Screenshot attached. Review its thumbnail before sending.");
  } catch (error) {
    status(
      error.message +
        " Click the Shipit toolbar icon on the tab to grant access.",
      true,
    );
  }
};
document.addEventListener("paste", async (event) => {
  const files = [...(event.clipboardData?.files || [])];
  if (files.length) {
    event.preventDefault();
    await addFiles(files);
  }
});
function renderProposals() {
  $("proposals").hidden = !proposals.length;
  $("proposals").replaceChildren(
    ...proposals.map((proposal) => {
      const card = document.createElement("article");
      card.className = "proposal";
      const title = document.createElement("strong");
      title.textContent = `Review ${proposal.service} change`;
      const target = document.createElement("p");
      target.textContent = proposal.file_id
        ? `Document: ${proposal.file_id}`
        : `Create: ${proposal.body.title || proposal.body.properties?.title}`;
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "Exact changes";
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(proposal.body, null, 2);
      details.append(summary, pre);
      const note = document.createElement("small");
      note.textContent = proposal.concurrency;
      const controls = document.createElement("div");
      controls.className = "proposal-controls";
      for (const approve of [false, true]) {
        const button = document.createElement("button");
        button.textContent = approve ? "Apply changes ↗" : "Dismiss";
        if (approve) button.className = "primary";
        button.onclick = async () => {
          if (controller) {
            status(
              "Wait for the current reply to finish before applying changes.",
              true,
            );
            return;
          }
          const buttons = card.querySelectorAll("button");
          buttons.forEach((b) => (b.disabled = true));
          try {
            const response = await api("/workspace/apply", {
              session_id: sessionId,
              proposal_id: proposal.id,
              approve,
            });
            const result = await response.json();
            proposals = proposals.filter((p) => p.id !== proposal.id);
            renderProposals();
            await persist();
            status(
              approve
                ? "Changes applied to Google Workspace."
                : "Proposal dismissed.",
            );
            if (approve) {
              const turn = {
                role: "assistant",
                text:
                  "Google Workspace confirmed the changes.\n\n```json\n" +
                  JSON.stringify(result.result, null, 2) +
                  "\n```",
              };
              turns.push(turn);
              message(turn);
              await persist();
            }
          } catch (error) {
            status(error.message, true);
            buttons.forEach((b) => (b.disabled = false));
          }
        };
        controls.append(button);
      }
      card.append(title, target, details, note, controls);
      return card;
    }),
  );
}
$("prompt").onkeydown = (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("composer").requestSubmit();
  }
};
function resizePrompt() {
  $("prompt").style.height = "auto";
  $("prompt").style.height = `${Math.min($("prompt").scrollHeight, 110)}px`;
}
$("prompt").addEventListener("input", resizePrompt);
$("composer").onsubmit = async (event) => {
  event.preventDefault();
  if (controller || captureBusy) return;
  const prompt = $("prompt").value.trim();
  if (!prompt) return;
  if (!token) {
    $("settings").click();
    return;
  }
  controller = new AbortController();
  busy(true);
  status("Connecting to your agent…");
  let reply, output;
  try {
    if (!modelCatalog.length) await loadConfig();
    if (!sessionId) {
      const response = await api("/sessions", {}, controller.signal);
      sessionId = (await response.json()).session_id;
      await persist();
    }
    const response = await api(
      "/chat",
      {
        session_id: sessionId,
        prompt,
        model: $("model").value,
        attachments: uploads.map(({ name, mime, data }) => ({
          name,
          mime,
          data,
        })),
        page: page && {
          title: page.title,
          url: page.url,
          text: page.text,
          mode: page.mode,
          truncated: page.truncated,
        },
      },
      controller.signal,
    );
    const user = {
      role: "user",
      text: prompt,
      source: [page?.title, ...uploads.map((f) => f.name)]
        .filter(Boolean)
        .join(" · "),
    };
    turns.push(user);
    message(user);
    $("prompt").value = "";
    resizePrompt();
    removePage();
    uploads = [];
    renderUploads();
    reply = { role: "assistant", text: "" };
    turns.push(reply);
    output = message(reply);
    status("Working…");
    await consumeEvents(response.body, (event) => {
      const p = event.payload || {};
      if (event.type === "text_delta") reply.text += p.chunk || "";
      if (event.type === "run_completed") {
        reply.text = p.output ?? reply.text;
        if (p.cancelled || p.summary?.gave_up || p.summary?.incomplete_reason)
          throw new Error(
            p.summary?.incomplete_reason ||
              "The agent stopped before completing the request",
          );
        status("Complete");
      }
      if (event.type.startsWith("tool_"))
        status(
          `${event.type.replaceAll("_", " ")} · ${p.name || p.tool_name || "tool"}`,
        );
      if (event.type === "context_compaction_started")
        status("Compacting conversation context…");
      if (event.type === "workspace_proposals") {
        proposals = p.proposals || [];
        renderProposals();
      }
      if (event.type === "error")
        throw new Error(p.message || "Agent run failed");
      if (event.type === "run_cancelled") throw new Error("Run cancelled");
      output.textContent = reply.text;
      const log = $("messages");
      log.scrollTop = log.scrollHeight;
    });
    renderMarkdown(output, reply.text);
  } catch (error) {
    const reason =
      error.name === "AbortError"
        ? "Stream stopped. An in-flight provider call may still finish on the backend."
        : error.message;
    status(reason, true);
    if (reply) {
      reply.text += `\n\n[Incomplete: ${reason}]`;
      output.textContent = reply.text;
    }
  } finally {
    controller = null;
    busy(false);
    await persist().catch(() =>
      status(
        "Could not retain this transcript in browser session storage.",
        true,
      ),
    );
  }
};
for (const turn of turns) message(turn);
if (turns.length) $("messages").scrollTop = $("messages").scrollHeight;
connection();
renderProposals();
if (extension && token)
  loadConfig().catch((error) => status(error.message, true));
if (!extension)
  status(
    "UI preview · Install the unpacked extension to connect and capture pages.",
  );
