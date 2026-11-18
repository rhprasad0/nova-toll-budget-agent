# The addon is baked in, not bind-mounted: mitmproxy unloads a script whose file
# disappears and then runs as an open proxy (found 2026-11-11 when a git checkout
# briefly removed it). host/dispatcher.py also preflights the proxy before every job.
FROM mitmproxy/mitmproxy:12.2.3
COPY allowlist.py allowlist.txt sandbox-allowlist.txt /addon/
# Nothing runs as root. The image's entrypoint needs root to remap its user to the
# CA directory's owner, so skip it: the factory machine's user is uid 1000, as is
# the image's mitmproxy user.
ENV HOME=/home/mitmproxy
USER mitmproxy
ENTRYPOINT []
