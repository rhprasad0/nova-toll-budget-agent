# Agent-readable I-95/I-495 current toll reports

- **Status:** Implemented
- **Scope:** Public current-price reports for routes priced only by the
  I-95/I-495 Express Lanes feed

## Purpose

TollChat will publish static reports that let search engines and general-purpose
AI agents retrieve the same current I-95/I-495 estimate that TollChat's
`get_current_toll_price` tool returns, without invoking the conversational
agent. A report answers this bounded question:

> For this directed I-95/I-495 Express Lanes route, what is TollChat's current
> two-axle E-ZPass toll estimate, where are its entry and exit, and when was its
> source observation recorded?

Each report is an as-of snapshot. It is not a guaranteed price, a future
forecast, or evidence that the lane will remain open.

## Goals

- Cover every public Oracle route whose priced components are exclusively on
  the I-95/I-495 Express Lanes facility.
- Publish the same success or unavailability result as
  `get_current_toll_price` for the fixed supported pricing profile.
- Identify both endpoints with canonical roadway labels, commonly recognized
  place names, direction, access role, aliases, and coordinates.
- Add that geographic context to the canonical Oracle schema and data through
  a versioned migration; the publisher must not maintain a separate place map.
- Refresh reports every 10 minutes, matching the I-95/I-495 feed cadence.
- Preserve the tool's observation time, 10-minute bin, provenance, recent
  movement, and prior-week comparison context.
- Serve accessible HTML and machine-readable JSON from the existing S3 and
  CloudFront site without invoking the conversational agent.
- Measure search-crawler requests, user-triggered agent requests, and AI
  referrals as
  separate signals without claiming downstream use or citation.

## Non-goals

- Publishing reports for I-66, Dulles Greenway, Dulles Toll Road, or
  mixed-facility routes.
- Publishing historical P25, P50, or P90 route estimates.
- Accepting a user-selected date or departure time.
- Predicting a future toll, lane direction, or lane availability.
- Providing navigation, travel time, untolled alternatives, or roadway
  geometry.
- Letting crawlers query RDS or invoke TollChat tools.
- Treating a crawler fetch as proof of a user, prompt, citation, or answer.
- Charging agents for access or returning machine-payment challenges.

## Route and pricing scope

The publisher enumerates routes from Oracle data. A route receives a report
only when:

1. its origin and destination are public route points;
2. its structurally supported pricing route contains at least one
   `facility: i95_i495` component; and
3. it contains no priced component from another facility.

Untolled handoffs and general-purpose gaps represented by the validated route
do not make a route mixed-facility. Unsupported origin-destination combinations
do not receive pages.

A report URL remains stable when the facility is closed, the requested
direction is unavailable, or current pricing data is missing or stale. In those
states the report publishes the same validated unavailability result as the
current-price tool and does not retain a numeric price as if it were current.

Oracle point IDs remain the stable machine identity, but they are not the
primary public description. Every report presents each endpoint using its
canonical roadway label and geographic context. Label or context corrections
do not change the underlying route identity or URL.

The initial release supports exactly the current-price tool's fixed profile:

```json
{
  "vehicle_class": "two_axle_passenger",
  "payment_method": "e_zpass",
  "transponder_mode": "toll"
}
```

Other vehicle, payment, or transponder profiles require a contract revision.

### Human-readable endpoint contract

Every origin and destination includes:

- `point_id`, used for stable matching rather than as the display name;
- `label`, the canonical roadway access label already used by TollChat;
- `place_name`, a curated commonly recognized locality such as `Dumfries` or
  `Tysons`;
- `region` and `country_code`;
- `aliases`, including alternate road and locality names such as `Route 286`,
  `Newington`, and `Tysons Corner`;
- `nearby_landmarks`, a separate list of recognizable places such as `Fort
  Belvoir` or `Ronald Reagan Washington National Airport`;
- `direction` and `role`, expanded for people as `northbound entry` or
  `northbound exit`; and
- a GeoJSON point with longitude and latitude.

The public `display_name` combines this context without pretending the route
starts at a town center. For example:

```text
Dumfries, Virginia — I-95 near Dumfries Road/Route 234 (northbound entry)
Tysons, Virginia — Westpark Drive (northbound exit)
```

Place names, aliases, and nearby landmarks are curated, versioned Oracle
metadata. Aliases are alternate names for the access point; nearby landmarks
provide orientation but do not resolve as that point. The publisher does not
call a runtime geocoder or infer locality names independently from coordinates.
A report is not published until both endpoints have complete human-readable
context.

### Required Oracle migration

This work includes `028_upgrade_oracle_1_12_1_to_1_13_0.sql` and the matching
Oracle 1.13.0 canonical bootstrap update. The migration adds these nullable
columns to `oracle.toll_route_point`:

Before migration 028 is authored, this worktree must be brought forward to the
repository revision containing migrations 026 and 027 and the Oracle 1.12.1
canonical bootstrap. The uninterrupted migration chain and clean baseline test
suite must be verified first; migration 028 must not skip or recreate a missing
predecessor.

| Column | Contract |
| --- | --- |
| `place_name` | Commonly recognized locality used in public route descriptions |
| `region` | Full first-level region name, such as `Virginia` |
| `country_code` | Uppercase ISO 3166-1 alpha-2 code, initially `US` |

The columns are nullable for facilities outside this release, but an all-or-none
constraint prevents partial geographic context. A second constraint requires
all public I-95 and I-495 report endpoints to have all three fields. Existing
`label`, `aliases`, `direction`, `point_type`, and `location` columns remain the
source of roadway, common-name, access-role, and coordinate context.

The migration must:

1. add the columns and constraints without replacing stable point IDs;
2. backfill every public I-95 and I-495 endpoint used by report enumeration;
3. add useful alternate road and locality names to the existing `aliases`
   array, plus separate nearby-landmark context;
4. update the bounded reporting operation to return the complete endpoint
   contract with each route;
5. preserve the existing prompt-point surface, which automatically benefits
   from the curated alias updates; and
6. advance `oracle.schema_version` from `1.12.1` to `1.13.0` only after all
   validation succeeds.

The forward migration must be reproducible from Oracle 1.12.1, and its result
must match the 1.13.0 canonical bootstrap. Before a PR is opened, the migration
must also be applied to the live `nova-toll-db` RDS database using the
`nova-toll` AWS profile, following the repository migration policy.

Migration contract tests cover complete I-95/I-495 context, nonempty strings,
uppercase country codes, preserved coordinates and IDs, alias uniqueness, the
Dumfries and Tysons examples, least-privilege reporting access, and migrated
schema parity. No publisher fallback file or runtime reverse-geocoding path is
allowed.

## Current-price parity contract

The JSON report wraps the exact domain result that
`get_current_toll_price` would serialize inside its successful Strands tool
response. It does not copy the transport-only `toolUseId`, `status`, progress
events, or safe operation-error envelope.

One shared current-price domain-result builder owns route-result assembly,
availability decisions, movement and comparison construction, rounding, and
serialization. It consumes normalized Oracle rows and an explicit evaluation
timestamp. The conversational tool and report publisher call that same builder;
they do not maintain parallel implementations. The tool remains responsible for
its Strands transport wrapper, while the publisher adds report metadata and
endpoint context around the shared domain result.

For the same route, pricing profile, evaluation time, and database snapshot,
the report and tool must agree on:

- route-validation status and reason;
- `method: latest_complete_current_facility_prices`;
- `maximum_observation_age_minutes: 30`;
- component order, route-step identity, price, and availability;
- observed versus `identity_proxy_v1` modeled provenance;
- 10-minute bin boundaries, source interval end, and observation time;
- recent movement over the current and two prior feed cycles;
- up to three same-weekday, same-bin prior-week comparisons;
- aggregate source kind; and
- the two-decimal route total.

The tool-parity payload keeps its origin and destination point IDs unchanged.
The report adds the endpoint metadata beside that payload so a person or agent
can map a natural-language request such as “Dumfries to Tysons Corner” to the
precise directed access points being priced.

A missing component is never converted to `$0`. A route price is available
only when every priced component is available. The total is the sum of the
current component prices, rounded to two decimal places using the current tool
contract.

The report preserves `source_status` in JSON. HTML follows TollChat's current
presentation rule: `NO_DETERMINATION` is non-material metadata for a successful
I-95/I-495 component and is not presented as a warning. Missing, stale,
facility-unavailable, and exceptional-schedule states remain material.

If the current-price tool contract changes, exhaustive covered-route and
availability-state parity tests must fail until the report schema and renderer
are deliberately updated. The report must not silently retain an older
interpretation of the tool result.

## Public resources

Each covered route has one HTML report and one JSON representation:

```text
/tolls/i95-i495/{origin-point-slug}/{destination-point-slug}/
/tolls/i95-i495/{origin-point-slug}/{destination-point-slug}/report.json
```

Point slugs are descriptive, deterministic combinations of place, up to two
distinct aliases, and direction. Text is normalized with Unicode NFKD, ASCII
transliteration, lowercase, and hyphens. If distinct point IDs produce the same
slug, the shortest deterministic point ID retains the descriptive slug and the
others receive their normalized point ID as a suffix. The complete point-ID-to-
slug map is frozen in the first successful manifest and reused, so later label
or context corrections do not move established URLs. A browsable I-95/I-495
route index links every report by human-readable place and roadway names, and
all indexable HTML reports appear in the sitemap.

### HTML contract

For an available route, the server-rendered page includes:

- a title and heading led by both place names, such as “Current I-95/I-495 toll
  from Dumfries to Tysons”;
- canonical roadway labels, direction, and entry or exit role for both
  endpoints;
- geographic aliases and enough locality context to disambiguate each place;
- the current estimated route total;
- the fixed vehicle, payment, and transponder profile;
- the Eastern evaluation time and visible "as of" language;
- the publication generation identifier;
- each priced component's price and observed or modeled provenance;
- each component's 10-minute bin and source observation time;
- recent movement when all three current-cycle samples are available;
- prior-week median, range, delta, and coverage when comparisons are available;
- material source, freshness, and modeling disclosures; and
- a link to the JSON representation.

For an unavailable route, the page shows the validated reason and relevant
timestamps but no current total. It may explain a tool-returned I-495-only
fallback, but it must not automatically substitute that fallback route or
price.

The useful report content must not require JavaScript, a cookie,
authentication, or a form submission.

### JSON contract

`report.json` contains publication metadata, human-readable route context, and
the current-price tool's domain result under `current_price`. A representative
successful report is:

```json
{
  "schema_version": "1.0.0",
  "generation_id": "2026-08-25T14:12:00Z",
  "published_at": "2026-08-25T14:12:00Z",
  "evaluated_at": "2026-08-25T14:12:00Z",
  "availability": "available",
  "facility": "i95_i495",
  "route": {
    "origin": {
      "point_id": "i95:218NO",
      "label": "I-95 Near Dumfries Road/Route 234",
      "place_name": "Dumfries",
      "region": "Virginia",
      "country_code": "US",
      "aliases": ["Dumfries Road", "Route 234"],
      "direction": "northbound",
      "role": "entry",
      "display_name": "Dumfries, Virginia — I-95 near Dumfries Road/Route 234 (northbound entry)",
      "location": {
        "type": "Point",
        "coordinates": [-77.32940018177031, 38.57367329785056]
      }
    },
    "destination": {
      "point_id": "i495:185ND",
      "label": "Westpark Drive",
      "place_name": "Tysons",
      "region": "Virginia",
      "country_code": "US",
      "aliases": ["Tysons Corner"],
      "direction": "northbound",
      "role": "exit",
      "display_name": "Tysons, Virginia — Westpark Drive (northbound exit)",
      "location": {
        "type": "Point",
        "coordinates": [-77.21660303306578, 38.91929165262628]
      }
    }
  },
  "current_price": {
    "origin_point_id": "i95:218NO",
    "destination_point_id": "i495:185ND",
    "method": "latest_complete_current_facility_prices",
    "evaluated_at": "2026-08-25T10:12:00-04:00",
    "maximum_observation_age_minutes": 30,
    "pricing_profile": {
      "vehicle_class": "two_axle_passenger",
      "payment_method": "e_zpass",
      "transponder_mode": "toll"
    },
    "source_kind": "observed",
    "components": [
      {
        "route_step_id": "step-1",
        "price_usd": "11.40",
        "source_kind": "observed",
        "pricing_method": "source_observation",
        "facility": "i95_i495",
        "component_evaluated_at": "2026-08-25T10:12:00-04:00",
        "bin_minutes": 10,
        "bin_start": "2026-08-25T10:00:00-04:00",
        "bin_end": "2026-08-25T10:10:00-04:00",
        "interval_end_at": "2026-08-25T10:09:00-04:00",
        "observed_at": "2026-08-25T10:09:05-04:00",
        "od_pair_id": 1234,
        "source_status": "NO_DETERMINATION",
        "recent_movement": {
          "method": "same_facility_leg_three_cycles",
          "direction": "rising",
          "samples": [
            {"cycle_offset": -2, "price_usd": "8.20"},
            {"cycle_offset": -1, "price_usd": "9.60"},
            {"cycle_offset": 0, "price_usd": "11.40"}
          ],
          "net_change_usd": "3.20",
          "net_change_percent": "39.0"
        },
        "prior_week_comparison": {
          "method": "same_weekday_same_facility_bins",
          "comparable_period_count": 3,
          "expected_comparable_period_count": 3,
          "comparable_prices": [
            {"week_offset": 3, "price_usd": "9.10"},
            {"week_offset": 2, "price_usd": "10.20"},
            {"week_offset": 1, "price_usd": "10.80"}
          ],
          "median_usd": "10.20",
          "minimum_usd": "9.10",
          "maximum_usd": "10.80",
          "current_delta_usd": "1.20",
          "current_delta_percent": "11.8",
          "position": "above_recent_range",
          "higher_than_count": 3
        }
      }
    ],
    "total_usd": "11.40"
  }
}
```

Optional tool fields are omitted when absent, matching the tool serializer.
Unavailable reports place the corresponding current-price unavailability
result under `current_price` instead of inventing a separate public error
vocabulary. HTML and JSON rendered during one publisher run receive the same
`generation_id`, but cross-object atomicity is not promised. A consumer that
fetches both representations compares their generation identifiers and uses or
refetches the newer object when they differ.

## Publication pipeline

The existing delivery architecture remains:

```text
I-95/I-495 fetch -> raw S3 object -> pricing loader -> report query
    -> publisher Lambda -> site S3 bucket -> CloudFront
```

The I-95/I-495 feed is fetched on 10-minute wall-clock boundaries. After a
successful database commit, the pricing loader emits a facility-scoped success
event containing the committed source watermark. That event invokes the report
publisher, which verifies the same watermark is visible before publishing a
numeric result. A delayed or retried load therefore cannot cause a new report
generation based on the previous feed cycle.

A separate 10-minute scheduled watchdog invokes the same idempotent publisher
without an expected watermark. It recovers missed success events and lets the
Oracle freshness rules publish `stale_observation` or another unavailable state
when a fetch or load fails. An unchanged source watermark and unchanged
availability result may be a no-op.

For each run, the publisher:

1. opens one read-only, repeatable-read database transaction;
2. records one evaluation timestamp and source watermark, and verifies an
   event-provided expected watermark when present;
3. reads one bulk result containing Oracle-owned endpoint context and every
   covered route and comparison row;
4. passes normalized rows through the shared current-price domain-result
   builder;
5. renders all HTML and JSON before changing public objects;
6. uploads complete route objects to the existing private site bucket; and
7. publishes the generation manifest and sitemap last.

The publisher must not issue a database query or invoke the Strands tool for
every page. It receives only `EXECUTE` on a bounded reporting operation and no
direct table access. Generated reports are runtime data, not
Terraform-managed S3 objects.

### Failure behavior

An individual S3 object is replaced only with a fully rendered object. The
publisher uploads a route's JSON before its HTML, but a failure or independent
CloudFront cache timing may expose siblings from different generations. That
condition is allowed, visible through `generation_id`, and covered by an
injected mid-upload failure test. A failure must never replace a valid object
with a partial document or error body. Every page visibly reports its own
evaluation and publication time.

An operational alarm fires when no complete publisher run has succeeded for 30
minutes. Old reports remain available as timestamped snapshots; consumers must
not describe them as current without considering their visible age.

### Caching

Report objects use validators (`ETag` and `Last-Modified`) and a CloudFront TTL
no longer than five minutes. Publication does not require per-object
invalidations.

### Edge routing

The publisher stores canonical HTML at the S3 key corresponding to
`/tolls/i95-i495/{origin-point-slug}/{destination-point-slug}/index.html`.
CloudFront's distribution-level `default_root_object` handles only the site
root, so it does not map a nested trailing-slash report URL to that object.

A small CloudFront Function associated with the default static cache behavior
appends `index.html` only when a `/tolls/` request URI ends in `/`. It leaves
`report.json`, `/robots.txt`, sitemap resources, assets, and `/api/*` unchanged.
This preserves the human-facing canonical URL while allowing the existing
private S3 REST origin to retrieve the real object. AWS publishes this exact
trailing-slash rewrite pattern for CloudFront Functions.
[CloudFront Functions URL rewrite example](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/example_cloudfront_functions_url_rewrite_single_page_apps_section.html)

Lambda@Edge is not required for this deterministic rewrite. The function has a
direct unit test covering a report directory, `report.json`, `/robots.txt`, and
an `/api/*` request.

## Agent discovery and retrieval

Public web resources are the cross-vendor interface. The initial release does
not require an installed connector, vendor-specific API, or remote MCP server.
Those integrations can provide stronger guarantees only after a user or
administrator explicitly connects them; they do not make an unconfigured
consumer assistant discover TollChat automatically.

### TollChat indexing configuration

CloudFront has no separate indexing switch. The deployed site currently returns
`403 AccessDenied` for `https://tollchat.ai/robots.txt` because the object is
absent from the private S3 origin. This release adds a Terraform-managed
`robots.txt` root object to the existing site bucket and serves it through the
default static CloudFront behavior. The bucket remains private and CloudFront
continues to read it through origin access control.

Cloudflare supplies DNS for `tollchat.ai`, but both public records have
`proxied = false`; requests go directly to CloudFront. Cloudflare AI crawler
controls therefore do not affect this site. Any edge-level agent block would
come from the associated AWS WAF web ACL or a future CloudFront policy.

The infrastructure change must:

- return `200` for `GET` and `HEAD` requests to `/robots.txt` on both
  `tollchat.ai` and `www.tollchat.ai`, with `Content-Type: text/plain`;
- publish the crawler policy below and the canonical apex-domain sitemap URL;
- return `200` for the route index, canonical HTML reports, JSON siblings, and
  sitemap without authentication or a WAF challenge;
- ensure canonical report HTML has neither a `noindex` robots meta directive
  nor an `X-Robots-Tag: noindex` response header; and
- keep the existing private-origin and `/api/*` protections unchanged.

No new CloudFront response-headers policy is required because the deployed
distribution does not currently add `X-Robots-Tag`. If a policy later adds that
header globally, the report cache behavior must remove or override it. AWS
documents that origin access control permits CloudFront to read a private S3
origin and that response-headers policies modify both cached and origin
responses.
[CloudFront private S3 origins](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html)
[CloudFront response-headers policies](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/modifying-response-headers.html)

### AWS service choices

The initial release uses native AWS services only where they remove custom
code or satisfy an explicit requirement:

- CloudFront Functions maps canonical nested report URLs to S3 object keys;
- AWS WAF Bot Control and its AI Activity Dashboard classify agent traffic;
- filtered WAF logs land in an encrypted S3 prefix;
- S3 lifecycle rules enforce the seven-day raw-log retention; and
- Athena deduplicates and aggregates WAF records for the daily report.

Bot Control incurs managed-rule charges, so its scope-down statement covers
only `/tolls/`. The release does not add Lambda@Edge, CloudFront real-time logs,
Kinesis Data Streams or Firehose, OpenSearch, QuickSight, a Glue crawler,
CloudWatch Synthetics, Security Lake, or AI traffic monetization. Static schema,
daily latency, deployment checks, and the existing monitoring stack cover the
requirements without them.
[CloudFront bot visibility and Bot Control](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/WAF-one-click.html)

Each HTML report must return `200`, contain the complete answer as visible
server-rendered text, declare one absolute apex-domain canonical URL, and link
its JSON sibling with:

```html
<link rel="canonical" href="https://tollchat.ai/tolls/i95-i495/{origin-point-slug}/{destination-point-slug}/">
<link rel="alternate" type="application/json" href="report.json">
```

The route index links reports by place name, alias, roadway label, and
direction. The XML sitemap lists only canonical HTML URLs and sets `lastmod` to
the actual report publication time. `changefreq` is only a hint and is not a
promise that any vendor will recrawl a report every 10 minutes.

Google's current guidance says ordinary Search eligibility, crawlable text,
internal links, and accurate visible content are sufficient for its AI
features; there is no special AI schema or `llms.txt` requirement. TollChat
therefore does not add `llms.txt` in the initial release. Any JSON-LD must match
visible HTML and must not represent a toll estimate as a merchant `Offer`.
[Google AI feature guidance](https://developers.google.com/search/docs/appearance/ai-features)
[Google generative-AI optimization guidance](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide)

### Crawler policy

`robots.txt` explicitly permits the report path for the search and
user-triggered agents TollChat intends to serve:

```text
User-agent: OAI-SearchBot
Allow: /tolls/

User-agent: ChatGPT-User
Allow: /tolls/

User-agent: Claude-SearchBot
Allow: /tolls/

User-agent: Claude-User
Allow: /tolls/

User-agent: Googlebot
Allow: /tolls/

User-agent: Google-Extended
Allow: /tolls/

User-agent: Google-Agent
Allow: /tolls/

User-agent: PerplexityBot
Allow: /tolls/

User-agent: Perplexity-User
Allow: /tolls/

User-agent: bingbot
Allow: /tolls/

User-agent: Amzn-SearchBot
Allow: /tolls/

User-agent: Amzn-User
Allow: /tolls/

User-agent: Applebot
Allow: /tolls/

User-agent: DuckAssistBot
Allow: /tolls/

Sitemap: https://tollchat.ai/sitemap.xml
```

OpenAI separates search discovery (`OAI-SearchBot`) from user-triggered page
retrieval (`ChatGPT-User`). Anthropic likewise separates
`Claude-SearchBot` from `Claude-User`. Google uses Googlebot for Search and its
AI features, `Google-Extended` as a robots product token affecting Gemini
grounding and training, and `Google-Agent` for user-triggered agent navigation.
`Google-Extended` has no distinct HTTP user-agent and therefore cannot be
counted separately in access logs.
[OpenAI crawler documentation](https://developers.openai.com/api/docs/bots)
[Anthropic crawler documentation](https://support.anthropic.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler)
[Google crawler documentation](https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers)
[Google user-triggered fetchers](https://developers.google.com/crawling/docs/crawlers-fetchers/google-user-triggered-fetchers)

The same public interface also supports other documented assistant families.
The initial version-controlled agent registry is:

| Family | Search or answer crawler | User-triggered fetcher | Training or policy-only identity |
| --- | --- | --- | --- |
| OpenAI | `OAI-SearchBot` | `ChatGPT-User` | `GPTBot` |
| Google | `Googlebot` | `Google-Agent` | `Google-Extended` policy token |
| Anthropic | `Claude-SearchBot` | `Claude-User` | `ClaudeBot` |
| Perplexity | `PerplexityBot` | `Perplexity-User` | none documented |
| Microsoft | `bingbot` | none documented | none documented |
| Amazon | `Amzn-SearchBot` | `Amzn-User` | `Amazonbot` |
| Apple | `Applebot` | none documented | `Applebot-Extended` policy token |
| DuckDuckGo | `DuckAssistBot` | none documented | none documented |

Perplexity and Amazon document distinct user-triggered fetchers and publish
separate network ranges. Bingbot supplies the Bing index used by Microsoft
Copilot experiences, but its requests are search crawls; without a distinct
documented Copilot fetcher, TollChat does not report them as Copilot user
requests. Applebot supplies search experiences including Siri, while
`Applebot-Extended` controls model use and does not itself fetch pages.
DuckAssistBot retrieves sources for AI-assisted answers, but is classified as
an answer crawler rather than a user-triggered fetcher because DuckDuckGo does
not document each request as user initiated.
[Perplexity crawler documentation](https://docs.perplexity.ai/docs/resources/perplexity-crawlers)
[Microsoft Copilot public-web guidance](https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/generative-ai-public-websites)
[Amazon crawler documentation](https://developer.amazon.com/en/amazonbot)
[Applebot documentation](https://support.apple.com/en-us/119829)
[DuckAssistBot documentation](https://duckduckgo.com/duckduckgo-help-pages/results/duckassistbot)

Training crawlers and policy tokens such as `GPTBot`, `ClaudeBot`, `Amazonbot`,
`Google-Extended`, and `Applebot-Extended` are a separate policy choice. They
are not required for current report retrieval and are never counted as report
usage. Policy-only tokens do not create separately measurable requests.

Search indexing does not guarantee 10-minute freshness. A search result may
contain an older snapshot; a user-triggered fetch can retrieve the current
static object. Every representation therefore leads with `evaluated_at`,
`published_at`, source observation time, and availability so an agent can
qualify the answer it actually retrieved.

## Agent usage measurement

AWS WAF Bot Control is the primary agent classifier. TollChat adds the
`AWSManagedRulesBotControlRuleSet` common inspection level, explicitly pins a
WBA-capable static version, and scopes evaluation to `/tolls/`. Every managed
rule action is initially overridden to `Count`, so classification cannot block,
challenge, CAPTCHA, rate-limit, or monetize a report request.

The Bot Control rule runs before the existing terminating `allow-static-site`
rule. Placing it afterward would make report traffic invisible to Bot Control.
The remaining static-site and `/api/*` security behavior stays unchanged.

AWS WAF's AI Activity Dashboard supplies broad discovery of more than 650 bot
and agent identities, categories, organizations, and verification states. Web
Bot Authentication adds cryptographic verification for participating agents;
AWS's existing verified-bot signal remains useful for agents that do not sign
requests. These native labels replace routine maintenance of vendor IP lists,
while the smaller registry above still maps documented agent names to
search-crawler, user-triggered, or training intent.
[AWS WAF AI Activity Dashboard](https://aws.amazon.com/about-aws/whats-new/2026/02/aws-waf-ai-activity-dashboard/)
[AWS WAF Bot Control and Web Bot Authentication](https://docs.aws.amazon.com/waf/latest/developerguide/waf-bot-control.html)
[AWS WAF Bot Control labels](https://docs.aws.amazon.com/waf/latest/developerguide/aws-managed-rule-groups-bot.html)

The Bot Control rule alone enables request sampling so the native dashboard can
populate. Web ACL data protection substitutes cookie values, authorization
headers, query strings, and referrers in both samples and full logs before AWS
stores them. Small non-terminating rules label recognized assistant referrer
families before substitution; the aggregate never needs the original URL.

TollChat enables AWS WAF logging to a dedicated encrypted S3 prefix. A
non-terminating rule labels `/tolls/` requests, and the logging filter retains
only records with that label. Logging redacts cookies, authorization headers,
query strings, and referrers; it retains the request ID, time, method, host, URI
path, user-agent, assistant-referrer family, WAF action, and Bot Control labels
needed for the metrics below. No raw `/api/*` or other site traffic is stored
for this feature.

CloudFront standard logging remains disabled because it is distribution-wide
and would also collect metadata for human chat requests. The initial metric is
therefore an allowed `agent_report_request`, not proof that the S3 origin
returned `200`. Deployed crawlability checks separately verify that every
published report resource returns `200`. Cache-behavior-scoped CloudFront
real-time logging may be considered later only if exact response-status
attribution becomes necessary.
[AWS WAF log fields](https://docs.aws.amazon.com/waf/latest/developerguide/logging-fields.html)

Only allowed `GET` requests to canonical report HTML or `report.json` count.
`HEAD`, `robots.txt`, sitemaps, assets, publisher requests, and `/api/*` traffic
do not. HTML and JSON requests remain separate so fetching both is not presented
as two users.

### Metric taxonomy

| Metric | Examples | What it supports | What it does not prove |
| --- | --- | --- | --- |
| `search_crawler_requests` | `OAI-SearchBot`, `Claude-SearchBot`, Googlebot, `PerplexityBot`, bingbot, `Amzn-SearchBot`, Applebot, `DuckAssistBot` | A search or answer crawler requested a report | The origin returned it or a person asked about the route |
| `user_triggered_agent_requests` | `ChatGPT-User`, `Claude-User`, `Google-Agent`, `Perplexity-User`, `Amzn-User` | A vendor says the request was user-triggered | The origin returned, cited, or showed the report |
| `ai_referral_visits` | Browser request with a recognized assistant referrer | A person clicked through from an identifiable assistant surface | All AI referrals; referrers may be absent |
| `training_crawler_requests` | `GPTBot`, `ClaudeBot`, `Amazonbot` | Operational crawler volume only | Product usage; excluded from usage totals |
| `unknown_agent_requests` | Known agent user agent without verified network identity | Declared automated interest | Vendor identity or user intent |

No combined “AI users” number is published. The primary adoption metric is
`verified_user_triggered_agent_requests`; search crawls and human referral
visits are reported beside it, not added to it. A request records an allowed
attempt to retrieve one report, not a confirmed response, unique person,
prompt, citation, or completed answer.

### Identity confidence

Every registry entry records vendor family, exact case-insensitive user-agent
token, agent mode, and official documentation URL. Every classified request
has `identity_confidence: declared|aws_verified|wba_verified`:

- `declared` means only a documented user-agent token matched;
- `aws_verified` requires the AWS WAF `bot:verified` label; and
- `wba_verified` requires a valid `bot:web_bot_auth:verified` signature label.

Invalid, expired, or unknown Web Bot Authentication signatures are never
promoted. A new semantic registry entry is added only from vendor
documentation, but Bot Control can still report newly recognized agents under
their AWS name, organization, and category as `other_ai_agent`. Heuristic names
without an AWS verification label remain `unknown_agent_requests`.

### Storage and reporting

Raw filtered WAF logs are encrypted, access-restricted, and retained for seven
days for classification retries. They contain viewer IPs and therefore are not
public usage data. A daily rollup stores only:

- UTC date and published-generation age, qualified by the five-minute
  CloudFront cache uncertainty;
- route identity and HTML or JSON representation;
- AWS bot name, organization, category, vendor family, and agent mode;
- declared, AWS-verified, or WBA-verified confidence;
- WAF action; and
- request count.

The rollup contains no raw IP, full user agent, referrer URL, cookie, query
string, or user identifier. The privacy notice must disclose the temporary
access-log retention before logging is enabled.

An idempotent Athena rollup recomputes the current and previous two UTC days,
deduplicates by WAF request ID, and publishes a date only after its unique run
has completed. Raw logs and Athena result objects expire after seven days;
privacy-safe aggregates remain internal. Metrics are labeled best-effort lower
bounds because log delivery can be late or incomplete. Delivered WAF log volume
is compared with the WAF request metric to expose material coverage gaps. The
native AI Activity Dashboard supplies the 14-day visual view and saved Athena
queries provide durable route/day history. The existing public `usage.json`
is not extended until the classifier has been validated against real traffic.
If agent metrics are later published, they retain the taxonomy above instead
of collapsing crawls, user-triggered retrievals, and referral visits into one
flattering but meaningless number.

Google Search Console is a separate vendor-reported source. Where its
Generative AI performance report is available, TollChat records Google AI
impressions and clicks independently; Googlebot access-log hits are not used as
a substitute for those metrics.
[Google Search generative AI controls and reporting](https://support.google.com/webmasters/answer/16908024)

## Data-quality and safety requirements

- Every route, component, price, comparison, and timestamp comes from one
  repeatable-read generation snapshot.
- Endpoint labels, place names, aliases, access roles, directions, and
  coordinates come from versioned Oracle metadata rather than publisher
  guesses or runtime geocoding.
- The public report contains no raw source payload, database locator,
  credential, or user data.
- Modeled components retain `identity_proxy_v1` provenance and are not
  presented as direct observations.
- A missing or stale price never becomes `$0`.
- A route direction mismatch never falls back to the reverse route.
- HTML escapes labels and aliases originating in source data.
- JSON uses a fixed schema and the correct content type.

## Implementation tasking

Work proceeds in this dependency order. Each task leaves its smallest relevant
runnable checks passing before the next task begins.

### 0. Establish the repository baseline

- Bring the worktree forward to current `main` without losing this document.
- Confirm migrations 026 and 027 are present, the canonical Oracle version is
  1.12.1, and the existing test suite is green.
- Recheck the live deployed schema version read-only before authoring migration
  028.

Exit: the branch has an uninterrupted, tested 1.12.1 migration baseline.

### 1. Share the current-price domain result

- Characterize the current tool's success and unavailability behavior with
  focused tests before refactoring it.
- Extract one domain-result builder from `get_current_toll_price`; give it
  normalized Oracle rows and an explicit evaluation timestamp.
- Keep the Strands tool input and transport envelope unchanged.
- Add exhaustive parity tests across every covered route plus missing, stale,
  closed, exceptional-schedule, modeled, and direction-mismatch states.

Exit: the existing tool uses the shared builder and its public behavior is
unchanged.

### 2. Upgrade Oracle and add the bounded report read

- Add migration 028, the 1.13.0 canonical bootstrap changes, geographic
  backfill, constraints, and aliases.
- Add the bounded reporting operation that returns complete endpoint context
  and normalized pricing inputs for all eligible I-95/I-495 routes in one
  repeatable-read snapshot.
- Grant the publisher role only `EXECUTE` on that operation.
- Apply 028 from 1.12.1 in a disposable database and verify canonical-bootstrap
  parity.

Exit: migration and reporting-operation contract tests pass without a
publisher-side place map.

### 3. Build event-driven publication

- Emit an I-95/I-495 load-success event only after the loader transaction
  commits, including the committed source watermark.
- Add the publisher Lambda, expected-watermark check, side-effect-safe duplicate
  handling, and bounded bulk read through the shared result builder.
- Add the 10-minute watchdog trigger and the 30-minute no-success alarm.
- Test delayed loads, duplicate events, missing events, failed loads, and stale
  transitions.

At this stage, duplicate deliveries may receive distinct snapshot-specific run
identifiers because the publisher has no public side effects or durable
checkpoint yet.

Exit: every committed feed cycle builds its matching validated generation,
while the watchdog builds or preserves honest unavailable states.

### 4. Render and publish public resources

- Render accessible route HTML, `report.json`, the route index, manifest, and
  sitemap from one in-memory generation.
- Make the manifest's canonical public-result fingerprint the durable,
  best-effort idempotency checkpoint for both load events and the watchdog.
  Exclude generation, publication, and evaluation metadata from the fingerprint.
  A same-watermark correction that changes no public result is a no-op.
- Reject publication older than the completed manifest. The source watermark
  validates event ordering but is not the deduplication key.
- Upload all JSON before HTML, then publish the route index and sitemap, and
  publish the manifest last.
- Add object-level failure tests, including failure between JSON and HTML, and
  require visible generation and freshness metadata. Cover retried deliveries
  with later snapshot timestamps, same-watermark corrections, delayed events,
  and unchanged watchdog results.
- Verify complete geographic labels and tool-parity disclosures in both
  available and unavailable pages.

Exit: all eligible routes render deterministically and mixed sibling
generations are detectable rather than corrupt.

### 5. Open and canonicalize the CloudFront surface

- Add the tested CloudFront Function for nested `/tolls/` `index.html` rewrites.
- Add the Terraform-managed `robots.txt`, crawler rules, absolute apex
  canonical links, sitemap exposure, report cache settings, and content types.
- Verify apex and `www` behavior, JavaScript-free rendering, no `noindex`, and
  successful retrieval with representative agent user agents.

Exit: the public surface is crawlable, canonical, and still isolated from
`/api/*`.

### 6. Add privacy-scoped agent measurement

- Keep the Terraform-managed Cloudflare apex and `www` records DNS-only and
  verify the deployed drift posture so AWS WAF sees direct viewer traffic.
- Add the pinned Bot Control common rule in Count mode before
  `allow-static-site`, scoped to `/tolls/`.
- Add scoped request sampling with Web ACL data protection, the `/tolls/` WAF
  label, filtered and redacted WAF logging, encrypted S3 destination, seven-day
  raw and query-result lifecycles, and least-privilege access.
- Add the idempotent Athena rollup with two-day replay, request-ID
  deduplication, completion checkpoints, confidence taxonomy, native dashboard,
  saved internal queries, coverage alarm, and no public `usage.json` change.
- Update the privacy notice before enabling logging.

Exit: agent requests are visible as best-effort lower bounds without collecting
raw human chat/API traffic for this feature.

### 7. Complete deployment evidence

- Run the full application, infrastructure, migration, parity, rendering,
  crawler, privacy, and failure-injection checks.
- Apply every pending migration to live `nova-toll-db` in dependency order with
  the `nova-toll` profile and verify deployed versions match the branch.
- Curate only passing evaluation evidence, update the results index, and run
  gitleaks.
- Prepare a review-ready commit; push or open the PR only with user
  authorization.

Exit: repository and live migration requirements are satisfied and the change
is ready for review.

## Acceptance criteria

The initial release is complete when:

1. the branch contains the complete migration chain through 027 before
   migration 028 advances Oracle from 1.12.1 to 1.13.0, passes disposable and
   canonical-bootstrap parity checks, and is successfully applied to live RDS;
2. every public I-95/I-495 report endpoint has complete Oracle-owned place,
   region, country, alias, direction, role, label, and coordinate context;
3. only routes priced exclusively by I-95/I-495 receive report URLs;
4. every covered route has one stable trailing-slash HTML URL with an absolute
   apex-domain canonical link and a matching JSON URL, both led by
   human-readable endpoint labels and geographic context, and the CloudFront
   Function maps the HTML URL to its nested S3 `index.html` key;
5. every committed I-95/I-495 feed cycle triggers publication of its verified
   source watermark, and the 10-minute watchdog publishes stale or unavailable
   transitions and recovers missed events;
6. the tool and publisher use one shared domain-result builder, and exhaustive
   covered-route and availability-state results match at the same evaluation
   time and database snapshot;
7. available totals, component order, provenance, timestamps, movement, and
   prior-week comparisons match the tool contract;
8. missing, stale, closed, and exceptional-schedule states publish the same
   unavailability result as the tool and expose no current total;
9. modeled prices are visibly disclosed in HTML and preserved in JSON;
10. publishing performs one bounded bulk database read and never invokes the
   conversational agent per route;
11. pages remain useful with JavaScript disabled;
12. Terraform publishes `/robots.txt` through the existing private S3 and
    CloudFront path, and deployed checks confirm that it returns `200` on both
    hostnames with the policy and sitemap URL above;
13. canonical report HTML returns `200` without a `noindex` meta directive or
    response header, and the route index, sitemap, and crawler policy expose the
    reports to every discovery and retrieval agent in the initial registry;
14. a pinned WBA-capable Bot Control common rule evaluates only `/tolls/` in
    Count mode before the terminating static-site allow rule;
15. filtered, redacted WAF logs contain only labeled `/tolls/` traffic for this
    feature and distinguish report HTML and JSON requests from assets, sitemaps,
    and publisher traffic without collecting `/api/*` traffic;
16. daily metrics separate search crawls, verified user-triggered requests,
    AI referrals, training crawls, and unverified agent requests by vendor
    family without labeling any of them unique users; and
17. raw-log retention, privacy disclosure, identity verification, two-day
    replay, request-ID deduplication, lower-bound qualification, and the
    privacy-preserving daily rollup satisfy the storage contract above.

For the Dumfries-to-Tysons acceptance example, an agent must be able to find
the report using either `Dumfries` or `Tysons Corner`, then state the exact
directed entry and exit that the published price covers without exposing point
IDs as the answer.

## Deferred decisions

- Whether demand justifies reports for another toll facility.
- Which additional vendors merit registry entries after they publish stable
  user-agent and identity documentation.
- Whether future demand justifies AWS WAF blocking, rate limits, or AI traffic
  monetization; the public-report release uses Count and Allow only.
- Whether high-volume routes need richer explanatory summaries.

These decisions do not block the I-95/I-495 current-price report release.
