"""Fixed directional-access checks outside the reversible I-95 lanes."""

from agent_tools import i66_route as i66_mod
from agent_tools import i495_route as i495_mod
from agent_tools.dulles_route import dulles_route


def test_i66_wrong_direction_exit_returns_recovery():
    assert set(i66_mod._POSITION) == set(i66_mod._NODES)
    result = i66_mod._lookup("I-495 N", "Lee Highway - Scott Street")

    assert result["status"] == "one_way_mismatch"
    assert result["direction"] == "EB"
    assert result["constraints"] == [
        {
            "location": "Lee Highway - Scott Street",
            "role": "exit",
            "required_direction": "EB",
            "available_directions": [],
            "nearby_options": ["Fairfax Drive", "Lee Highway - Spout Run Parkway"],
        }
    ]


def test_i495_wrong_direction_exit_returns_recovery():
    result = i495_mod._lookup(
        "Westpark Drive", "495 Express Lanes Start/Georg Wash. Mem. Pkwy."
    )

    assert result["status"] == "one_way_mismatch"
    assert result["direction"] == "Northbound"
    assert result["constraints"][0]["role"] == "exit"
    assert result["constraints"][0]["nearby_options"][0] == (
        "495 Express Lanes End/George Wash. Mem. Pkwy."
    )


def test_i495_dual_mismatch_never_offers_an_unroutable_pair():
    result = i495_mod._lookup(
        "495 Express Lanes End/George Wash. Mem. Pkwy.",
        "495 Express Lanes Start/Georg Wash. Mem. Pkwy.",
    )

    entry, exit = result["constraints"]
    assert entry["role"] == "entry" and exit["role"] == "exit"
    assert exit["nearby_options"] == ["495 Express Lanes End/George Wash. Mem. Pkwy."]


def test_fixed_directional_access_does_not_depend_on_time():
    calls = (
        lambda at_time: i66_mod.i66_route(
            "I-495 N", "Lee Highway - Scott Street", at_time
        ),
        lambda at_time: i495_mod.i495_route(
            "Westpark Drive",
            "495 Express Lanes Start/Georg Wash. Mem. Pkwy.",
            at_time,
        ),
        lambda at_time: dulles_route(
            "Exit 2B - Compass Creek Pkwy", "Exit 8 - SR 606 (Ox Rd)", at_time
        ),
    )
    for call in calls:
        morning = call("2026-08-04T07:00:00-04:00")
        evening = call("2026-08-04T17:00:00-04:00")
        assert morning == evening
        assert morning["status"] == "one_way_mismatch"
