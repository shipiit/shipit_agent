# Agent runtime review — 2026-10-06

## Scope and evidence

This is a focused review of the main Agent runtime, sync/async streaming,
session management, output budgeting, MCP result handling and schema caching,
and core file tools. It is not a completed line-by-line audit of every module,
integration or optional dependency. Local regression suites and scripted-model
workflows do not establish production quality across all providers.

## Research applied

- Anthropic's [tool engineering guidance](https://www.anthropic.com/engineering/writing-tools-for-agents)
  emphasizes relevant responses, discoverable tools, and evaluations measuring
  correctness alongside calls, errors, latency and token consumption. Shipit
  already has deferred discovery and bounded model-facing tool output; preserve
  canonical evidence while improving those boundaries rather than indiscriminately
  adding more overlapping tools.
- The MCP project's [annotation guidance](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)
  distinguishes behavioral hints from security guarantees. A read-only annotation
  is not authorization or proof of safe retry. The host must enforce permissions.

## Concrete findings addressed

1. Structured-only MCP results were kept in metadata but described as empty in
   model-visible text. They now render as compact JSON if no other text exists.
2. Static tool metadata could override current execution success/failure. Current
   execution status now wins; non-boolean read-only hints are not accepted.
3. Result deduplication compared raw output but ignored changing semantic views.
   Both must now match before a repeated result is suppressed.
4. Syntactically valid but malformed schema-cache data could crash warm discovery.
   Invalid descriptors now produce a cache miss and live discovery.

See [reliability hardening](reliability-hardening.md) for the preceding session,
stream lifecycle, token accounting, workspace, and targeted-recall changes.

## Highest-value remaining work

- **Durable budgets:** current session usage is in-memory. Company-wide or
  cross-worker spend limits need durable accounting, atomic reservations and
  reconciliation, not a prompt instruction or a per-agent counter.
- **Real-provider evaluations:** run held-out tasks on actual configured models,
  compare success rates, uncached/cache input, output, retries, latency and cost.
  An offline payload reduction is not a billed-token reduction.
- **Provider/cache behavior:** test prefix stability versus dynamic schemas and
  compaction. Caching must be reported by the provider, not inferred from reuse.
- **Production MCP lifecycle:** validate authentication renewal, server-side
  tool changes, tenant scoping, and reconnect behavior with authorized test
  connectors. Annotation hints are not substitutes for these checks.
- **App-building evaluations:** expand beyond the tested small WSGI repair loop
  to multi-file projects and real-model tasks with independent verification.

More tools, more retries, or more subagents can increase cost. Optimization must
hold correctness and evidence availability constant, and measure total cost per
successful task rather than only the size of one request.
