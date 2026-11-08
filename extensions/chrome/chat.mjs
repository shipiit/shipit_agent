// Sending a message: open a session, stream the reply, and render it.
import { consumeEvents } from "./core.mjs";
import { renderMarkdown } from "./render.mjs";
import { $, busy, message, status } from "./ui.mjs";

export function wireComposer(ctx) {
  $("composer").onsubmit = async (event) => {
    event.preventDefault();
    if (ctx.controller || ctx.captureBusy) return;
    const prompt = $("prompt").value.trim();
    if (!prompt) return;
    if (!ctx.token) {
      $("settings").click();
      return;
    }
    ctx.controller = new AbortController();
    busy(true);
    status("Connecting to your agent…");
    let reply, output;
    try {
      if (!ctx.modelCatalog.length) await ctx.loadConfig();
      if (!ctx.sessionId) {
        const response = await ctx.api("/sessions", {}, ctx.controller.signal);
        ctx.sessionId = (await response.json()).session_id;
        await ctx.persist();
      }
      const response = await ctx.api(
        "/chat",
        {
          session_id: ctx.sessionId,
          prompt,
          model: $("model").value,
          attachments: ctx.uploads.map(({ name, mime, data }) => ({
            name,
            mime,
            data,
          })),
          page: ctx.page && {
            title: ctx.page.title,
            url: ctx.page.url,
            text: ctx.page.text,
            mode: ctx.page.mode,
            truncated: ctx.page.truncated,
          },
        },
        ctx.controller.signal,
      );
      const user = {
        role: "user",
        text: prompt,
        source: [ctx.page?.title, ...ctx.uploads.map((f) => f.name)]
          .filter(Boolean)
          .join(" · "),
      };
      ctx.turns.push(user);
      message(user);
      $("prompt").value = "";
      ctx.resizePrompt();
      ctx.removePage();
      ctx.uploads = [];
      ctx.renderUploads();
      reply = { role: "assistant", text: "" };
      ctx.turns.push(reply);
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
          ctx.proposals = p.proposals || [];
          ctx.renderProposals();
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
      ctx.controller = null;
      busy(false);
      await ctx.persist().catch(() =>
        status(
          "Could not retain this transcript in browser session storage.",
          true,
        ),
      );
    }
  };
}
