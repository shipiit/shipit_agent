from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Iterable

from shipit_agent import (
    Agent,
    DEFAULT_AGENT_PROMPT,
    FileMemoryStore,
    FileSessionStore,
    FileTraceStore,
    FunctionTool,
    Message,
    get_builtin_tools,
)
from shipit_agent.llms import (
    AnthropicChatLLM,
    BedrockChatLLM,
    GeminiChatLLM,
    GroqChatLLM,
    LiteLLMChatLLM,
    OllamaChatLLM,
    OpenAIChatLLM,
    SimpleEchoLLM,
    TogetherChatLLM,
    VertexAIChatLLM,
)

DEFAULT_WORKSPACE = '.shipit_workspace'
SUPPORTED_PROVIDERS = (
    'shipit',
    'bedrock',
    'openai',
    'anthropic',
    'gemini',
    'vertex',
    'litellm',
    'groq',
    'together',
    'ollama',
)


def _discover_env_file() -> Path | None:
    """Walk up from CWD looking for a .env file.

    Notebooks run with CWD=notebooks/, scripts with CWD=repo-root. Either way
    we want to find a .env at the project root so users can set credentials
    once and switch providers with `SHIPIT_LLM_PROVIDER=openai` etc.
    """
    start = Path.cwd().resolve()
    for candidate in (start, *start.parents):
        dotenv = candidate / '.env'
        if dotenv.exists():
            return dotenv
    return None


def load_env_file(path: str | Path | None = None) -> dict[str, str]:
    """Load a .env file into os.environ (without overriding existing vars).

    If ``path`` is None, walks upward from CWD to discover one. Returns the
    map of keys that were loaded so callers can log or inspect them.
    """
    env_path = Path(path) if path else _discover_env_file()
    loaded: dict[str, str] = {}
    if env_path is None or not env_path.exists():
        return loaded

    for line in env_path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)
        loaded[key.strip()] = value
    return loaded


def _require_any(names: Iterable[str], *, provider: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    joined = ', '.join(names)
    raise RuntimeError(f'Missing environment variable for {provider}. Set one of: {joined}')


def build_llm_from_env(provider: str | None = None):
    # Auto-load a .env file from CWD or any parent directory. This is what
    # makes `build_llm_from_env('openai')` work from a notebook whose CWD is
    # `notebooks/` — without it, OPENAI_API_KEY is never seen and the helper
    # raises "Missing environment variable for openai".
    load_env_file()
    selected = (provider or os.getenv('SHIPIT_LLM_PROVIDER', 'bedrock')).strip().lower()

    if selected in {'shipit', 'echo'}:
        return SimpleEchoLLM()
    if selected == 'bedrock':
        region = os.getenv('AWS_REGION_NAME') or os.getenv('AWS_DEFAULT_REGION')
        if not region and not os.getenv('AWS_PROFILE'):
            # Fall back to the default AWS config on the machine (~/.aws/config).
            try:
                import boto3  # type: ignore
                session = boto3.session.Session()
                region = session.region_name
                if region:
                    os.environ['AWS_REGION_NAME'] = region
                    os.environ.setdefault('AWS_DEFAULT_REGION', region)
            except Exception:
                region = None
            if not region:
                raise RuntimeError(
                    'Bedrock requires AWS_REGION_NAME or AWS_DEFAULT_REGION, or an AWS_PROFILE '
                    'configured locally (or a default region in ~/.aws/config).'
                )
        return BedrockChatLLM(
            model=os.getenv('SHIPIT_BEDROCK_MODEL', 'bedrock/openai.gpt-oss-120b-1:0')
        )
    if selected == 'openai':
        _require_any(['OPENAI_API_KEY'], provider='openai')
        # SHIPIT_OPENAI_TOOL_CHOICE=required forces at least one tool call per
        # turn — useful for gpt-4o-mini and other lazy models. Accepts any
        # value OpenAI's API accepts ("auto"|"required"|"none").
        tool_choice = os.getenv('SHIPIT_OPENAI_TOOL_CHOICE') or None
        return OpenAIChatLLM(
            model=os.getenv('SHIPIT_OPENAI_MODEL', 'gpt-4o-mini'),
            tool_choice=tool_choice,
        )
    if selected == 'anthropic':
        _require_any(['ANTHROPIC_API_KEY'], provider='anthropic')
        return AnthropicChatLLM(model=os.getenv('SHIPIT_ANTHROPIC_MODEL', 'claude-3-5-sonnet-latest'))
    if selected == 'gemini':
        _require_any(['GEMINI_API_KEY', 'GOOGLE_API_KEY'], provider='gemini')
        return GeminiChatLLM(model=os.getenv('SHIPIT_GEMINI_MODEL', 'gemini/gemini-1.5-pro'))
    if selected in {'vertex', 'vertex_ai', 'vertexai'}:
        _require_any(
            [
                'GOOGLE_APPLICATION_CREDENTIALS',
                'SHIPIT_VERTEX_CREDENTIALS_FILE',
            ],
            provider='vertex',
        )
        # Service-account JSON file path. VertexAIChatLLM will set
        # GOOGLE_APPLICATION_CREDENTIALS from this, so google-auth picks it up.
        credentials_file = (
            os.getenv('SHIPIT_VERTEX_CREDENTIALS_FILE')
            or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        )
        project_id = (
            os.getenv('VERTEXAI_PROJECT')
            or os.getenv('GOOGLE_CLOUD_PROJECT')
        )
        location = (
            os.getenv('VERTEXAI_LOCATION')
            or os.getenv('VERTEX_LOCATION')
            or os.getenv('GOOGLE_CLOUD_LOCATION')
        )
        _require_any(['VERTEXAI_PROJECT', 'GOOGLE_CLOUD_PROJECT'], provider='vertex')
        _require_any(['VERTEXAI_LOCATION', 'VERTEX_LOCATION', 'GOOGLE_CLOUD_LOCATION'], provider='vertex')
        return VertexAIChatLLM(
            model=os.getenv('SHIPIT_VERTEX_MODEL', 'vertex_ai/gemini-1.5-pro'),
            service_account_file=credentials_file,
            project_id=project_id,
            location=location,
        )
    if selected in {'litellm', 'litellm_proxy', 'proxy'}:
        # Generic LiteLLM adapter — points at either the public LiteLLM SDK
        # path OR a self-hosted LiteLLM proxy server. When SHIPIT_LITELLM_API_BASE
        # is set, we assume a proxy and use LiteLLMProxyChatLLM (which defaults
        # custom_llm_provider="openai" since the proxy always speaks OpenAI).
        from shipit_agent.llms import LiteLLMProxyChatLLM

        model = _require_any(['SHIPIT_LITELLM_MODEL'], provider='litellm')
        api_key = os.getenv('SHIPIT_LITELLM_API_KEY')
        api_base = os.getenv('SHIPIT_LITELLM_API_BASE')
        custom_provider = os.getenv('SHIPIT_LITELLM_CUSTOM_PROVIDER')

        if api_base:
            # Proxy mode — use the convenience wrapper with sensible defaults.
            return LiteLLMProxyChatLLM(
                model=model,
                api_base=api_base,
                api_key=api_key,
                custom_llm_provider=custom_provider or 'openai',
            )

        # Direct LiteLLM SDK mode.
        completion_kwargs: dict[str, Any] = {}
        if api_key:
            completion_kwargs['api_key'] = api_key
        if custom_provider:
            completion_kwargs['custom_llm_provider'] = custom_provider
        return LiteLLMChatLLM(model=model, **completion_kwargs)
    if selected == 'groq':
        _require_any(['GROQ_API_KEY'], provider='groq')
        return GroqChatLLM(model=os.getenv('SHIPIT_GROQ_MODEL', 'groq/llama-3.3-70b-versatile'))
    if selected == 'together':
        _require_any(['TOGETHERAI_API_KEY', 'TOGETHER_API_KEY'], provider='together')
        return TogetherChatLLM(
            model=os.getenv(
                'SHIPIT_TOGETHER_MODEL',
                'together_ai/meta-llama/Llama-3.1-70B-Instruct-Turbo',
            )
        )
    if selected == 'ollama':
        return OllamaChatLLM(model=os.getenv('SHIPIT_OLLAMA_MODEL', 'ollama/llama3.1'))

    raise RuntimeError(
        f'Unsupported SHIPIT_LLM_PROVIDER={selected!r}. Supported values: {", ".join(SUPPORTED_PROVIDERS)}'
    )


def project_context(**_ignored) -> str:
    # Accept and ignore stray kwargs — some LLMs hallucinate an `action` argument
    # for zero-arg tools because the generated JSON schema has no properties.
    return (
        'This workspace uses SHIPIT Agent for tool-using workflows. '
        'Prefer grounded answers, explain tradeoffs clearly, and use tools before guessing.'
    )


def add_numbers(a: int, b: int, **_ignored) -> str:
    return str(int(a) + int(b))


def build_demo_tools(*, llm, workspace_root: str):
    tools = get_builtin_tools(
        llm=llm,
        workspace_root=workspace_root,
        web_search_provider=os.getenv('SHIPIT_WEB_SEARCH_PROVIDER', 'duckduckgo'),
        web_search_api_key=os.getenv('SHIPIT_WEB_SEARCH_API_KEY'),
    )
    tools.extend(
        [
            FunctionTool.from_callable(
                project_context,
                name='project_context',
                description='Return the local project context and execution style for this agent.',
            ),
            FunctionTool.from_callable(
                add_numbers,
                name='add_numbers',
                description='Add two integers and return the result.',
            ),
        ]
    )
    return tools


def build_demo_agent(*, llm=None, workspace_root: str = DEFAULT_WORKSPACE, history: list[Message] | None = None) -> Agent:
    workspace = Path(workspace_root)
    workspace.mkdir(parents=True, exist_ok=True)
    active_llm = llm or build_llm_from_env()
    return Agent(
        llm=active_llm,
        prompt=os.getenv('SHIPIT_AGENT_PROMPT', DEFAULT_AGENT_PROMPT),
        name='shipit-demo',
        description='Runnable multi-tool demo agent with memory, sessions, traces, and provider selection.',
        tools=build_demo_tools(llm=active_llm, workspace_root=str(workspace)),
        history=list(history or []),
        memory_store=FileMemoryStore(workspace / 'memory.json'),
        session_store=FileSessionStore(workspace / 'sessions'),
        trace_store=FileTraceStore(workspace / 'traces'),
        session_id=os.getenv('SHIPIT_SESSION_ID', 'demo-session'),
        trace_id=os.getenv('SHIPIT_TRACE_ID', 'demo-trace'),
    )


def main(argv: list[str] | None = None) -> int:
    load_env_file('.env')
    args = list(argv or sys.argv[1:])
    prompt = ' '.join(args).strip() or os.getenv(
        'SHIPIT_PROMPT',
        'Use the available tools to inspect the workspace, gather context, and answer clearly.',
    )
    stream = os.getenv('SHIPIT_STREAM', '0').lower() in {'1', 'true', 'yes'}
    workspace_root = os.getenv('SHIPIT_WORKSPACE_ROOT', DEFAULT_WORKSPACE)
    agent = build_demo_agent(workspace_root=workspace_root)

    if stream:
        for event in agent.stream(prompt):
            details = f' :: {event.message}' if event.message else ''
            print(f'[{event.type}]{details}')
        return 0

    result = agent.run(prompt)
    print(result.output)
    if result.tool_results:
        print('\nTool results:')
        for item in result.tool_results:
            print(f'- {item.name}: {item.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
