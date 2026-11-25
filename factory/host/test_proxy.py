"""End-to-end checks of the egress proxy: the real image, run as compose runs it,
against an echo server that answers for every allowlisted name on an internal
network. Needs Docker; CI's factory job has it, so there a missing Docker fails.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

FACTORY = Path(__file__).resolve().parents[1]

MITMPROXY = "mitmproxy/mitmproxy:12.2.3"
TOKEN = "test-token-not-a-credential"
CLOUDFLARE = "/cloudflare/terraform-provider-cloudflare/releases/download/"
RDS = "/global/global-bundle.pem"
REPOSITORY = "/rhprasad0/nova-toll-budget-agent"
LAB = "/rhprasad0/chaos-lab"
GRADER = "/rhprasad0/chaos-lab-grader"
GITHUB_TOKEN = "github-test-token-not-a-credential"
API_TOKEN = "github-read-token-not-a-credential"

ECHO = r"""
import datetime, http.server, json, ssl, threading
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

key = ec.generate_private_key(ec.SECP256R1())
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "echo")])
now = datetime.datetime.now(datetime.timezone.utc)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(1).not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
with open("/tmp/echo.pem", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))
    f.write(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

class Echo(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        self.do_GET()

    def do_GET(self):
        body = json.dumps({"path": self.path, "headers": dict(self.headers)}).encode()
        self.send_response(200)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def serve(port, tls):
    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), Echo)
    if tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain("/tmp/echo.pem")
        server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()

for port, tls in ((80, False), (2222, False)):
    threading.Thread(target=serve, args=(port, tls), daemon=True).start()
serve(443, True)
"""

CLIENT = r"""
import json, socket, ssl, sys, time

def head(s):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    return data

def rest(s):
    data = b""
    try:
        while chunk := s.recv(65536):
            data += chunk
    except OSError:
        pass
    return data

def status(data):
    parts = data.split(b" ", 2)
    return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

def parse(data):
    code = status(data)
    body = data.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in data else b""
    try:
        return {"status": code, "echo": json.loads(body)}
    except ValueError:
        return {"status": code}

def proxy():
    for _ in range(60):
        try:
            return socket.create_connection((sys.argv[2], 8080), timeout=10)
        except OSError:
            time.sleep(1)
    sys.exit("proxy never listened")

def connect(host, port):
    s = proxy()
    s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode())
    return s, status(head(s))

def https(host, path, host_header=None, body=b""):
    s, code = connect(host, 443)
    if code != 200:
        return {"status": code}
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    t = context.wrap_socket(s, server_hostname=host)
    method = "POST" if body else "GET"
    t.sendall((f"{method} {path} HTTP/1.1\r\nHost: {host_header or host}\r\n"
               f"Content-Length: {len(body)}\r\n"
               "Authorization: Bearer from-the-sandbox\r\nConnection: close\r\n\r\n").encode()
              + body)
    return parse(rest(t))

def plain(url, host_header):
    s = proxy()
    s.sendall(f"GET {url} HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n\r\n".encode())
    return parse(rest(s))

cases = json.loads(sys.argv[1])
results = {}
for name, (kind, *args) in cases.items():
    if kind == "connect":
        results[name] = {"status": connect(*args)[1]}
    elif kind == "https":
        results[name] = https(*args)
    elif kind == "post":
        results[name] = https(args[0], args[1], None, b"x" * 4096)
    else:
        results[name] = plain(*args)
print(json.dumps(results))
"""

CASES: dict[str, list[Any]] = {
    "anthropic": ["https", "api.anthropic.com", "/v1/messages"],
    "pypi": ["https", "pypi.org", "/simple/"],
    "cloudflare_release": ["https", "github.com", CLOUDFLARE + "v5/sums"],
    "rds_bundle": ["https", "truststore.pki.rds.amazonaws.com", RDS],
    "unlisted_host": ["connect", "evil", 443],
    "unlisted_https": ["https", "evil", "/search?q=x"],
    "anthropic_upper": ["https", "API.ANTHROPIC.COM", "/v1/messages"],
    "anthropic_trailing_dot": ["https", "api.anthropic.com.", "/v1/messages"],
    "other_port": ["connect", "api.anthropic.com", 2222],
    "listed_host_other_port": ["connect", "github.com", 22],
    "host_header_mismatch": ["https", "pypi.org", "/", "api.anthropic.com"],
    "plain_http": ["plain", "http://api.anthropic.com/", "api.anthropic.com"],
    "absolute_form_faked_host": ["plain", "http://evil/x", "api.anthropic.com"],
    "github_other_path": ["https", "github.com", "/someone/repo"],
    "github_dot_dot": ["https", "github.com", CLOUDFLARE + "../../../../x/y"],
    "github_encoded_dot_dot": ["https", "github.com", CLOUDFLARE + "%2e%2e/%2e%2e/x"],
    "github_double_slash": ["https", "github.com", CLOUDFLARE + "v5//x"],
    "rds_suffix": ["https", "truststore.pki.rds.amazonaws.com", RDS + "X"],
    "repository": ["https", "github.com", REPOSITORY + ".git/info/refs"],
    "repository_page": ["https", "github.com", REPOSITORY + "/issues/1"],
    "repository_api": ["https", "api.github.com", "/repos" + REPOSITORY + "/issues"],
    "other_repository_api": ["https", "api.github.com", "/repos/someone/repo"],
    "repository_push": ["post", "github.com", REPOSITORY + "/git-receive-pack"],
    "other_repository_push": ["post", "github.com", "/someone/repo/git-receive-pack"],
    "lab_clone": ["https", "github.com", LAB + ".git/info/refs"],
    "lab_push": ["post", "github.com", LAB + "/git-receive-pack"],
    "lab_api": ["https", "api.github.com", "/repos" + LAB + "/pulls"],
    "grader_clone": ["https", "github.com", GRADER + ".git/info/refs"],
    "grader_unsuffixed_clone": ["https", "github.com", GRADER + "/info/refs"],
    "grader_api": [
        "https",
        "api.github.com",
        "/repos" + GRADER + "/contents/README.md",
    ],
    "grader_encoded": [
        "https",
        "github.com",
        LAB + "%2f..%2fchaos-lab-grader/info/refs",
    ],
    "worker_poll": ["https", "api.anthropic.com", "/v1/environments/env_1/work/poll"],
    "pypi_upload": ["post", "pypi.org", "/legacy/"],
    "registry_pull": [
        "https",
        "registry-1.docker.io",
        "/v2/postgis/postgis/manifests/17",
    ],
    "registry_push": ["post", "registry-1.docker.io", "/v2/someone/x/blobs/uploads/"],
}
SANDBOX = {
    "pypi", "cloudflare_release", "rds_bundle", "repository", "repository_page",
    "repository_api", "repository_push", "worker_poll", "registry_pull",
    "unlisted_host", "unlisted_https", "pypi_upload", "registry_push", "rds_suffix",
    "lab_clone", "lab_push", "lab_api",
}  # fmt: skip
ALLOWED = {
    "subscription": {"anthropic", "pypi", "cloudflare_release", "rds_bundle", "worker_poll",
                     "pypi_upload"},
    "sandbox-read": SANDBOX,
    "sandbox-write": SANDBOX,
}  # fmt: skip


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], check=check, text=True, capture_output=True, timeout=300
    )


@pytest.fixture(scope="module")
def results() -> Iterator[dict[str, Any]]:
    if not shutil.which("docker"):
        if os.environ.get("CI"):
            pytest.fail("the factory job needs Docker for the proxy checks")
        pytest.skip("needs Docker")
    tag = f"factory-proxy-test-{uuid.uuid4().hex[:8]}"
    docker("build", "--quiet", "--tag", f"{tag}:test", str(FACTORY / "proxy"))
    docker("network", "create", "--internal", tag)
    aliases = ["api.anthropic.com", "pypi.org", "github.com", "api.github.com", "evil"]
    aliases += ["truststore.pki.rds.amazonaws.com", "registry-1.docker.io"]
    try:
        docker("run", "--detach", "--name", f"{tag}-echo", "--network", tag,
               *[a for alias in aliases for a in ("--network-alias", alias)],
               "--entrypoint", "python3", MITMPROXY, "-c", ECHO)  # fmt: skip
        proxies: dict[str, tuple[list[str], list[str]]] = {
            "subscription": (
                ["--env", f"CLAUDE_CODE_OAUTH_TOKEN={TOKEN}"],
                proxy_command(),
            ),
            "sandbox-read": (sandbox_env(), sandbox_proxy_command()),
            "sandbox-write": (
                [*sandbox_env(), "--env", f"GITHUB_TOKEN={GITHUB_TOKEN}"],
                sandbox_proxy_command(),
            ),
        }
        for name, (env, command) in proxies.items():
            docker("run", "--detach", "--name", f"{tag}-{name}", "--network", tag,
                   "--network-alias", name, "--tmpfs", "/state/flows:mode=1777",
                   *env, f"{tag}:test", *command, "--set", "ssl_insecure=true")  # fmt: skip
        client = ["run", "--rm", "--network", tag, "--entrypoint", "python3", MITMPROXY]
        out = {
            name: json.loads(
                docker(*client, "-c", CLIENT, json.dumps(CASES), name).stdout
            )
            for name in proxies
        }
        yield out
    finally:
        docker("rm", "--force", f"{tag}-echo",
               *[f"{tag}-{name}" for name in ("subscription", "sandbox-read", "sandbox-write")],
               check=False)  # fmt: skip
        docker("network", "rm", tag, check=False)
        docker("image", "rm", f"{tag}:test", check=False)


def proxy_command() -> list[str]:
    """The proxy's command exactly as compose.yaml runs it."""
    text = (FACTORY / "compose.yaml").read_text()
    block = re.search(r"    command:\n((?:      - .+\n)+)", text)
    assert block
    return [line.strip()[2:] for line in block.group(1).splitlines()]


def sandbox_env() -> list[str]:
    return [
        "--env",
        "ALLOWLIST=sandbox-allowlist.txt",
        "--env",
        f"GITHUB_API_TOKEN={API_TOKEN}",
    ]


def sandbox_proxy_command() -> list[str]:
    """The sandbox proxies' command exactly as sandbox/compose.yaml runs it."""
    text = (FACTORY / "sandbox/compose.yaml").read_text()
    block = re.search(r"  command:\n((?:    - .+\n)+)", text)
    assert block
    return [line.strip()[2:] for line in block.group(1).splitlines()]


def test_compose_drops_traffic_that_is_not_http() -> None:
    for command in (proxy_command(), sandbox_proxy_command()):
        assert command[command.index("--set") + 1] == "rawtcp=false"
    assert "stream_large_bodies=1" in sandbox_proxy_command()


def authorization(result: dict[str, Any]) -> str | None:
    headers: dict[str, str] = result["echo"]["headers"]
    return next((v for k, v in headers.items() if k.lower() == "authorization"), None)


def test_token_reaches_only_https_to_anthropic(results: dict[str, Any]) -> None:
    subscription = results["subscription"]
    assert subscription["anthropic"]["status"] == 200
    assert authorization(subscription["anthropic"]) == f"Bearer {TOKEN}"
    for name in ("pypi", "rds_bundle"):
        assert subscription[name]["status"] == 200, name
        assert authorization(subscription[name]) == "Bearer from-the-sandbox", name
    assert subscription["cloudflare_release"]["status"] == 200
    assert authorization(subscription["cloudflare_release"]) is None


def test_sandbox_proxies_pass_the_worker_key_and_hold_the_github_tokens(
    results: dict[str, Any],
) -> None:
    basic = base64.b64encode(f"x-access-token:{GITHUB_TOKEN}".encode()).decode()
    for proxy, git in (("sandbox-read", None), ("sandbox-write", f"Basic {basic}")):
        found = results[proxy]
        assert authorization(found["worker_poll"]) == "Bearer from-the-sandbox", proxy
        assert authorization(found["repository"]) == git, proxy
        assert authorization(found["repository_push"]) == git, proxy
        assert authorization(found["repository_page"]) is None, proxy
        assert authorization(found["repository_api"]) == f"Bearer {API_TOKEN}", proxy
        assert authorization(found["cloudflare_release"]) is None, proxy


@pytest.mark.parametrize("proxy", sorted(ALLOWED))
@pytest.mark.parametrize("name", sorted(CASES))
def test_only_allowlisted_requests_reach_upstream(
    results: dict[str, Any], proxy: str, name: str
) -> None:
    found = results[proxy][name]
    if name in ALLOWED[proxy]:
        assert found["status"] == 200, found
    else:
        assert found["status"] in {0, 403}, found
        assert "echo" not in found
