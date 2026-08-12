import importlib.util
import json
import stat
from pathlib import Path

from strands.hooks import BeforeModelCallEvent, BeforeToolCallEvent, MessageAddedEvent

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "diagnose_duplicate_planner",
    ROOT / "scripts" / "diagnose_duplicate_planner.py",
)
assert SPEC and SPEC.loader
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


def _tool_message(call_id: str, arguments: dict[str, str]) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": [
            {
                "reasoningContent": {
                    "reasoningText": {"text": f"summary before {call_id}"},
                }
            },
            {
                "toolUse": {
                    "toolUseId": call_id,
                    "name": "plan_toll_route",
                    "input": arguments,
                }
            },
        ],
    }


def test_classifies_distinct_identical_planner_calls_as_duplicate():
    arguments = {
        "origin_corridor": "i95",
        "destination_corridor": "i495",
    }
    messages = [
        _tool_message("call-one", arguments),
        _tool_message("call-two", dict(reversed(list(arguments.items())))),
    ]

    classification = diagnostic.classify_planner_calls(messages)

    assert classification == {
        "status": "duplicate",
        "planner_call_count": 2,
        "tool_use_ids": ["call-one", "call-two"],
        "arguments": [arguments, dict(reversed(list(arguments.items())))],
    }


def test_does_not_conflate_repeated_history_or_changed_arguments():
    arguments = {"origin_corridor": "i95", "destination_corridor": "i495"}
    repeated_history = [
        _tool_message("same-call", arguments),
        _tool_message("same-call", arguments),
    ]
    changed = [
        _tool_message("call-one", arguments),
        _tool_message(
            "call-two",
            {"origin_corridor": "i495", "destination_corridor": "i95"},
        ),
    ]

    assert diagnostic.classify_planner_calls(repeated_history)["status"] == "normal"
    assert diagnostic.classify_planner_calls(changed)["status"] == "other"


def test_extracts_reasoning_summaries_in_message_order():
    messages = [
        _tool_message("call-one", {"origin_corridor": "i95"}),
        {"role": "assistant", "content": [{"text": "final"}]},
        _tool_message("call-two", {"origin_corridor": "i95"}),
    ]

    assert diagnostic.reasoning_summaries(messages) == [
        "summary before call-one",
        "summary before call-two",
    ]


def test_stops_only_after_normal_and_duplicate_trials_exist():
    assert diagnostic.should_stop(["normal", "duplicate"])
    assert diagnostic.should_stop(["other", "duplicate", "normal"])
    assert not diagnostic.should_stop(["duplicate"])
    assert not diagnostic.should_stop(["normal", "other"])


def test_enables_reasoning_summary_without_changing_other_model_params():
    class Model:
        def __init__(self):
            self.updated = None

        def get_config(self):
            return {
                "model_id": "gpt-5.6-luna",
                "params": {
                    "max_output_tokens": 2048,
                    "reasoning": {"effort": "low"},
                    "prompt_cache_key": "tollchat-agent-v1",
                },
            }

        def update_config(self, **kwargs):
            self.updated = kwargs

    agent = type("Agent", (), {"model": Model()})()

    diagnostic.enable_reasoning_summary(agent)

    assert agent.model.updated == {
        "params": {
            "max_output_tokens": 2048,
            "reasoning": {"effort": "low", "summary": "auto"},
            "prompt_cache_key": "tollchat-agent-v1",
        }
    }


def test_appends_unsanitized_jsonl_with_private_permissions(tmp_path):
    path = tmp_path / "raw.jsonl"
    record = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "reasoningContent": {
                            "reasoningText": {"text": "exact raw summary"}
                        }
                    }
                ],
            }
        ]
    }

    diagnostic.append_raw_record(path, record)

    assert json.loads(path.read_text()) == record
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_recorder_preserves_raw_hook_event_order():
    emitted = []
    recorder = diagnostic.RawTraceRecorder(emitted.append)
    agent = object()
    message = {"role": "assistant", "content": [{"text": "raw output"}]}
    tool_use = {
        "toolUseId": "call-one",
        "name": "plan_toll_route",
        "input": {"origin_corridor": "i95"},
    }

    recorder.before_model(BeforeModelCallEvent(agent=agent))
    recorder.message_added(MessageAddedEvent(agent=agent, message=message))
    recorder.before_tool(
        BeforeToolCallEvent(
            agent=agent,
            selected_tool=None,
            tool_use=tool_use,
            invocation_state={},
        )
    )

    assert [event["event"] for event in emitted] == [
        "before_model",
        "message_added",
        "before_tool",
    ]
    assert emitted[1]["payload"] == message
    assert emitted[2]["payload"] == tool_use
