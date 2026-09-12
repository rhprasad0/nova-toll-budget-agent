\set ON_ERROR_STOP on

BEGIN;
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(hashtext('tollchat-v2-oracle-schema-version'));

DO $migration$
DECLARE
    current_version text;
    pricing_version text;
    provenance jsonb := jsonb_build_object(
        'evidence_urls', jsonb_build_array(
            'https://p3.virginia.gov/media/p3/documents/p3-agreements/i-95i-395fredex/02C3_C-3-Attach_1-0a_395_Express_Lanes_SOW.pdf',
            'https://www.vdot.virginia.gov/media/vdotvirginiagov/projects/northern-virginia/395-express-lanes-extension-in-the-city-/BoardsforWeb.pdf',
            'https://www.expresslanes.com/images/flash/access-maps/washignton-boulevard/large-access-static.png',
            'https://www.transurban.com/content/dam/transurban-pdfs/02/news/TCL_395_Express_Lanes_Project_Approved.pdf'
        ),
        'method', 'reviewed_operator_access_point_with_vdot_route_context',
        'provider', 'Virginia Department of Transportation',
        'retrieved_at', '2026-09-11',
        'source_feature_common_name', 'I-395R',
        'source_feature_id', 96035,
        'source_feature_name', 'R-VA   IS00395RV',
        'source_jurisdiction_code', NULL,
        'source_jurisdiction_name', NULL,
        'source_route_number', '395',
        'source_route_type', 'Interstate',
        'source_url', 'https://services.arcgis.com/p5v98VHDX9Atv3l7/arcgis/rest/services/LRS_Route_Master/FeatureServer/0'
    );
BEGIN
    SELECT version INTO STRICT current_version
    FROM oracle.schema_version
    WHERE singleton;
    SELECT version INTO STRICT pricing_version
    FROM pricing.schema_version
    WHERE singleton;

    IF current_version NOT IN ('1.14.0', '1.14.1') THEN
        RAISE EXCEPTION 'expected oracle schema version 1.14.0 or 1.14.1, got %',
            current_version;
    END IF;
    IF pricing_version <> '1.3.0' THEN
        RAISE EXCEPTION 'oracle 1.14.1 requires pricing 1.3.0';
    END IF;

    IF current_version = '1.14.0' THEN
        IF (SELECT count(*) FROM oracle.toll_route_point) <> 220
           OR (SELECT count(*) FROM oracle.toll_connection) <> 996 THEN
            RAISE EXCEPTION 'oracle 1.14.0 source state is incompatible';
        END IF;

        UPDATE oracle.toll_route_point AS point
        SET location = oracle.ST_SetSRID(
                oracle.ST_MakePoint(coordinate.longitude, coordinate.latitude), 4326
            )::oracle.geography,
            direction = CASE point.point_id
                WHEN 'i95:22329ND' THEN 'NB' ELSE point.direction END,
            region = CASE point.point_id
                WHEN 'i95:2249ND' THEN 'Virginia' ELSE point.region END,
            source_metadata = point.source_metadata || jsonb_build_object(
                'coordinate_quality', 'approximate_interchange',
                'coordinate_source', provenance
            )
        FROM (VALUES
            ('i95:22329ND', -77.0659710000000::numeric, 38.8663530000000::numeric),
            ('i95:2232ND', -77.0659710000000::numeric, 38.8663530000000::numeric),
            ('i95:2232SO', -77.03933::numeric, 38.878511::numeric),
            ('i95:2233SO', -77.0574660000000::numeric, 38.8663900000000::numeric),
            ('i95:2239ND', -77.0574660000000::numeric, 38.8663900000000::numeric),
            ('i95:223ND', -77.0574660000000::numeric, 38.8663900000000::numeric),
            ('i95:223SO', -77.0659710000000::numeric, 38.8663530000000::numeric),
            ('i95:2249ND', -77.0461277::numeric, 38.8707667::numeric),
            ('i95:224ND', -77.0396420000000::numeric, 38.8780160000000::numeric),
            ('i95:224NO', -77.052876::numeric, 38.865725::numeric)
        ) AS coordinate(point_id, longitude, latitude)
        WHERE point.point_id = coordinate.point_id;

        UPDATE oracle.toll_connection
        SET source_metadata = jsonb_set(
            source_metadata,
            '{general_purpose_fallback,i95_direction}',
            '"NB"'::jsonb
        )
        WHERE connection_id IN (
            'source:i95_shared:Southbound:180SO:22329ND',
            'source:i95_shared:Southbound:182SO:22329ND',
            'source:i95_shared:Southbound:183SO:22329ND',
            'source:i95_shared:Southbound:185SO:22329ND',
            'source:i95_shared:Southbound:186SO:22329ND',
            'source:i95_shared:Southbound:187SO:22329ND',
            'source:i95_shared:Southbound:188SO:22329ND'
        );

        UPDATE oracle.schema_version
        SET version = '1.14.1', installed_at = statement_timestamp()
        WHERE singleton AND version = '1.14.0';
    END IF;

    IF (SELECT count(*) FROM oracle.toll_route_point
        WHERE point_id IN (
            'i95:22329ND', 'i95:2232ND', 'i95:2232SO', 'i95:2233SO',
            'i95:2239ND', 'i95:223ND', 'i95:223SO', 'i95:2249ND',
            'i95:224ND', 'i95:224NO'
        )
          AND source_metadata->>'coordinate_quality' = 'approximate_interchange'
          AND source_metadata->'coordinate_source' = provenance) <> 10
       OR (SELECT direction FROM oracle.toll_route_point
           WHERE point_id = 'i95:22329ND') <> 'NB'
       OR NOT EXISTS (
           SELECT 1 FROM oracle.toll_route_point
           WHERE point_id = 'i95:2249ND'
             AND place_name = 'Arlington'
             AND region = 'Virginia'
             AND label = 'Washington D.C. from I-495 Southbound via I-395'
             AND aliases @> ARRAY['Washington D.C.']
       )
       OR (SELECT count(*) FROM oracle.toll_connection
           WHERE connection_id IN (
               'source:i95_shared:Southbound:180SO:22329ND',
               'source:i95_shared:Southbound:182SO:22329ND',
               'source:i95_shared:Southbound:183SO:22329ND',
               'source:i95_shared:Southbound:185SO:22329ND',
               'source:i95_shared:Southbound:186SO:22329ND',
               'source:i95_shared:Southbound:187SO:22329ND',
               'source:i95_shared:Southbound:188SO:22329ND'
           )
             AND source_metadata->'general_purpose_fallback'->>'i95_direction' = 'NB'
       ) <> 7 THEN
        RAISE EXCEPTION 'oracle 1.14.1 northern I-395 metadata did not install cleanly';
    END IF;
END
$migration$;

COMMIT;
