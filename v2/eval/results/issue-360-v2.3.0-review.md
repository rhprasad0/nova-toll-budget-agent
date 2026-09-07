# Issue 360: v2.3.0 public review evidence

Dataset 2.3.0 is a metadata-only release of the 250-case public v2 corpus.
The format remains 2.0.0, membership remains
`135021bff4e1ab1fac289a46f734f81dba7b95d452344383c19f3d4dc1dfccbe`, and the
public dataset SHA-256 is
`6fd9a3944407f1f39a803d8bf8498d032f22891643c4ffca0857d2e259ede49d`.

## Review status coverage

- 60 public cases are `human_reviewed`: the fixed 30-case pilot plus the
  disjoint 30-case balanced selection.
- 190 public cases are `synthetic_unreviewed`.
- The parent-controlled private manifest has 50 `synthetic_unreviewed` cases.

These are review-coverage labels, not model outcomes or release gates.
No rows, fixtures, prompts, application behavior, or oracle data changed.

## Returned v2 packets

Both packets were validated with the immutable 2.2.0 public manifest that
produced them, the explicit retained public root, and the trusted rate card.
They were not rerun or rebound to the 2.3.0 manifest.

- Balanced: 30 cards, 21 `Pass`, 9 `Fail`.
- Follow-up: 3 cards, all `Pass`.
- Public manifest binding: `c08cdce610b4b42ca8acbec63db2074e8d72cefc631ccfb95924e4a53b9cb02a`.
- Dataset binding: `6d0bfbe3950dfb07614488b44545eeee8c25109a4d950bdbebb3f63fd1a4b333`.
- Evidence binding: `917db5b5187ed721b3cb9291185949bc7c1e417e9ac51f223419c5e336a12e09`.

The historical v1 record remains separate: 30 decisions with 26 `Pass`, 1
`Fail`, and 3 `Unsure`. The source download is unavailable; the retained
Slice 2A validation record preserves its original bindings and decisions.

## Public Fail findings

The nine balanced findings and one historical v1 finding are human review
notes. They are deferred observations, not authorizations to change the
oracle, corpus, fixtures, application, or release gates.

1. `topology-proof-dca-to-i95-north-current` — appears to be an Oracle issue;
   northbound I-95 should have yielded a valid trip.
2. `topology-proof-dca-to-i95-north-annual` — do not offer to price two
   separate trips.
3. `topology-proof-dca-to-i95-south-current` — clarification is not useful
   because users will not know `181`/`1819`.
4. `topology-proof-dca-to-i95-south-annual` — reject for now; future
   implementation may change this.
5. `pentagon-eads-to-westpark` — no response.
6. `springfield-franconia-to-westpark` — legs need labels.
7. `dulles-to-reagan-current-price` — incomplete answer.
8. `leesburg-route-28-schedule-inputs` — no note supplied.
9. `dulles-to-reagan-annual-unavailable` — should be valid, oracle needs a
   later fix.
10. `topology-probe-dca-to-iad-current` — possible DCA/Pentagon-Eads/I-95
    oracle coverage gap; a missing direct edge does not prove every whole
    journey is prohibited.

The tenth finding is retained from the historical v1 review. All ten remain
deferred human observations; no route, state, or pricing behavior was changed.
