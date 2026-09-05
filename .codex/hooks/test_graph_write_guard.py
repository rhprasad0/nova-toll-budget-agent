#!/usr/bin/env python3
"""Direct-runnable stdlib tests for graph-write-guard.py."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HOOK = Path(__file__).with_name("graph-write-guard.py")


class GraphWriteGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temp.name)
        self.repo = self.temp_root / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.temp_root)
        self.git("config", "user.email", "guard@example.test", cwd=self.repo)
        self.git("config", "user.name", "Graph Guard", cwd=self.repo)
        (self.repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        self.git("add", "tracked.txt", cwd=self.repo)
        self.git("commit", "-qm", "initial", cwd=self.repo)
        self.worktrees = self.repo / ".worktrees"
        self.worktrees.mkdir()
        self.target = self.worktrees / "child"
        self.sibling = self.worktrees / "child-sibling"
        self.git("worktree", "add", "--detach", "-q", str(self.target), "HEAD", cwd=self.repo)
        self.git("worktree", "add", "--detach", "-q", str(self.sibling), "HEAD", cwd=self.repo)
        self.outside = self.temp_root / "outside"
        self.outside.mkdir()
        self.script = self.repo / ".codex" / "hooks" / HOOK.name
        self.script.parent.mkdir(parents=True)
        shutil.copy2(HOOK, self.script)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str, cwd: Path) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        )
        return result.stdout

    def invoke(self, *args: str, payload: dict | None = None, cwd: Path | None = None):
        result = subprocess.run(
            [sys.executable, str(self.script), *args],
            cwd=cwd or self.repo,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
        )
        output = json.loads(result.stdout) if result.stdout.strip() else None
        return result.returncode, output, result.stderr

    def register(self, agent_id: str = "agent-1", role: str = "builder", target: Path | None = None):
        return self.invoke(
            "register", agent_id, role, str(target or self.target), cwd=self.repo
        )

    def payload(
        self,
        role: str = "builder",
        agent_id: str = "agent-1",
        tool: str = "Bash",
        command: str = "cd /tmp && pwd",
        payload_cwd: Path | None = None,
    ) -> dict:
        return {
            "agent_type": role,
            "agent_id": agent_id,
            "tool_name": tool,
            "tool_input": {"command": command},
            "cwd": str(payload_cwd or self.repo),
        }

    def denied_reason(self, output: dict) -> str:
        nested = output["hookSpecificOutput"]
        self.assertEqual(nested["hookEventName"], "PreToolUse")
        self.assertEqual(nested["permissionDecision"], "deny")
        self.assertTrue(nested["permissionDecisionReason"])
        return nested["permissionDecisionReason"]

    def test_registration_is_idempotent_and_immutable(self) -> None:
        self.assertEqual(self.register()[0], 0)
        record_path = self.repo / ".worktrees" / ".graph-assignments" / "agent-1.json"
        original = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(self.register()[0], 0)
        self.assertEqual(json.loads(record_path.read_text(encoding="utf-8")), original)
        self.assertNotEqual(self.register(role="explorer")[0], 0)
        self.assertNotEqual(self.register(target=self.sibling)[0], 0)
        self.assertEqual(json.loads(record_path.read_text(encoding="utf-8")), original)

    def test_registration_rejects_invalid_role_main_outside_and_registry(self) -> None:
        self.assertNotEqual(self.register(role="security_reviewer")[0], 0)
        self.assertNotEqual(self.register(agent_id="main", target=self.repo)[0], 0)
        self.assertNotEqual(self.register(agent_id="outside", target=self.outside)[0], 0)
        registry = self.repo / ".worktrees" / ".graph-assignments"
        registry.mkdir()
        self.assertNotEqual(self.register(agent_id="registry", target=registry)[0], 0)

    def test_stale_or_recreated_worktree_is_rejected_for_registration_and_use(self) -> None:
        self.assertEqual(self.register()[0], 0)
        shutil.rmtree(self.target)
        self.assertNotEqual(self.register(agent_id="deleted")[0], 0)
        _, output, _ = self.invoke("pre-tool-use", payload=self.payload())
        self.assertIn("live worktree", self.denied_reason(output))
        self.target.mkdir()
        self.assertNotEqual(self.register(agent_id="recreated")[0], 0)
        _, output, _ = self.invoke("pre-tool-use", payload=self.payload())
        self.assertIn("Git metadata", self.denied_reason(output))

    def test_subagent_start_requires_native_id_and_injects_context(self) -> None:
        code, output, _ = self.invoke(
            "subagent-start",
            payload={"agent_type": "builder", "agent_id": "native-uuid"},
        )
        self.assertEqual(code, 0)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("native-uuid", context)
        self.assertIn("Report", context)
        self.assertIn("Wait", context)
        self.assertIsNone(
            self.invoke(
                "subagent-start",
                payload={"agent_type": "security_reviewer", "agent_id": "native-uuid"},
            )[1]
        )
        _, missing, _ = self.invoke(
            "subagent-start", payload={"agent_type": "builder", "agent_id": ""}
        )
        self.assertIn("Do not use tools", missing["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("permissionDecision", missing["hookSpecificOutput"])

    def test_role_exclusions_and_missing_registration(self) -> None:
        sentinel = "*** Update File: /outside/sentinel"
        for role in (None, "security_reviewer", "unrelated"):
            payload = self.payload(role=role or "", agent_id="", tool="apply_patch", command=sentinel)
            if role is None:
                payload.pop("agent_type")
            self.assertEqual(self.invoke("pre-tool-use", payload=payload)[1], None)
        _, output, _ = self.invoke(
            "pre-tool-use", payload=self.payload(agent_id="native-unregistered")
        )
        reason = self.denied_reason(output)
        self.assertIn("register", reason)
        self.assertIn("native-unregistered", reason)

    def test_bash_requires_literal_cd_inside_assignment(self) -> None:
        self.register()
        allowed = self.payload(command=f"cd {self.target} && pwd")
        self.assertIsNone(self.invoke("pre-tool-use", payload=allowed)[1])
        heredoc = self.payload(
            command=f"cd {self.target} && cat <<'EOF'\nIt's safe to leave the remainder unparsed.\nEOF"
        )
        self.assertIsNone(self.invoke("pre-tool-use", payload=heredoc)[1])
        continuation = self.payload(command=f"cd {self.target}\\\n && pwd")
        self.assertIn("control characters", self.denied_reason(self.invoke("pre-tool-use", payload=continuation)[1]))
        for command in (
            "pwd",
            f"cd {self.repo} && pwd",
            f"cd {self.sibling} && pwd",
            f"cd {self.outside} && pwd",
            f"cd {self.target}/../child-sibling && pwd",
            "cd $ASSIGNED && pwd",
        ):
            _, output, _ = self.invoke(
                "pre-tool-use", payload=self.payload(command=command)
            )
            reason = self.denied_reason(output)
            self.assertTrue(
                "assigned" in reason or "Bash command" in reason or "literal absolute" in reason
            )
        (self.target / "to-sibling").symlink_to(self.sibling, target_is_directory=True)
        _, output, _ = self.invoke(
            "pre-tool-use",
            payload=self.payload(command=f"cd {self.target}/to-sibling && pwd"),
        )
        self.assertIn("outside", self.denied_reason(output))

    def test_apply_patch_checks_all_destinations_and_canonical_paths(self) -> None:
        self.register()
        allowed = self.payload(
            tool="apply_patch",
            command=f"*** Update File: {self.target}/new-file.txt",
        )
        self.assertIsNone(self.invoke("pre-tool-use", payload=allowed)[1])
        spaced = self.payload(
            tool="apply_patch",
            command=f"*** Add File: {self.target}/filename with spaces.txt\r\n+smoke\r\n",
        )
        self.assertIsNone(self.invoke("pre-tool-use", payload=spaced)[1])
        leading_space = self.payload(
            tool="apply_patch",
            command=f"*** Add File:  {self.target}/leading-space.txt\r\n+smoke\r\n",
        )
        self.assertIn("outside", self.denied_reason(self.invoke("pre-tool-use", payload=leading_space)[1]))
        (self.target / "link ").symlink_to(self.sibling, target_is_directory=True)
        _, output, _ = self.invoke(
            "pre-tool-use",
            payload=self.payload(
                tool="apply_patch", command=f"*** Add File: {self.target}/link /escape.txt"
            ),
        )
        self.assertIn("outside", self.denied_reason(output))
        mixed = self.payload(
            tool="apply_patch",
            command=(
                f"*** Add File: {self.target}/safe-mixed.txt\n"
                f"\t*** Add File: {self.sibling}/indented-outside.txt\n"
            ),
        )
        self.assertIn("outside", self.denied_reason(self.invoke("pre-tool-use", payload=mixed)[1]))
        (self.target / "to-sibling").symlink_to(self.sibling, target_is_directory=True)
        (self.target / "link.txt").symlink_to(self.sibling / "tracked.txt")
        crlf_sibling = self.payload(
            tool="apply_patch",
            command=f"*** Update File: {self.target}/link.txt\r\n@@\r\n-old\r\n+new\r\n",
        )
        self.assertIn("outside", self.denied_reason(self.invoke("pre-tool-use", payload=crlf_sibling)[1]))
        (self.target / "unicode-trim-link.txt").symlink_to(self.sibling / "tracked.txt")
        trailing_unicode = self.payload(
            tool="apply_patch",
            command=f"*** Update File: {self.target}/unicode-trim-link.txt\u2003\n@@\n",
        )
        self.assertIn("outside", self.denied_reason(self.invoke("pre-tool-use", payload=trailing_unicode)[1]))
        bad_commands = (
            "*** Update File: no-header-only-command",
            f"*** Add File: {self.repo}/main-file.txt",
            f"*** Add File: {self.sibling}/sibling-file.txt",
            f"*** Add File: {self.outside}/outside-file.txt",
            "*** Add File: ../child-sibling/escape.txt",
            "*** Move to: to-sibling/escape.txt",
        )
        for command in bad_commands:
            payload_cwd = self.target if "../" in command or "to-sibling" in command else self.repo
            _, output, _ = self.invoke(
                "pre-tool-use",
                payload=self.payload(
                    tool="apply_patch", command=command, payload_cwd=payload_cwd
                ),
            )
            self.assertTrue(self.denied_reason(output))

    def test_corrupt_record_fails_closed_with_canonical_denial(self) -> None:
        self.register()
        record_path = self.repo / ".worktrees" / ".graph-assignments" / "agent-1.json"
        record_path.write_text("{broken", encoding="utf-8")
        _, output, _ = self.invoke("pre-tool-use", payload=self.payload())
        self.assertIn("invalid", self.denied_reason(output))

    def test_apply_patch_cannot_replace_active_guard_source(self) -> None:
        active_script = self.target / ".codex" / "hooks" / HOOK.name
        active_script.parent.mkdir(parents=True)
        shutil.copy2(HOOK, active_script)
        self.script = active_script
        self.assertEqual(self.register()[0], 0)
        _, output, _ = self.invoke(
            "pre-tool-use",
            payload=self.payload(
                tool="apply_patch", command=f"*** Update File: {active_script}"
            ),
        )
        self.assertIn("active guard source", self.denied_reason(output))


if __name__ == "__main__":
    unittest.main()
