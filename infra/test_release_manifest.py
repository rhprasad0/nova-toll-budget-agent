import argparse
import hashlib
import json
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from infra import release_manifest

SHA = "1" * 40
RUN = "12345"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.input = self.root / "input.txt"
        self.input.write_text("reviewed\n", encoding="utf-8")
        subprocess.run(["git", "-C", self.root, "add", "input.txt"], check=True)
        self.packages = self.root / "packages"
        self.packages.mkdir()
        for name in release_manifest.PACKAGES:
            (self.packages / name).write_bytes(name.encode())
        self.checksums = self.packages / "DEPLOYMENT_SHA256SUMS"
        self.checksums.write_text(
            "".join(
                f"{digest(self.packages / name)}  {name}\n"
                for name in release_manifest.PACKAGES
            ),
            encoding="ascii",
        )
        self.manifest = self.root / "manifest.json"
        self.manifest_value = {
            "schema_version": 1,
            "provider_identity": release_manifest.PROVIDER_IDENTITY,
            "deployment_inputs": {"input.txt": digest(self.input)},
            "packages": {
                name: digest(self.packages / name) for name in release_manifest.PACKAGES
            },
            "mutations": [],
            "permissions": [],
        }
        self.write_manifest()

    def tearDown(self):
        self.temporary.cleanup()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.manifest_value), encoding="utf-8")

    def enable_timed_mode(self):
        for relative in sorted(release_manifest.TIMED_INPUTS):
            self.track(relative, b"timed-reviewed\n")
        (self.packages / "timed-checks.zip").write_bytes(b"timed-checks.zip")
        self.checksums.write_text(
            "".join(
                f"{digest(self.packages / name)}  {name}\n"
                for name in release_manifest.TIMED_PACKAGES
            ),
            encoding="ascii",
        )
        self.manifest_value["deployment_inputs"] = {
            relative: digest(self.root / relative)
            for relative in sorted({"input.txt", *release_manifest.TIMED_INPUTS})
        }
        self.manifest_value["packages"] = {
            name: digest(self.packages / name)
            for name in release_manifest.TIMED_PACKAGES
        }
        self.write_manifest()

    def track(self, relative, content=b"reviewed\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        subprocess.run(["git", "-C", self.root, "add", relative], check=True)
        return path

    def bundle_context(self):
        values = {
            "EXACT_INPUTS": {"input.txt"},
            "INPUT_PREFIXES": (),
            "BUNDLE_MARKER": "bundle.sh",
            "BUNDLE_FIXED_INPUTS": {
                "bundle.sh",
                "bundle-helper.py",
                "db/schema.sql",
            },
            "BUNDLE_OPTIONAL_INPUTS": {"future.py"},
            "BUNDLE_INPUT_PREFIXES": ("migrations/",),
        }
        stack = ExitStack()
        for name, value in values.items():
            stack.enter_context(mock.patch.object(release_manifest, name, value))
        return stack

    def args(self, **changes):
        values = {
            "manifest": self.manifest,
            "package_dir": self.packages,
            "checksums": self.checksums,
            "candidate_sha": SHA,
            "run_id": RUN,
            "repo_root": self.root,
            "write_evidence": self.root / "evidence.json",
            "evidence": None,
            "bundle_root": None,
        }
        values.update(changes)
        return argparse.Namespace(**values)

    def verify(self, **changes):
        exact_inputs = changes.pop("_exact_inputs", {"input.txt"})
        with (
            mock.patch.object(release_manifest, "EXACT_INPUTS", exact_inputs),
            mock.patch.object(release_manifest, "INPUT_PREFIXES", ()),
            mock.patch.object(release_manifest, "FIXED_BACKENDS", {}),
        ):
            return release_manifest.verify(self.args(**changes))

    def assert_rejected(self, reason, **changes):
        with self.assertRaisesRegex(release_manifest.Invalid, f"^{reason}$"):
            self.verify(**changes)

    def test_source_then_artifact_verification_accepts(self):
        first = self.verify()
        evidence = self.root / "evidence.json"
        second = self.verify(repo_root=None, write_evidence=None, evidence=evidence)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "accepted")
        self.assertNotIn(SHA, json.dumps(first))

    def test_rejects_internally_consistent_unreviewed_bundle_payload(self):
        first = self.verify()
        evidence = self.root / "evidence.json"
        bundle = self.root / "bundle"
        bundle.mkdir()
        (bundle / "input.txt").write_text("tampered\n", encoding="utf-8")
        package_root = bundle / "v2/infra/build"
        package_root.mkdir(parents=True)
        for name in release_manifest.PACKAGES:
            (package_root / name).write_bytes((self.packages / name).read_bytes())
        (bundle / "release-manifest.json").write_text(
            json.dumps({"files": {"input.txt": digest(bundle / "input.txt")}}),
            encoding="utf-8",
        )
        self.assertEqual(first["status"], "accepted")
        self.assert_rejected(
            "bundle_payload_digest_mismatch",
            repo_root=None,
            write_evidence=None,
            evidence=evidence,
            bundle_root=bundle,
        )

    def test_accepts_reviewed_development_overlay_scaffold(self):
        reviewed = {
            "infra/account-contract.json": b"{}\n",
            "v2/infra/main.tf": b"terraform {}\n",
            "v2/infra/.terraform.lock.hcl": b"lock\n",
            "v2/infra/backend.development.hcl": b"backend\n",
            "v2/infra/development.tfvars": b'environment = "development"\n',
            "v2/infra/lambda-stub/handler.py": b"def handler(event, context): pass\n",
        }
        bundle = self.root / "development-overlay"
        for relative, content in reviewed.items():
            path = bundle / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        package_root = bundle / "v2/infra/build"
        package_root.mkdir(parents=True)
        for name in release_manifest.PACKAGES:
            (package_root / name).write_bytes((self.packages / name).read_bytes())

        release_manifest._verify_bundle_payload(
            bundle,
            {
                relative: hashlib.sha256(content).hexdigest()
                for relative, content in reviewed.items()
            },
            {name: digest(self.packages / name) for name in release_manifest.PACKAGES},
        )

    def test_rejects_stale_input_and_package_boundaries(self):
        self.input.write_text("changed\n", encoding="utf-8")
        self.assert_rejected("input_digest_mismatch")
        self.input.write_text("reviewed\n", encoding="utf-8")

        for name in release_manifest.PACKAGES:
            package = self.packages / name
            original = package.read_bytes()
            package.unlink()
            self.assert_rejected("package_inventory_invalid")
            package.write_bytes(b"changed")
            self.assert_rejected("package_digest_mismatch")
            package.write_bytes(original)
        (self.packages / "extra.zip").write_bytes(b"extra")
        self.assert_rejected("package_inventory_invalid")

        (self.packages / "extra.zip").unlink()
        (self.packages / "extra.zip").write_bytes(b"extra")
        self.checksums.write_text(
            "".join(
                f"{digest(self.packages / name)}  {name}\n"
                for name in (*release_manifest.PACKAGES, "extra.zip")
            ),
            encoding="ascii",
        )
        self.assert_rejected("package_inventory_invalid")

    def test_timed_marker_requires_full_inventory_and_five_packages(self):
        self.enable_timed_mode()
        self.assertEqual(self.verify()["status"], "accepted")

        missing = min(release_manifest.TIMED_INPUTS)
        self.manifest_value["deployment_inputs"].pop(missing)
        self.write_manifest()
        self.assert_rejected("inventory_incomplete")

        self.enable_timed_mode()
        (self.packages / "timed-checks.zip").unlink()
        self.assert_rejected("package_inventory_invalid")

    def test_legacy_mode_excludes_tracked_timed_inputs(self):
        for relative in sorted(release_manifest.TIMED_INPUTS):
            self.track(relative)
        with (
            mock.patch.object(release_manifest, "EXACT_INPUTS", {"input.txt"}),
            mock.patch.object(release_manifest, "INPUT_PREFIXES", ()),
        ):
            self.assertEqual(release_manifest._tracked_inputs(self.root), ["input.txt"])

    def test_production_control_inventory_is_feature_detected_and_complete(self):
        non_marker = next(
            path
            for path in sorted(release_manifest.PRODUCTION_CONTROL_INPUTS)
            if path != release_manifest.PRODUCTION_CONTROL_MARKER
        )
        with (
            mock.patch.object(release_manifest, "EXACT_INPUTS", {"input.txt"}),
            mock.patch.object(release_manifest, "INPUT_PREFIXES", ()),
        ):
            self.track(non_marker)
            self.assertEqual(release_manifest._tracked_inputs(self.root), ["input.txt"])
            self.track(release_manifest.PRODUCTION_CONTROL_MARKER)
            with self.assertRaisesRegex(
                release_manifest.Invalid, "^inventory_incomplete$"
            ):
                release_manifest._tracked_inputs(self.root)
            for relative in sorted(release_manifest.PRODUCTION_CONTROL_INPUTS):
                if relative not in {
                    non_marker,
                    release_manifest.PRODUCTION_CONTROL_MARKER,
                }:
                    self.track(relative)
            expected = sorted(
                {"input.txt", *release_manifest.PRODUCTION_CONTROL_INPUTS}
            )
            self.assertEqual(release_manifest._tracked_inputs(self.root), expected)
            release_manifest._verify_inputs(
                self.root,
                {relative: digest(self.root / relative) for relative in expected},
            )

    def test_rejects_missing_symlinked_and_extra_inputs(self):
        self.input.unlink()
        self.assert_rejected("input_unreadable")
        target = self.root / "target.txt"
        target.write_text("reviewed\n", encoding="utf-8")
        self.input.symlink_to(target)
        self.assert_rejected("input_unreadable")
        self.input.unlink()
        self.input.write_text("reviewed\n", encoding="utf-8")

        extra = self.root / "extra.txt"
        extra.write_text("extra\n", encoding="utf-8")
        subprocess.run(["git", "-C", self.root, "add", "extra.txt"], check=True)
        self.assert_rejected(
            "inventory_mismatch", _exact_inputs={"input.txt", "extra.txt"}
        )

    def test_rejects_inventory_and_manifest_shapes(self):
        self.manifest_value["deployment_inputs"] = {"../input.txt": digest(self.input)}
        self.write_manifest()
        self.assert_rejected("inventory_invalid")

        self.manifest_value["deployment_inputs"] = {"input.txt": digest(self.input)}
        self.manifest_value["mutations"] = [{"address": "unsupported"}]
        self.write_manifest()
        self.assert_rejected("mutation_contract_invalid")

        self.manifest.write_text(
            '{"schema_version":1,"schema_version":1}', encoding="utf-8"
        )
        self.assert_rejected("duplicate_json_key")

    def test_rejects_runtime_and_evidence_mismatch(self):
        self.assert_rejected("runtime_binding_invalid", candidate_sha="main")
        self.verify()
        evidence = self.root / "evidence.json"
        value = json.loads(evidence.read_text(encoding="utf-8"))
        value["run_id"] = "999"
        evidence.write_text(json.dumps(value), encoding="utf-8")
        self.assert_rejected(
            "evidence_mismatch", repo_root=None, write_evidence=None, evidence=evidence
        )

        value["run_id"] = RUN
        value["candidate_sha"] = "2" * 40
        evidence.write_text(json.dumps(value), encoding="utf-8")
        self.assert_rejected(
            "evidence_mismatch", repo_root=None, write_evidence=None, evidence=evidence
        )

    def test_rejects_symlinks_and_does_not_regenerate_manifest(self):
        target = self.root / "target.zip"
        target.write_bytes(b"agentcore.zip")
        (self.packages / "agentcore.zip").unlink()
        (self.packages / "agentcore.zip").symlink_to(target)
        self.assert_rejected("package_unreadable")
        self.assertEqual(
            json.loads(self.manifest.read_text(encoding="utf-8")), self.manifest_value
        )

        self.manifest.unlink()
        self.manifest.symlink_to(self.root / "missing.json")
        self.assert_rejected("manifest_unreadable")

    def test_untracked_bundle_marker_preserves_old_inventory(self):
        marker = self.root / "v2/scripts/build_release_bundle.sh"
        marker.parent.mkdir(parents=True)
        marker.write_text("untracked\n", encoding="utf-8")
        with (
            mock.patch.object(release_manifest, "EXACT_INPUTS", {"input.txt"}),
            mock.patch.object(release_manifest, "INPUT_PREFIXES", ()),
        ):
            self.assertEqual(release_manifest._tracked_inputs(self.root), ["input.txt"])

    def test_future_bundle_helpers_are_allowlisted_and_digest_checked(self):
        helpers = {
            "v2/scripts/classify_deployment_error.py": b"classify\n",
            "v2/scripts/run_private_stage.sh": b"stage\n",
        }
        with (
            mock.patch.object(release_manifest, "EXACT_INPUTS", {"input.txt"}),
            mock.patch.object(release_manifest, "INPUT_PREFIXES", ()),
            mock.patch.object(
                release_manifest,
                "BUNDLE_MARKER",
                "bundle.sh",
            ),
            mock.patch.object(
                release_manifest,
                "BUNDLE_FIXED_INPUTS",
                {"bundle.sh", "bundle-helper.py", "db/schema.sql"},
            ),
            mock.patch.object(release_manifest, "BUNDLE_INPUT_PREFIXES", ()),
        ):
            self.assertEqual(release_manifest._tracked_inputs(self.root), ["input.txt"])
            self.track("bundle.sh")
            self.track("bundle-helper.py")
            self.track("db/schema.sql")
            fixed = {"bundle.sh", "bundle-helper.py", "db/schema.sql"}
            self.assertEqual(
                release_manifest._tracked_inputs(self.root),
                sorted({"input.txt", *fixed}),
            )
            release_manifest._verify_inputs(
                self.root,
                {
                    relative: digest(self.root / relative)
                    for relative in sorted({"input.txt", *fixed})
                },
            )

            for relative, content in helpers.items():
                self.track(relative, content)
            self.track("v2/scripts/unrelated_helper.py")
            selected = release_manifest._tracked_inputs(self.root)
            expected = sorted(
                {
                    "input.txt",
                    *helpers,
                    "bundle.sh",
                    "bundle-helper.py",
                    "db/schema.sql",
                }
            )
            self.assertEqual(selected, expected)
            self.assertNotIn("v2/scripts/unrelated_helper.py", selected)

            inputs = {relative: digest(self.root / relative) for relative in selected}
            release_manifest._verify_inputs(self.root, inputs)
            for relative in helpers:
                omitted = inputs.copy()
                omitted.pop(relative)
                with self.assertRaisesRegex(
                    release_manifest.Invalid, "^inventory_mismatch$"
                ):
                    release_manifest._verify_inputs(self.root, omitted)

            for relative, content in helpers.items():
                path = self.root / relative
                path.write_bytes(b"changed\n")
                with self.assertRaisesRegex(
                    release_manifest.Invalid, "^input_digest_mismatch$"
                ):
                    release_manifest._verify_inputs(self.root, inputs)
                path.write_bytes(content)

    def test_bundle_selects_archived_robots_input(self):
        self.assertIn("v2/agent/robots.txt", release_manifest.BUNDLE_FIXED_INPUTS)
        self.assertTrue(release_manifest._selected("v2/agent/robots.txt", True))

    def test_tracked_bundle_marker_selects_bounded_inventory(self):
        tracked = {"input.txt", "bundle.sh", "bundle-helper.py", "db/schema.sql"}
        for relative in tracked - {"input.txt"}:
            self.track(relative)
        self.track("migrations/002.sql")
        self.track("future.py")
        self.track("unknown.txt")
        with self.bundle_context():
            selected = release_manifest._tracked_inputs(self.root)
        self.assertEqual(
            selected,
            sorted(
                {
                    "input.txt",
                    "bundle.sh",
                    "bundle-helper.py",
                    "db/schema.sql",
                    "migrations/002.sql",
                    "future.py",
                }
            ),
        )
        self.assertNotIn("unknown.txt", selected)

    def test_tracked_bundle_marker_requires_fixed_inputs(self):
        self.track("bundle.sh")
        with (
            self.bundle_context(),
            self.assertRaisesRegex(release_manifest.Invalid, "^inventory_incomplete$"),
        ):
            release_manifest._tracked_inputs(self.root)

    def test_bundle_manifest_rejects_omission_and_changed_payload(self):
        for relative in (
            "bundle.sh",
            "bundle-helper.py",
            "db/schema.sql",
            "migrations/001.sql",
        ):
            self.track(relative)
        input_paths = sorted(
            {
                "input.txt",
                "bundle.sh",
                "bundle-helper.py",
                "db/schema.sql",
                "migrations/001.sql",
            }
        )
        inputs = {relative: digest(self.root / relative) for relative in input_paths}
        self.manifest_value["deployment_inputs"] = inputs
        self.write_manifest()
        with self.bundle_context():
            self.assertEqual(self.verify()["status"], "accepted")
            (self.root / "evidence.json").unlink()
            self.manifest_value["deployment_inputs"].pop("migrations/001.sql")
            self.write_manifest()
            with self.assertRaisesRegex(
                release_manifest.Invalid, "^inventory_mismatch$"
            ):
                self.verify()
            self.manifest_value["deployment_inputs"]["migrations/001.sql"] = digest(
                self.root / "migrations/001.sql"
            )
            self.write_manifest()
            self.track("migrations/001.sql", b"changed\n")
            (self.root / "evidence.json").unlink(missing_ok=True)
            with self.assertRaisesRegex(
                release_manifest.Invalid, "^input_digest_mismatch$"
            ):
                self.verify()


if __name__ == "__main__":
    unittest.main()
