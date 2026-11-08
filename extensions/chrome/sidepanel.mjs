import { BRIDGE } from "./core.mjs";
import { wireComposer } from "./chat.mjs";
import { wireControls } from "./controls.mjs";
import { createProposals } from "./proposals.mjs";
import { $, message, status } from "./ui.mjs";
import { createUploads } from "./uploads.mjs";

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
function removePage() {
  page = null;
  $("page-card").hidden = true;
}
const ctx = {
  get token() {
    return token;
  },
  set token(value) {
    token = value;
  },
  get sessionId() {
    return sessionId;
  },
  set sessionId(value) {
    sessionId = value;
  },
  get turns() {
    return turns;
  },
  set turns(value) {
    turns = value;
  },
  get page() {
    return page;
  },
  set page(value) {
    page = value;
  },
  get controller() {
    return controller;
  },
  set controller(value) {
    controller = value;
  },
  get uploads() {
    return uploads;
  },
  set uploads(value) {
    uploads = value;
  },
  get modelCatalog() {
    return modelCatalog;
  },
  set modelCatalog(value) {
    modelCatalog = value;
  },
  get proposals() {
    return proposals;
  },
  set proposals(value) {
    proposals = value;
  },
  get workspaceConfigured() {
    return workspaceConfigured;
  },
  set workspaceConfigured(value) {
    workspaceConfigured = value;
  },
  get captureBusy() {
    return captureBusy;
  },
  set captureBusy(value) {
    captureBusy = value;
  },
  extension,
  sourceWindowId,
  api,
  persist,
  loadConfig,
  currentTab,
  removePage,
  resizePrompt,
};
const { renderUploads, addFiles } = createUploads(ctx);
ctx.renderUploads = renderUploads;
ctx.addFiles = addFiles;
const { renderProposals } = createProposals(ctx);
ctx.renderProposals = renderProposals;
wireControls(ctx);
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
wireComposer(ctx);
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
