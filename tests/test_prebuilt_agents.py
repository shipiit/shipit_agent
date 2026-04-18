"""Tests for prebuilt agent definitions and the agent registry.

Covers AgentDefinition dataclass behaviour (serialisation, prompt construction),
AgentRegistry loading/search/merge operations, and data-integrity checks
against the built-in agents.json shipped with the package.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shipit_agent.agents.definition import AgentDefinition
from shipit_agent.agents.registry import AgentRegistry


# =========================================================================== #
# Helpers
# =========================================================================== #


def _make_agent(**overrides) -> AgentDefinition:
    """Create an AgentDefinition with sensible defaults, overridable per-field."""
    defaults = dict(
        id="test-agent",
        name="Test Agent",
        role="test specialist",
        goal="Verify everything works correctly.",
        backstory="Built for testing purposes.",
        model="gpt-4",
        tools=["tool_a", "tool_b"],
        skills=["skill_x"],
        max_iterations=5,
        prompt="Follow instructions carefully.",
        category="Testing",
        tags=["test", "demo"],
        version="2.0.0",
        author="tester",
    )
    defaults.update(overrides)
    return AgentDefinition(**defaults)


# =========================================================================== #
# TestAgentDefinition
# =========================================================================== #


class TestAgentDefinition:
    """Unit tests for the AgentDefinition dataclass."""

    # 1 -------------------------------------------------------------------- #
    def test_default_values(self) -> None:
        """An empty AgentDefinition should have sensible zero-value defaults."""
        agent = AgentDefinition()
        assert agent.id == ""
        assert agent.name == ""
        assert agent.role == ""
        assert agent.goal == ""
        assert agent.backstory == ""
        assert agent.model == ""
        assert agent.tools == []
        assert agent.skills == []
        assert agent.max_iterations == 8
        assert agent.prompt == ""
        assert agent.category == ""
        assert agent.tags == []
        assert agent.version == "1.0.0"
        assert agent.author == "shipit"

    # 2 -------------------------------------------------------------------- #
    def test_full_construction(self) -> None:
        """All fields can be set via the constructor."""
        agent = _make_agent()
        assert agent.id == "test-agent"
        assert agent.name == "Test Agent"
        assert agent.role == "test specialist"
        assert agent.goal == "Verify everything works correctly."
        assert agent.backstory == "Built for testing purposes."
        assert agent.model == "gpt-4"
        assert agent.tools == ["tool_a", "tool_b"]
        assert agent.skills == ["skill_x"]
        assert agent.max_iterations == 5
        assert agent.prompt == "Follow instructions carefully."
        assert agent.category == "Testing"
        assert agent.tags == ["test", "demo"]
        assert agent.version == "2.0.0"
        assert agent.author == "tester"

    # 3 -------------------------------------------------------------------- #
    def test_to_dict_camel_case(self) -> None:
        """to_dict() should produce camelCase keys matching JSON wire format."""
        agent = _make_agent()
        d = agent.to_dict()

        # Spot-check camelCase conversions
        assert "maxIterations" in d
        assert "max_iterations" not in d
        assert d["maxIterations"] == 5

        assert "id" in d  # single-word keys stay the same
        assert d["id"] == "test-agent"

        # All expected camelCase keys present
        expected_keys = {
            "id",
            "name",
            "role",
            "goal",
            "backstory",
            "model",
            "tools",
            "skills",
            "maxIterations",
            "prompt",
            "category",
            "tags",
            "version",
            "author",
        }
        assert set(d.keys()) == expected_keys

    # 4 -------------------------------------------------------------------- #
    def test_from_dict_snake_case(self) -> None:
        """from_dict() should accept snake_case keys."""
        data = {
            "id": "from-snake",
            "name": "Snake Agent",
            "max_iterations": 12,
            "tools": ["t1"],
        }
        agent = AgentDefinition.from_dict(data)
        assert agent.id == "from-snake"
        assert agent.name == "Snake Agent"
        assert agent.max_iterations == 12
        assert agent.tools == ["t1"]

    # 5 -------------------------------------------------------------------- #
    def test_from_dict_camel_case(self) -> None:
        """from_dict() should accept camelCase keys."""
        data = {
            "id": "from-camel",
            "name": "Camel Agent",
            "maxIterations": 15,
            "tools": ["t2"],
        }
        agent = AgentDefinition.from_dict(data)
        assert agent.id == "from-camel"
        assert agent.name == "Camel Agent"
        assert agent.max_iterations == 15
        assert agent.tools == ["t2"]

    # 6 -------------------------------------------------------------------- #
    def test_from_dict_ignores_unknown_keys(self) -> None:
        """Extra keys in the input dict should be silently ignored."""
        data = {
            "id": "robust",
            "unknownField": "should not crash",
            "anotherBogusKey": 42,
        }
        agent = AgentDefinition.from_dict(data)
        assert agent.id == "robust"
        # Unknown keys don't appear as attributes
        assert not hasattr(agent, "unknown_field")

    # 7 -------------------------------------------------------------------- #
    def test_system_prompt_all_sections(self) -> None:
        """system_prompt() should include all four sections when all fields are set."""
        agent = _make_agent(
            role="security expert",
            goal="Find vulnerabilities.",
            backstory="10 years of pen-testing experience.",
            prompt="Scan every file carefully.",
        )
        prompt = agent.system_prompt()

        assert "# Role" in prompt
        assert "You are a security expert." in prompt
        assert "# Goal" in prompt
        assert "Find vulnerabilities." in prompt
        assert "# Background" in prompt
        assert "10 years of pen-testing experience." in prompt
        assert "# Instructions" in prompt
        assert "Scan every file carefully." in prompt

    # 8 -------------------------------------------------------------------- #
    def test_system_prompt_partial(self) -> None:
        """system_prompt() with only role and prompt omits Goal and Background."""
        agent = AgentDefinition(
            role="code reviewer",
            prompt="Check for style issues.",
        )
        prompt = agent.system_prompt()

        assert "# Role" in prompt
        assert "You are a code reviewer." in prompt
        assert "# Instructions" in prompt
        assert "Check for style issues." in prompt

        # Sections for missing fields should not appear
        assert "# Goal" not in prompt
        assert "# Background" not in prompt

    # 9 -------------------------------------------------------------------- #
    def test_system_prompt_empty(self) -> None:
        """system_prompt() returns empty string when no fields are set."""
        agent = AgentDefinition()
        assert agent.system_prompt() == ""

    # 10 ------------------------------------------------------------------- #
    def test_roundtrip_serialization(self) -> None:
        """to_dict() -> from_dict() should produce an equivalent AgentDefinition."""
        original = _make_agent()
        roundtripped = AgentDefinition.from_dict(original.to_dict())

        assert roundtripped.id == original.id
        assert roundtripped.name == original.name
        assert roundtripped.role == original.role
        assert roundtripped.goal == original.goal
        assert roundtripped.backstory == original.backstory
        assert roundtripped.model == original.model
        assert roundtripped.tools == original.tools
        assert roundtripped.skills == original.skills
        assert roundtripped.max_iterations == original.max_iterations
        assert roundtripped.prompt == original.prompt
        assert roundtripped.category == original.category
        assert roundtripped.tags == original.tags
        assert roundtripped.version == original.version
        assert roundtripped.author == original.author

    # 11 ------------------------------------------------------------------- #
    def test_to_dict_defensive_copy(self) -> None:
        """Mutating a list in the returned dict must not affect the original agent."""
        agent = _make_agent(tools=["original_tool"])
        d = agent.to_dict()
        d["tools"].append("injected")

        # The agent's own tools list should be untouched
        assert agent.tools == ["original_tool"]


# =========================================================================== #
# TestAgentRegistry
# =========================================================================== #


class TestAgentRegistry:
    """Tests for AgentRegistry loading, lookup, search, and composition."""

    # 12 ------------------------------------------------------------------- #
    def test_default_registry_loads(self) -> None:
        """AgentRegistry.default() loads without raising."""
        registry = AgentRegistry.default()
        assert registry is not None

    # 13 ------------------------------------------------------------------- #
    def test_default_registry_has_agents(self) -> None:
        """The built-in registry should contain at least 30 agents."""
        registry = AgentRegistry.default()
        assert len(registry) >= 30

    # 14 ------------------------------------------------------------------- #
    def test_default_registry_has_categories(self) -> None:
        """The built-in registry should span at least 5 categories."""
        registry = AgentRegistry.default()
        assert len(registry.categories()) >= 5

    # 15 ------------------------------------------------------------------- #
    def test_get_existing_agent(self) -> None:
        """get() returns the correct agent for a known id."""
        registry = AgentRegistry.default()
        agent = registry.get("security-auditor")
        assert agent is not None
        assert agent.id == "security-auditor"
        assert agent.name  # non-empty name

    # 16 ------------------------------------------------------------------- #
    def test_get_nonexistent_agent(self) -> None:
        """get() returns None for an id that does not exist."""
        registry = AgentRegistry.default()
        assert registry.get("nonexistent-agent-xyz") is None

    # 17 ------------------------------------------------------------------- #
    def test_search_finds_results(self) -> None:
        """search() returns agents matching the query."""
        registry = AgentRegistry.default()
        results = registry.search("security")
        assert len(results) > 0
        # At least one result should have 'security' somewhere in its fields
        texts = " ".join(
            f"{a.id} {a.name} {a.role} {a.goal} {a.category} {' '.join(a.tags)}"
            for a in results
        ).lower()
        assert "security" in texts

    # 18 ------------------------------------------------------------------- #
    def test_search_no_results(self) -> None:
        """search() returns an empty list for a nonsense query."""
        registry = AgentRegistry.default()
        assert registry.search("xyznonexistent") == []

    # 19 ------------------------------------------------------------------- #
    def test_search_ranks_by_relevance(self) -> None:
        """The first result of a search should be the most relevant."""
        registry = AgentRegistry.default()
        results = registry.search("security auditor")
        assert len(results) >= 1
        # The top result should have "security" in its id or name
        top = results[0]
        combined = f"{top.id} {top.name} {top.role}".lower()
        assert "security" in combined

    # 20 ------------------------------------------------------------------- #
    def test_list_by_category(self) -> None:
        """list_by_category() returns agents in the given category."""
        registry = AgentRegistry.default()
        security_agents = registry.list_by_category("Security")
        assert len(security_agents) >= 1
        for agent in security_agents:
            assert agent.category.lower() == "security"

    # 21 ------------------------------------------------------------------- #
    def test_list_by_category_case_insensitive(self) -> None:
        """list_by_category() matching is case-insensitive."""
        registry = AgentRegistry.default()
        upper = registry.list_by_category("SECURITY")
        lower = registry.list_by_category("security")
        mixed = registry.list_by_category("Security")

        ids_upper = {a.id for a in upper}
        ids_lower = {a.id for a in lower}
        ids_mixed = {a.id for a in mixed}

        assert ids_upper == ids_lower == ids_mixed

    # 22 ------------------------------------------------------------------- #
    def test_list_all_sorted(self) -> None:
        """list_all() returns agents sorted by id."""
        registry = AgentRegistry.default()
        agents = registry.list_all()
        ids = [a.id for a in agents]
        assert ids == sorted(ids)

    # 23 ------------------------------------------------------------------- #
    def test_categories_unique_sorted(self) -> None:
        """categories() returns a sorted list with no duplicates."""
        registry = AgentRegistry.default()
        cats = registry.categories()
        assert cats == sorted(cats)
        assert len(cats) == len(set(cats))

    # 24 ------------------------------------------------------------------- #
    def test_contains(self) -> None:
        """The 'in' operator checks agent id membership."""
        registry = AgentRegistry.default()
        assert "security-auditor" in registry
        assert "no-such-agent-ever" not in registry

    # 25 ------------------------------------------------------------------- #
    def test_len(self) -> None:
        """len() returns the number of agents."""
        registry = AgentRegistry.default()
        assert len(registry) == len(registry.list_all())

    # 26 ------------------------------------------------------------------- #
    def test_repr(self) -> None:
        """repr() shows the agent count."""
        registry = AgentRegistry.default()
        r = repr(registry)
        assert "AgentRegistry" in r
        assert str(len(registry)) in r

    # 27 ------------------------------------------------------------------- #
    def test_load_from_file(self, tmp_path: Path) -> None:
        """load() reads a JSON array file and creates a valid registry."""
        agents_data = [
            {
                "id": "alpha",
                "name": "Alpha Agent",
                "role": "helper",
                "category": "Test",
            },
            {"id": "beta", "name": "Beta Agent", "role": "checker", "category": "Test"},
        ]
        json_file = tmp_path / "custom_agents.json"
        json_file.write_text(json.dumps(agents_data), encoding="utf-8")

        registry = AgentRegistry.load(json_file)
        assert len(registry) == 2
        assert registry.get("alpha") is not None
        assert registry.get("beta") is not None
        assert registry.get("alpha").name == "Alpha Agent"

    # 28 ------------------------------------------------------------------- #
    def test_from_directory(self, tmp_path: Path) -> None:
        """from_directory() reads individual .json files from a directory."""
        for agent_id in ("gamma", "delta"):
            data = {
                "id": agent_id,
                "name": f"{agent_id.title()} Agent",
                "role": "worker",
            }
            (tmp_path / f"{agent_id}.json").write_text(
                json.dumps(data), encoding="utf-8"
            )

        registry = AgentRegistry.from_directory(tmp_path)
        assert len(registry) == 2
        assert "gamma" in registry
        assert "delta" in registry

    # 29 ------------------------------------------------------------------- #
    def test_merge_override(self) -> None:
        """merge() lets the second registry override agents with the same id."""
        a1 = _make_agent(id="shared", name="Original")
        a2 = _make_agent(id="shared", name="Override")

        reg_a = AgentRegistry([a1])
        reg_b = AgentRegistry([a2])
        merged = reg_a.merge(reg_b)

        assert merged.get("shared").name == "Override"

    # 30 ------------------------------------------------------------------- #
    def test_merge_preserves_non_overlapping(self) -> None:
        """merge() keeps agents unique to each registry."""
        a1 = _make_agent(id="only-in-a", name="Agent A")
        a2 = _make_agent(id="only-in-b", name="Agent B")

        reg_a = AgentRegistry([a1])
        reg_b = AgentRegistry([a2])
        merged = reg_a.merge(reg_b)

        assert len(merged) == 2
        assert "only-in-a" in merged
        assert "only-in-b" in merged


# =========================================================================== #
# TestAgentDefinitionIntegrity
# =========================================================================== #


class TestAgentDefinitionIntegrity:
    """Data-integrity checks against every agent in the built-in registry.

    These tests catch missing or malformed fields before they reach users.
    """

    @pytest.fixture(scope="class")
    def default_agents(self) -> list[AgentDefinition]:
        """Load the built-in agents once for all integrity tests."""
        return AgentRegistry.default().list_all()

    # 31 ------------------------------------------------------------------- #
    def test_all_agents_have_id(self, default_agents: list[AgentDefinition]) -> None:
        """Every agent must have a non-empty id."""
        for agent in default_agents:
            assert agent.id, f"Agent with name={agent.name!r} has an empty id"

    # 32 ------------------------------------------------------------------- #
    def test_all_agents_have_name(self, default_agents: list[AgentDefinition]) -> None:
        """Every agent must have a non-empty name."""
        for agent in default_agents:
            assert agent.name, f"Agent {agent.id!r} has an empty name"

    # 33 ------------------------------------------------------------------- #
    def test_all_agents_have_role(self, default_agents: list[AgentDefinition]) -> None:
        """Every agent must have a non-empty role."""
        for agent in default_agents:
            assert agent.role, f"Agent {agent.id!r} has an empty role"

    # 34 ------------------------------------------------------------------- #
    def test_all_agents_have_prompt(
        self, default_agents: list[AgentDefinition]
    ) -> None:
        """Every agent must have a non-empty prompt."""
        for agent in default_agents:
            assert agent.prompt, f"Agent {agent.id!r} has an empty prompt"

    # 35 ------------------------------------------------------------------- #
    def test_all_agents_have_category(
        self, default_agents: list[AgentDefinition]
    ) -> None:
        """Every agent must have a non-empty category."""
        for agent in default_agents:
            assert agent.category, f"Agent {agent.id!r} has an empty category"

    # 36 ------------------------------------------------------------------- #
    def test_all_agents_have_tools(self, default_agents: list[AgentDefinition]) -> None:
        """Every agent must list at least one tool."""
        for agent in default_agents:
            assert len(agent.tools) >= 1, f"Agent {agent.id!r} has no tools"

    # 37 ------------------------------------------------------------------- #
    def test_no_duplicate_ids(self, default_agents: list[AgentDefinition]) -> None:
        """All agent IDs in the built-in registry must be unique."""
        ids = [a.id for a in default_agents]
        assert len(ids) == len(
            set(ids)
        ), f"Duplicate IDs found: {[x for x in ids if ids.count(x) > 1]}"

    # 38 ------------------------------------------------------------------- #
    def test_system_prompt_non_empty(
        self, default_agents: list[AgentDefinition]
    ) -> None:
        """Every agent's system_prompt() must return non-empty content."""
        for agent in default_agents:
            prompt = agent.system_prompt()
            assert prompt.strip(), f"Agent {agent.id!r} has an empty system_prompt()"

    # 39 ------------------------------------------------------------------- #
    def test_all_categories_represented(
        self, default_agents: list[AgentDefinition]
    ) -> None:
        """The built-in agents should span at least 6 distinct categories."""
        categories = {a.category for a in default_agents if a.category}
        assert (
            len(categories) >= 6
        ), f"Only {len(categories)} categories found: {categories}"
