#!/usr/bin/env python3
"""Protected fixed-target delivery. All routing changes use saved Terraform plans."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.cookiejar
import json
import mimetypes
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

if __package__:
    from . import blue_green as gate
    from . import check_development_release as checks
else:
    import blue_green as gate
    import check_development_release as checks

account = "903859731897"
artifact_bucket = "nova-toll-agentcore-903859731897"
site_bucket = "tollchat-site-903859731897-dev"
header_parameter = "/nova-toll/development/candidate-header"
aws = checks.aws
environment = "development"
LAST_CANARY: dict[str, Any] = {}


def configure(target: str) -> None:
    global account, artifact_bucket, site_bucket, header_parameter, environment
    gate.require(target in {"development", "production"}, "environment")
    environment = target
    account = "903859731897" if environment == "development" else "920534282028"
    artifact_bucket = f"nova-toll-agentcore-{account}"
    site_bucket = f"tollchat-site-{account}" + (
        "-dev" if environment == "development" else ""
    )
    header_parameter = f"/nova-toll/{environment}/candidate-header"
    checks.configure(environment)


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    path.chmod(0o600)


def terraform(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["terraform", f"-chdir={root}", *args],
        capture_output=True,
        text=True,
        timeout=1200,
        check=False,
    )
    gate.require(result.returncode == 0, "terraform_failed")
    return result.stdout


def current(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = json.loads(terraform(root, "state", "pull"))
    return raw["outputs"]["release_state"]["value"], {
        "lineage": raw["lineage"],
        "serial": raw["serial"],
    }


def upload(
    path: Path, bucket: str, key: str, content_type: str, cache: str
) -> dict[str, Any]:
    checksum = base64.b64encode(hashlib.sha256(path.read_bytes()).digest()).decode()
    try:
        head = aws(
            "s3api",
            "head-object",
            "--bucket",
            bucket,
            "--key",
            key,
            "--checksum-mode",
            "ENABLED",
            "--expected-bucket-owner",
            account,
        )
        gate.require(
            head.get("ContentType") == content_type
            and head.get("CacheControl") == cache,
            "immutable_metadata",
        )
    except checks.CheckFailure:
        head = aws(
            "s3api",
            "put-object",
            "--bucket",
            bucket,
            "--key",
            key,
            "--body",
            str(path),
            "--if-none-match",
            "*",
            "--content-type",
            content_type,
            "--cache-control",
            cache,
            "--checksum-algorithm",
            "SHA256",
            "--checksum-sha256",
            checksum,
            "--expected-bucket-owner",
            account,
        )
    gate.require(
        head.get("ChecksumSHA256") == checksum
        and head.get("VersionId") not in (None, "", "null"),
        "immutable_upload",
    )
    return head


def render_asset(relative: str, source: bytes, release: str) -> bytes:
    if relative.endswith((".html", ".mjs", ".css")):
        return source.replace(
            b"/assets/", f"/releases/{release}/assets/".encode()
        ).replace(b'"/chat.mjs"', f'"/releases/{release}/chat.mjs"'.encode())
    return source


def prepare_descriptor(bundle: Path, previous: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads((bundle / "release-manifest.json").read_text())
    release = manifest["commit_sha"]
    gate.require(
        re.fullmatch(r"[0-9a-f]{40}", release) is not None
        and release == os.environ.get("GITHUB_SHA"),
        "release_checkout",
    )
    hashes = {item["path"]: item["sha256"] for item in manifest["files"]}
    inactive = "green" if previous["active"] == "blue" else "blue"
    result = gate.descriptor(previous["slots"][inactive])
    result.update(release_id=release, asset_prefix=f"/releases/{release}")
    for kind, filename in (("runtime", "agentcore"), ("proxy", "chat-proxy")):
        relative = f"v2/infra/build/{filename}.zip"
        path = bundle / relative
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        gate.require(sha == hashes[relative], "artifact_hash")
        key = f"releases/{release}/{filename}.zip"
        artifact = upload(
            path, artifact_bucket, key, "application/zip", "private, no-store"
        )
        result.update(
            {
                f"{kind}_key": key,
                f"{kind}_object_version": artifact["VersionId"],
                f"{kind}_sha256": sha
                if kind == "runtime"
                else artifact["ChecksumSHA256"],
            }
        )
    with tempfile.TemporaryDirectory() as temporary:
        for relative in sorted(hashes):
            if relative.startswith("v2/agent/assets/"):
                destination = relative.removeprefix("v2/agent/")
            elif relative in {
                f"v2/agent/{name}"
                for name in (
                    "dev_chat.html",
                    "public_chat.mjs",
                    "faq.html",
                    "privacy.txt",
                    "terms.txt",
                )
            }:
                destination = {
                    "dev_chat.html": "index.html",
                    "public_chat.mjs": "chat.mjs",
                }.get(Path(relative).name, Path(relative).name)
            else:
                continue
            source = (bundle / relative).read_bytes()
            gate.require(
                hashlib.sha256(source).hexdigest() == hashes[relative], "asset_hash"
            )
            output = Path(temporary) / "asset"
            output.write_bytes(render_asset(destination, source, release))
            kind = (
                "text/javascript"
                if destination.endswith(".mjs")
                else mimetypes.guess_type(destination)[0] or "application/octet-stream"
            )
            upload(
                output,
                site_bucket,
                f"releases/{release}/{destination}",
                kind,
                "no-store"
                if destination.endswith((".html", ".txt"))
                else "public, max-age=31536000, immutable",
            )
    return result


def plan(
    root: Path,
    bundle: Path,
    foundation: Path,
    work: Path,
    phase: str,
    previous: dict[str, Any],
    inputs: dict[str, Any],
) -> Path:
    variables = work / f"{phase}.tfvars.json"
    write(variables, inputs)
    saved = work / f"{phase}.tfplan"
    args = [
        "plan",
        "-input=false",
        f"-out={saved}",
        f"-var-file={environment}.tfvars",
        f"-var-file={foundation}",
        f"-var-file={variables}",
    ]
    for variable, name in (
        ("loader", "loader"),
        ("publisher", "publisher"),
        ("timed_checks", "timed-checks"),
    ):
        args.append(
            f"-var={variable}_package_path={bundle / 'v2/infra/build' / (name + '.zip')}"
        )
    terraform(root, *args)
    gate.validate_plan(
        json.loads(terraform(root, "show", "-json", str(saved))), previous, phase
    )
    return saved


def wait_routing(root: Path, expected: dict[str, Any]) -> None:
    resources = {
        item["address"]: item["values"]
        for item in json.loads(terraform(root, "show", "-json"))["values"][
            "root_module"
        ]["resources"]
    }
    deadline = time.monotonic() + 900
    for name in ("site", "staging"):
        distribution = resources[f"aws_cloudfront_distribution.{name}"]
        while True:
            actual = aws("cloudfront", "get-distribution", "--id", distribution["id"])[
                "Distribution"
            ]
            origins = {
                item["Id"]: item
                for item in actual["DistributionConfig"]["Origins"]["Items"]
            }
            slot = (
                expected["active"]
                if name == "site"
                else ("green" if expected["active"] == "blue" else "blue")
            )
            target = expected["slots"][slot]
            gate.require(
                origins["public-chat"]["DomainName"]
                == target["proxy_url"].removeprefix("https://").rstrip("/")
                and origins["documents"]["OriginPath"] == target["asset_prefix"],
                "routing_identity",
            )
            if actual["Status"] == "Deployed":
                break
            gate.require(time.monotonic() < deadline, "routing_timeout")
            time.sleep(15)
    for resource in ("tollchat_root", "tollchat_proxy"):
        integration = resources[f"aws_api_gateway_integration.{resource}"]
        actual = aws(
            "apigateway",
            "get-integration",
            "--rest-api-id",
            integration["rest_api_id"],
            "--resource-id",
            integration["resource_id"],
            "--http-method",
            "ANY",
        )
        gate.require(
            actual["uri"] == integration["uri"]
            and expected["slots"][expected["active"]]["proxy_arn"] + ":live"
            in actual["uri"],
            "private_routing",
        )
    api_stage = resources["aws_api_gateway_stage.tollchat"]
    actual_stage = aws(
        "apigateway",
        "get-stage",
        "--rest-api-id",
        api_stage["rest_api_id"],
        "--stage-name",
        "preview",
    )
    gate.require(
        actual_stage["deploymentId"] == api_stage["deployment_id"], "private_deployment"
    )


def readiness(slot: dict[str, Any]) -> None:
    function = aws(
        "lambda",
        "get-function",
        "--function-name",
        slot["proxy_arn"],
        "--qualifier",
        slot["proxy_version"],
    )["Configuration"]
    gate.require(
        function["CodeSha256"] == slot["proxy_sha256"]
        and function["Version"] == slot["proxy_version"]
        and function["State"] == "Active",
        "proxy_ready",
    )
    proxy_environment = function["Environment"]["Variables"]
    gate.require(
        proxy_environment["RELEASE_ID"] == slot["release_id"]
        and proxy_environment["AGENTCORE_RUNTIME_ARN"] == slot["runtime_arn"]
        and proxy_environment["AGENTCORE_RUNTIME_ENDPOINT"] == slot["endpoint"],
        "proxy_pairing",
    )
    alias = aws(
        "lambda", "get-alias", "--function-name", slot["proxy_arn"], "--name", "live"
    )
    gate.require(
        alias["FunctionVersion"] == slot["proxy_version"]
        and not alias.get("RoutingConfig", {}).get("AdditionalVersionWeights"),
        "published_alias",
    )
    endpoint = aws(
        "bedrock-agentcore-control",
        "get-agent-runtime-endpoint",
        "--agent-runtime-id",
        slot["runtime_id"],
        "--endpoint-name",
        slot["endpoint"],
    )
    gate.require(
        endpoint["status"] == "READY"
        and endpoint["liveVersion"] == slot["runtime_version"]
        and endpoint["agentRuntimeArn"] == slot["runtime_arn"],
        "endpoint_ready",
    )
    runtime = aws(
        "bedrock-agentcore-control",
        "get-agent-runtime",
        "--agent-runtime-id",
        slot["runtime_id"],
        "--agent-runtime-version",
        slot["runtime_version"],
    )
    artifact = runtime["agentRuntimeArtifact"]["codeConfiguration"]["code"]["s3"]
    gate.require(
        artifact["bucket"] == artifact_bucket
        and artifact["prefix"] == slot["runtime_key"]
        and artifact["versionId"] == slot["runtime_object_version"],
        "runtime_artifact",
    )
    gate.require(
        runtime["environmentVariables"]["TOLLCHAT_RELEASE_ID"] == slot["release_id"],
        "runtime_release",
    )
    for endpoint_name in ("DEFAULT", slot["endpoint"]):
        group = f"/aws/bedrock-agentcore/runtimes/{slot['runtime_id']}-{endpoint_name}"
        protection = aws(
            "logs", "get-data-protection-policy", "--log-group-identifier", group
        )
        policy = json.loads(protection["policyDocument"])
        gate.require(
            any(
                "arn:aws:dataprotection::aws:data-identifier/Address"
                in item.get("DataIdentifier", [])
                and item.get("Operation", {}).get("Deidentify") == {"MaskConfig": {}}
                for item in policy.get("Statement", [])
            ),
            "trace_protection",
        )
        subscriptions = aws(
            "logs", "describe-subscription-filters", "--log-group-name", group
        )
        suffix = "-dev" if environment == "development" else ""
        destination = f"arn:aws:firehose:us-east-1:{account}:deliverystream/nova-toll-v2-agentcore-traces{suffix}"
        gate.require(
            any(
                item.get("destinationArn") == destination
                for item in subscriptions["subscriptionFilters"]
            ),
            "trace_subscription",
        )


def probe(slot: dict[str, Any]) -> dict[str, Any]:
    checks.serving_expected = slot
    checks.serving_observed.clear()
    LAST_CANARY.clear()
    LAST_CANARY.update(
        checks.canary(
            {"version": slot["runtime_version"], "alias_version": slot["proxy_version"]}
        )
    )
    observed = dict(checks.serving_observed)
    gate.verify_serving(observed, slot)
    return observed


def private_probe(root: Path, slot: dict[str, Any]) -> None:
    preview = json.loads(terraform(root, "output", "-json", "private_preview"))
    public_site = checks.profile_site
    try:
        checks.profile_site = preview["origin"]
        gate.require(preview["stage"] == "preview", "private_stage")
        checks.profile_path_prefix = "/preview"
        probe(slot)
    finally:
        checks.profile_site = public_site
        checks.profile_path_prefix = ""


def assets(slot: dict[str, Any], *, document: bool = False) -> None:
    jar = http.cookiejar.CookieJar()
    prefix = slot["asset_prefix"]
    code, _, page = checks.request(jar, prefix + "/index.html")
    gate.require(code == 200, "retained_document")
    if document:
        status, content_type, served = checks.request(jar, "/")
        gate.require(
            status == 200 and content_type == "text/html" and served == page,
            "candidate_document",
        )
    paths = set(re.findall(rb'(?:src|href)="(/releases/[^"?#]+)', page))
    gate.require(
        bool(paths) and all(path.startswith((prefix + "/").encode()) for path in paths),
        "asset_prefix",
    )
    paths.add((prefix + "/index.html").encode())
    for raw in paths:
        path = raw.decode()
        code, content_type, body = checks.request(jar, path)
        expected_type = (
            "text/javascript"
            if path.endswith(".mjs")
            else mimetypes.guess_type(path)[0] or "application/octet-stream"
        )
        head = aws(
            "s3api",
            "head-object",
            "--bucket",
            site_bucket,
            "--key",
            path.lstrip("/"),
            "--checksum-mode",
            "ENABLED",
            "--expected-bucket-owner",
            account,
        )
        gate.require(
            code == 200
            and content_type == expected_type
            and head.get("ChecksumSHA256")
            == base64.b64encode(hashlib.sha256(body).digest()).decode(),
            "asset_content",
        )


def validate_candidate(prepared: dict[str, Any], claim: str) -> dict[str, Any]:
    slot = prepared["slots"]["green" if prepared["active"] == "blue" else "blue"]
    readiness(slot)
    checks.candidate_header = aws(
        "ssm", "get-parameter", "--name", header_parameter, "--with-decryption"
    )["Parameter"]["Value"]
    try:
        observed = probe(slot)
        assets(slot, document=True)
        candidate_canary = dict(LAST_CANARY)
        candidate_canary.update(checks.security_checks())
        output = os.environ.get("CANARY_EVIDENCE_FILE")
        if output:
            write(Path(output), candidate_canary)
        jar = http.cookiejar.CookieJar()
        gate.require(
            checks.request(
                jar,
                "/api/chat",
                {"message": checks.PROMPT},
                origin="https://invalid.example",
            )[0]
            == 403,
            "origin",
        )
        checks.answer(checks.request(jar, "/api/chat", {"message": checks.PROMPT}))
        old_token = checks.token(jar)
        checks.reset(jar)
        gate.require(
            checks.request(
                http.cookiejar.CookieJar(),
                "/api/chat",
                {"message": checks.PROMPT},
                cookie=old_token,
            )[0]
            == 401,
            "session_reset",
        )
        checks.candidate_header = None
        active = prepared["slots"][prepared["active"]]
        readiness(active)
        probe(active)
        checks.security_checks()
        assets(active, document=True)
        assets(slot)
        checks.candidate_header = "invalid-candidate-header"
        probe(prepared["slots"][prepared["active"]])
        return {
            "state_sha256": gate.digest(prepared),
            "claim": claim,
            "checked_at": int(time.time()),
            "checks": {key: True for key in gate.CHECKS},
            "serving": observed,
        }
    finally:
        checks.candidate_header = None
        checks.serving_expected = None


def observe(
    probe_once: Callable[[], bool],
    restore: Callable[[], bool],
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    failures = 0
    results: list[bool] = []
    for index in range(5):
        started = clock()
        try:
            ok = probe_once() is True and clock() - started <= 60
        except Exception:
            ok = False
        results.append(ok)
        failures = 0 if ok else failures + 1
        if failures == 2:
            try:
                recovered = restore() is True
            except Exception:
                recovered = False
            return {
                "deployment": "failed",
                "recovery": "recovered" if recovered else "failed",
                "probes": results,
            }
        if index < 4:
            sleep(max(0, 60 - (clock() - started)))
    return {
        "deployment": "succeeded",
        "recovery": "not_attempted",
        "probes": results,
    }


def recover(
    root: Path, bundle: Path, foundation: Path, work: Path, prepared: dict[str, Any]
) -> bool:
    actual, identity = current(root)
    gate.require(actual["slots"] == prepared["slots"], "stale_recovery")
    promoted = dict(
        prepared, active="green" if prepared["active"] == "blue" else "blue"
    )
    saved = plan(
        root,
        bundle,
        foundation,
        work,
        "recover",
        promoted,
        gate.desired(promoted, promote=True),
    )
    gate.require(current(root)[1] == identity, "stale_recovery")
    terraform(root, "apply", "-input=false", str(saved))
    restored, _ = current(root)
    gate.require(restored == prepared, "restore_state")
    wait_routing(root, restored)
    readiness(restored["slots"][restored["active"]])
    probe(restored["slots"][restored["active"]])
    private_probe(root, restored["slots"][restored["active"]])
    for slot in restored["slots"].values():
        assets(slot)
    return True


def recovery_key(release: str, claim: str) -> str:
    gate.require(
        re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", release) is not None, "release_id"
    )
    gate.require(
        re.fullmatch(r"[0-9]+(?::[0-9]+)?", claim) is not None, "recovery_claim"
    )
    return f"releases/{release}/recovery/{claim}.json"


def load_recovery(work: Path, release: str, claim: str, version: str) -> dict[str, Any]:
    gate.require(bool(version) and version != "null", "recovery_version")
    path = work / "context.json"
    aws(
        "s3api",
        "get-object",
        "--bucket",
        artifact_bucket,
        "--key",
        recovery_key(release, claim),
        "--version-id",
        version,
        "--expected-bucket-owner",
        account,
        str(path),
    )
    context = json.loads(path.read_text())
    gate.require(
        context["claim"] == claim and context["environment"] == environment,
        "recovery_claim",
    )
    inactive = "green" if context["prepared"]["active"] == "blue" else "blue"
    gate.require(
        context["prepared"]["slots"][inactive]["release_id"] == release,
        "recovery_release",
    )
    return context


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare-plan", "finish", "recover"])
    for name in (
        "terraform-root",
        "bundle-root",
        "foundation-vars",
        "work-dir",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--claim", required=True)
    parser.add_argument(
        "--environment", choices=["development", "production"], default="development"
    )
    parser.add_argument("--saved-plan", type=Path)
    parser.add_argument("--release-id")
    parser.add_argument("--record-version")
    parser.add_argument("--expected-state-sha256")
    args = parser.parse_args()
    os.umask(0o077)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    root, bundle, foundation, work = (
        args.terraform_root.resolve(),
        args.bundle_root.resolve(),
        args.foundation_vars.resolve(),
        args.work_dir.resolve(),
    )
    result: dict[str, Any] = {"deployment": "failed", "recovery": "not_attempted"}
    recovery_record: dict[str, str] | None = None
    authorized = False
    try:
        configure(args.environment)
        caller = aws("sts", "get-caller-identity")
        gate.require(caller["Account"] == account, "account")
        role = (
            "nova-toll-v2-development-delivery"
            if environment == "development"
            else (
                "nova-toll-production-planner"
                if args.phase == "prepare-plan"
                else "nova-toll-production-deploy"
            )
        )
        gate.require(
            caller["Arn"].startswith(f"arn:aws:sts::{account}:assumed-role/{role}/")
            or (
                args.phase == "recover"
                and re.fullmatch(
                    rf"arn:aws:sts::{account}:assumed-role/AWSReservedSSO_AdministratorAccess_[0-9a-f]{{16}}/[^/]+",
                    caller["Arn"],
                )
                is not None
            ),
            "delivery_role",
        )
        authorized = True
        context_file = work / "context.json"
        if args.phase == "prepare-plan":
            previous, identity = current(root)
            write(work / "previous.json", previous)
            candidate = prepare_descriptor(bundle, previous)
            inputs = gate.desired(previous, candidate)
            saved = plan(root, bundle, foundation, work, "prepare", previous, inputs)
            write(
                context_file,
                {
                    "claim": args.claim,
                    "previous": previous,
                    "identity": identity,
                    "inputs": inputs,
                    "plan_sha256": hashlib.sha256(saved.read_bytes()).hexdigest(),
                },
            )
            result = {"deployment": "prepared_plan", "recovery": "not_attempted"}
        elif args.phase == "recover":
            gate.require(
                all((args.release_id, args.record_version, args.expected_state_sha256)),
                "manual_recovery_identity",
            )
            context = load_recovery(
                work, args.release_id, args.claim, args.record_version
            )
            _, identity = current(root)
            gate.require(
                gate.digest(identity) == args.expected_state_sha256
                and identity["lineage"] == context["identity"]["lineage"],
                "stale_recovery",
            )
            result = {
                "deployment": "failed",
                "recovery": "recovered"
                if recover(root, bundle, foundation, work, context["prepared"])
                else "failed",
            }
        else:
            if args.saved_plan is not None:
                document = json.loads(
                    terraform(root, "show", "-json", str(args.saved_plan.resolve()))
                )
                previous = document["prior_state"]["values"]["outputs"][
                    "release_state"
                ]["value"]
                if not foundation.exists():
                    write(
                        foundation,
                        {"foundation": document["variables"]["foundation"]["value"]},
                    )
                gate.validate_plan(document, previous, "prepare")
                actual, identity = current(root)
                gate.require(actual == previous, "stale_prepare")
                inputs = {
                    key: document["variables"][key]["value"]
                    for key in ("active_slot", "release_slots")
                }
                (work / "prepare.tfplan").write_bytes(args.saved_plan.read_bytes())
                write(
                    context_file,
                    {
                        "claim": args.claim,
                        "previous": previous,
                        "identity": identity,
                        "inputs": inputs,
                        "plan_sha256": hashlib.sha256(
                            args.saved_plan.read_bytes()
                        ).hexdigest(),
                    },
                )
            context = json.loads(context_file.read_text())
            gate.require(context["claim"] == args.claim, "release_claim")
            previous, identity = current(root)
            gate.require(
                previous == context["previous"] and identity == context["identity"],
                "stale_prepare",
            )
            saved = work / "prepare.tfplan"
            gate.require(
                hashlib.sha256(saved.read_bytes()).hexdigest()
                == context["plan_sha256"],
                "saved_plan",
            )
            terraform(root, "apply", "-input=false", str(saved))
            prepared, _ = current(root)
            gate.require(
                gate.desired(prepared) == context["inputs"], "prepared_identity"
            )
            context["prepared"] = prepared
            context["environment"] = environment
            write(context_file, context)
            wait_routing(root, prepared)
            private_probe(root, prepared["slots"][prepared["active"]])
            evidence = validate_candidate(prepared, args.claim)
            write(work / "candidate-evidence.json", evidence)
            gate.require(current(root)[0] == prepared, "stale_promotion")
            gate.verify_evidence(evidence, prepared, args.claim)
            saved = plan(
                root,
                bundle,
                foundation,
                work,
                "promote",
                prepared,
                gate.desired(prepared, promote=True),
            )
            gate.verify_evidence(evidence, current(root)[0], args.claim)
            inactive = "green" if prepared["active"] == "blue" else "blue"
            key = recovery_key(prepared["slots"][inactive]["release_id"], args.claim)
            record = upload(
                context_file,
                artifact_bucket,
                key,
                "application/json",
                "private, no-store",
            )
            recovery_record = {"key": key, "version_id": record["VersionId"]}
            write(args.output, {**result, "recovery_record": recovery_record})
            try:
                terraform(root, "apply", "-input=false", str(saved))
                promoted, _ = current(root)
                gate.require(
                    gate.desired(promoted) == gate.desired(prepared, promote=True),
                    "promoted_identity",
                )
                gate.require(
                    promoted["slots"] == prepared["slots"], "promoted_artifacts"
                )
                wait_routing(root, promoted)
                private_probe(root, promoted["slots"][promoted["active"]])
            except Exception:
                result = {"deployment": "failed", "recovery": "failed"}
                if recover(root, bundle, foundation, work, prepared):
                    result["recovery"] = "recovered"
            else:
                result = observe(
                    lambda: bool(probe(promoted["slots"][promoted["active"]])),
                    lambda: recover(root, bundle, foundation, work, prepared),
                )
                result["active"] = current(root)[0]["active"]
    except (
        gate.Rejected,
        checks.CheckFailure,
        KeyError,
        ValueError,
        TypeError,
        OSError,
        subprocess.SubprocessError,
    ):
        pass
    if recovery_record is not None:
        result["recovery_record"] = recovery_record
    if authorized and args.phase != "prepare-plan":
        try:
            final_state, _ = current(root)
            result["active"] = final_state["active"]
            result["releases"] = {
                name: {
                    key: slot[key]
                    for key in (
                        "release_id",
                        "proxy_arn",
                        "proxy_version",
                        "runtime_arn",
                        "runtime_version",
                        "endpoint",
                        "asset_prefix",
                    )
                }
                for name, slot in final_state["slots"].items()
            }
        except (
            gate.Rejected,
            KeyError,
            ValueError,
            OSError,
            subprocess.SubprocessError,
        ):
            result["active"] = "unverified"
    write(args.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["deployment"] in {"succeeded", "prepared_plan"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
