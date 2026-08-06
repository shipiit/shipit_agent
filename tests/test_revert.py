"""Revert — and the invariant that stops the flag becoming a lie again."""

from __future__ import annotations

import pytest

from shipit_agent.approvals import (
    ActionState,
    ApprovalQueue,
    FileSnapshotReverter,
    can_revert,
    register_reverter,
    reverter_for,
)
from shipit_agent.approvals.revert import REVERTERS
from shipit_agent.tools.contracts import CONTRACTS, ActionKind, ToolContract


class TestTheInvariant:
    def test_every_contract_promising_revert_has_a_reverter(self) -> None:
        """The whole point of this module.

        Before it, 18 contracts promised revert and 0 implementations existed —
        a UI reading the flag would offer an undo button that did nothing.
        """
        promised = {n for n, c in CONTRACTS.items() if c.implements_revert}
        missing = sorted(n for n in promised if not can_revert(n))
        assert not missing, f"promise revert with no reverter: {missing}"

    def test_connectors_declare_honestly(self) -> None:
        # No per-vendor inverse operation exists, so the flag must be false.
        for tool in ("jira", "linear", "notion", "confluence", "google_drive"):
            assert not CONTRACTS[tool].implements_revert, tool

    def test_sends_are_never_revertible(self) -> None:
        # You cannot unsend a message.
        for tool in ("slack", "zendesk"):
            assert not CONTRACTS[tool].implements_revert, tool

    def test_filesystem_writes_are(self) -> None:
        for tool in ("write_file", "edit_file", "notebook_edit"):
            assert CONTRACTS[tool].implements_revert and can_revert(tool), tool


class TestFileSnapshot:
    def test_restores_a_modified_file(self, tmp_path) -> None:
        target = tmp_path / "app.py"
        target.write_text("original")
        reverter = FileSnapshotReverter(backup_root=tmp_path / "bak")

        snapshot = reverter.capture("write_file", {"path": str(target)})
        target.write_text("clobbered")
        reverter.restore(snapshot)
        assert target.read_text() == "original"

    def test_deletes_a_file_that_did_not_exist(self, tmp_path) -> None:
        target = tmp_path / "new.py"
        reverter = FileSnapshotReverter(backup_root=tmp_path / "bak")

        snapshot = reverter.capture("write_file", {"path": str(target)})
        target.write_text("created by the agent")
        reverter.restore(snapshot)
        # Restoring "nothing" has to mean nothing, or revert leaves litter
        # that looks like real output.
        assert not target.exists()

    def test_preserves_bytes_exactly(self, tmp_path) -> None:
        target = tmp_path / "data.bin"
        payload = bytes(range(256)) * 4
        target.write_bytes(payload)
        reverter = FileSnapshotReverter(backup_root=tmp_path / "bak")

        snapshot = reverter.capture("write_file", {"path": str(target)})
        target.write_bytes(b"nope")
        reverter.restore(snapshot)
        assert target.read_bytes() == payload

    def test_recreates_a_missing_parent_directory(self, tmp_path) -> None:
        target = tmp_path / "nested" / "app.py"
        target.parent.mkdir()
        target.write_text("original")
        reverter = FileSnapshotReverter(backup_root=tmp_path / "bak")

        snapshot = reverter.capture("edit_file", {"path": str(target)})
        import shutil

        shutil.rmtree(target.parent)
        reverter.restore(snapshot)
        assert target.read_text() == "original"

    @pytest.mark.parametrize("key", ["path", "file", "filename", "notebook_path"])
    def test_finds_the_target_under_any_common_key(self, tmp_path, key) -> None:
        target = tmp_path / "x.py"
        target.write_text("v1")
        reverter = FileSnapshotReverter(backup_root=tmp_path / "bak")
        assert reverter.capture("write_file", {key: str(target)}) is not None

    def test_no_identifiable_target_captures_nothing(self, tmp_path) -> None:
        reverter = FileSnapshotReverter(backup_root=tmp_path / "bak")
        assert reverter.capture("write_file", {"content": "x"}) is None

    def test_restoring_nothing_raises_rather_than_silently_succeeding(self) -> None:
        with pytest.raises(ValueError):
            FileSnapshotReverter().restore(None)

    def test_a_lost_backup_raises(self, tmp_path) -> None:
        target = tmp_path / "x.py"
        target.write_text("v1")
        reverter = FileSnapshotReverter(backup_root=tmp_path / "bak")
        snapshot = reverter.capture("write_file", {"path": str(target)})
        snapshot.backup.unlink()
        with pytest.raises(FileNotFoundError):
            reverter.restore(snapshot)


class TestQueueRevert:
    def _queue(self, tmp_path, target):
        queue = ApprovalQueue()
        queue.submit(
            tool="write_file",
            arguments={"path": str(target)},
            apply_fn=lambda: target.write_text("agent wrote this"),
        )
        return queue

    def test_approve_then_revert(self, tmp_path) -> None:
        target = tmp_path / "app.py"
        target.write_text("original")
        queue = self._queue(tmp_path, target)

        queue.approve(1, by="rahul")
        assert target.read_text() == "agent wrote this"
        queue.revert(1)
        assert target.read_text() == "original"

    def test_a_pending_action_cannot_be_reverted(self, tmp_path) -> None:
        queue = self._queue(tmp_path, tmp_path / "app.py")
        assert not queue.get(1).can_revert
        with pytest.raises(ValueError, match="never applied"):
            queue.revert(1)

    def test_reverting_twice_is_a_no_op(self, tmp_path) -> None:
        target = tmp_path / "app.py"
        target.write_text("original")
        queue = self._queue(tmp_path, target)
        queue.approve(1)
        queue.revert(1)
        queue.revert(1)
        assert target.read_text() == "original"

    def test_can_revert_goes_false_after_reverting(self, tmp_path) -> None:
        target = tmp_path / "app.py"
        target.write_text("v1")
        queue = self._queue(tmp_path, target)
        queue.approve(1)
        assert queue.get(1).can_revert
        queue.revert(1)
        assert not queue.get(1).can_revert

    def test_revertable_lists_newest_first(self, tmp_path) -> None:
        queue = ApprovalQueue()
        for i in range(3):
            target = tmp_path / f"f{i}.py"
            target.write_text("v1")
            queue.submit(tool="write_file", arguments={"path": str(target)},
                         apply_fn=lambda t=target: t.write_text("v2"))
        queue.approve_all()
        assert [a.id for a in queue.revertable()] == [3, 2, 1]

    def test_a_non_revertible_tool_refuses(self) -> None:
        queue = ApprovalQueue()
        queue.submit(tool="slack", arguments={"channel": "#eng"}, apply_fn=lambda: None)
        queue.approve(1)
        assert not queue.get(1).can_revert
        with pytest.raises(NotImplementedError):
            queue.revert(1)

    def test_unknown_id_raises(self) -> None:
        with pytest.raises(KeyError):
            ApprovalQueue().revert(99)

    def test_a_failed_capture_does_not_block_the_action(self, tmp_path) -> None:
        # Capture is best-effort; the action still applies, and can_revert
        # then correctly reports False.
        queue = ApprovalQueue()
        applied = []
        queue.submit(tool="write_file", arguments={"content": "no path here"},
                     apply_fn=lambda: applied.append(1))
        queue.approve(1)
        assert applied == [1]
        assert queue.get(1).state is ActionState.APPROVED
        assert not queue.get(1).can_revert


class TestRegistration:
    def teardown_method(self) -> None:
        REVERTERS.pop("my_connector", None)

    def test_registering_earns_the_flag(self) -> None:
        class Undoer:
            def capture(self, tool, arguments):
                return arguments
            def restore(self, snapshot):
                pass

        assert not can_revert("my_connector")
        register_reverter("my_connector", Undoer())
        assert can_revert("my_connector")
        assert reverter_for("my_connector") is not None

    def test_something_that_is_not_a_reverter_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            register_reverter("my_connector", object())

    def test_a_contract_can_then_claim_revert(self) -> None:
        class Undoer:
            def capture(self, tool, arguments):
                return None
            def restore(self, snapshot):
                pass

        register_reverter("my_connector", Undoer())
        contract = ToolContract(
            action_kind=ActionKind("x.write", "X"), implements_revert=True
        )
        assert contract.implements_revert and can_revert("my_connector")
