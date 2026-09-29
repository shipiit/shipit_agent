"""Read-only MCP stdio fixture. No network, credentials or production records."""
import json
import sys


def response(method, params):
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "case-fixture", "version": "1"}}
    if method == "tools/list":
        return {"tools": [{"name": "archive_case_lookup",
            "description": "Retrieve a case archive record with evidence code and amount by case ID.",
            "inputSchema": {"type": "object", "properties": {"record_id": {"type": "string"}}, "required": ["record_id"]},
            "annotations": {"readOnlyHint": True}}]}
    if method == "tools/call":
        ident = params.get("arguments", {}).get("record_id", "")
        rows = [{"id": f"CASE-{i}", "code": f"evidence-{7919 * (i + 1)}", "amount": 100 + i * 17}
                for i in range(5) if ident == f"CASE-{i}"]
        return {"content": [{"type": "text", "text": json.dumps(rows)}], "isError": False}
    if method == "ping":
        return {}
    raise ValueError("Unsupported fixture method")


if __name__ == "__main__":
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        try:
            payload = {"result": response(request["method"], request.get("params", {}))}
        except (KeyError, ValueError) as exc:
            payload = {"error": {"code": -32601, "message": str(exc)}}
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], **payload}), flush=True)
