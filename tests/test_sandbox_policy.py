"""The sandbox option: settings, profiles, wrapping and the bash permission verdict.

These run on any platform; tests/test_sandbox_live.py runs real sandboxes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shipit_agent.llms import LLMResponse
from shipit_agent.sandbox import SandboxPolicy, SandboxUnavailable, wrap_argv
from shipit_agent.sandbox import wrap as wrap_module
from shipit_agent.sandbox.backends import bubblewrap_args, seatbelt_profile
from shipit_agent.sdk import AgentOptions, build_agent
from shipit_agent.tools.bash import BashTool

ON = {"enabled": True}


def policy(**settings) -> SandboxPolicy:
    return SandboxPolicy.from_settings({**ON, **settings})


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch):
    """Pretend a backend is (or is not) available."""
    def use(name: str | None) -> None:
        monkeypatch.setattr(wrap_module, "available_backend", lambda: name)
    use("seatbelt")
    return use


def test_settings_use_the_sdk_names_and_defaults() -> None:
    p = SandboxPolicy.from_settings({
        "enabled": True, "excludedCommands": ["docker *"], "autoAllowBashIfSandboxed": False,
        "network": {"allowedDomains": ["pypi.org"], "allowLocalBinding": True},
        "filesystem": {"denyWrite": ["/x"], "allowWrite": ["/y"], "denyRead": ["/z"]},
    })
    assert (p.enabled, p.auto_allow_bash, p.allow_unsandboxed, p.fail_if_unavailable) == (True, False, True, False)
    assert p.excluded_commands == ("docker *",) and p.allow_network and p.allow_local_binding
    assert (p.deny_write, p.allow_write, p.deny_read) == (("/x",), ("/y",), ("/z",))
    assert not SandboxPolicy.from_settings({}).enabled
    assert not policy().allow_network


@pytest.mark.parametrize("settings, where", [
    ({"enabeld": True}, "sandbox"),
    ({"network": {"allowedDomain": []}}, "sandbox.network"),
    ({"filesystem": {"denywrite": []}}, "sandbox.filesystem"),
])
def test_a_misspelt_setting_is_an_error_not_ignored(settings, where) -> None:
    with pytest.raises(ValueError, match=f"unknown {where}"):
        SandboxPolicy.from_settings(settings)


def test_settings_must_be_a_dict() -> None:
    with pytest.raises(TypeError):
        SandboxPolicy.from_settings({"network": ["x"]})


@pytest.mark.parametrize("command, excluded", [
    ("docker ps", True),
    ("docker ps && docker images", True),
    ("docker ps && rm -rf build", False),       # one sandboxed part keeps it all in
    ("ls", False),
    ("", False),
])
def test_excluded_commands_need_every_part_to_match(command, excluded) -> None:
    assert policy(excludedCommands=["docker *"]).excludes(command) is excluded
    assert not policy().excludes("docker ps")


def test_seatbelt_denies_writes_except_the_allowed_folders(tmp_path: Path) -> None:
    profile = seatbelt_profile(policy(filesystem={"denyWrite": [str(tmp_path / "keep")]}), [str(tmp_path)])
    assert "(deny file-write*)" in profile
    assert f'(subpath "{tmp_path}")' in profile
    # Last rule wins in Seatbelt, so the carve-out must follow the allow.
    assert profile.index(f'(subpath "{tmp_path}")') < profile.index(f'(deny file-write* (subpath "{tmp_path / "keep"}"))')
    assert "(deny network*)" in profile


def test_seatbelt_network_rules() -> None:
    assert "(deny network*)" not in seatbelt_profile(policy(network={"allowedDomains": ["*"]}), [])
    local = seatbelt_profile(policy(network={"allowLocalBinding": True, "allowUnixSockets": ["/var/run/x.sock"]}), [])
    assert '(allow network-bind network-inbound (local ip "localhost:*"))' in local
    assert '(path-literal "/var/run/x.sock")' in local
    assert "(allow network* (remote unix-socket))" in seatbelt_profile(policy(network={"allowAllUnixSockets": True}), [])


def test_seatbelt_quotes_paths() -> None:
    assert r'(subpath "/tmp/a\"b")' in seatbelt_profile(policy(), ['/tmp/a"b'])


def test_bubblewrap_mounts_read_only_with_writable_folders(tmp_path: Path) -> None:
    secret_dir, secret_file = tmp_path / "secret", tmp_path / "key.txt"
    secret_dir.mkdir()
    secret_file.write_text("k")
    args = bubblewrap_args(policy(filesystem={
        "denyWrite": [str(tmp_path / "keep")], "denyRead": [str(secret_dir), str(secret_file), "/no/such/path"],
    }), [str(tmp_path), "/no/such/dir"])
    assert args[:3] == ["--ro-bind", "/", "/"] and "--unshare-net" in args
    assert ["--bind", str(tmp_path), str(tmp_path)] == args[args.index("--bind"):args.index("--bind") + 3]
    assert "/no/such/dir" not in args and "/no/such/path" not in args
    assert ["--tmpfs", str(secret_dir)] == args[args.index("--tmpfs"):args.index("--tmpfs") + 2]
    hide = args.index("/dev/null") - 1
    assert args[hide:hide + 3] == ["--ro-bind", "/dev/null", str(secret_file)]
    keep = args.index(str(tmp_path / "keep")) if str(tmp_path / "keep") in args else None
    assert keep is None  # denyWrite of a path that does not exist is skipped
    assert "--unshare-net" not in bubblewrap_args(policy(network={"allowedDomains": ["*"]}), [])


def test_wrap_leaves_commands_alone_when_off_excluded_or_approved_out(backend) -> None:
    argv = ["/bin/bash", "-lc", "docker ps"]
    assert wrap_argv(argv, "docker ps", None, []).argv == argv
    assert wrap_argv(argv, "docker ps", SandboxPolicy(), []).argv == argv
    assert not wrap_argv(argv, "docker ps", policy(excludedCommands=["docker *"]), []).sandboxed
    assert not wrap_argv(argv, "ls", policy(), [], unsandboxed=True).sandboxed
    # Asking out is ignored when unsandboxed commands are not allowed.
    assert wrap_argv(argv, "ls", policy(allowUnsandboxedCommands=False), [], unsandboxed=True).sandboxed
    wrapped = wrap_argv(argv, "ls", policy(), [])
    assert wrapped.sandboxed and wrapped.argv[-3:] == argv and wrapped.argv[0] == "/usr/bin/sandbox-exec"


def test_no_sandbox_here_runs_unsandboxed_or_fails_as_asked(backend, caplog, monkeypatch) -> None:
    backend(None)
    monkeypatch.setattr(wrap_module, "_warned_unavailable", False)
    with caplog.at_level("WARNING"):
        out = wrap_argv(["x"], "ls", policy(), [])
    assert not out.sandboxed and "unavailable" in caplog.text
    with pytest.raises(SandboxUnavailable):
        wrap_argv(["x"], "ls", policy(failIfUnavailable=True), [])


def _bash(tmp_path: Path, **settings) -> BashTool:
    return BashTool(root_dir=tmp_path, sandbox_policy=policy(**settings))


def test_the_unsandboxed_flag_is_offered_only_when_allowed(tmp_path: Path) -> None:
    def props(tool: BashTool) -> dict:
        return tool.schema()["function"]["parameters"]["properties"]

    assert "dangerouslyDisableSandbox" in props(_bash(tmp_path))
    assert "dangerouslyDisableSandbox" not in props(_bash(tmp_path, allowUnsandboxedCommands=False))
    assert "dangerouslyDisableSandbox" not in props(BashTool(root_dir=tmp_path))


def test_sandboxed_risky_commands_need_no_approval(tmp_path: Path, backend) -> None:
    risky = {"command": "rm -rf build"}
    assert _bash(tmp_path).assess_command(risky).level == "safe"
    assert _bash(tmp_path, autoAllowBashIfSandboxed=False).assess_command(risky).level == "risky"
    assert _bash(tmp_path).assess_command({"command": "rm -rf /"}).level == "blocked"
    out = _bash(tmp_path).assess_command({"command": "ls", "dangerouslyDisableSandbox": True})
    assert out.level == "risky" and "outside the sandbox" in out.reasons[-1]
    backend(None)
    assert _bash(tmp_path).assess_command(risky).level == "risky"


class Quiet:
    model = "m"

    def complete(self, **_):
        return LLMResponse(content="ok")


def test_agent_options_sandbox_reaches_bash_and_run_code(tmp_path: Path, backend) -> None:
    extra = tmp_path / "shared"
    extra.mkdir()
    agent = build_agent(AgentOptions(llm=Quiet(), cwd=tmp_path, tools=["bash", "run_code"],
                                     add_dirs=[extra], sandbox={"enabled": True}))
    tools = {t.name: t for t in agent.tools}
    assert all(tools[n].sandbox_policy.enabled for n in ("bash", "run_code"))
    assert extra.resolve() in tools["bash"].extra_roots


def test_agent_options_sandbox_errors(tmp_path: Path, backend) -> None:
    with pytest.raises(ValueError, match="unknown sandbox"):
        build_agent(AgentOptions(llm=Quiet(), cwd=tmp_path, sandbox={"enable": True}))
    backend(None)
    with pytest.raises(SandboxUnavailable):
        build_agent(AgentOptions(llm=Quiet(), cwd=tmp_path, sandbox={"enabled": True, "failIfUnavailable": True}))
