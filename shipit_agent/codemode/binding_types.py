"""Bindings: a tool's actions exposed as callable methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from shipit_agent.tools.contracts import ToolContract


@dataclass(frozen=True, slots=True)
class BindingMethod:
    """One callable operation on a binding."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()

    def signature(self) -> str:
        """``create_issue(owner, repo, title, *, body=None, labels=None)``."""
        required = [p for p in self.parameters if p in self.required]
        optional = [p for p in self.parameters if p not in self.required]
        parts = list(required)
        if optional:
            parts.append("*")
            parts.extend(f"{name}=None" for name in optional)
        return f"{self.name}({', '.join(parts)})"

    def describe(self) -> str:
        """Signature plus one line per parameter — what the agent reads."""
        lines = [self.signature()]
        if self.description:
            lines.append(f"    {self.description}")
        for name, spec in self.parameters.items():
            kind = spec.get("type", "any")
            note = spec.get("description", "")
            flag = "" if name in self.required else " (optional)"
            lines.append(f"    - {name}: {kind}{flag}{' — ' + note if note else ''}")
        return "\n".join(lines)


@dataclass(slots=True)
class Binding:
    """One resource in the agent's ``env``.

    ``invoke`` is supplied by the runtime and is what routes a call back
    through the permission gate; a binding built without one is inert, which
    is the safe default for a catalog-only listing.
    """

    name: str
    tool_name: str
    title: str
    description: str
    methods: dict[str, BindingMethod]
    contract: ToolContract
    tool: Any = None
    invoke: Callable[[str, dict[str, Any]], Any] | None = field(
        default=None, repr=False
    )
    catalog: Any = None

    # ── discovery ────────────────────────────────────────────────────────

    def method_names(self) -> list[str]:
        return sorted(self.methods)

    def shares_one_parameter_set(self) -> bool:
        """Do all methods draw from one flat parameter bag?

        True for the connector shape (an `action` enum over shared params),
        false once a tool declares per-method parameters via
        ``action_parameters``.
        """
        if len(self.methods) < 2:
            return False
        first = next(iter(self.methods.values()))
        return all(
            m.parameters is first.parameters or m.parameters == first.parameters
            for m in self.methods.values()
        )

    def describe(self, *, include_parameters: bool = True) -> str:
        """The binding's API, for ``describe_binding``.

        This is the progressive-discovery payload: the agent asks for *one*
        binding and gets only that one's surface, instead of carrying every
        integration's schema in its prompt for the whole run.
        """
        header = f"env.{self.name} — {self.title}"
        lines = [header, "=" * len(header)]
        if self.description:
            lines += ["", self.description]
        if self.contract.read_only:
            lines += ["", "Read-only: calls run immediately, no approval needed."]
        elif self.contract.action_kind:
            lines += [
                "",
                f"Actions on this binding are gated as "
                f"'{self.contract.action_kind.label}' "
                f"({self.contract.action_kind.tag}).",
            ]
        if self.shares_one_parameter_set():
            # A connector schema is one flat parameter bag selected by an
            # `action` enum, so every method would otherwise repeat all ~19
            # parameters. Print them once and list the methods by name — the
            # same information, an order of magnitude less to read.
            lines += ["", "Methods:"]
            lines += [f"  {name}" for name in self.method_names()]
            if include_parameters:
                shared = self.methods[self.method_names()[0]]
                lines += ["", "Parameters (shared; each method uses a subset):"]
                for param, spec in shared.parameters.items():
                    kind = spec.get("type", "any")
                    note = spec.get("description", "")
                    flag = "" if param in shared.required else " (optional)"
                    lines.append(
                        f"  - {param}: {kind}{flag}{' — ' + note if note else ''}"
                    )
        else:
            lines += ["", "Methods:"]
            for name in self.method_names():
                method = self.methods[name]
                lines.append("")
                body = method.describe() if include_parameters else method.signature()
                lines.extend(f"  {line}" for line in body.splitlines())
        if self.catalog is not None:
            rendered = self.catalog.render()
            if rendered:
                lines += ["", "Reachable entries:", rendered]
        return "\n".join(lines)

    def summary_line(self) -> str:
        """One line for the system prompt's binding list."""
        return f"- env.{self.name}: {self.title}"

    # ── invocation ───────────────────────────────────────────────────────

    def __getattr__(self, item: str) -> Any:
        # Only reached for names not already on the dataclass, so real
        # attributes are never shadowed by a method lookup.
        if item.startswith("_") or item not in getattr(self, "methods", {}):
            raise AttributeError(
                f"env.{getattr(self, 'name', '?')} has no method {item!r}. "
                f"Known: {', '.join(getattr(self, 'methods', {}) or ['(none)'])}"
            )

        def _call(**kwargs: Any) -> Any:
            return self.call(item, **kwargs)

        _call.__name__ = item
        return _call

    def call(self, method: str, **kwargs: Any) -> Any:
        """Invoke *method*, routed through the runtime's gate."""
        if method not in self.methods:
            raise AttributeError(
                f"env.{self.name} has no method {method!r}. "
                f"Known: {', '.join(self.method_names()) or '(none)'}"
            )
        if self.invoke is None:
            raise RuntimeError(
                f"env.{self.name} is not bound to a runtime — it can be "
                f"inspected but not called."
            )
        return self.invoke(method, dict(kwargs))

