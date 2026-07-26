"""Tests for find_toll_locations.

Pure local JSON lookup, no network, no RDS, no psycopg import at all --
unlike the four route tools, there is no pricing stage here to fake.
Fixtures are verified directly against the committed oracles (oracles/
i95.json, i66.json, dulles_toll_road.json, i66_otb.json).
"""

import find_toll_locations as m
from find_toll_locations import find_toll_locations


def test_empty_query_returns_corridor_menu():
    result = find_toll_locations()
    assert set(result.keys()) == {"corridors"}
    ids = {c["corridor"] for c in result["corridors"]}
    assert ids == {
        "i95",
        "i495",
        "i66_itb",
        "i66_otb",
        "dulles_toll_road",
        "dulles_greenway",
    }
    by_id = {c["corridor"]: c for c in result["corridors"]}
    assert by_id["i66_otb"]["pricing_tool"] is None
    assert by_id["i66_otb"]["priced"] is False
    assert by_id["i95"]["pricing_tool"] == "i95_route"
    assert by_id["i95"]["priced"] is True


def test_empty_query_with_corridor_returns_just_that_corridors_summary():
    result = find_toll_locations(corridor="i66_itb")
    assert [c["corridor"] for c in result["corridors"]] == ["i66_itb"]
    # Never a label dump, even scoped to one corridor.
    assert "matches" not in result


def test_unknown_corridor_is_an_error():
    result = find_toll_locations("anything", corridor="i66")
    assert result["error"] == "unknown corridor 'i66'"
    assert set(result["valid_options"]) == {
        "i95",
        "i495",
        "i66_itb",
        "i66_otb",
        "dulles_toll_road",
        "dulles_greenway",
    }


def test_substring_match_finds_springfield():
    result = find_toll_locations("springfield")
    labels = {match["label"] for match in result["matches"]}
    assert "Franconia-Springfield Parkway/Route 289" in labels
    assert all(match["corridor"] == "i95" for match in result["matches"])
    assert all(match["pricing_tool"] == "i95_route" for match in result["matches"])


def test_punctuation_normalized_match_finds_washington_dc():
    result = find_toll_locations("Washington DC")
    labels = {match["label"] for match in result["matches"]}
    assert "Washington D.C." in labels


def test_locality_alias_finds_tysons():
    result = find_toll_locations("Tysons", corridor="i495")
    labels = {match["label"] for match in result["matches"]}
    assert "Jones Branch Drive/Route 123" in labels


def test_difflib_fallback_tolerates_typo_without_false_positive():
    # A whole-label difflib comparison would favor the short, unrelated
    # "Stringfellow Rd" over the intended (much longer) Springfield labels
    # purely on length -- this is exactly the bug the token-level fallback
    # in _search() exists to avoid.
    result = find_toll_locations("Sprinfield")
    labels = {match["label"] for match in result["matches"]}
    assert "Franconia-Springfield Parkway/Route 289" in labels
    assert "Stringfellow Rd" not in labels


def test_no_match_is_an_error_with_corridor_ids_as_valid_options():
    result = find_toll_locations("zzz_not_a_real_place_zzz")
    assert "error" in result
    assert set(result["valid_options"]) == {
        "i95",
        "i495",
        "i66_itb",
        "i66_otb",
        "dulles_toll_road",
        "dulles_greenway",
    }


def test_entry_and_exit_capable_reflect_role_within_filtered_pairs():
    # Franconia-Springfield Parkway/Route 289 (node 206SO) is entry-only on
    # i95 -- verified against oracles/i95.json directly.
    result = find_toll_locations(
        "Franconia-Springfield Parkway/Route 289", corridor="i95"
    )
    by_node = {match["node_id"]: match for match in result["matches"]}
    assert by_node["206SO"]["entry_capable"] is True
    assert by_node["206SO"]["exit_capable"] is False
    assert by_node["206SD"]["entry_capable"] is False
    assert by_node["206SD"]["exit_capable"] is True


def test_i66_otb_matches_are_flagged_unpriced_with_unverified_exit_capability():
    result = find_toll_locations("vaden")
    assert len(result["matches"]) == 1
    match = result["matches"][0]
    assert match["corridor"] == "i66_otb"
    assert match["pricing_tool"] is None
    assert match["priced"] is False
    assert match["entry_capable"] is True
    assert match["exit_capable"] is None


def test_i95_i495_split_matches_each_tools_own_node_filter():
    # oracles/i95.json is one shared file -- i95_route.py/i495_route.py
    # split it by node["path"].startswith("495"); find_toll_locations must
    # mirror that split exactly or it can hand back a label the matching
    # pricing tool can never resolve.
    i495_labels = {n["label"] for n in m._i495_nodes.values()}
    i95_labels = {n["label"] for n in m._i95_nodes.values()}
    assert "Jones Branch Drive/Route 123" in i495_labels
    assert "Jones Branch Drive/Route 123" not in i95_labels
    assert "Franconia-Springfield Parkway/Route 289" in i95_labels
    assert "Franconia-Springfield Parkway/Route 289" not in i495_labels


def test_raw_node_id_is_an_exact_match_not_a_substring_match():
    # "418" is itself a full node id in i66_otb (Vaden Drive) and, without
    # an exact-match tier ahead of substring matching, a spurious substring
    # hit inside an unrelated id ("1819", Exit 18/19 on dulles_toll_road).
    result = find_toll_locations("418")
    assert len(result["matches"]) == 1
    assert result["matches"][0] == {
        "corridor": "i66_otb",
        "label": "Vaden Drive",
        "node_id": "418",
        "pricing_tool": None,
        "priced": False,
        "entry_capable": True,
        "exit_capable": None,
    }

    result = find_toll_locations("206SO")
    assert result["matches"] == [
        {
            "corridor": "i95",
            "label": "Franconia-Springfield Parkway/Route 289",
            "node_id": "206SO",
            "pricing_tool": "i95_route",
            "priced": True,
            "entry_capable": True,
            "exit_capable": False,
        }
    ]


def test_tool_spec_matches_signature():
    assert find_toll_locations.tool_spec["name"] == "find_toll_locations"
    # Strands omits "required" entirely (rather than an empty list) when
    # every parameter has a default -- both query and corridor do.
    assert "required" not in find_toll_locations.tool_spec["inputSchema"]["json"]
