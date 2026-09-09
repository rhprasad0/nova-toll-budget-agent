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

    def assert_patch_denied(self, payload: dict, fragment: str | None = None) -> None:
        _, output, _ = self.invoke("pre-tool-use", payload=payload)
        self.assertIsNotNone(output)
        reason = self.denied_reason(output)
        if fragment:
            self.assertIn(fragment, reason)

    def test_registration_is_idempotent_and_immutable(self) -> None:
        self.assertEqual(self.register()[0], 0)
        record_path = self.repo / ".worktrees" / ".graph-assignments" / "agent-1.json"
        original = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(self.register()[0], 0)
        self.assertEqual(json.loads(record_path.read_text(encoding="utf-8")), original)
        self.assertNotEqual(self.register(role="explorer")[0], 0)
        self.assertNotEqual(self.register(target=self.sibling)[0], 0)
        self.assertEqual(json.loads(record_path.read_text(encoding="utf-8")), original)

    def test_eval_roles_use_existing_identity_and_worktree_guard(self) -> None:
        for role in ("case_miner", "eval_runner", "eval_reviewer", "eval_fixer"):
            agent_id = f"native-{role}"
            _, started, _ = self.invoke(
                "subagent-start", payload={"agent_type": role, "agent_id": agent_id}
            )
            self.assertIn(agent_id, started["hookSpecificOutput"]["additionalContext"])
            payload = self.payload(role=role, agent_id=agent_id,
                                   command=f"cd {self.target} && pwd")
            self.assertIn("register", self.denied_reason(
                self.invoke("pre-tool-use", payload=payload)[1]))
            self.assertEqual(self.register(agent_id=agent_id, role=role)[0], 0)
            self.assertIsNone(self.invoke("pre-tool-use", payload=payload)[1])
            payload["tool_input"]["command"] = f"cd {self.sibling} && pwd"
            self.assertIn("outside", self.denied_reason(
                self.invoke("pre-tool-use", payload=payload)[1]))

    def test_researcher_uses_existing_identity_and_worktree_guard(self) -> None:
        role = "researcher"
        agent_id = "native-researcher"
        _, started, _ = self.invoke(
            "subagent-start", payload={"agent_type": role, "agent_id": agent_id}
        )
        self.assertIn(agent_id, started["hookSpecificOutput"]["additionalContext"])
        payload = self.payload(role=role, agent_id=agent_id,
                               command=f"cd {self.target} && git rev-parse --show-toplevel")
        self.assertIn("register", self.denied_reason(
            self.invoke("pre-tool-use", payload=payload)[1]))
        self.assertEqual(self.register(agent_id=agent_id, role=role)[0], 0)
        self.assertIsNone(self.invoke("pre-tool-use", payload=payload)[1])
        payload["tool_input"]["command"] = f"cd {self.sibling} && git rev-parse --show-toplevel"
        self.assertIn("outside", self.denied_reason(
            self.invoke("pre-tool-use", payload=payload)[1]))

    def test_researcher_is_limited_to_fixed_reads_and_research_artifact(self) -> None:
        role = "researcher"
        agent_id = "native-researcher-boundary"
        self.assertEqual(self.register(agent_id=agent_id, role=role)[0], 0)
        for command in (
            f"cd {self.target} && git rev-parse --show-toplevel",
            f"cd {self.target} && sed -n '1,260p' AGENTS.md",
            f"cd {self.target} && sed -n '1,320p' .graph/contract.md",
            f"cd {self.target} && sed -n '1,320p' .graph/explore.md",
        ):
            payload = self.payload(role=role, agent_id=agent_id, command=command)
            self.assertIsNone(self.invoke("pre-tool-use", payload=payload)[1])
        for command in (
            f"cd {self.target} && cat .graph/research.md",
            f"cd {self.target} && sed -n '1,240p' .codex/config.toml",
            f"cd {self.target} && touch .graph/research.md",
        ):
            payload = self.payload(role=role, agent_id=agent_id, command=command)
            self.assertIn("limited", self.denied_reason(
                self.invoke("pre-tool-use", payload=payload)[1]))
        sibling = self.payload(
            role=role,
            agent_id=agent_id,
            command=f"cd {self.sibling} && sed -n '1,260p' AGENTS.md",
        )
        self.assertIn("outside", self.denied_reason(
            self.invoke("pre-tool-use", payload=sibling)[1]))
        allowed = self.payload(
            role=role,
            agent_id=agent_id,
            tool="apply_patch",
            command=f"*** Add File: {self.target}/.graph/research.md",
        )
        self.assertIsNone(self.invoke("pre-tool-use", payload=allowed)[1])
        relative = self.payload(
            role=role,
            agent_id=agent_id,
            tool="apply_patch",
            command="*** Update File: .graph/research.md",
            payload_cwd=self.target,
        )
        self.assertIsNone(self.invoke("pre-tool-use", payload=relative)[1])
        for command in (
            f"*** Add File: {self.target}/other.md",
            f"*** Delete File: {self.target}/.graph/research.md",
            (
                f"*** Add File: {self.target}/.graph/research.md\n"
                f"*** Add File: {self.target}/other.md"
            ),
        ):
            payload = self.payload(role=role, agent_id=agent_id,
                                   tool="apply_patch", command=command)
            self.assertIn("research.md", self.denied_reason(
                self.invoke("pre-tool-use", payload=payload)[1]))
        redirected = self.target / ".graph"
        redirected_target = self.sibling / "research-target"
        redirected_target.mkdir()
        redirected.symlink_to(redirected_target, target_is_directory=True)
        escaped = self.payload(
            role=role,
            agent_id=agent_id,
            tool="apply_patch",
            command="*** Update File: .graph/research.md",
            payload_cwd=self.target,
        )
        self.assertIn("outside", self.denied_reason(
            self.invoke("pre-tool-use", payload=escaped)[1]))

    def test_registration_rejects_invalid_role_main_outside_and_registry(self) -> None:
        self.assertNotEqual(self.register(role="unrelated")[0], 0)
        self.assertNotEqual(self.register(agent_id="main", target=self.repo)[0], 0)
        self.assertNotEqual(self.register(agent_id="outside", target=self.outside)[0], 0)
        registry = self.repo / ".worktrees" / ".graph-assignments"
        registry.mkdir()
        self.assertNotEqual(self.register(agent_id="registry", target=registry)[0], 0)

    def test_non_builder_roles_are_limited_to_their_owned_graph_artifact(self) -> None:
        owned_artifacts = {
            "explorer": "explore.md",
            "researcher": "research.md",
            "pre_checker": "checklist.md",
            "checker": "verdict.md",
            "security_reviewer": "security-verdict.md",
        }
        for role, artifact in owned_artifacts.items():
            with self.subTest(role=role):
                agent_id = f"native-{role}"
                self.assertEqual(self.register(agent_id=agent_id, role=role)[0], 0)
                owned = self.payload(
                    role=role,
                    agent_id=agent_id,
                    tool="apply_patch",
                    command=f"*** Add File: {self.target}/.graph/{artifact}",
                )
                self.assertIsNone(self.invoke("pre-tool-use", payload=owned)[1])
                relative = self.payload(
                    role=role,
                    agent_id=agent_id,
                    tool="apply_patch",
                    command=f"*** Update File: .graph/{artifact}",
                    payload_cwd=self.target,
                )
                self.assertIsNone(self.invoke("pre-tool-use", payload=relative)[1])
                for command in (
                    f"*** Update File: {self.target}/tracked.txt",
                    f"*** Update File: {self.target}/.graph/other.md",
                    f"*** Delete File: {self.target}/.graph/{artifact}",
                    f"*** Move to: {self.target}/.graph/{artifact}",
                    f"*** Update File: {self.repo}/.graph/{artifact}",
                    f"*** Update File: {self.sibling}/.graph/{artifact}",
                ):
                    self.assert_patch_denied(
                        self.payload(
                            role=role,
                            agent_id=agent_id,
                            tool="apply_patch",
                            command=command,
                        ),
                        artifact,
                    )
                graph = self.target / ".graph"
                if graph.is_symlink():
                    graph.unlink()
                graph.mkdir(exist_ok=True)
                escaped_graph = self.sibling / f"escaped-{role}"
                escaped_graph.mkdir()
                graph.rmdir()
                graph.symlink_to(escaped_graph, target_is_directory=True)
                self.assert_patch_denied(
                    self.payload(
                        role=role,
                        agent_id=agent_id,
                        tool="apply_patch",
                        command=f"*** Update File: .graph/{artifact}",
                        payload_cwd=self.target,
                    ),
                    "outside",
                )
                graph.unlink()

                graph.mkdir()
                graph_alias = self.target / f"graph-alias-{role}"
                graph_alias.mkdir()
                (graph_alias / artifact).write_text("alias\n", encoding="utf-8")
                graph.rmdir()
                graph.symlink_to(graph_alias, target_is_directory=True)
                try:
                    self.assert_patch_denied(
                        self.payload(
                            role=role,
                            agent_id=agent_id,
                            tool="apply_patch",
                            command=f"*** Update File: .graph/{artifact}",
                            payload_cwd=self.target,
                        ),
                        "symlink",
                    )
                finally:
                    graph.unlink()
                graph.mkdir()
                active_guard = self.target / ".codex" / "hooks" / HOOK.name
                active_guard.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(HOOK, active_guard)
                owned_file = graph / artifact
                owned_file.symlink_to(active_guard)
                try:
                    self.assert_patch_denied(
                        self.payload(
                            role=role,
                            agent_id=agent_id,
                            tool="apply_patch",
                            command=f"*** Update File: .graph/{artifact}",
                            payload_cwd=self.target,
                        ),
                        "symlink",
                    )
                finally:
                    owned_file.unlink()
                for hardlink_target in (
                    self.target / "tracked.txt",
                    active_guard,
                ):
                    owned_file.hardlink_to(hardlink_target)
                    try:
                        self.assert_patch_denied(
                            self.payload(
                                role=role,
                                agent_id=agent_id,
                                tool="apply_patch",
                                command=f"*** Update File: .graph/{artifact}",
                                payload_cwd=self.target,
                            ),
                            "hard link",
                        )
                    finally:
                        owned_file.unlink()

    def test_builder_cannot_patch_reserved_graph_artifacts(self) -> None:
        self.assertEqual(self.register()[0], 0)
        reserved_artifacts = (
            "contract.md",
            "acceptance.md",
            "STATE.md",
            "explore.md",
            "research.md",
            "checklist.md",
            "verdict.md",
            "security-verdict.md",
        )
        for artifact in reserved_artifacts:
            self.assert_patch_denied(
                self.payload(
                    tool="apply_patch",
                    command=f"*** Update File: {self.target}/.graph/{artifact}",
                ),
                artifact,
            )
        self.assertIsNone(
            self.invoke(
                "pre-tool-use",
                payload=self.payload(
                    tool="apply_patch",
                    command=f"*** Update File: {self.target}/.graph/change.md",
                ),
            )[1]
        )
        self.assertIsNone(
            self.invoke(
                "pre-tool-use",
                payload=self.payload(
                    tool="apply_patch",
                    command=f"*** Update File: {self.target}/tracked.txt",
                ),
            )[1]
        )

    def test_builder_rejects_hardlink_aliases_to_any_protected_source(self) -> None:
        self.assertEqual(self.register()[0], 0)
        graph = self.target / ".graph"
        graph.mkdir()
        protected_graph_targets = {
            artifact: graph / artifact
            for artifact in (
                "contract.md",
                "acceptance.md",
                "STATE.md",
                "explore.md",
                "research.md",
                "checklist.md",
                "verdict.md",
                "security-verdict.md",
            )
        }
        for target in protected_graph_targets.values():
            target.write_text("protected\n", encoding="utf-8")
        active_guard = self.target / ".codex" / "hooks" / HOOK.name
        active_guard.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HOOK, active_guard)
        outside_file = self.outside / "outside.txt"
        outside_file.write_text("outside\n", encoding="utf-8")
        hardlink_targets = {
            **protected_graph_targets,
            "active-guard": active_guard,
            "main-checkout": self.repo / "tracked.txt",
            "outside-worktree": outside_file,
        }
        for name, target in hardlink_targets.items():
            with self.subTest(target=name):
                alias = self.target / f"hardlink-alias-{name}"
                alias.hardlink_to(target)
                try:
                    self.assert_patch_denied(
                        self.payload(
                            tool="apply_patch",
                            command=f"*** Update File: {alias}",
                        ),
                        "hard link",
                    )
                finally:
                    alias.unlink()

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
        _, security_started, _ = self.invoke(
            "subagent-start",
            payload={"agent_type": "security_reviewer", "agent_id": "native-uuid"},
        )
        self.assertIn("native-uuid", security_started["hookSpecificOutput"]["additionalContext"])
        _, missing, _ = self.invoke(
            "subagent-start", payload={"agent_type": "builder", "agent_id": ""}
        )
        self.assertIn("Do not use tools", missing["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("permissionDecision", missing["hookSpecificOutput"])

    def test_role_exclusions_and_missing_registration(self) -> None:
        sentinel = "*** Update File: /outside/sentinel"
        for role in (None, "unrelated"):
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
