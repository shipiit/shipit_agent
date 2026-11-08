// Workspace change proposals: review cards with Apply and Dismiss.
import { $, message, status } from "./ui.mjs";

export function createProposals(ctx) {
  function renderProposals() {
    $("proposals").hidden = !ctx.proposals.length;
    $("proposals").replaceChildren(
      ...ctx.proposals.map((proposal) => {
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
            if (ctx.controller) {
              status(
                "Wait for the current reply to finish before applying changes.",
                true,
              );
              return;
            }
            const buttons = card.querySelectorAll("button");
            buttons.forEach((b) => (b.disabled = true));
            try {
              const response = await ctx.api("/workspace/apply", {
                session_id: ctx.sessionId,
                proposal_id: proposal.id,
                approve,
              });
              const result = await response.json();
              ctx.proposals = ctx.proposals.filter((p) => p.id !== proposal.id);
              renderProposals();
              await ctx.persist();
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
                ctx.turns.push(turn);
                message(turn);
                await ctx.persist();
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
  return { renderProposals };
}
