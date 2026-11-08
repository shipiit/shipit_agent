// Page capture, settings, new chat and prompt shortcuts.
import { extractPage, workspaceTarget } from "./core.mjs";
import { $, status } from "./ui.mjs";

export function wireControls(ctx) {
  $("remove-page").onclick = ctx.removePage;
  $("attach").onclick = async () => {
    if (!ctx.extension) {
      status(
        "Page capture is available when installed as a Chrome extension.",
        true,
      );
      return;
    }
    try {
      const tab = await ctx.currentTab();
      if (!tab?.id || !/^https?:/.test(tab.url || ""))
        throw new Error(
          "Open a webpage and click the Shipit toolbar icon on that tab first.",
        );
      const [snapshot] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: extractPage,
      });
      if (!snapshot?.result) throw new Error("Could not capture this page.");
      ctx.page = snapshot.result;
      if (!ctx.page.text && !workspaceTarget(ctx.page.url))
        throw new Error(
          "No readable text found. Select or paste the document content instead.",
        );
      $("page-card").hidden = false;
      $("page-title").textContent = ctx.page.title;
      $("page-source").textContent = ctx.page.url;
      $("page-summary").textContent =
        `Review ${ctx.page.mode} · ${ctx.page.text.length.toLocaleString()} characters${ctx.page.truncated ? " · truncated" : ""}`;
      $("page-limit").textContent = ctx.page.limitation;
      $("page-preview").textContent = ctx.page.text;
      status(
        "Snapshot ready. Review it before sending. It will be attached to your next message only.",
      );
      const target = workspaceTarget(ctx.page.url);
      if (target)
        status(
          ctx.workspaceConfigured
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
    $("token").value = ctx.token;
    $("config-status").textContent = "";
    $("config").showModal();
  };
  $("cancel-config").onclick = () => $("config").close();
  $("config-form").onsubmit = async (event) => {
    event.preventDefault();
    if ($("connect-button").disabled) return;
    const next = $("token").value.trim();
    const previous = ctx.token;
    $("connect-button").disabled = true;
    $("connect-button").textContent = "Connecting…";
    $("config-status").textContent = "";
    ctx.token = next;
    try {
      await ctx.loadConfig();
      if (next !== previous) {
        ctx.sessionId = "";
        ctx.turns = [];
        ctx.proposals = [];
        ctx.renderProposals();
        document.querySelectorAll(".message").forEach((el) => el.remove());
        $("welcome").hidden = false;
      }
      $("dot").classList.add("connected");
      await ctx.persist();
      $("config").close();
      status("Connected. Choose a model and ask your question.");
    } catch (error) {
      ctx.token = previous;
      $("config-status").textContent = error.message;
    } finally {
      $("connect-button").disabled = false;
      $("connect-button").textContent = "Connect agent ↗";
    }
  };
  $("new").onclick = async () => {
    try {
      if (ctx.sessionId) await ctx.api("/sessions/delete", { session_id: ctx.sessionId });
    } catch (error) {
      if (!error.message.includes("expired")) {
        status(error.message, true);
        return;
      }
    }
    ctx.sessionId = "";
    ctx.turns = [];
    ctx.uploads = [];
    ctx.proposals = [];
    ctx.renderUploads();
    ctx.renderProposals();
    ctx.removePage();
    document.querySelectorAll(".message").forEach((el) => el.remove());
    $("welcome").hidden = false;
    await ctx.persist();
    status("New chat. Previous chat history cleared from this bridge.");
  };
  for (const button of document.querySelectorAll("[data-prompt]"))
    button.onclick = () => {
      $("prompt").value = button.dataset.prompt;
      $("prompt").focus();
      if (!ctx.page)
        status(
          "Attach the current page, or paste the relevant context, before sending.",
        );
    };
  $("stop").onclick = () => ctx.controller?.abort();
}
