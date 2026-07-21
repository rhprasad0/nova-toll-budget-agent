-- Verbatim from docs/poller-spec.md §Database schema. Do not diverge.

CREATE TABLE trip_pricing (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    feed               text NOT NULL CHECK (feed IN ('i95', 'i66')),
    interval_start_at  timestamptz,              -- i66 only
    interval_end_at    timestamptz NOT NULL,
    current_at         timestamptz,              -- i95 only
    calculated_at      timestamptz NOT NULL,
    corridor_id        integer NOT NULL,
    corridor_name      text NOT NULL,
    od_pair_id         integer,                  -- i95 only
    od_pair_name       text,                     -- i95 only
    start_zone_id      integer NOT NULL,
    start_zone_name    text,
    end_zone_id        integer NOT NULL,
    end_zone_name      text NOT NULL,
    zone_toll_rate_usd numeric(10,2) NOT NULL,
    link_status        text NOT NULL DEFAULT 'NOT_APPLICABLE',  -- i66 has none
    s3_key             text NOT NULL,            -- raw object provenance
    ingested_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (feed, interval_end_at, start_zone_id, end_zone_id)  -- upsert key
);
