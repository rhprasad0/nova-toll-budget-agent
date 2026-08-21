\set ON_ERROR_STOP on

DO $$
DECLARE
    points jsonb;
    point jsonb;
    previous_id text;
BEGIN
    SELECT oracle.get_toll_route_prompt_points() INTO points;
    IF jsonb_typeof(points) <> 'array'
       OR jsonb_array_length(points) <> 220 THEN
        RAISE EXCEPTION 'prompt point payload is not the canonical 220-point array';
    END IF;

    FOR point IN SELECT value FROM jsonb_array_elements(points) LOOP
        IF (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(point) AS key)
           <> ARRAY[
               'aliases', 'direction', 'label', 'location', 'network_id',
               'point_id', 'point_type', 'source_node_id'
           ]::text[]
           OR point->>'point_id' <= coalesce(previous_id, '')
           OR point->'location'->>'type' <> 'Point'
           OR jsonb_array_length(point->'location'->'coordinates') <> 2 THEN
            RAISE EXCEPTION 'prompt point payload is malformed or unordered: %', point;
        END IF;
        previous_id := point->>'point_id';
    END LOOP;

    IF NOT points @> jsonb_build_array(jsonb_build_object(
        'point_id', 'greenway:1:entry:EB',
        'network_id', 'greenway',
        'source_node_id', '1',
        'point_type', 'entry',
        'direction', 'EB',
        'label', 'Exit 1 - US 15/SR 7 (Leesburg Bypass)',
        'aliases', '[]'::jsonb,
        'location', jsonb_build_object(
            'type', 'Point',
            'coordinates', jsonb_build_array(-77.5652813, 39.1000972)
        )
    )) THEN
        RAISE EXCEPTION 'known prompt point is missing or changed';
    END IF;
END $$;

SET ROLE tollchat_agent;
DO $$
BEGIN
    IF jsonb_array_length(oracle.get_toll_route_prompt_points()) <> 220 THEN
        RAISE EXCEPTION 'agent prompt-point execution returned the wrong count';
    END IF;
END $$;
RESET ROLE;

SET ROLE pricing_caller;
DO $$
BEGIN
    BEGIN
        PERFORM oracle.get_toll_route_prompt_points();
        RAISE EXCEPTION 'pricing caller executed the agent prompt-point function';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
END $$;
RESET ROLE;
