-- Mirrors docs/poller-spec.md §Database schema. Keep in sync; the schema
-- version below must match the spec and is enforced by test_schema_contract.py.
-- schema version: 3.0.0

-- I-95/395/495: OD pairs exist and legitimately share start/end zones at
-- different rates, so od_pair_id is part of the key. current_at/od_pair_id/
-- od_pair_name/link_status are NOT NULL because the source feed always
-- populates them (verified against 1.2M archived + live rows).
CREATE TABLE trip_pricing_i95 (
    interval_end_at    timestamptz NOT NULL,
    current_at         timestamptz NOT NULL,
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    od_pair_id         integer NOT NULL,
    od_pair_name       text NOT NULL,
    start_zone_id      integer NOT NULL,
    start_zone_name    text,                      -- blank for some Prince William OD pairs
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    link_status        text NOT NULL,
    s3_key             text NOT NULL,              -- raw object provenance
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (interval_end_at, start_zone_id, end_zone_id, od_pair_id)
);

-- I-66 ITB: no OD pairs, so the key is zone-only. interval_start_at is
-- always present (i95 never had it); every key column is NOT NULL so no
-- NULLS NOT DISTINCT is needed, unlike the old shared table.
CREATE TABLE trip_pricing_i66 (
    interval_start_at  timestamptz NOT NULL,
    interval_end_at    timestamptz NOT NULL,
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    start_zone_id      integer NOT NULL,
    start_zone_name    text,                      -- nullable, same reason as i95
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    s3_key             text NOT NULL,
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (interval_end_at, start_zone_id, end_zone_id)
);
