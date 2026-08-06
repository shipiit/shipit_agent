"""Bindings and catalogs — the `env` namespace behind code mode."""

from __future__ import annotations

import pytest

from shipit_agent.codemode.bindings import (
    DEFAULT_METHOD,
    BindingMethod,
    binding_name_for,
    build_binding,
    build_bindings,
)
from shipit_agent.codemode.catalog import (
    MAX_ENTRIES,
    MAX_TITLE_LENGTH,
    CatalogEntry,
    ResourceCatalog,
    load_catalog,
    normalize_catalog,
)


class FakeTool:
    """A tool with an action enum, like every shipit connector."""

    def __init__(self, name="github", actions=("get_issue", "create_issue")):
        self.name = name
        self.description = "Work with GitHub issues and pull requests."
        self.prompt_instructions = ""
        self._actions = list(actions)

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": self._actions},
                        "owner": {"type": "string", "description": "Repo owner"},
                        "repo": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["action", "owner", "repo"],
                },
            },
        }


class SimpleTool:
    """A tool with no action enum — one operation."""

    name = "read_file"
    description = "Read a file."
    prompt_instructions = ""

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }


class TestNaming:
    @pytest.mark.parametrize(
        "tool_name,expected",
        [
            ("github", "GITHUB"),
            ("google_sheets", "SHEETS"),
            ("google_drive", "DRIVE"),
            ("linkedin_search", "LINKEDIN"),
            ("custom_api", "CUSTOM"),
            ("read_file", "READ_FILE"),
            ("linear__create_issue", "CREATE_ISSUE"),
        ],
    )
    def test_binding_names(self, tool_name, expected) -> None:
        assert binding_name_for(tool_name) == expected

    def test_never_empty(self) -> None:
        assert binding_name_for("___")


class TestBindingConstruction:
    def test_action_enum_becomes_methods(self) -> None:
        binding = build_binding(FakeTool())
        assert binding.method_names() == ["create_issue", "get_issue"]

    def test_action_is_not_also_a_parameter(self) -> None:
        binding = build_binding(FakeTool())
        assert "action" not in binding.methods["get_issue"].parameters

    def test_action_is_dropped_from_required(self) -> None:
        binding = build_binding(FakeTool())
        assert binding.methods["get_issue"].required == ("owner", "repo")

    def test_no_enum_yields_one_call_method(self) -> None:
        binding = build_binding(SimpleTool())
        assert binding.method_names() == [DEFAULT_METHOD]
        assert "path" in binding.methods[DEFAULT_METHOD].parameters

    def test_contract_is_carried(self) -> None:
        assert build_binding(SimpleTool()).contract.read_only
        assert not build_binding(FakeTool()).contract.read_only

    def test_a_broken_schema_does_not_raise(self) -> None:
        class Broken:
            name = "broken"
            description = ""

            def schema(self):
                raise RuntimeError("no schema for you")

        binding = build_binding(Broken())
        assert binding.method_names() == [DEFAULT_METHOD]

    def test_alternative_action_keys(self) -> None:
        class OpTool(FakeTool):
            def schema(self):
                return {
                    "function": {
                        "name": "git_ops",
                        "parameters": {
                            "properties": {
                                "operation": {"type": "string", "enum": ["status", "diff"]}
                            }
                        },
                    }
                }

        assert build_binding(OpTool()).method_names() == ["diff", "status"]


class TestSignatures:
    def test_signature_orders_required_first(self) -> None:
        method = BindingMethod(
            name="create_issue",
            description="",
            parameters={"owner": {}, "repo": {}, "title": {}, "body": {}},
            required=("owner", "repo"),
        )
        assert method.signature() == "create_issue(owner, repo, *, title=None, body=None)"

    def test_signature_with_no_optionals(self) -> None:
        method = BindingMethod("get", "", {"id": {}}, ("id",))
        assert method.signature() == "get(id)"

    def test_signature_with_no_parameters(self) -> None:
        assert BindingMethod("ping", "", {}, ()).signature() == "ping()"

    def test_describe_lists_parameters_with_types(self) -> None:
        described = build_binding(FakeTool()).methods["create_issue"].describe()
        assert "owner: string" in described
        assert "Repo owner" in described
        assert "(optional)" in described  # title is not required


class TestDescribe:
    def test_describe_names_the_binding_and_methods(self) -> None:
        described = build_binding(FakeTool()).describe()
        assert "env.GITHUB" in described
        assert "create_issue" in described and "get_issue" in described

    def test_read_only_bindings_say_so(self) -> None:
        assert "Read-only" in build_binding(SimpleTool()).describe()

    def test_gated_bindings_name_their_action_kind(self) -> None:
        described = build_binding(FakeTool()).describe()
        assert "vcs.write" in described

    def test_catalog_is_included(self) -> None:
        catalog = normalize_catalog([{"id": "acme/web", "title": "Web app"}])
        described = build_binding(FakeTool(), catalog=catalog).describe()
        assert "acme/web" in described

    def test_summary_line_is_one_line(self) -> None:
        line = build_binding(FakeTool()).summary_line()
        assert line.startswith("- env.GITHUB") and "\n" not in line


class TestInvocation:
    def test_method_access_routes_through_invoke(self) -> None:
        seen = []
        binding = build_binding(
            FakeTool(), invoke=lambda m, kw: seen.append((m, kw)) or "ok"
        )
        assert binding.get_issue(owner="acme", repo="web", number=1) == "ok"
        assert seen == [("get_issue", {"owner": "acme", "repo": "web", "number": 1})]

    def test_call_by_name(self) -> None:
        binding = build_binding(FakeTool(), invoke=lambda m, kw: (m, kw))
        assert binding.call("create_issue", title="x") == ("create_issue", {"title": "x"})

    def test_unknown_method_raises_with_a_useful_message(self) -> None:
        binding = build_binding(FakeTool(), invoke=lambda m, kw: None)
        with pytest.raises(AttributeError, match="create_issue"):
            binding.nonexistent_method(a=1)

    def test_unbound_binding_can_be_inspected_but_not_called(self) -> None:
        binding = build_binding(FakeTool())
        assert binding.describe()
        with pytest.raises(RuntimeError, match="not bound"):
            binding.get_issue(owner="a", repo="b")

    def test_real_attributes_are_not_shadowed(self) -> None:
        binding = build_binding(FakeTool())
        assert binding.name == "GITHUB"
        assert isinstance(binding.methods, dict)


class TestBuildBindings:
    def test_builds_a_namespace(self) -> None:
        bindings = build_bindings([FakeTool(), SimpleTool()])
        assert set(bindings) == {"GITHUB", "READ_FILE"}

    def test_name_collisions_are_suffixed_not_dropped(self) -> None:
        bindings = build_bindings([FakeTool("github"), FakeTool("github_tool")])
        assert set(bindings) == {"GITHUB", "GITHUB_2"}
        assert len(bindings) == 2

    def test_unnamed_tools_are_skipped(self) -> None:
        class Nameless:
            name = ""

        assert build_bindings([Nameless()]) == {}

    def test_every_builtin_binds(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        tools = get_builtin_tools(llm=None, project_root=".")
        bindings = build_bindings(tools)
        # One binding per tool — a collision must suffix, never drop, or the
        # agent's env would differ from what its prompt says it is.
        assert len(bindings) == len(tools)
        for binding in bindings.values():
            assert binding.methods
            assert binding.describe()


class TestCatalogNormalization:
    def test_dicts_become_entries(self) -> None:
        catalog = normalize_catalog([{"id": "a", "title": "Alpha", "description": "x"}])
        assert catalog.entries == [CatalogEntry("a", "Alpha", "x")]

    def test_bare_strings_work(self) -> None:
        assert normalize_catalog(["alpha"]).entries[0].id == "alpha"

    def test_dict_with_entries_key(self) -> None:
        assert len(normalize_catalog({"entries": [{"id": "a", "title": "A"}]})) == 1

    def test_alternative_field_names(self) -> None:
        catalog = normalize_catalog([{"name": "repo", "summary": "the repo"}])
        assert catalog.entries[0].id == "repo"
        assert catalog.entries[0].description == "the repo"

    def test_control_characters_are_stripped(self) -> None:
        catalog = normalize_catalog([{"id": "a\x00b", "title": "A\x1bB"}])
        assert "\x00" not in catalog.entries[0].id
        assert "\x1b" not in catalog.entries[0].title

    def test_bidi_and_zero_width_are_stripped(self) -> None:
        # These make injected text render differently from how it tokenizes.
        catalog = normalize_catalog([{"id": "a​b", "title": "A‮B"}])
        assert "​" not in catalog.entries[0].id
        assert "‮" not in catalog.entries[0].title

    def test_whitespace_is_collapsed(self) -> None:
        catalog = normalize_catalog([{"id": "a", "title": "A  \n\n  B"}])
        assert catalog.entries[0].title == "A B"

    def test_fields_are_clamped(self) -> None:
        catalog = normalize_catalog([{"id": "a", "title": "T" * 5000}])
        assert len(catalog.entries[0].title) == MAX_TITLE_LENGTH

    def test_unusable_entries_are_dropped(self) -> None:
        assert normalize_catalog([{"description": "no id or title"}]).entries == []
        assert normalize_catalog([{"id": "   ", "title": "x"}]).entries == []

    def test_order_is_deterministic(self) -> None:
        raw = [{"id": "b", "title": "Beta"}, {"id": "a", "title": "Alpha"}]
        assert [e.id for e in normalize_catalog(raw).entries] == ["a", "b"]
        assert normalize_catalog(raw).entries == normalize_catalog(raw[::-1]).entries

    def test_duplicate_ids_are_removed(self) -> None:
        raw = [{"id": "a", "title": "A"}, {"id": "a", "title": "A again"}]
        assert len(normalize_catalog(raw)) == 1

    def test_entry_count_is_capped_and_the_truncation_is_visible(self) -> None:
        raw = [{"id": f"id{i:03}", "title": f"T{i:03}"} for i in range(MAX_ENTRIES + 20)]
        catalog = normalize_catalog(raw)
        assert len(catalog) == MAX_ENTRIES
        assert catalog.truncated
        assert "truncated" in catalog.render()

    def test_upstream_truncation_flag_is_honoured(self) -> None:
        assert normalize_catalog({"entries": [{"id": "a", "title": "A"}],
                                  "truncated": True}).truncated

    @pytest.mark.parametrize("garbage", [None, 42, "a string", object(), {"x": 1}])
    def test_garbage_yields_an_empty_catalog_rather_than_raising(self, garbage) -> None:
        assert normalize_catalog(garbage).entries == []

    def test_non_entry_items_are_skipped(self) -> None:
        assert len(normalize_catalog([{"id": "a", "title": "A"}, 42, None])) == 1

    def test_renormalizing_is_stable(self) -> None:
        once = normalize_catalog([{"id": "a", "title": "A"}])
        assert normalize_catalog(once).entries == once.entries


class TestCatalogRendering:
    def test_empty_renders_to_nothing(self) -> None:
        assert ResourceCatalog().render() == ""

    def test_entries_render_one_per_line(self) -> None:
        catalog = normalize_catalog(
            [{"id": "a", "title": "Alpha", "description": "first"}]
        )
        assert catalog.render() == "  - a: Alpha — first"

    def test_serializable(self) -> None:
        import json

        assert json.dumps(normalize_catalog([{"id": "a", "title": "A"}]).to_dict())


class TestCatalogLoading:
    def test_a_tool_that_offers_one(self) -> None:
        class WithCatalog(SimpleTool):
            def agent_catalog(self):
                return [{"id": "x", "title": "X"}]

        assert len(load_catalog(WithCatalog())) == 1

    def test_a_tool_that_does_not(self) -> None:
        assert load_catalog(SimpleTool()).entries == []

    def test_a_raising_tool_loses_only_its_own_catalog(self) -> None:
        class Broken(SimpleTool):
            def agent_catalog(self):
                raise RuntimeError("upstream is down")

        assert load_catalog(Broken()).entries == []


class TestDescribeBindingTool:
    def _ctx(self, bindings=None):
        from shipit_agent.tools.base import ToolContext
        from shipit_agent.tools.describe_binding.describe_binding_tool import (
            BINDINGS_STATE_KEY,
        )

        if bindings is None:
            bindings = build_bindings([FakeTool(), SimpleTool()])
        return ToolContext(prompt="x", state={BINDINGS_STATE_KEY: bindings})

    def _tool(self):
        from shipit_agent.tools.describe_binding import DescribeBindingTool

        return DescribeBindingTool()

    def test_describes_one_binding(self) -> None:
        out = self._tool().run(self._ctx(), name="GITHUB")
        assert "env.GITHUB" in out.text
        assert out.metadata["binding"] == "GITHUB"
        assert "create_issue" in out.metadata["methods"]

    def test_returns_only_the_requested_binding(self) -> None:
        # The whole point: one binding's surface, not the entire API space.
        out = self._tool().run(self._ctx(), name="GITHUB")
        assert "READ_FILE" not in out.text

    @pytest.mark.parametrize("written", ["github", "GitHub", "env.GITHUB", " GITHUB "])
    def test_name_matching_is_forgiving(self, written) -> None:
        # Models write env.GITHUB, github and GitHub interchangeably; failing
        # on case would spend a turn on nothing.
        assert self._tool().run(self._ctx(), name=written).metadata["binding"] == "GITHUB"

    def test_matches_by_underlying_tool_name(self) -> None:
        out = self._tool().run(self._ctx(), name="read_file")
        assert out.metadata["binding"] == "READ_FILE"

    def test_unknown_binding_lists_what_is_available(self) -> None:
        out = self._tool().run(self._ctx(), name="nope")
        assert "No binding named" in out.text
        assert "env.GITHUB" in out.text

    def test_no_name_lists_everything(self) -> None:
        out = self._tool().run(self._ctx())
        assert "env.GITHUB" in out.text and "env.READ_FILE" in out.text

    def test_outside_code_mode_it_says_so(self) -> None:
        from shipit_agent.tools.base import ToolContext

        out = self._tool().run(ToolContext(prompt="x"), name="GITHUB")
        assert "only populated when" in out.text
        assert out.metadata["binding"] is None

    def test_it_is_an_observation(self) -> None:
        from shipit_agent.tools.contracts import contract_for

        assert contract_for("describe_binding").read_only

    def test_registered_as_a_builtin(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        names = {getattr(t, "name", "") for t in get_builtin_tools(llm=None, project_root=".")}
        assert "describe_binding" in names


class TestPromptCollapse:
    def test_code_mode_is_dramatically_smaller_than_50_schemas(self) -> None:
        """The reason code mode exists, pinned as a test."""
        import json

        from shipit_agent.builtins import get_builtin_tools

        tools = get_builtin_tools(llm=None, project_root=".")
        full = len(json.dumps([t.schema() for t in tools]))

        core_names = {
            "read_file", "write_file", "edit_file", "bash", "glob_files",
            "grep_files", "web_search", "open_url", "describe_binding",
            "ask_user", "todo", "plan_task", "give_up",
        }
        core = len(json.dumps(
            [t.schema() for t in tools if getattr(t, "name", "") in core_names]
        ))
        index = len("\n".join(b.summary_line() for b in build_bindings(tools).values()))

        assert core + index < full * 0.35, (
            f"code mode {core + index} vs {full} — expected a large collapse"
        )

    def test_describing_one_binding_is_cheap(self) -> None:
        from shipit_agent.builtins import get_builtin_tools

        bindings = build_bindings(get_builtin_tools(llm=None, project_root="."))
        # Paid once, on demand — not every call, forever.
        assert len(bindings["GITHUB"].describe()) < 4_000
