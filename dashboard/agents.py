from typing import Final

AGENT_NAMES: Final = {
    "agent_01Y8aT4NryjgTqtipBqBssyY": "worker",
    "agent_011ssC4G41v97wCzCAjg8iQU": "reviewer",
    "agent_01N8SxzRnREt1Rzsu6LCRzPD": "docs",
}
NAMED_AGENTS: Final = ("worker", "reviewer", "docs")
OTHER: Final = "other"


def agent_label(agent_id: str) -> str:
    if not agent_id:
        return OTHER
    return AGENT_NAMES.get(agent_id, agent_id)


def ordered_labels(present: set[str]) -> list[str]:
    extra = sorted(present - set(NAMED_AGENTS) - {OTHER})
    tail = [OTHER] if OTHER in present else []
    return [*NAMED_AGENTS, *extra, *tail]
