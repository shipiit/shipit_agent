"""Guide 05: connections, the connector catalog and per-user OAuth."""

from cells import code, md

TITLE = "Connections and OAuth"

CELLS = [
    md("""
    # Guide 05 · Connections and OAuth

    A connection is a service your agent acts in on someone's behalf: Linear, GitHub, Slack, Notion. In shipit
    every connector is an MCP server from a catalog. Some read a key from the environment; the hosted ones use
    **per-user OAuth**, so each person signs in once and the agent acts as them.

    **What you'll learn**

    1. Browse the connector catalog and read a connector's manifest
    2. What happens when a key or a token is missing
    3. The OAuth authorization-code flow by hand, against a local test provider
    4. Why the `state` value matters (replay protection)
    5. `OAuthCredentialManager`: per-user tokens that refresh themselves
    6. Using a user's token inside a tool, and recovering when a token is revoked

    Every output below is real. The OAuth provider is a small local server this notebook starts, so the flow
    runs end to end without a real Linear or GitHub account.
    """),
    md("""
    ## 1 · Models
    """),
    code("""
    import os

    from shipit_agent import Agent
    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")
    """),
    md("""
    ## 2 · The catalog
    """),
    code("""
    from collections import Counter

    from shipit_agent import list_connectors

    connectors = list_connectors()
    print(len(connectors), "connectors")
    print("by category:", dict(Counter(c.category for c in connectors)))
    print("by auth:    ", dict(Counter("oauth" if c.uses_oauth else c.auth for c in connectors)))
    """),
    code("""
    for c in connectors:
        how = "hosted" if c.url else "stdio "
        auth = "per-user OAuth" if c.uses_oauth else (", ".join(c.required_env) or "no key")
        print(f"{c.name:14} {how}  {auth:28} {c.description}")
    """),
    md("""
    ## 3 · One connector's manifest

    Each connector is one declarative manifest: where it lives, how it authenticates, and the scopes it asks for.
    """),
    code("""
    linear = next(c for c in connectors if c.name == "linear")
    for field in ("name", "category", "kind", "url", "auth", "uses_oauth", "oauth", "scopes", "suggest"):
        print(f"{field:11} {getattr(linear, field)!r}")
    """),
    md("""
    ## 4 · Missing keys fail early, with a clear message

    `connect()` checks a connector's requirements before anything starts.
    """),
    code("""
    from shipit_agent import connect

    for name in ("linear", "airtable"):
        try:
            connect(name)
        except Exception as error:
            print(f"{name}: {type(error).__name__}: {error}\\n")
    """),
    md("""
    ## 5 · A local OAuth provider

    A real provider (Linear, GitHub) has an authorize page where the user signs in and approves, and a token
    endpoint. This stand-in approves every request at once, issues one-time codes, swaps them for tokens, and
    can refresh or revoke them. It runs in a background thread on a free port.
    """),
    code("""
    import json
    import secrets
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlencode, urlparse

    class Provider:
        codes: dict[str, str] = {}
        refresh_tokens: set[str] = set()
        calls: Counter = Counter()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the notebook quiet
            pass

        def do_GET(self):  # the authorize page: the user approves, we redirect back with a code
            q = parse_qs(urlparse(self.path).query)
            code = secrets.token_urlsafe(8)
            Provider.codes[code] = q["client_id"][0]
            Provider.calls["authorize"] += 1
            self.send_response(302)
            self.send_header("Location", f"{q['redirect_uri'][0]}?{urlencode({'code': code, 'state': q['state'][0]})}")
            self.end_headers()

        def do_POST(self):  # the token endpoint
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers["content-length"])).decode()).items()}
            Provider.calls[form["grant_type"]] += 1
            ok = (form["grant_type"] == "authorization_code" and Provider.codes.pop(form.get("code", ""), None)) or \\
                 (form["grant_type"] == "refresh_token" and form.get("refresh_token") in Provider.refresh_tokens)
            if not ok:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "invalid_grant"}')
                return
            refresh = secrets.token_urlsafe(12)
            Provider.refresh_tokens.add(refresh)
            body = {"access_token": "at_" + secrets.token_urlsafe(12), "refresh_token": refresh,
                    "token_type": "Bearer", "expires_in": 3600}
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    BASE = f"http://127.0.0.1:{server.server_port}"
    print("provider running at", BASE)
    """),
    md("""
    ## 6 · The flow by hand, step 1: send the user to sign in

    `OAuthHelper` is the authorization-code flow on its own. `create_authorization_url` makes a one-time `state`
    nonce, saves it with your payload (here, which user is connecting), and returns the URL to redirect to.
    """),
    code("""
    from pathlib import Path

    from shipit_agent import FileOAuthStateStore, OAuthClientConfig, OAuthHelper

    config = OAuthClientConfig(
        client_id="demo-client", client_secret="demo-secret",
        redirect_uri="https://app.example.com/oauth/callback",
        scopes=["read", "write"],
        authorize_url=f"{BASE}/authorize", token_url=f"{BASE}/token",
    )
    oauth = OAuthHelper(config, state_store=FileOAuthStateStore("oauth_state.json"))

    start = oauth.create_authorization_url(state_payload={"user_id": "u_812"})
    print(start["url"].replace(BASE, "<provider>"))
    """),
    md("""
    ## 7 · Step 2: the callback brings a code

    In a web app the browser comes back to your redirect URI. Here we follow the provider's redirect by hand and
    read the `code` and `state` from it.
    """),
    code("""
    import http.client

    def sign_in(url: str) -> dict[str, str]:
        \"\"\"What the browser does: open the authorize page and land on the callback.\"\"\"
        parsed = urlparse(url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port)
        conn.request("GET", f"{parsed.path}?{parsed.query}")
        location = conn.getresponse().getheader("Location")
        return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}

    callback = sign_in(start["url"])
    print({k: v[:6] + "…" for k, v in callback.items()})
    """),
    md("""
    ## 8 · Step 3: exchange the code for tokens

    Passing `state` checks it against the saved nonce: the defence against login CSRF. The result is stamped with
    `expires_at`.
    """),
    code("""
    tokens = oauth.exchange_code(code=callback["code"], state=callback["state"])
    print({k: (v[:9] + "…" if isinstance(v, str) and len(v) > 12 else v) for k, v in tokens.items()})
    """),
    md("""
    ## 9 · A state works once

    The nonce is consumed on success, so a replayed callback is refused before any request is made.
    """),
    code("""
    try:
        oauth.exchange_code(code=callback["code"], state=callback["state"])
    except ValueError as error:
        print("refused:", error)
    """),
    md("""
    ## 10 · Refresh

    Access tokens are short-lived; the refresh token gets a new one. `token_is_expired` says when.
    """),
    code("""
    from shipit_agent.integrations.oauth import token_is_expired

    print("expired now?", token_is_expired(tokens))
    renewed = oauth.refresh_token(tokens["refresh_token"])
    print("new access token differs:", renewed["access_token"] != tokens["access_token"])
    print("provider calls so far:", dict(Provider.calls))
    """),
    md("""
    ## 11 · `OAuthCredentialManager`: the whole flow, per user

    In an app you don't juggle tokens yourself. The manager keeps one token per (user, connector) in a store,
    and refreshes it when it's near expiry. Register the connector's OAuth helper once.
    """),
    code("""
    from shipit_agent.connectors import FileTokenStore, OAuthCredentialManager

    manager = OAuthCredentialManager(FileTokenStore("tokens"))
    manager.register("linear", OAuthHelper(config, state_store=FileOAuthStateStore("oauth_state.json")))

    url = manager.authorize_url(user="ada", connector="linear")       # your "Connect Linear" button
    back = sign_in(url)                                                  # Ada approves
    manager.complete(connector="linear", code=back["code"], state=back["state"])   # your callback route

    print("status:", manager.status(user="ada", connector="linear"))
    print("ada's connections:", manager.connections(user="ada"))
    print("bob's connections:", manager.connections(user="bob"))
    """),
    md("""
    ## 12 · Tokens that refresh themselves

    `access_token()` returns a valid token, refreshing it first if it's expired. Here Ada's stored token is
    aged past its expiry, and the next call refreshes it.
    """),
    code("""
    import time

    first = manager.access_token(user="ada", connector="linear")
    stored = manager.store.get("ada", "linear")
    manager.store.set("ada", "linear", {**stored, "expires_at": time.time() - 10})

    before = Provider.calls["refresh_token"]
    second = manager.access_token(user="ada", connector="linear")
    print("refreshed:", second != first, "| refresh calls:", Provider.calls["refresh_token"] - before)
    print("on disk:", sorted(p.name for p in Path("tokens").rglob("*") if p.is_file()))
    """),
    md("""
    ## 13 · A user's token inside a tool

    Your own tools can act as the signed-in user: resolve their token at call time, never store it in the prompt.
    The agent's `session_id` carries who it's working for.
    """),
    code("""
    from shipit_agent.tools import FunctionTool

    def my_issues(cycle: str = "current") -> str:
        \"\"\"List the signed-in user's Linear issues for a cycle.\"\"\"
        token = manager.access_token(user="ada", connector="linear")
        # A real tool would call Linear's API with: Authorization: Bearer <token>
        return json.dumps({"cycle": cycle, "auth": token[:6] + "…", "issues": [
            {"id": "ENG-412", "title": "Retry webhooks on 5xx", "state": "In review"},
            {"id": "ENG-418", "title": "Rotate the signing key", "state": "Todo"},
        ]})

    agent = Agent(llm=haiku, prompt="You help Ada with her Linear work. Be brief.",
                  tools=[FunctionTool.from_callable(my_issues, read_only=True)])
    print(agent.run("What's on my plate this cycle, and what's closest to done?").output)
    """),
    md("""
    ## 14 · When a token is revoked

    If the user revokes access at the provider, refresh fails and the manager raises `NeedsReconnect`: your app
    shows "Reconnect Linear" instead of making calls that fail silently.
    """),
    code("""
    Provider.refresh_tokens.clear()            # the user revoked access at the provider
    stored = manager.store.get("ada", "linear")
    manager.store.set("ada", "linear", {**stored, "expires_at": time.time() - 10})
    try:
        manager.access_token(user="ada", connector="linear")
    except Exception as error:
        print(type(error).__name__, "->", error)
    """),
    md("""
    ## 15 · The same tool on Gemma 4

    After Ada reconnects, Gemma 4 31B (Bedrock) runs the same tool.
    """),
    code("""
    back = sign_in(manager.authorize_url(user="ada", connector="linear"))
    manager.complete(connector="linear", code=back["code"], state=back["state"])

    agent = Agent(llm=gemma, prompt="You help Ada with her Linear work. Be brief.",
                  tools=[FunctionTool.from_callable(my_issues, read_only=True)])
    print(agent.run("What's on my plate this cycle?").output)
    """),
    md("""
    ## 16 · In a web app

    The same three calls map onto two routes and a per-request agent. With FastAPI:

    ```python
    @app.get("/connect/linear")
    def connect_linear(user=Depends(current_user)):
        return RedirectResponse(manager.authorize_url(user=user.id, connector="linear"))

    @app.get("/oauth/callback")
    def callback(code: str, state: str):
        manager.complete(connector="linear", code=code, state=state)
        return RedirectResponse("/settings/connections")

    @app.post("/ask")
    def ask(body: Question, user=Depends(current_user)):
        agent = Agent(llm=llm, mcps=[manager.connect("linear", user=user.id)])
        return {"answer": agent.run(body.text).output}
    ```

    `manager.connect(connector, user=...)` returns the hosted MCP server with that user's token attached.

    ## 17 · Clean up
    """),
    code("""
    import shutil

    server.shutdown()
    shutil.rmtree("tokens", ignore_errors=True)
    Path("oauth_state.json").unlink(missing_ok=True)
    """),
    md("""
    ## 18 · Summary

    - `list_connectors()` is the catalog; each connector says where it lives and how it authenticates.
    - `connect()` fails early and clearly when a key or token is missing.
    - `OAuthHelper` is the authorization-code flow; `state` is checked and consumed, so replays are refused.
    - `OAuthCredentialManager` keeps per-user tokens, refreshes them, and raises `NeedsReconnect` when it can't.
    - Tools resolve the user's token at call time; `manager.connect()` attaches a hosted connector per user.

    **Next:** Guide 06 — RAG.
    """),
]
