-- Read-only parity verification for the live public and pricing generations.

\set ON_ERROR_STOP on

DO $$
BEGIN
    IF (SELECT version FROM pricing.schema_version WHERE singleton) <> '1.1.1' THEN
        RAISE EXCEPTION 'unexpected pricing schema version';
    END IF;

    IF (SELECT count(*) FROM pricing.backfill_state) <> 2
       OR EXISTS (
            SELECT 1
            FROM pricing.backfill_state
            WHERE public_row_count <> pricing_row_count
       ) THEN
        RAISE EXCEPTION 'pricing backfill is incomplete';
    END IF;

    IF (SELECT count(*) FROM public.trip_pricing_i95)
          <> (SELECT count(*) FROM pricing.trip_pricing_i95)
       OR (SELECT count(*) FROM public.trip_pricing_i66)
          <> (SELECT count(*) FROM pricing.trip_pricing_i66) THEN
        RAISE EXCEPTION 'current public/pricing row counts differ';
    END IF;

    IF EXISTS (
        (SELECT to_jsonb(source_row) - 'ingested_at'
         FROM public.trip_pricing_i95 AS source_row
         EXCEPT
         SELECT to_jsonb(pricing_row) - 'ingested_at'
         FROM pricing.trip_pricing_i95 AS pricing_row)
        UNION ALL
        (SELECT to_jsonb(pricing_row) - 'ingested_at'
         FROM pricing.trip_pricing_i95 AS pricing_row
         EXCEPT
         SELECT to_jsonb(source_row) - 'ingested_at'
         FROM public.trip_pricing_i95 AS source_row)
        UNION ALL
        (SELECT to_jsonb(source_row) - 'ingested_at'
         FROM public.trip_pricing_i66 AS source_row
         EXCEPT
         SELECT to_jsonb(pricing_row) - 'ingested_at'
         FROM pricing.trip_pricing_i66 AS pricing_row)
        UNION ALL
        (SELECT to_jsonb(pricing_row) - 'ingested_at'
         FROM pricing.trip_pricing_i66 AS pricing_row
         EXCEPT
         SELECT to_jsonb(source_row) - 'ingested_at'
         FROM public.trip_pricing_i66 AS source_row)
    ) THEN
        RAISE EXCEPTION 'current public/pricing business rows differ';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pricing.trip_pricing_i95
        WHERE ingested_at IS NULL
        UNION ALL
        SELECT 1
        FROM pricing.trip_pricing_i66
        WHERE ingested_at IS NULL
    ) THEN
        RAISE EXCEPTION 'pricing rows are missing ingestion provenance';
    END IF;
END $$;
