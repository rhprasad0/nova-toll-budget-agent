"""Build the canonical SQL seed for the TollChat v2 routing oracle."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = Path(__file__).resolve().parent / "sources"
DEFAULT_OUTPUT = ROOT / "v2" / "db" / "oracle" / "data.sql"
DEFAULT_MAP_OUTPUT = ROOT / "v2" / "agent" / "assets" / "coverage-locations.json"
LOCATION_FILE = SOURCE_DIR / "route_point_locations.json"

SOURCE_FILES = {
    "i95_shared": "i95.json",
    "i66": "i66.json",
    "dtr": "dulles_toll_road.json",
    "greenway": "dulles_greenway.json",
}

EXPECTED_POINTS = 220
EXPECTED_CONNECTIONS = 995
EXPECTED_REACHABLE_PAIRS = 2745
EXPECTED_MAX_SHORTEST_PATH = 7
_DTR_CONNECTION_CHARGE = {
    "label": "Dulles Toll Road connection",
    "price_off_peak_usd": "2.00",
    "price_peak_usd": "2.00",
}

CORRIDOR_POSITIONS = {
    "i66": {
        node_id: position
        for position, node_ids in enumerate(
            (
                ("1",),
                ("2", "3", "5"),
                ("4",),
                ("6",),
                ("7",),
                ("10",),
                ("11",),
                ("8", "9", "12"),
                ("13", "17"),
                ("14",),
                ("15",),
                ("16",),
            )
        )
        for node_id in node_ids
    },
    "greenway": {
        "1": 0,
        "2A": 1,
        "2B": 1.1,
        "3": 2,
        "4": 3,
        "5": 4,
        "6": 5,
        "7": 6,
        "8": 7,
        "28": 8,
    },
}

PREFERRED_ALTERNATIVES = {
    "i66:17:entry:WB": ("i66:12:exit:EB", "i66:13:exit:EB"),
    "greenway:2B:exit:WB": ("greenway:2A:entry:EB",),
}

WASHINGTON_POINT_LABELS = {
    "i66:16:entry:WB": ("Washington D.C. I-66", ("Washington",)),
    "i66:16:exit:EB": ("Washington D.C. I-66", ("Washington",)),
    "i95:2232SO": ("Washington D.C. I-395 Southbound", ("Washington D.C.",)),
    "i95:224ND": (
        "Washington D.C. I-95/I-395 Northbound",
        ("Washington D.C.",),
    ),
    "i95:2249ND": (
        "Washington D.C. from I-495 Southbound via I-395",
        ("Washington D.C.",),
    ),
}

I95_REPORT_CONTEXT = {
    "495 Express Lanes End/George Wash. Mem. Pkwy.": (
        "McLean",
        "Virginia",
        ("George Washington Memorial Parkway", "GW Parkway", "McLean"),
        ("American Legion Memorial Bridge",),
    ),
    "495 Express Lanes Start/Georg Wash. Mem. Pkwy.": (
        "McLean",
        "Virginia",
        ("George Washington Memorial Parkway", "GW Parkway", "McLean"),
        ("American Legion Memorial Bridge",),
    ),
    "Braddock Road": (
        "Ravensworth",
        "Virginia",
        ("Braddock Road", "Ravensworth", "Annandale"),
        (),
    ),
    "Courthouse Road/Route 630": (
        "Stafford",
        "Virginia",
        ("Courthouse Road", "Route 630", "Stafford Courthouse"),
        (),
    ),
    "Fairfax County Parkway/Route 286": (
        "Newington",
        "Virginia",
        ("Fairfax County Parkway", "Route 286", "Newington"),
        ("Fort Belvoir",),
    ),
    "Franconia-Springfield Parkway/Route 289": (
        "Springfield",
        "Virginia",
        ("Franconia-Springfield Parkway", "Route 289", "Springfield"),
        ("Franconia-Springfield Metro Station",),
    ),
    "Gallows Road": (
        "Woodburn",
        "Virginia",
        ("Gallows Road", "Woodburn", "Merrifield"),
        ("Inova Fairfax Medical Campus", "Mosaic District"),
    ),
    "Gordon Boulevard/Route 123": (
        "Lorton",
        "Virginia",
        ("Gordon Boulevard", "Route 123", "Occoquan", "Lorton"),
        (),
    ),
    "Heller Road": (
        "Springfield",
        "Virginia",
        ("Heller Road", "Newington", "Springfield"),
        ("Fort Belvoir",),
    ),
    "I-395 Near Edsall Road": (
        "Lincolnia",
        "Virginia",
        ("Edsall Road", "Lincolnia", "Alexandria"),
        (),
    ),
    "I-495 EB / I-95 NB": (
        "Springfield",
        "Virginia",
        ("Springfield Interchange", "Mixing Bowl", "Springfield"),
        ("Springfield Town Center",),
    ),
    "I-495 Near Braddock Road": (
        "North Springfield",
        "Virginia",
        ("Braddock Road", "North Springfield", "Annandale"),
        (),
    ),
    "I-495/I-95 Near Van Dorn Street": (
        "Lincolnia",
        "Virginia",
        ("Van Dorn Street", "Lincolnia", "Springfield"),
        (),
    ),
    "I-95 Near Backlick Road": (
        "Springfield",
        "Virginia",
        ("Backlick Road", "Springfield"),
        ("Springfield Town Center",),
    ),
    "I-95 Near Cardinal Drive": (
        "Montclair",
        "Virginia",
        ("Cardinal Drive", "Montclair", "Dale City"),
        (),
    ),
    "I-95 Near Courthouse Road/Route 630": (
        "Stafford",
        "Virginia",
        ("Courthouse Road", "Route 630", "Stafford Courthouse"),
        (),
    ),
    "I-95 Near Dale Boulevard": (
        "Potomac Mills",
        "Virginia",
        ("Dale Boulevard", "Potomac Mills", "Dale City"),
        ("Potomac Mills",),
    ),
    "I-95 Near Dumfries Road/Route 234": (
        "Dumfries",
        "Virginia",
        ("Dumfries Road", "Route 234", "Montclair", "Dumfries"),
        (),
    ),
    "I-95 Near Fairfax County Parkway": (
        "Newington",
        "Virginia",
        ("Fairfax County Parkway", "Route 286", "Newington"),
        ("Fort Belvoir",),
    ),
    "I-95 Near Franconia-Springfield Pkwy NB": (
        "Springfield",
        "Virginia",
        ("Franconia-Springfield Parkway", "Route 289", "Springfield"),
        ("Franconia-Springfield Metro Station",),
    ),
    "I-95 Near Franconia-Springfield Pkwy SB": (
        "Springfield",
        "Virginia",
        ("Franconia-Springfield Parkway", "Route 289", "Springfield"),
        ("Franconia-Springfield Metro Station",),
    ),
    "I-95 Near Garrisonville Road/Route 610": (
        "Stafford",
        "Virginia",
        ("Garrisonville Road", "Route 610", "Stafford"),
        (),
    ),
    "I-95 Near Gordon Boulevard/Route 123": (
        "Lorton",
        "Virginia",
        ("Gordon Boulevard", "Route 123", "Occoquan", "Lorton"),
        (),
    ),
    "I-95 Near Joplin Road/Quantico": (
        "Quantico",
        "Virginia",
        ("Joplin Road", "Quantico"),
        ("Marine Corps Base Quantico", "National Museum of the Marine Corps"),
    ),
    "I-95 Near Old Keene Mill Road/Route 644": (
        "Springfield",
        "Virginia",
        ("Old Keene Mill Road", "Route 644", "Springfield"),
        ("Springfield Town Center",),
    ),
    "I-95 Near Quantico": (
        "Quantico",
        "Virginia",
        ("Quantico", "Triangle"),
        ("Marine Corps Base Quantico", "National Museum of the Marine Corps"),
    ),
    "I-95 Near Route 17": (
        "Fredericksburg",
        "Virginia",
        ("Route 17", "Warrenton Road", "Falmouth", "Fredericksburg"),
        (),
    ),
    "I-95 Near US-1": (
        "Lorton",
        "Virginia",
        ("Route 1", "Richmond Highway", "Lorton"),
        ("Workhouse Arts Center",),
    ),
    "Interstate 66": (
        "Idylwood",
        "Virginia",
        ("I-66", "Idylwood", "Dunn Loring"),
        (),
    ),
    "Jones Branch Drive/Route 123": (
        "Tysons",
        "Virginia",
        ("Jones Branch Drive", "Route 123", "Tysons Corner"),
        ("The Boro Tysons",),
    ),
    "Lee Highway (Route 29)": (
        "Idylwood",
        "Virginia",
        ("Lee Highway", "Route 29", "Idylwood", "Merrifield"),
        (),
    ),
    "Near Pentagon/Eads Street to DC": (
        "Arlington",
        "Virginia",
        ("Pentagon", "Pentagon City", "Crystal City", "National Landing"),
        ("Pentagon", "Ronald Reagan Washington National Airport"),
    ),
    "Old Keene Mill Road/Route 644": (
        "Springfield",
        "Virginia",
        ("Old Keene Mill Road", "Route 644", "Springfield"),
        ("Springfield Town Center",),
    ),
    "Opitz Boulevard": (
        "Potomac Mills",
        "Virginia",
        ("Opitz Boulevard", "Potomac Mills", "Woodbridge"),
        ("Potomac Mills",),
    ),
    "Pentagon/Eads Street": (
        "Arlington",
        "Virginia",
        ("Pentagon", "Pentagon City", "Crystal City", "National Landing"),
        ("Pentagon", "Ronald Reagan Washington National Airport"),
    ),
    "Prince William Parkway/Route 294": (
        "Potomac Mills",
        "Virginia",
        ("Prince William Parkway", "Route 294", "Potomac Mills", "Woodbridge"),
        ("Potomac Mills",),
    ),
    "Route 267": (
        "Tysons",
        "Virginia",
        ("Dulles Toll Road", "Dulles Access Road", "Tysons Corner"),
        (),
    ),
    "Route 7 (Leesburg Pike)": (
        "Tysons",
        "Virginia",
        ("Route 7", "Leesburg Pike", "Tysons Corner"),
        ("Tysons Corner Center",),
    ),
    "Seminary Road": (
        "Alexandria",
        "Virginia",
        ("Seminary Road", "Alexandria"),
        (),
    ),
    "Shirlington Circle": (
        "Alexandria",
        "Virginia",
        ("Shirlington", "Arlington", "Alexandria"),
        ("Village at Shirlington",),
    ),
    "US-1": (
        "Lorton",
        "Virginia",
        ("Route 1", "Richmond Highway", "Lorton"),
        ("Workhouse Arts Center",),
    ),
    "Washington Boulevard/Route 27": (
        "Arlington",
        "Virginia",
        ("Washington Boulevard", "Route 27", "Pentagon"),
        ("Pentagon", "Arlington National Cemetery"),
    ),
    "Washington D.C.": (
        "Washington",
        "District of Columbia",
        ("Washington D.C.", "Washington", "District of Columbia"),
        ("National Mall", "Ronald Reagan Washington National Airport"),
    ),
    "Westpark Drive": (
        "Tysons",
        "Virginia",
        ("Westpark Drive", "Tysons Corner"),
        ("Tysons Galleria",),
    ),
}

I95_REPORT_POINT_PLACES = {
    "i495:187SD": "Dunn Loring",
    "i495:187SO": "Dunn Loring",
    "i495:188SO": "Merrifield",
    "i95:216SD": "Potomac Mills",
    "i95:2249ND": "Arlington",
    "i95:225NO": "Alexandria",
    "i95:225SD": "Alexandria",
    "i95:236SO": "Dale City",
}

AIRPORT_ALIASES = {
    "airport_dca": (
        "DCA",
        "Reagan Airport",
        "Reagan National Airport",
        "Washington National Airport",
    ),
    "airport_iad": ("IAD", "Dulles Airport", "Washington Dulles"),
}


@dataclass(frozen=True)
class Point:
    point_id: str
    network_id: str
    source_node_id: str
    point_type: str
    direction: str | None
    label: str
    place_name: str | None
    region: str | None
    country_code: str | None
    longitude: str | None
    latitude: str | None
    aliases: tuple[str, ...]
    source_metadata: dict[str, Any]


@dataclass(frozen=True)
class Connection:
    connection_id: str
    from_point_id: str
    to_point_id: str
    connection_type: str
    required_i95_direction: str | None
    source_route_key: str | None
    source_metadata: dict[str, Any]


def _load_source(source_key: str) -> dict[str, Any]:
    path = SOURCE_DIR / SOURCE_FILES[source_key]
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return cast(dict[str, Any], value)


def _load_locations() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    value: object = json.loads(LOCATION_FILE.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{LOCATION_FILE} must contain an object")
    raw = cast(dict[str, object], value)
    sources = raw.get("sources")
    locations = raw.get("locations")
    if not isinstance(sources, dict) or not isinstance(locations, dict):
        raise ValueError(f"{LOCATION_FILE} must contain sources and locations")
    return cast(dict[str, dict[str, Any]], sources), cast(
        dict[str, dict[str, Any]], locations
    )


def _location(
    sources: dict[str, dict[str, Any]],
    locations: dict[str, dict[str, Any]],
    network_id: str,
    source_node_id: str,
) -> tuple[str, str, dict[str, Any]]:
    key = f"{network_id}:{source_node_id}"
    location = locations.get(key)
    if location is None:
        raise ValueError(f"missing curated location for {key}")
    source_name = location.get("source")
    source = sources.get(source_name) if isinstance(source_name, str) else None
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if (
        source is None
        or not isinstance(latitude, str)
        or not isinstance(longitude, str)
    ):
        raise ValueError(f"invalid curated location for {key}")
    quality = source.get("coordinate_quality")
    if quality not in {"approximate_interchange", "official_reference_point"}:
        raise ValueError(f"invalid coordinate quality for {key}")
    return (
        longitude,
        latitude,
        {
            "coordinate_quality": quality,
            "coordinate_source": {
                source_key: source_value
                for source_key, source_value in source.items()
                if source_key != "coordinate_quality"
            },
        },
    )


def _source_context(source: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in source.items() if key not in {"nodes", "pairs"}
    }


def _shared_network(node: dict[str, Any]) -> str:
    path = str(node["path"])
    return "i495" if path.startswith("495") else "i95"


def _shared_direction(node: dict[str, Any]) -> str:
    path = str(node["path"])
    if path.endswith("North"):
        return "NB"
    if path.endswith("South"):
        return "SB"
    return {"Northbound": "NB", "Southbound": "SB"}[str(node["direction"])]


def _shared_role(node: dict[str, Any]) -> str:
    return {"entries": "entry", "exits": "exit"}[str(node["side"])]


def _shared_point_id(source_node_id: str, node: dict[str, Any]) -> str:
    return f"{_shared_network(node)}:{source_node_id}"


def _movement_point_id(
    network_id: str, source_node_id: str, point_type: str, direction: str
) -> str:
    return f"{network_id}:{source_node_id}:{point_type}:{direction}"


def _metadata(
    source_key: str,
    source: dict[str, Any],
    payload_key: str,
    payload: dict[str, Any],
    *,
    coordinate_quality: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_file": SOURCE_FILES[source_key],
        "source_context": _source_context(source),
        payload_key: payload,
    }
    if coordinate_quality is not None:
        result["coordinate_quality"] = coordinate_quality
    return result


def _alternative_ranking(
    network_id: str, source_node_id: str, point_id: str
) -> dict[str, Any]:
    ranking: dict[str, Any] = {}
    position = CORRIDOR_POSITIONS.get(network_id, {}).get(source_node_id)
    if position is not None:
        ranking["corridor_position"] = position
    if preferences := PREFERRED_ALTERNATIVES.get(point_id):
        ranking["preferred_point_ids"] = list(preferences)
    return {"alternative_ranking": ranking} if ranking else {}


def build_points() -> dict[str, Point]:
    points: dict[str, Point] = {}
    location_sources, locations = _load_locations()
    shared = _load_source("i95_shared")
    shared_nodes = shared["nodes"]
    if not isinstance(shared_nodes, dict):
        raise ValueError("i95 nodes must be an object")
    typed_shared_nodes = cast(dict[str, dict[str, Any]], shared_nodes)
    if {str(node["label"]) for node in typed_shared_nodes.values()} != set(
        I95_REPORT_CONTEXT
    ):
        raise ValueError("I-95 report context does not match source labels")
    for source_node_id, raw_node in typed_shared_nodes.items():
        point_id = _shared_point_id(source_node_id, raw_node)
        label = str(raw_node["label"])
        aliases: tuple[str, ...] = ()
        place_name, region, place_aliases, nearby_landmarks = I95_REPORT_CONTEXT[label]
        metadata = _metadata(
            "i95_shared",
            shared,
            "source_node",
            raw_node,
            coordinate_quality="provisional_generalized",
        )
        if source_node_id == "192NO":
            label = "I-495 Express northbound start at I-95 (TP1NB)"
            aliases = ("TP1NB", "Springfield Interchange", str(raw_node["label"]))
            metadata["curated_boundary"] = {
                "basis": "v2/docs/oracle-spec.md",
                "evidence_url": "https://www.expresslanes.com/sites/default/files/inline-files/495%20Express%20Lanes%20-%20The%20First%20Year.pdf",
                "pricing_zone_id": 495001,
                "pricing_zone_name": "NB 495 TP Past 95/395 (TP1NB)",
            }
        elif source_node_id == "192SD":
            label = "I-495 Express southbound end at I-95 (TP1SB)"
            aliases = ("TP1SB", "Springfield Interchange", str(raw_node["label"]))
            metadata["curated_boundary"] = {
                "basis": "v2/docs/oracle-spec.md",
                "evidence_url": "https://www.expresslanes.com/sites/default/files/inline-files/495%20Express%20Lanes%20-%20The%20First%20Year.pdf",
                "pricing_zone_id": 495101,
                "pricing_zone_name": "SB 495 TP Before 95/395 (TP1SB)",
            }
        elif source_node_id == "234NO":
            label = "I-95 Express northbound start near Route 17"
            aliases = ("I-95 Near Route 17", "Route 17 northbound entrance")
            metadata["curated_boundary"] = {
                "basis": "v2/docs/oracle-spec.md",
                "evidence_url": "https://improve95.vdot.virginia.gov/fredex/",
                "access_variants": [
                    "northbound_general_purpose_through_slip_ramp",
                    "route_17_route_3_local_flyover",
                ],
            }
        elif source_node_id == "235SD":
            label = "I-95 Express southbound end near Route 17"
            aliases = ("I-95 Near Route 17", "Route 17 southbound exit")
            metadata["curated_boundary"] = {
                "basis": "v2/docs/oracle-spec.md",
                "evidence_url": "https://improve95.vdot.virginia.gov/fredex/",
                "access_variants": [
                    "general_purpose_continuation",
                    "route_17_route_3_local_exit",
                ],
            }
        if point_id in WASHINGTON_POINT_LABELS:
            label, aliases = WASHINGTON_POINT_LABELS[point_id]
        place_name = I95_REPORT_POINT_PLACES.get(point_id, place_name)
        aliases = tuple(dict.fromkeys((*aliases, *place_aliases)))
        metadata["report_context"] = {
            "nearby_landmarks": list(nearby_landmarks),
        }
        points[point_id] = Point(
            point_id=point_id,
            network_id=_shared_network(raw_node),
            source_node_id=source_node_id,
            point_type=_shared_role(raw_node),
            direction=_shared_direction(raw_node),
            label=label,
            place_name=place_name,
            region=region,
            country_code="US",
            longitude=str(raw_node["longitude"]),
            latitude=str(raw_node["latitude"]),
            aliases=aliases,
            source_metadata=metadata,
        )

    for network_id in ("i66", "dtr", "greenway"):
        source = _load_source(network_id)
        nodes = source["nodes"]
        if not isinstance(nodes, dict):
            raise ValueError(f"{network_id} nodes must be an object")
        typed_nodes = cast(dict[str, dict[str, Any]], nodes)
        for source_node_id, raw_node in typed_nodes.items():
            label = str(raw_node["label"])
            longitude, latitude, location_metadata = _location(
                location_sources, locations, network_id, source_node_id
            )
            for point_type, field in (("entry", "entry_in"), ("exit", "exit_in")):
                raw_directions = raw_node.get(field, [])
                if not isinstance(raw_directions, list):
                    raise ValueError(
                        f"invalid directions on {network_id}:{source_node_id}"
                    )
                for raw_direction in cast(list[object], raw_directions):
                    direction = str(raw_direction)
                    point_id = _movement_point_id(
                        network_id, source_node_id, point_type, direction
                    )
                    point_label, aliases = WASHINGTON_POINT_LABELS.get(
                        point_id, (label, ())
                    )
                    metadata = _metadata(
                        network_id,
                        source,
                        "source_node",
                        raw_node,
                    )
                    metadata.update(location_metadata)
                    metadata.update(
                        _alternative_ranking(network_id, source_node_id, point_id)
                    )
                    points[point_id] = Point(
                        point_id=point_id,
                        network_id=network_id,
                        source_node_id=source_node_id,
                        point_type=point_type,
                        direction=direction,
                        label=point_label,
                        place_name=None,
                        region=None,
                        country_code=None,
                        longitude=longitude,
                        latitude=latitude,
                        aliases=aliases,
                        source_metadata=metadata,
                    )

    for airport_id, label in (
        ("airport_iad", "Washington Dulles International Airport"),
        ("airport_dca", "Ronald Reagan Washington National Airport"),
    ):
        source_node_id = airport_id.removeprefix("airport_").upper()
        longitude, latitude, location_metadata = _location(
            location_sources, locations, airport_id, source_node_id
        )
        points[airport_id] = Point(
            point_id=airport_id,
            network_id=airport_id,
            source_node_id=source_node_id,
            point_type="airport",
            direction=None,
            label=label,
            place_name=None,
            region=None,
            country_code=None,
            longitude=longitude,
            latitude=latitude,
            aliases=AIRPORT_ALIASES[airport_id],
            source_metadata={
                "curated": True,
                "basis": "v2/docs/oracle-spec.md",
                **location_metadata,
            },
        )

    location_keys = {
        f"{point.network_id}:{point.source_node_id}"
        for point in points.values()
        if point.source_metadata["coordinate_quality"]
        in {"approximate_interchange", "official_reference_point"}
    }
    if location_keys != set(locations):
        raise ValueError("curated location file contains unknown or unused points")

    return points


def _source_connection_id(
    source_key: str, direction: str, entry: str, exit_id: str
) -> str:
    return f"source:{source_key}:{direction}:{entry}:{exit_id}"


def _curated_connection(
    connection_id: str,
    from_point_id: str,
    to_point_id: str,
    connection_type: str,
    required_i95_direction: str | None = None,
    evidence_url: str | None = None,
    pricing_charge: dict[str, str] | None = None,
) -> Connection:
    source_metadata: dict[str, Any] = {
        "curated": True,
        "basis": "v2/docs/oracle-spec.md",
    }
    if evidence_url is not None:
        source_metadata["evidence_url"] = evidence_url
    if pricing_charge is not None:
        source_metadata["pricing_facility"] = "dtr"
        source_metadata["pricing_charge"] = pricing_charge
    return Connection(
        connection_id=connection_id,
        from_point_id=from_point_id,
        to_point_id=to_point_id,
        connection_type=connection_type,
        required_i95_direction=required_i95_direction,
        source_route_key=connection_id if pricing_charge is not None else None,
        source_metadata=source_metadata,
    )


def build_connections(points: dict[str, Point]) -> dict[str, Connection]:
    connections: dict[str, Connection] = {}
    shared = _load_source("i95_shared")
    shared_nodes = cast(dict[str, dict[str, Any]], shared["nodes"])
    for raw_pair in cast(list[dict[str, Any]], shared["pairs"]):
        entry = str(raw_pair["entry"])
        exit_id = str(raw_pair["exit"])
        direction = str(raw_pair["direction"])
        from_id = _shared_point_id(entry, shared_nodes[entry])
        to_id = _shared_point_id(exit_id, shared_nodes[exit_id])
        connection_type = (
            "within_facility"
            if points[from_id].network_id == points[to_id].network_id
            else "general_purpose_gap"
        )
        required_i95_direction = None
        if connection_type == "within_facility" and points[from_id].network_id == "i95":
            required_i95_direction = _shared_direction(shared_nodes[entry])
        connection_id = _source_connection_id("i95_shared", direction, entry, exit_id)
        source_metadata = _metadata("i95_shared", shared, "source_pair", raw_pair)
        if connection_type == "general_purpose_gap":
            i95_node = (
                shared_nodes[entry]
                if points[from_id].network_id == "i95"
                else shared_nodes[exit_id]
            )
            source_metadata["general_purpose_fallback"] = {
                "boundary_point_id": (
                    "i495:192NO" if direction == "Northbound" else "i495:192SD"
                ),
                "i95_direction": _shared_direction(i95_node),
            }
        connections[connection_id] = Connection(
            connection_id=connection_id,
            from_point_id=from_id,
            to_point_id=to_id,
            connection_type=connection_type,
            required_i95_direction=required_i95_direction,
            source_route_key=f"{direction}:{entry}:{exit_id}",
            source_metadata=source_metadata,
        )

    for network_id in ("i66", "dtr", "greenway"):
        source = _load_source(network_id)
        for raw_pair in cast(list[dict[str, Any]], source["pairs"]):
            entry = str(raw_pair["entry"])
            exit_id = str(raw_pair["exit"])
            direction = str(raw_pair["direction"])
            from_id = _movement_point_id(network_id, entry, "entry", direction)
            to_id = _movement_point_id(network_id, exit_id, "exit", direction)
            connection_id = _source_connection_id(network_id, direction, entry, exit_id)
            connections[connection_id] = Connection(
                connection_id=connection_id,
                from_point_id=from_id,
                to_point_id=to_id,
                connection_type="within_facility",
                required_i95_direction=None,
                source_route_key=f"{direction}:{entry}:{exit_id}",
                source_metadata=_metadata(network_id, source, "source_pair", raw_pair),
            )

    curated = (
        _curated_connection(
            "greenway_to_dtr",
            "greenway:28:exit:EB",
            "dtr:28:entry:EB",
            "toll_handoff",
            pricing_charge=_DTR_CONNECTION_CHARGE,
        ),
        _curated_connection(
            "dtr_to_greenway",
            "dtr:28:exit:WB",
            "greenway:28:entry:WB",
            "toll_handoff",
            pricing_charge=_DTR_CONNECTION_CHARGE,
        ),
        _curated_connection(
            "i66_to_i495",
            "i66:5:exit:WB",
            "i495:187SO",
            "toll_handoff",
        ),
        _curated_connection(
            "i66_to_i495_north",
            "i66:5:exit:WB",
            "i495:187NO",
            "toll_handoff",
        ),
        _curated_connection(
            "i495_to_i66",
            "i495:187ND",
            "i66:3:entry:EB",
            "toll_handoff",
        ),
        _curated_connection(
            "i495_south_to_i66",
            "i495:187SD",
            "i66:5:entry:EB",
            "toll_handoff",
        ),
        _curated_connection(
            "i66_to_dulles_toll_road",
            "i66:6:exit:WB",
            "dtr:66:entry:WB",
            "toll_handoff",
        ),
        _curated_connection(
            "dulles_toll_road_to_i66",
            "dtr:66:exit:EB",
            "i66:6:entry:EB",
            "toll_handoff",
        ),
        _curated_connection(
            "dulles_toll_road_to_i495",
            "dtr:1819:exit:EB",
            "i495:182SO",
            "toll_handoff",
        ),
        _curated_connection(
            "dulles_toll_road_to_i495_north",
            "dtr:1819:exit:EB",
            "i495:182NO",
            "toll_handoff",
            evidence_url="https://495next.vdot.virginia.gov/about/using/",
        ),
        _curated_connection(
            "dulles_toll_road_westbound_to_i495_north",
            "dtr:1819:exit:WB",
            "i495:182NO",
            "toll_handoff",
            evidence_url="https://495next.vdot.virginia.gov/about/using/",
        ),
        _curated_connection(
            "i495_to_dulles_toll_road",
            "i495:182ND",
            "dtr:1819:entry:WB",
            "toll_handoff",
        ),
        _curated_connection(
            "i495_south_to_dulles_toll_road",
            "i495:182SD",
            "dtr:1819:entry:WB",
            "toll_handoff",
        ),
        _curated_connection(
            "iad_to_i66", "airport_iad", "i66:6:entry:EB", "airport_access"
        ),
        _curated_connection(
            "i66_to_iad", "i66:6:exit:WB", "airport_iad", "airport_access"
        ),
        Connection(
            connection_id="iad_to_dtr_via_i66",
            from_point_id="airport_iad",
            to_point_id="dtr:66:entry:WB",
            connection_type="airport_access",
            required_i95_direction=None,
            source_route_key=None,
            source_metadata={
                "curated": True,
                "basis": "v2/docs/oracle-spec.md",
                "composed_from": ["iad_to_i66", "i66_to_dulles_toll_road"],
            },
        ),
        Connection(
            connection_id="dtr_to_iad_via_i66",
            from_point_id="dtr:66:exit:EB",
            to_point_id="airport_iad",
            connection_type="airport_access",
            required_i95_direction=None,
            source_route_key=None,
            source_metadata={
                "curated": True,
                "basis": "v2/docs/oracle-spec.md",
                "composed_from": ["dulles_toll_road_to_i66", "i66_to_iad"],
            },
        ),
        _curated_connection(
            "iad_to_i495_north", "airport_iad", "i495:182NO", "airport_access"
        ),
        _curated_connection(
            "iad_to_i495_south", "airport_iad", "i495:182SO", "airport_access"
        ),
        _curated_connection(
            "i495_north_to_iad", "i495:182ND", "airport_iad", "airport_access"
        ),
        _curated_connection(
            "i495_south_to_iad", "i495:182SD", "airport_iad", "airport_access"
        ),
        _curated_connection(
            "i95_north_to_dca",
            "i95:223ND",
            "airport_dca",
            "airport_access",
            required_i95_direction="NB",
        ),
        _curated_connection(
            "i95_north_to_dca_from_i495_south",
            "i95:2239ND",
            "airport_dca",
            "airport_access",
            required_i95_direction="NB",
        ),
        _curated_connection(
            "dca_to_i95_north",
            "airport_dca",
            "i95:224NO",
            "airport_access",
            required_i95_direction="NB",
        ),
        _curated_connection(
            "dca_to_i95_south",
            "airport_dca",
            "i95:2233SO",
            "airport_access",
            required_i95_direction="SB",
        ),
    )
    for connection in curated:
        if connection.connection_id in connections:
            raise ValueError(f"duplicate curated connection {connection.connection_id}")
        connections[connection.connection_id] = connection

    return connections


def _validate_connection(points: dict[str, Point], connection: Connection) -> None:
    if connection.from_point_id not in points or connection.to_point_id not in points:
        raise ValueError(f"unresolved endpoints on {connection.connection_id}")
    if connection.from_point_id == connection.to_point_id:
        raise ValueError(f"self connection {connection.connection_id}")
    from_point = points[connection.from_point_id]
    to_point = points[connection.to_point_id]
    if connection.connection_type == "within_facility":
        if (
            from_point.network_id != to_point.network_id
            or from_point.point_type != "entry"
            or to_point.point_type != "exit"
            or from_point.direction != to_point.direction
        ):
            raise ValueError(
                f"invalid within-facility connection {connection.connection_id}"
            )
        expected_i95_direction = (
            from_point.direction if from_point.network_id == "i95" else None
        )
        if connection.required_i95_direction != expected_i95_direction:
            raise ValueError(f"invalid I-95 requirement on {connection.connection_id}")
    elif connection.connection_type == "general_purpose_gap":
        if (
            {from_point.network_id, to_point.network_id} != {"i95", "i495"}
            or from_point.point_type != "entry"
            or to_point.point_type != "exit"
        ):
            raise ValueError(f"invalid general-purpose gap {connection.connection_id}")
        if connection.required_i95_direction is not None:
            raise ValueError(
                f"general-purpose gap requires I-95 on {connection.connection_id}"
            )
        expected_boundary = (
            "i495:192NO"
            if connection.source_metadata["source_pair"]["direction"] == "Northbound"
            else "i495:192SD"
        )
        i95_point = from_point if from_point.network_id == "i95" else to_point
        expected_i95_direction = _shared_direction(
            cast(dict[str, Any], i95_point.source_metadata["source_node"])
        )
        fallback = connection.source_metadata.get("general_purpose_fallback", {})
        if (
            fallback.get("boundary_point_id") != expected_boundary
            or fallback.get("i95_direction") != expected_i95_direction
        ):
            raise ValueError(
                f"invalid general-purpose boundary on {connection.connection_id}"
            )
    elif connection.connection_type == "toll_handoff":
        if (
            from_point.network_id == to_point.network_id
            or from_point.point_type != "exit"
            or to_point.point_type != "entry"
        ):
            raise ValueError(f"invalid toll handoff {connection.connection_id}")
        if connection.required_i95_direction is not None:
            raise ValueError(
                f"toll handoff requires I-95 on {connection.connection_id}"
            )
        priced = connection.connection_id in {"greenway_to_dtr", "dtr_to_greenway"}
        if priced and (
            connection.source_route_key != connection.connection_id
            or connection.source_metadata.get("pricing_facility") != "dtr"
            or connection.source_metadata.get("pricing_charge")
            != _DTR_CONNECTION_CHARGE
        ):
            raise ValueError(f"invalid priced handoff {connection.connection_id}")
        if not priced and (
            connection.source_route_key is not None
            or "pricing_facility" in connection.source_metadata
            or "pricing_charge" in connection.source_metadata
        ):
            raise ValueError(f"unexpected priced handoff {connection.connection_id}")
    elif connection.connection_type == "airport_access":
        valid_roles = (
            from_point.point_type == "airport" and to_point.point_type == "entry"
        ) or (from_point.point_type == "exit" and to_point.point_type == "airport")
        if not valid_roles:
            raise ValueError(f"invalid airport connection {connection.connection_id}")
        expected_i95_direction = {
            "i95_north_to_dca": "NB",
            "i95_north_to_dca_from_i495_south": "NB",
            "dca_to_i95_north": "NB",
            "dca_to_i95_south": "SB",
        }.get(connection.connection_id)
        if connection.required_i95_direction != expected_i95_direction:
            raise ValueError(
                f"invalid airport I-95 requirement on {connection.connection_id}"
            )
    else:
        raise ValueError(f"unknown connection type on {connection.connection_id}")


def graph_metrics(
    points: dict[str, Point], connections: dict[str, Connection]
) -> tuple[int, int]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for connection in connections.values():
        adjacency[connection.from_point_id].append(connection.to_point_id)
    destinations = {
        point.point_id
        for point in points.values()
        if point.point_type in {"exit", "airport"}
    }
    origins = [
        point.point_id
        for point in points.values()
        if point.point_type in {"entry", "airport"}
    ]
    reachable_pairs = 0
    maximum = 0
    for origin in origins:
        queue = deque([(origin, 0)])
        visited = {origin}
        while queue:
            point_id, depth = queue.popleft()
            if point_id != origin and point_id in destinations:
                reachable_pairs += 1
                maximum = max(maximum, depth)
            if points[point_id].point_type == "airport" and point_id != origin:
                continue
            for destination in adjacency[point_id]:
                if destination not in visited:
                    visited.add(destination)
                    queue.append((destination, depth + 1))
    return reachable_pairs, maximum


def validate(points: dict[str, Point], connections: dict[str, Connection]) -> None:
    if len(points) != EXPECTED_POINTS:
        raise ValueError(f"expected {EXPECTED_POINTS} points, found {len(points)}")
    if len(connections) != EXPECTED_CONNECTIONS:
        raise ValueError(
            f"expected {EXPECTED_CONNECTIONS} connections, found {len(connections)}"
        )
    quality_counts: dict[str, int] = defaultdict(int)
    for point in points.values():
        if (point.longitude is None) != (point.latitude is None):
            raise ValueError(f"partial coordinate on {point.point_id}")
        if point.longitude is None or point.latitude is None:
            raise ValueError(f"missing coordinate on {point.point_id}")
        longitude = float(point.longitude)
        latitude = float(point.latitude)
        if not (-78 <= longitude <= -76 and 38 <= latitude <= 40):
            raise ValueError(
                f"coordinate outside Northern Virginia on {point.point_id}"
            )
        quality = point.source_metadata.get("coordinate_quality")
        if not isinstance(quality, str):
            raise ValueError(f"missing coordinate quality on {point.point_id}")
        quality_counts[quality] += 1
        if quality != "provisional_generalized" and not isinstance(
            point.source_metadata.get("coordinate_source"), dict
        ):
            raise ValueError(f"missing coordinate source on {point.point_id}")
    expected_quality_counts = {
        "provisional_generalized": 107,
        "approximate_interchange": 111,
        "official_reference_point": 2,
    }
    if dict(quality_counts) != expected_quality_counts:
        raise ValueError(
            f"unexpected coordinate quality counts: {dict(quality_counts)}"
        )
    endpoint_pairs: set[tuple[str, str]] = set()
    for connection in connections.values():
        _validate_connection(points, connection)
        pair = (connection.from_point_id, connection.to_point_id)
        if pair in endpoint_pairs:
            raise ValueError(f"duplicate directed endpoints {pair}")
        endpoint_pairs.add(pair)
    counts: dict[str, int] = defaultdict(int)
    for connection in connections.values():
        counts[connection.connection_type] += 1
    expected_counts = {
        "within_facility": 670,
        "general_purpose_gap": 300,
        "toll_handoff": 13,
        "airport_access": 12,
    }
    if dict(counts) != expected_counts:
        raise ValueError(f"unexpected connection counts: {dict(counts)}")
    modeled_gap_count = sum(
        any(
            1374 <= int(od_id) <= 1389
            for od_id in c.source_metadata["source_pair"]["ods"]
        )
        for c in connections.values()
        if c.connection_type == "general_purpose_gap"
    )
    if modeled_gap_count != 107:
        raise ValueError(
            f"expected 107 modeled-OD gap routes, found {modeled_gap_count}"
        )
    reachable_pairs, maximum = graph_metrics(points, connections)
    if reachable_pairs != EXPECTED_REACHABLE_PAIRS:
        raise ValueError(
            f"expected {EXPECTED_REACHABLE_PAIRS} reachable pairs, found {reachable_pairs}"
        )
    if maximum != EXPECTED_MAX_SHORTEST_PATH:
        raise ValueError(
            f"expected maximum shortest path {EXPECTED_MAX_SHORTEST_PATH}, found {maximum}"
        )
    if maximum > 12:
        raise ValueError("a supported shortest path exceeds the 12-connection bound")


def _sql_text(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _sql_json(value: dict[str, Any]) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return _sql_text(serialized) + "::jsonb"


def _sql_text_array(values: tuple[str, ...]) -> str:
    if not values:
        return "ARRAY[]::text[]"
    return "ARRAY[" + ", ".join(_sql_text(value) for value in values) + "]::text[]"


def render_sql(points: dict[str, Point], connections: dict[str, Connection]) -> str:
    lines = [
        "-- Generated by v2/oracle/build_oracle_data.py; do not edit.",
        "",
        "INSERT INTO oracle.toll_route_point (",
        "    point_id, network_id, source_node_id, point_type, direction,",
        "    label, place_name, region, country_code, location, aliases, source_metadata",
        ") VALUES",
    ]
    point_values: list[str] = []
    for point in sorted(points.values(), key=lambda item: item.point_id):
        location = "NULL"
        if point.longitude is not None and point.latitude is not None:
            location = (
                "oracle.ST_SetSRID(oracle.ST_MakePoint("
                f"{point.longitude}, {point.latitude}), 4326)::oracle.geography"
            )
        point_values.append(
            "    ("
            + ", ".join(
                (
                    _sql_text(point.point_id),
                    _sql_text(point.network_id),
                    _sql_text(point.source_node_id),
                    _sql_text(point.point_type),
                    _sql_text(point.direction),
                    _sql_text(point.label),
                    _sql_text(point.place_name),
                    _sql_text(point.region),
                    _sql_text(point.country_code),
                    location,
                    _sql_text_array(point.aliases),
                    _sql_json(point.source_metadata),
                )
            )
            + ")"
        )
    lines.append(",\n".join(point_values) + ";")
    lines.extend(
        (
            "",
            "INSERT INTO oracle.toll_connection (",
            "    connection_id, from_point_id, to_point_id, connection_type,",
            "    required_i95_direction, source_route_key, source_metadata",
            ") VALUES",
        )
    )
    connection_values: list[str] = []
    for connection in sorted(connections.values(), key=lambda item: item.connection_id):
        connection_values.append(
            "    ("
            + ", ".join(
                (
                    _sql_text(connection.connection_id),
                    _sql_text(connection.from_point_id),
                    _sql_text(connection.to_point_id),
                    _sql_text(connection.connection_type),
                    _sql_text(connection.required_i95_direction),
                    _sql_text(connection.source_route_key),
                    _sql_json(connection.source_metadata),
                )
            )
            + ")"
        )
    lines.append(",\n".join(connection_values) + ";")
    lines.append("")
    return "\n".join(lines)


def render_coverage_locations(points: dict[str, Point]) -> str:
    grouped: dict[tuple[float, float], list[dict[str, str | None]]] = defaultdict(list)
    for point in sorted(points.values(), key=lambda item: item.point_id):
        if point.longitude is None or point.latitude is None:
            raise ValueError(f"missing map coordinates for {point.point_id}")
        coordinates = (float(point.longitude), float(point.latitude))
        grouped[coordinates].append(
            {
                "point_id": point.point_id,
                "facility": point.network_id,
                "label": point.label,
                "direction": point.direction,
                "role": point.point_type,
            }
        )
    snapshot = {
        "schema_version": 1,
        "locations": [
            {"coordinates": list(coordinates), "points": grouped[coordinates]}
            for coordinates in sorted(grouped)
        ],
    }
    return json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"


def build_sql() -> str:
    points = build_points()
    connections = build_connections(points)
    validate(points, connections)
    return render_sql(points, connections)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--map-output", type=Path, default=DEFAULT_MAP_OUTPUT)
    args = parser.parse_args()
    points = build_points()
    connections = build_connections(points)
    validate(points, connections)
    outputs = (
        (args.output, render_sql(points, connections)),
        (args.map_output, render_coverage_locations(points)),
    )
    if args.check:
        stale = [
            path
            for path, rendered in outputs
            if not path.exists() or path.read_text(encoding="utf-8") != rendered
        ]
        if stale:
            raise SystemExit(
                "generated oracle data is stale: "
                + ", ".join(str(path) for path in stale)
            )
        print("oracle data is current: " + ", ".join(str(path) for path, _ in outputs))
        return 0
    for path, rendered in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
