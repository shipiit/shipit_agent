"""Workspace change proposals: drafting a change, listing proposals and applying one the user approved."""

from __future__ import annotations

import copy
import json
import uuid
from urllib.parse import quote

from .browser_workspace_services import SERVICES


class _ProposalActions:
    """Workspace change proposals: drafting a change, listing proposals and applying one the user approved."""

    def _propose(self, action, service, file_id, args):
        if service not in SERVICES:
            raise ValueError("Choose docs, sheets or slides")
        if len(json.dumps(args)) > 100000:
            raise ValueError("Change proposal exceeds the size limit")
        if action == "propose_create":
            title = args.get("title")
            if not isinstance(title, str) or not title.strip() or len(title) > 250:
                raise ValueError("A title of 1–250 characters is required")
            method, url = "POST", SERVICES[service][0]
            body = (
                {"properties": {"title": title}}
                if service == "sheets"
                else {"title": title}
            )
            before = None
        elif action == "propose_values":
            if (
                service != "sheets"
                or not isinstance(args.get("range"), str)
                or not args["range"]
            ):
                raise ValueError("A Sheets range is required")
            values = args.get("values")
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(row, list) for row in values)
            ):
                raise ValueError("Provide a nonempty array of cell rows")
            before = self._read(service, file_id, args["range"])
            url = (
                self._target(service, file_id)
                + "/values/"
                + quote(args["range"], safe="")
                + "?valueInputOption=USER_ENTERED"
            )
            method, body = "PUT", {"range": args["range"], "values": values}
        else:
            requests = args.get("requests")
            if (
                not isinstance(requests, list)
                or not 1 <= len(requests) <= 100
                or any(not isinstance(r, dict) for r in requests)
            ):
                raise ValueError("Provide 1–100 Google batchUpdate request objects")
            before = self._read(service, file_id)
            method, url = "POST", self._target(service, file_id) + ":batchUpdate"
            body = {"requests": copy.deepcopy(requests)}
            if service in {"docs", "slides"}:
                revision = before.get("revisionId")
                if not revision:
                    raise ValueError(
                        "Google did not return a revision ID; cannot safely stage this edit"
                    )
                body["writeControl"] = {"requiredRevisionId": revision}
        proposal = {
            "id": uuid.uuid4().hex,
            "service": service,
            "action": action,
            "file_id": file_id,
            "method": method,
            "body": copy.deepcopy(body),
            "state": "pending",
            "range": args.get("range"),
            "concurrency": "Google revision check"
            if service in {"docs", "slides"} and action == "propose_update"
            else "Best-effort content check; Google Sheets does not provide an atomic revision guard",
        }
        with self.lock:
            if len(self.proposals) >= 20:
                raise ValueError(
                    "Review or dismiss existing proposals before preparing more"
                )
            self.proposals[proposal["id"]] = {**proposal, "url": url, "before": before}
        return {"status": "awaiting_user_apply", "proposal": proposal}

    def public_proposals(self):
        with self.lock:
            return [
                {
                    k: copy.deepcopy(v)
                    for k, v in p.items()
                    if k not in {"url", "before"}
                }
                for p in self.proposals.values()
                if p["state"] == "pending"
            ]

    def apply(self, proposal_id, approve):
        if not isinstance(proposal_id, str) or type(approve) is not bool:
            raise ValueError("A valid proposal ID and approval are required")
        with self.lock:
            proposal = self.proposals.get(proposal_id)
            if not proposal or proposal["state"] != "pending":
                raise ValueError("Proposal already resolved or missing")
            if not approve:
                del self.proposals[proposal_id]
                return {"status": "dismissed"}
            if proposal["service"] == "sheets" and proposal["before"] is not None:
                current = self._read("sheets", proposal["file_id"], proposal["range"])
                if current != proposal["before"]:
                    raise ValueError(
                        "Spreadsheet changed. Ask the agent to read it and prepare a fresh proposal."
                    )
            # Do not replay writes after ambiguous network failure.
            proposal["state"] = "submitting"
            try:
                result = self.client.request(
                    proposal["method"], proposal["url"], proposal["body"]
                )
            except Exception:
                proposal["state"] = "unknown"
                raise ValueError(
                    "Submission failed or its outcome is unknown. Check the document before proposing another change."
                ) from None
            proposal["state"] = "applied"
            return {"status": "applied", "result": result}
