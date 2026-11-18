import json
import re
import subprocess
from pathlib import Path

from factory.host import dispatcher

COMPOSE = dispatcher.FACTORY / "compose.yaml"
ENV = {
    "FACTORY_TRUST_ANCHOR_ARN": "arn:aws:rolesanywhere:us-east-1:111122223333:trust-anchor/example",
    "FACTORY_PROFILE_ARN": "arn:aws:rolesanywhere:us-east-1:111122223333:profile/example",
    "FACTORY_ROLE_ARN": "arn:aws:iam::111122223333:role/example",
    "FACTORY_RDS_HOST": "db.example.us-east-1.rds.amazonaws.com",
    "FACTORY_RDS_ADDR": "fd7a:115c:a1e0:b1a:0:1:ac1f:1",
    "FACTORY_TRACES_BUCKET": "example-bucket",
}


def image(service: str) -> str:
    block = COMPOSE.read_text().split(f"\n  {service}:\n", 1)[1]
    match = re.search(r"^    image: (\S+)$", block, re.M)
    assert match, service
    return match.group(1)


def test_collector_config_validates_with_the_pinned_image() -> None:
    config = dispatcher.FACTORY / "collector/config.yaml"
    result = subprocess.run(
        ["docker", "run", "--rm", "--env", "FACTORY_TRACES_BUCKET=example",
         "--env", f"COLLECTOR_CONFIG={config.read_text()}",
         image("collector"), "validate", "--config=env:COLLECTOR_CONFIG"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr


def test_compose_resolves_and_keeps_the_trace_stack_off_the_sandbox_network(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "factory.env"
    env_file.write_text("".join(f"{key}={value}\n" for key, value in ENV.items()))
    result = subprocess.run(
        ["docker", "compose", "--file", str(COMPOSE), "--env-file", str(env_file),
         "config", "--format", "json"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    services = json.loads(result.stdout)["services"]
    owner = services["trace-netns"]
    assert "internal" not in owner["networks"]
    assert ENV["FACTORY_RDS_HOST"] in str(owner["extra_hosts"])
    assert {p["host_ip"] for p in owner["ports"]} == {"127.0.0.1"}
    for name in ("aws-credentials", "phoenix", "collector"):
        assert services[name]["network_mode"] == "service:trace-netns"
