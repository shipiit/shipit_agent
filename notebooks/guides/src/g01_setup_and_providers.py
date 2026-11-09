"""Guide 01: setup, .env and every provider."""

from cells import code, md

TITLE = "Setup, .env and every model provider"

CELLS = [
    md("""
    # Guide 01 · Setup, `.env` and every model provider

    shipit-agent runs the same agent loop on any model. This guide sets up a project, shows how the
    environment picks a provider, and runs the same question on **Haiku 5.5** on the Anthropic API and on **Gemma 4 31B
    on AWS Bedrock**, then shows the cells for every other provider.

    **What you'll learn**

    1. Install shipit-agent and the extras you need
    2. Write a `.env` file and check which keys are set, without printing them
    3. Browse all 19 built-in provider profiles
    4. Build a model from the environment, or choose one in code
    5. Run the same question on two models and compare tokens, time and cost
    6. Stream tokens, read usage and cached tokens, and track cost
    7. Use the async SDK with a model string

    Every output below is real: the notebook was run end to end.
    """),
    md("""
    ## 1 · Install

    The core package has one required dependency. Each provider SDK is an optional extra:

    ```bash
    pip install shipit-agent                    # the core
    pip install "shipit-agent[anthropic]"       # Anthropic (Opus, Sonnet, Haiku)
    pip install "shipit-agent[bedrock]"         # AWS Bedrock (Gemma, gpt-oss, Llama…)
    pip install "shipit-agent[openai]"          # OpenAI
    pip install "shipit-agent[litellm]"         # Gemini, Groq, Together, Mistral, DeepSeek and more
    pip install "shipit-agent[all]"             # everything
    ```
    """),
    code("""
    import shipit_agent

    print("shipit-agent", shipit_agent.__version__)
    """),
    md("""
    ## 2 · The `.env` file

    Keep keys out of code. Put them in a `.env` file at the root of your project; `build_llm_from_env()`
    loads the first `.env` it finds walking up from the working directory, and variables already set in
    the shell win over the file.

    ```bash
    # .env
    SHIPIT_LLM_PROVIDER=anthropic            # which provider build_llm_from_env() uses by default
    SHIPIT_ANTHROPIC_MODEL=claude-haiku-5-5  # the model for that provider
    ANTHROPIC_API_KEY=sk-ant-...

    # AWS Bedrock reads your normal AWS credentials (profile, role or keys)
    AWS_REGION_NAME=us-east-1
    SHIPIT_BEDROCK_MODEL=google.gemma-4-31b

    OPENAI_API_KEY=sk-...
    ```

    Add `.env` to `.gitignore`.
    """),
    md("""
    ## 3 · Which keys are set?

    A quick check that never prints a value, only whether each variable is present.
    """),
    code("""
    import os

    from shipit_agent.llms.factory import load_env_file

    load_env_file()
    for name in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
                 "TOGETHER_API_KEY", "MISTRAL_API_KEY", "DEEPSEEK_API_KEY", "XAI_API_KEY"]:
        print(f"{name:20} {'set' if os.getenv(name) else 'missing'}")
    """),
    md("""
    ## 4 · The provider catalog

    shipit ships a profile for each provider: its default model, the variable that overrides the model,
    the keys it needs, and what it supports.
    """),
    code("""
    from shipit_agent.providers import list_providers

    print(f"{'provider':11} {'default model':42} {'model variable':24} {'key':5} cache")
    for p in list_providers():
        print(f"{p.name:11} {(p.default_model or '-'):42} {(p.model_env[0] if p.model_env else '-'):24} "
              f"{'yes' if p.needs_key else 'no':5} {'yes' if p.supports_prompt_cache else 'no'}")
    """),
    md("""
    ## 5 · Build a model from the environment

    `build_llm_from_env(provider)` reads the provider's model variable and its keys. With no argument it
    uses `SHIPIT_LLM_PROVIDER`.
    """),
    code("""
    from shipit_agent.llms import build_llm_from_env

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    print(type(haiku).__name__, haiku.model)
    """),
    md("""
    ## 6 · A first call

    `Agent(llm=...)` with no tools is a plain conversation. `run()` returns an `AgentResult`: the answer
    in `output`, and token usage in `metadata["usage"]`.
    """),
    code("""
    from shipit_agent import Agent

    result = Agent(llm=haiku).run("In one sentence, what is an AI agent?")
    print(result.output)
    print(result.metadata["usage"])
    """),
    md("""
    ## 7 · Choose the model in code

    `build_llm_from_settings()` takes the model id directly, for when the model is a decision in your code
    rather than in the environment. Here: Gemma 4 31B on AWS Bedrock.
    """),
    code("""
    from shipit_agent.llms.factory import build_llm_from_settings

    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")
    print(type(gemma).__name__, gemma.model)

    print(Agent(llm=gemma).run("In one sentence, what is an AI agent?").output)
    """),
    md("""
    ## 8 · Same question, two models

    The agent code doesn't change. A `CostTracker` per run prices each model with shipit's pricing table.
    """),
    code("""
    import time

    from shipit_agent.costs import CostTracker

    question = "Name three things an agent needs besides a model. One short line each."
    print(f"{'model':22} {'seconds':>8} {'tokens':>7} {'cost':>9}")
    answers = {}
    for name, llm in [("claude-haiku-5-5", haiku), ("gemma-4-31b (bedrock)", gemma)]:
        tracker = CostTracker()
        started = time.perf_counter()
        result = Agent(llm=llm, hooks=tracker.as_hooks()).run(question)
        answers[name] = result.output
        tokens = tracker.total_tokens["input_tokens"] + tracker.total_tokens["output_tokens"]
        print(f"{name:22} {time.perf_counter() - started:8.1f} {tokens:7} ${tracker.total_cost:8.5f}")
    """),
    code("""
    for name, answer in answers.items():
        print(f"--- {name}\\n{answer}\\n")
    """),
    md("""
    ## 9 · A helper for optional providers

    The next cells try providers you may not have set up. `try_provider` runs one short question and
    reports a missing key or a rejected call in one line instead of stopping the notebook.
    """),
    code("""
    def try_provider(name: str) -> None:
        from shipit_agent.providers import get_profile

        profile = get_profile(name)
        if profile.require_env and not any(os.getenv(v) for v in profile.require_env):
            print(f"{name:11} skipped: set {' or '.join(profile.require_env)}")
            return
        try:
            llm = build_llm_from_env(name)
            print(f"{name:11} {llm.model} -> {Agent(llm=llm).run('Reply with one word: ready').output.strip()}")
        except Exception as error:
            print(f"{name:11} call failed: {type(error).__name__} (check the key and the model id)")
    """),
    md("""
    ## 10 · OpenAI

    The same call on OpenAI, when `OPENAI_API_KEY` is set. The model comes from `SHIPIT_OPENAI_MODEL`
    (default `gpt-5.5`).
    """),
    code("""
    try_provider("openai")
    """),
    md("""
    ## 11 · Every other provider

    The pattern is the same for all of them. Each cell below runs when its key is set and says what to
    set when it isn't, so the notebook never fails for a provider you don't use.
    """),
    code("""
    for name in ["gemini", "groq", "together", "mistral", "deepseek", "xai", "openrouter", "cerebras", "fireworks"]:
        try_provider(name)
    """),
    md("""
    ## 12 · Local models with Ollama

    Ollama needs no key, only a running server. This cell checks for one on the default port first.
    """),
    code("""
    import socket

    def ollama_running(host="127.0.0.1", port=11434) -> bool:
        with socket.socket() as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0

    if ollama_running():
        local = build_llm_from_env("ollama")
        print(local.model, "->", Agent(llm=local).run("Reply with one word: ready").output)
    else:
        print("skipped: start Ollama (ollama serve) and pull a model, e.g. ollama pull llama3.1")
    """),
    md("""
    ## 13 · Stream the answer

    `agent.stream()` yields events as they happen. `text_delta` events carry the answer as it is written.
    """),
    code("""
    pieces, types = [], []
    for event in Agent(llm=haiku).stream("Write a haiku about a test suite going green."):
        types.append(event.type)
        if event.type == "text_delta":
            pieces.append(event.payload.get("chunk", ""))

    print("".join(pieces))
    print(f"\\n{len(types)} events; {types.count('text_delta')} text deltas; last: {types[-1]}")
    """),
    md("""
    ## 14 · Usage and cached tokens

    Anthropic models cache the stable start of a request (the system prompt and tools), so a second run with
    the same long prompt reads it back at about a tenth of the price. shipit reports it the same way on
    every provider: `cache_read_input_tokens`, and `cache_creation_input_tokens` for the write.
    """),
    code("""
    handbook = "\\n".join(f"Rule {i}: answer briefly, cite the rule number, and never invent facts about project {i}."
                         for i in range(1, 400))
    cached_agent_prompt = "You are a support assistant. Follow the handbook.\\n\\n" + handbook

    for attempt in (1, 2):
        result = Agent(llm=haiku, prompt=cached_agent_prompt).run("What does rule 7 say? One line.")
        usage = result.metadata["usage"]
        print(f"run {attempt}: input {usage.get('prompt_tokens')}, "
              f"cache write {usage.get('cache_creation_input_tokens', 0)}, "
              f"cache read {usage.get('cache_read_input_tokens', 0)}")
    """),
    md("""
    ## 15 · Budgets

    `max_budget_usd` stops a run between steps once its estimated cost reaches the limit, and `max_turns`
    caps the number of model calls. Both work on every provider shipit has prices for.
    """),
    code("""
    capped = Agent(llm=haiku, max_budget_usd=0.05, max_turns=4)
    print(capped.run("Reply with one word: ready").output)
    """),
    md("""
    ## 16 · A fallback model

    If the main model fails after its retries, `fallback_model` takes over: a model id, a list of ids, or an
    adapter. Here Gemma backs up Haiku.
    """),
    code("""
    resilient = Agent(llm=haiku, fallback_model=gemma)
    print(resilient.run("Reply with one word: ready").output)
    """),
    md("""
    ## 17 · The async SDK

    `shipit_agent.sdk` is the async API: `query()` streams typed messages for one prompt. Pass a model id as a
    string; shipit picks the provider from it. In a notebook, top-level `async for` works directly.
    """),
    code("""
    from shipit_agent.sdk import AgentOptions, ResultMessage, query

    options = AgentOptions(model="claude-haiku-5-5", max_turns=2)
    async for message in query(prompt="Reply with one word: ready", options=options):
        if isinstance(message, ResultMessage):
            print(message.subtype, "|", message.result, "| turns:", message.num_turns,
                  "| cost: $", round(message.total_cost_usd or 0, 5))
    """),
    md("""
    ## 18 · Summary

    - Keys and model choices live in `.env`; `build_llm_from_env()` reads them, and never needs them in code.
    - `build_llm_from_settings()` picks a model in code.
    - The agent, tools, streaming, usage and budgets behave the same on every provider.
    - Cached tokens are reported under the same keys everywhere.

    **Next:** Guide 02 — the Agent: `run()`, `stream()`, results and every event.
    """),
]
