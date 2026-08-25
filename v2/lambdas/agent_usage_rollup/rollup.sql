INSERT INTO agent_report_rollups
WITH raw AS (
    SELECT
        from_unixtime(timestamp / 1000.0) AS requested_at,
        httprequest.requestid AS request_id,
        httprequest.uri AS uri,
        action AS waf_action,
        labels,
        lower(coalesce(element_at(
            transform(
                filter(httprequest.headers, header -> lower(header.name) = 'user-agent'),
                header -> header.value
            ),
            1
        ), '')) AS user_agent,
        row_number() OVER (
            PARTITION BY httprequest.requestid
            ORDER BY timestamp DESC
        ) AS request_rank
    FROM agent_report_waf_logs
    WHERE log_date = replace('{report_date}', '-', '/')
      AND httprequest.httpmethod = 'GET'
      AND action = 'ALLOW'
      AND (
          regexp_like(httprequest.uri, '^/tolls/i95-i495/[^/]+/[^/]+/$')
          OR regexp_like(httprequest.uri, '^/tolls/i95-i495/[^/]+/[^/]+/report[.]json$')
      )
), registry_matches AS (
    SELECT
        raw.*,
        registry.vendor_family AS declared_vendor_family,
        registry.agent_mode,
        row_number() OVER (
            PARTITION BY raw.request_id
            ORDER BY length(registry.user_agent_token) DESC NULLS LAST
        ) AS registry_rank
    FROM raw
    LEFT JOIN agent_registry registry
      ON raw.user_agent LIKE concat('%', lower(registry.user_agent_token), '%')
    WHERE raw.request_rank = 1
), identified AS (
    SELECT
        registry_matches.*,
        regexp_extract(uri, '^/tolls/i95-i495/([^/]+)/', 1) AS origin_slug,
        regexp_extract(uri, '^/tolls/i95-i495/[^/]+/([^/]+)/', 1) AS destination_slug,
        CASE WHEN uri LIKE '%/report.json' THEN 'json' ELSE 'html' END AS representation,
        regexp_extract(
            array_join(transform(labels, label -> label.name), ','),
            'bot:name:([^,]+)',
            1
        ) AS aws_bot_name,
        regexp_extract(
            array_join(transform(labels, label -> label.name), ','),
            'bot:organization:([^,]+)',
            1
        ) AS aws_organization,
        regexp_extract(
            array_join(transform(labels, label -> label.name), ','),
            'bot:category:([^,]+)',
            1
        ) AS aws_category
    FROM registry_matches
    WHERE registry_rank = 1
), mapped AS (
    SELECT
        identified.*,
        nullif(regexp_extract(
            array_join(transform(labels, label -> label.name), ','),
            'assistant-referrer-([^,]+)',
            1
        ), '') AS referrer_vendor_family,
        CASE
            WHEN aws_organization IN (
                'amazon', 'anthropic', 'apple', 'duckduckgo', 'google',
                'microsoft', 'openai', 'perplexity'
            ) THEN aws_organization
            WHEN aws_bot_name IN ('chatgpt', 'chatgpt_user', 'gptbot', 'oai_searchbot') THEN 'openai'
            WHEN aws_bot_name IN ('anthropic', 'claude_searchbot', 'claude_user', 'claude_web', 'claudebot') THEN 'anthropic'
            WHEN aws_bot_name IN ('perplexitybot', 'perplexity_user') THEN 'perplexity'
            WHEN aws_bot_name IN ('bingbot', 'copilot') THEN 'microsoft'
            WHEN aws_bot_name IN ('gemini_deep_research', 'google_common_crawler', 'googlebot') THEN 'google'
            WHEN aws_bot_name IN ('amazonbot', 'amzn_searchbot', 'amzn_user', 'bedrockbot') THEN 'amazon'
            WHEN aws_bot_name IN ('applebot', 'applebot_extended') THEN 'apple'
            WHEN aws_bot_name = 'duckassistbot' THEN 'duckduckgo'
            ELSE NULL
        END AS aws_vendor_family
    FROM identified
), requests AS (
    SELECT
        mapped.*,
        CASE
            WHEN agent_mode IS NOT NULL THEN agent_mode
            WHEN referrer_vendor_family IS NOT NULL THEN 'ai_referral'
            WHEN any_match(labels, label -> label.name LIKE '%:bot:category:ai') THEN 'unknown_agent'
            ELSE 'unclassified'
        END AS traffic_class,
        CASE
            WHEN any_match(labels, label -> label.name LIKE '%:bot:web_bot_auth:verified')
                 AND aws_vendor_family IS NOT NULL
                 AND (declared_vendor_family IS NULL OR aws_vendor_family = declared_vendor_family)
                THEN 'wba_verified'
            WHEN any_match(labels, label -> label.name LIKE '%:bot:verified')
                 AND aws_vendor_family IS NOT NULL
                 AND (declared_vendor_family IS NULL OR aws_vendor_family = declared_vendor_family)
                THEN 'aws_verified'
            WHEN agent_mode IS NOT NULL THEN 'declared'
            ELSE NULL
        END AS identity_confidence,
        CASE
            WHEN declared_vendor_family IS NOT NULL THEN declared_vendor_family
            WHEN aws_vendor_family IS NOT NULL
                 AND (
                     any_match(labels, label -> label.name LIKE '%:bot:web_bot_auth:verified')
                     OR any_match(labels, label -> label.name LIKE '%:bot:verified')
                 ) THEN aws_vendor_family
            WHEN referrer_vendor_family IS NOT NULL THEN referrer_vendor_family
            ELSE 'unknown'
        END AS vendor_family
    FROM mapped
), with_generation AS (
    SELECT
        requests.*,
        marker.generation_id,
        marker.published_at,
        row_number() OVER (
            PARTITION BY requests.request_id
            ORDER BY from_iso8601_timestamp(marker.published_at) DESC NULLS LAST
        ) AS generation_rank
    FROM requests
    JOIN agent_report_generations marker
      ON from_iso8601_timestamp(marker.published_at) <= requests.requested_at
     AND contains(
         marker.route_keys,
         concat('tolls/i95-i495/', requests.origin_slug, '/', requests.destination_slug)
     )
)
SELECT
    min(requested_at) AS first_requested_at,
    max(requested_at) AS last_requested_at,
    count(*) AS request_count,
    date_diff('second', from_iso8601_timestamp(published_at), min(requested_at)) AS published_generation_age_seconds,
    origin_slug,
    destination_slug,
    representation,
    traffic_class,
    vendor_family,
    identity_confidence,
    aws_bot_name,
    aws_organization,
    aws_category,
    waf_action,
    generation_id,
    published_at,
    DATE '{report_date}' AS report_date,
    '{run_id}' AS run_id
FROM with_generation
WHERE generation_rank = 1
GROUP BY
    origin_slug,
    destination_slug,
    representation,
    traffic_class,
    vendor_family,
    identity_confidence,
    aws_bot_name,
    aws_organization,
    aws_category,
    waf_action,
    generation_id,
    published_at
