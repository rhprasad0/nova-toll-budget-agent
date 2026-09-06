FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285

WORKDIR /opt/tollchat
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY eval/runtime-requirements.txt /tmp/runtime-requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check --require-hashes -r /tmp/runtime-requirements.txt \
    && rm /tmp/runtime-requirements.txt

COPY agent/__init__.py /opt/tollchat/agent/__init__.py
COPY agent/toll_agent.py /opt/tollchat/agent/toll_agent.py
COPY agent_tools/current_price_domain.py /opt/tollchat/agent_tools/current_price_domain.py
COPY agent_tools/get_annual_toll_ballpark.py /opt/tollchat/agent_tools/get_annual_toll_ballpark.py
COPY agent_tools/get_current_toll_price.py /opt/tollchat/agent_tools/get_current_toll_price.py
COPY agent_tools/validate_toll_route.py /opt/tollchat/agent_tools/validate_toll_route.py
COPY agent-sops/nova-toll-pricing-assistant.sop.md /opt/tollchat/agent-sops/nova-toll-pricing-assistant.sop.md
COPY eval/fixture_runner.py /opt/tollchat/eval/fixture_runner.py
COPY eval/container_worker.py /opt/tollchat/eval/container_worker.py

USER 10001:10001
ENTRYPOINT ["python", "-m", "eval.container_worker"]
