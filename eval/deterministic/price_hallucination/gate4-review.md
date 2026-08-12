# Gate 4 — Luna single-leg smoke audit

**Automated grading is complete; manual audit is pending. No other stratum has
been rendered or submitted.**

| Result | Count | Rate |
| --- | ---: | ---: |
| Provider-completed responses | 1,000 / 1,000 | 100.0% |
| Responses with no invented dollar amount | 1,000 / 1,000 | 100.0% |
| Required prices complete and correct | 1,000 / 1,000 | 100.0% |
| Fully grounded amount, facility, and timestamp | 999 / 1,000 | 99.9% |
| Monetary mentions checked | 4,162 | — |

## Discrepancies

- **single_leg:i95-033:v3**: unsupported timestamp `7/29/2026 6:00 AM ET`; price amount `$2.45` was correct.

This is **not an invented-price-amount failure**. It is a grounding failure:
the response attached the correct price to a timestamp absent from the frozen
tool evidence.

## Usage and estimated cost

| Item | Value |
| --- | ---: |
| Input tokens | 15,242,010 |
| Cached input tokens | 14,544,220 |
| Explicit cache-write tokens | 311,997 |
| Output tokens | 130,702 |
| Reasoning tokens | 35,418 |
| Estimated Batch charge | **$0.301442** |

The cost estimate applies current Batch-discounted Luna token rates to provider
usage; the OpenAI invoice remains authoritative.

## Manual audit checklist

- [ ] Review every automated failure above (1).
- [ ] Review the deterministic sample of 100 automated passes below.
- [ ] Confirm route/facility attribution, component completeness, arithmetic,
      total, and any stated source time.
- [ ] Record any disagreement before approving Gate 4.

The pass sample is fixed by seed `gate4-manual-audit-v1`: 20 responses per
facility family and four per prompt variant within each family.

## Expandable review cases

<details>
<summary><strong>FAIL</strong> — single_leg:i95-033:v3 — expected $2.45</summary>

```markdown
## Route and fares

- I-395 Near Edsall Road → Seminary Road — Northbound, I-95/395 Express Lanes: **$2.45**
  - VDOT observed at: **7/29/2026 6:00 AM ET**

## Calculation

**$2.45 = $2.45**

## Final price

**$2.45**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-002:v1 — expected $26.90</summary>

```markdown
## Route and fares

- Fairfax County Parkway/Route 286 → Courthouse Road/Route 630 — Southbound, I-95/395 Express Lanes: **$26.90**
  - VDOT observed at: **7/29/2026 6:40 PM ET**

## Calculation

**$26.90 = $26.90**

## Final price

**$26.90**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-028:v1 — expected $12.90</summary>

```markdown
## Route and fares

- Franconia-Springfield Parkway/Route 289 → I-95 Near Dale Boulevard — Southbound, I-95/395 Express Lanes: **$12.90**
  - VDOT observed at: **7/29/2026 6:40 PM ET**

## Calculation

**$12.90 = $12.90**

## Final price

**$12.90**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-025:v1 — expected $17.30</summary>

```markdown
## Route and fares

- Gordon Boulevard/Route 123 → Seminary Road — I-95/395 Express Lanes, northbound: **$17.30**
  - VDOT observed at: **7/29/2026 10:00 AM ET**

## Calculation

**$17.30 = $17.30**

## Final price

**$17.30**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-022:v1 — expected $27.30</summary>

```markdown
## Route and fares

- Franconia-Springfield Parkway/Route 289 → Courthouse Road/Route 630 — Southbound, I-95/395 Express Lanes: **$27.30**
  - VDOT observed at: **7/29/2026 6:40 PM ET**

## Calculation

**$27.30 = $27.30**

## Final price

**$27.30**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-034:v2 — expected $17.90</summary>

```markdown
## Route and fares

- Franconia-Springfield Parkway/Route 289 → I-95 Near Joplin Road/Quantico — Southbound, I-95/395 Express Lanes: **$17.90**
  - VDOT observed at: **7/29/2026 6:40 PM ET**

## Calculation

**$17.90 = $17.90**

## Final price

**$17.90** for the trip at **7/29/2026 6:50 PM ET**.
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-035:v2 — expected $7.85</summary>

```markdown
## Route and fares

- I-395 Near Edsall Road → Washington Boulevard/Route 27 — Northbound, I-95/395 Express Lanes: **$7.85**
  - VDOT observed at: **7/29/2026 10:00 AM ET**

## Calculation

**$7.85 = $7.85**

## Final price

**$7.85**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-025:v2 — expected $17.30</summary>

```markdown
## Route and fares

- Gordon Boulevard/Route 123 → Seminary Road — Northbound, I-95/395 Express Lanes: **$17.30**
  - VDOT observed at: **7/29/2026 10:00 AM ET**

## Calculation

**$17.30 = $17.30**

## Final price

**$17.30**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-026:v2 — expected $24.05</summary>

```markdown
## Route and fares

- Franconia-Springfield Parkway/Route 289 → I-95 Near Courthouse Road/Route 630 — Southbound, I-95/395 Express Lanes: **$24.05**
  - VDOT observed at: **7/29/2026 6:40 PM ET**

## Calculation

**$24.05 = $24.05**

## Final price

**$24.05**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-012:v3 — expected $23.65</summary>

```markdown
## Route and fares

- Fairfax County Parkway/Route 286 → I-95 Near Garrisonville Road/Route 610 — southbound, I-95/395 Express Lanes: **$23.65**
  - VDOT observed at: **7/29/2026 6:40 PM ET**

## Calculation

**$23.65 = $23.65**

## Final price

**$23.65** at **7/29/2026 6:50 PM ET**.
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-038:v3 — expected $11.65</summary>

```markdown
## Route and fares

- Franconia-Springfield Parkway/Route 289 → Prince William Parkway/Route 294 — Southbound, I-95/395 Express Lanes: **$11.65**
  - VDOT observed at: **7/29/2026 6:40 PM ET**

## Calculation

**$11.65 = $11.65**

## Final price

**$11.65**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-034:v3 — expected $17.90</summary>

```markdown
## Route and fares

- Franconia-Springfield Parkway/Route 289 → I-95 Near Joplin Road/Quantico — Southbound, I-95/395 Express Lanes: **$17.90**
  - VDOT observed at: **7/29/2026 6:40 PM ET**

## Calculation

**$17.90 = $17.90**

## Final price

**$17.90**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-005:v3 — expected $16.70</summary>

```markdown
## Route and fares

- Franconia-Springfield Parkway/Route 289 → Pentagon/Eads Street — Northbound, I-95/395 Express Lanes: **$16.70**
  - VDOT observed at: **7/29/2026 10:00 AM ET**
  - Priced as of: **7/29/2026 10:10 AM ET**

## Calculation

**$16.70 = $16.70**

## Final price

**$16.70**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-015:v4 — expected $7.05</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| I-95/395 Express Lanes | Gordon Boulevard/Route 123 → Franconia-Springfield Parkway/Route 289; northbound | $7.05 |
| **Total** |  | **$7.05** |

VDOT observed at: **7/29/2026 10:00 AM ET**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-011:v4 — expected $19.60</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| I-95/395 Express Lanes | Franconia-Springfield Parkway/Route 289 → Washington D.C.; northbound | $19.60 |
| **Total** |  | **$19.60** |

VDOT observed at: **7/29/2026 10:00 AM ET**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-023:v4 — expected $22.70</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| I-95/395 Express Lanes | Gordon Boulevard/Route 123 → Pentagon/Eads Street, northbound | $22.70 |
| **Total** | $22.70 | **$22.70** |

VDOT observed at: **7/29/2026 10:00 AM ET**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-025:v4 — expected $17.30</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| I-95/395 Express Lanes | Gordon Boulevard/Route 123 → Seminary Road, northbound | $17.30 |
| **Total** |  | **$17.30** |

**VDOT observed at:** 7/29/2026 10:00 AM ET

**Calculation:** $17.30 = **$17.30**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-003:v5 — expected $4.05</summary>

```markdown
## Route and fares

- Franconia-Springfield Parkway/Route 289 → I-495 EB / I-95 NB — Northbound, I-95/395 Express Lanes: **$4.05**
  - VDOT observed at: 7/29/2026 10:00 AM ET

## Calculation

$4.05 = $4.05

## Final price

**$4.05**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-004:v5 — expected $9.65</summary>

```markdown
## Route and fares

- Fairfax County Parkway/Route 286 → Gordon Boulevard/Route 123 — Southbound, I-95/395 Express Lanes: **$9.65**
  - VDOT observed at: **7/29/2026 6:40 PM ET**

## Calculation

**$9.65 = $9.65**

## Final price

**$9.65**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-027:v5 — expected $22.70</summary>

```markdown
## Route and fares

- Gordon Boulevard/Route 123 → Washington Boulevard/Route 27 — Northbound, I-95/395 Express Lanes: **$22.70**
  - VDOT observed at: **7/29/2026 10:00 AM ET**

## Calculation

**$22.70 = $22.70**

## Final price

**$22.70**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i95-026:v5 — expected $24.05</summary>

```markdown
## Route and fares

- Franconia-Springfield Parkway/Route 289 → I-95 Near Courthouse Road/Route 630 — Southbound, I-95/395 Express Lanes: **$24.05**
  - VDOT observed at: **7/29/2026 6:40 PM ET**

## Calculation

**$24.05 = $24.05**

## Final price

**$24.05**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-021:v1 — expected $1.55</summary>

```markdown
## Route and fares

- Gallows Road → Lee Highway (Route 29), northbound — I-495 Express Lanes: **$1.55**
  - VDOT observed at: 7/29/2026 11:50 AM ET

## Calculation

$1.55 = $1.55

## Final price

**$1.55**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-030:v1 — expected $4.75</summary>

```markdown
## Route and fares

- Jones Branch Drive/Route 123 → Gallows Road — I-495 Express Lanes, southbound: **$4.75**
  - VDOT observed at: **7/29/2026 11:50 AM ET**

## Calculation

**$4.75 = $4.75**

## Final price

**$4.75**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-018:v1 — expected $0.00</summary>

```markdown
## Route and fares

- I-495 Near Braddock Road → I-495/I-95 Near Van Dorn Street — Southbound, I-495 Express Lanes: **$0.00**
  - VDOT observed at: **7/29/2026 11:50 AM ET**

## Calculation

$0.00 = $0.00

## Final price

**$0.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-038:v1 — expected $1.10</summary>

```markdown
## Route and fares

- Jones Branch Drive/Route 123 → Westpark Drive — I-495 Express Lanes, southbound: **$1.10**
  - VDOT observed at: 7/29/2026 11:50 AM ET

## Calculation

**$1.10 = $1.10**

## Final price

**$1.10**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-034:v2 — expected $7.75</summary>

```markdown
## Route and fares

- Jones Branch Drive/Route 123 → I-495/I-95 Near Van Dorn Street — Southbound, I-495 Express Lanes: **$7.75**
  - VDOT observed at: **7/29/2026 11:50 AM ET**

## Calculation

**$7.75 = $7.75**

## Final price

**$7.75**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-020:v2 — expected $3.00</summary>

```markdown
## Route and fares

- Interstate 66 → Braddock Road — I-495 Express Lanes, southbound: **$3.00**
  - VDOT observed at: 7/29/2026 11:50 AM ET

## Calculation

**$3.00 = $3.00**

## Final price

**$3.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-011:v2 — expected $8.60</summary>

```markdown
## Route and fares

- Braddock Road → Route 7 (Leesburg Pike) — Northbound, I-495 Express Lanes: **$8.60**
  - VDOT observed at: **7/29/2026 11:50 AM ET**

## Calculation

**$8.60 = $8.60**

## Final price

**$8.60**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-003:v2 — expected $7.20</summary>

```markdown
## Route and fares

- Braddock Road → Interstate 66 — **Northbound, I-495 Express Lanes: $7.20**
  - VDOT observed at: **7/29/2026 11:50 AM ET**

## Calculation

$7.20 = $7.20

## Final price

**$7.20**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-039:v3 — expected $9.60</summary>

```markdown
## Route and fares

- I-495 Near Braddock Road → Route 7 (Leesburg Pike) — **I-495 Express Lanes, northbound: $9.60**
  - VDOT observed at: **7/29/2026 11:50 AM ET**

## Calculation

**$9.60 = $9.60**

## Final price

**$9.60**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-031:v3 — expected $8.20</summary>

```markdown
## Route and fares

- I-495 Near Braddock Road → Interstate 66 — Northbound, I-495 Express Lanes: **$8.20**
  - VDOT observed at: **7/29/2026 11:50 AM ET**

## Calculation

**$8.20 = $8.20**

## Final price

**$8.20**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-006:v3 — expected $10.75</summary>

```markdown
## Route and fares

- 495 Express Lanes Start/Georg Wash. Mem. Pkwy. → I-495 Near Braddock Road — Southbound, I-495 Express Lanes: **$10.75**
  - VDOT observed at: **7/29/2026 11:50 AM ET**

## Calculation

**$10.75 = $10.75**

## Final price

**$10.75**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-009:v3 — expected $12.00</summary>

```markdown
## Route and fares

- Braddock Road → Route 267 — Northbound, I-495 Express Lanes: **$12.00**
  - VDOT observed at: **7/29/2026 11:50 AM ET**

## Calculation

**$12.00 = $12.00**

## Final price

**$12.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-037:v4 — expected $13.00</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| I-495 Express Lanes | I-495 Near Braddock Road → Route 267, northbound | $13.00 |
| **Total** |  | **$13.00** |

VDOT observed at: 7/29/2026 11:50 AM ET
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-021:v4 — expected $1.55</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| I-495 Express Lanes | Gallows Road → Lee Highway (Route 29), northbound | $1.55 |
| **Total** |  | **$1.55** |

VDOT observed at: 7/29/2026 11:50 AM ET  
Priced for: 7/29/2026 12:00 PM ET
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-016:v4 — expected $4.40</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| I-495 Express Lanes | 495 Express Lanes Start/Georg Wash. Mem. Pkwy. → Westpark Drive, southbound | $4.40 |
| **Total** |  | **$4.40** |

VDOT observed at: 7/29/2026 11:50 AM ET
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-027:v4 — expected $6.10</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| I-495 Express Lanes | Gallows Road → Westpark Drive, northbound | $6.10 |
| **Total** |  | **$6.10** |

VDOT observed at: 7/29/2026 11:50 AM ET
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-016:v5 — expected $4.40</summary>

```markdown
## Route and fares

- 495 Express Lanes Start/Georg Wash. Mem. Pkwy. → Westpark Drive — Southbound, I-495 Express Lanes: **$4.40**
  - VDOT observed at: **7/29/2026 11:50 AM ET**

## Calculation

**$4.40 = $4.40**

## Final price

**$4.40**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-031:v5 — expected $8.20</summary>

```markdown
## Route and fares

- I-495 Near Braddock Road → Interstate 66 — Northbound, I-495 Express Lanes: **$8.20**
  - VDOT observed at: 7/29/2026 11:50 AM ET

## Calculation

**$8.20 = $8.20**

## Final price

**$8.20**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-022:v5 — expected $1.60</summary>

```markdown
## Route and fares

- Interstate 66 → Gallows Road — Southbound on I-495 Express Lanes: **$1.60**
  - VDOT observed at: **7/29/2026 11:50 AM ET**

## Calculation

**$1.60 = $1.60**

## Final price

**$1.60**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i495-019:v5 — expected $6.85</summary>

```markdown
## Route and fares

- Gallows Road → Jones Branch Drive/Route 123 — **I-495 Express Lanes, northbound: $6.85**
  - VDOT observed at: **7/29/2026 11:50 AM ET**

## Calculation

**$6.85 = $6.85**

## Final price

**$6.85**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-033:v1 — expected $1.80</summary>

```markdown
## Route and fares

- I-495 N → Route 7 - Leesburg Pike — I-66 EB: **$1.80**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$1.80 = $1.80**

## Final price

**$1.80**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-030:v1 — expected $0.00</summary>

```markdown
## Route and fares

- Lee Highway - Scott Street → Route 267 - Dulles Toll Road — I-66 WB: **$0.00**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$0.00 = $0.00**

## Final price

**$0.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-020:v1 — expected $0.00</summary>

```markdown
**Route and fares**
- Fairfax Drive → Route 7 - Leesburg Pike — I-66 WB: **$0.00**
  - VDOT observed at: 7/29/2026 8:26 AM ET

**Calculation**

$0.00 = $0.00

**Final price**

**$0.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-002:v1 — expected $0.00</summary>

```markdown
## Route and fares

- Exit 75 - Pentagon/Alexandria → Glebe Road — I-66 WB: **$0.00**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$0.00 = $0.00**

## Final price

**$0.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-030:v2 — expected $0.00</summary>

```markdown
## Route and fares

- Lee Highway - Scott Street → Route 267 - Dulles Toll Road — I-66 WB: **$0.00**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$0.00 = $0.00**

## Final price

**$0.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-032:v2 — expected $0.00</summary>

```markdown
## Route and fares

- Lee Highway - Scott Street → Route 7 - Leesburg Pike — I-66 WB: **$0.00**
  - VDOT observed at: 7/29/2026 8:26 AM ET

## Calculation

$0.00 = $0.00

## Final price

**$0.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-011:v2 — expected $12.15</summary>

```markdown
## Route and fares

- I-495 Express Lanes N → Exit 75 - Pentagon/Alexandria — I-66 EB: **$12.15**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$12.15 = $12.15**

## Final price

**$12.15**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-015:v2 — expected $12.15</summary>

```markdown
## Route and fares

- I-495 Express Lanes N → Lee Highway - Spout Run Parkway — I-66 EB: **$12.15**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$12.15 = $12.15**

## Final price

**$12.15**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-005:v3 — expected $4.30</summary>

```markdown
## Route and fares

- Glebe Road → Lee Highway - Spout Run Parkway — I-66 EB: **$4.30**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$4.30 = $4.30**

## Final price

**$4.30**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-029:v3 — expected $7.80</summary>

```markdown
## Route and fares

- I-495 N → Fairfax Drive — I-66 EB: **$7.80**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$7.80 = $7.80**

## Final price

**$7.80**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-025:v3 — expected $12.15</summary>

```markdown
## Route and fares

- I-495 N → Exit 73 - Rosslyn — I-66 Express Lanes, eastbound: **$12.15**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$12.15 = $12.15**

## Final price

**$12.15**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-001:v3 — expected $4.30</summary>

```markdown
## Route and fares

- Glebe Road → Exit 73 - Rosslyn — I-66 EB: **$4.30**
  - VDOT observed at: 7/29/2026 8:26 AM ET

## Calculation

$4.30 = $4.30

## Final price

**$4.30**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-029:v4 — expected $7.80</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| I-66 EB Express Lanes | I-495 N → Fairfax Drive | $7.80 |
| **Total** |  | **$7.80** |

**VDOT observed at:** 7/29/2026 8:26 AM ET
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-039:v4 — expected $4.20</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| I-66 EB Express Lanes | I-495 N → Westmoreland St | $4.20 |
| **Total** |  | **$4.20** |

VDOT observed at: **7/29/2026 8:26 AM ET**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-008:v4 — expected $0.00</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| I-66 WB Express Lanes | Exit 75 - Pentagon/Alexandria → Route 267 - Dulles Toll Road | $0.00 |
| **Total** |  | **$0.00** |

VDOT observed at: **7/29/2026 8:26 AM ET**.
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-009:v4 — expected $12.15</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| I-66 Express Lanes | I-495 Express Lanes N → Exit 73 - Rosslyn, eastbound | $12.15 |
| **Total** |  | **$12.15** |

VDOT observed at: **7/29/2026 8:26 AM ET**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-024:v5 — expected $0.00</summary>

```markdown
## Route and fares

- Lee Highway - Scott Street → Glebe Road — I-66 WB: **$0.00**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$0.00 = $0.00**

## Final price

**$0.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-036:v5 — expected $0.00</summary>

```markdown
## Route and fares

- Lee Highway - Spout Run Parkway → Glebe Road — I-66 WB: **$0.00**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$0.00 = $0.00**

## Final price

**$0.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-027:v5 — expected $12.15</summary>

```markdown
## Route and fares

- I-495 N → Exit 75 - Pentagon/Alexandria — I-66 EB, eastbound: **$12.15**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$12.15 = $12.15**

## Final price

**$12.15**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:i66_itb-007:v5 — expected $4.30</summary>

```markdown
## Route and fares

- Glebe Road → Washington — I-66 Eastbound: **$4.30**
  - VDOT observed at: **7/29/2026 8:26 AM ET**

## Calculation

**$4.30 = $4.30**

## Final price

**$4.30**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-010:v1 — expected $4.00</summary>

```markdown
## Route and fares

- Exit 12 - SR 602 (Reston Pkwy) → Exit 11 - SR 286 (Fairfax County Pkwy), westbound — Dulles Toll Road
  - Entrance ramp at Exit 12: $2.00
  - Exit ramp at Exit 11: $2.00
  - Travel time: 7/29/2026 12:00 PM ET

## Calculation

$2.00 + $2.00 = $4.00

## Final price

**$4.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-032:v1 — expected $2.00</summary>

```markdown
**Route and fares**
- Exit 15 - SR 676 (Wolf Trap) → Exit 10 - SR 657 — Dulles Toll Road, WB
  - Exit ramp at Exit 10 - SR 657: **$2.00**

**Calculation**

$2.00 = **$2.00**

**Final price**

**$2.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-020:v1 — expected $2.00</summary>

```markdown
## Route and fares

- Exit 13 - SR 828 (Wiehle Ave) → Route 28 (Dulles Toll Road / Dulles Greenway), westbound
  - Dulles Toll Road: **Entrance ramp at Exit 13 - SR 828 (Wiehle Ave): $2.00**

## Calculation

$2.00 = **$2.00**

## Final price

**$2.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-038:v1 — expected $2.00</summary>

```markdown
## Route and fares

- Exit 15 - SR 676 (Wolf Trap) → Exit 13 - SR 828 (Wiehle Ave), westbound — Dulles Toll Road
  - Dulles Toll Road: Exit ramp at Exit 13 - SR 828 (Wiehle Ave): **$2.00**

## Calculation

$2.00 = **$2.00**

## Final price

**$2.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-033:v2 — expected $6.00</summary>

```markdown
## Route and fares

- Exit 11 - SR 286 (Fairfax County Pkwy) → I-66 / Dulles Toll Road junction — eastbound, Dulles Toll Road
  - Entrance ramp at Exit 11 - SR 286 (Fairfax County Pkwy): **$2.00**
  - Mainline plaza: **$4.00**

## Calculation

$2.00 + $4.00 = **$6.00**

## Final price

**$6.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-034:v2 — expected $2.00</summary>

```markdown
## Route and fares

- Exit 15 - SR 676 (Wolf Trap) → Exit 11 - SR 286 (Fairfax County Pkwy) — westbound on the Dulles Toll Road
  - Exit ramp at Exit 11 - SR 286 (Fairfax County Pkwy): **$2.00**

## Calculation

$2.00 = **$2.00**

## Final price

**$2.00** for travel at **7/29/2026 12:00 PM ET**.
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-011:v2 — expected $8.00</summary>

```markdown
## Route and fares

- Exit 10 - SR 657 → Exit 16 - SR 7 (Leesburg Pike) — eastbound, Dulles Toll Road
  - Entrance ramp at Exit 10 - SR 657: **$2.00**
  - Mainline plaza: **$4.00**
  - Exit ramp at Exit 16 - SR 7 (Leesburg Pike): **$2.00**

## Calculation

**$2.00 + $4.00 + $2.00 = $8.00**

## Final price

**$8.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-024:v2 — expected $4.00</summary>

```markdown
## Route and fares

- Exit 14 - SR 674 (Hunter Mill Rd) → Exit 11 - SR 286 (Fairfax County Pkwy), westbound — Dulles Toll Road
  - Dulles Toll Road entrance ramp at Exit 14: **$2.00**
  - Dulles Toll Road exit ramp at Exit 11: **$2.00**
  - Rate period: none

## Calculation

**$2.00 + $2.00 = $4.00**

## Final price

**$4.00** for travel at **7/29/2026 12:00 PM ET**.
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-022:v3 — expected $4.00</summary>

```markdown
## Route and fares

- Exit 14 - SR 674 (Hunter Mill Rd) → Exit 10 - SR 657 — Dulles Toll Road, westbound
  - Entrance ramp at Exit 14 - SR 674 (Hunter Mill Rd): **$2.00**
  - Exit ramp at Exit 10 - SR 657: **$2.00**

## Calculation

$2.00 + $2.00 = **$4.00**

## Final price

**$4.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-029:v3 — expected $8.00</summary>

```markdown
## Route and fares

- Exit 11 - SR 286 (Fairfax County Pkwy) → Exit 17 - SR 684 (Spring Hill Rd) — Dulles Toll Road, eastbound
  - Entrance ramp at Exit 11: **$2.00**
  - Mainline plaza: **$4.00**
  - Exit ramp at Exit 17: **$2.00**

## Calculation

$2.00 + $4.00 + $2.00 = **$8.00**

## Final price

**$8.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-014:v3 — expected $4.00</summary>

```markdown
## Route and fares

- Exit 13 - SR 828 (Wiehle Ave) → Exit 10 - SR 657 — Dulles Toll Road, westbound
  - Entrance ramp at Exit 13 - SR 828 (Wiehle Ave): **$2.00**
  - Exit ramp at Exit 10 - SR 657: **$2.00**

## Calculation

**$2.00 + $2.00 = $4.00**

## Final price

**$4.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-009:v3 — expected $2.00</summary>

```markdown
## Route and fares

- Exit 10 - SR 657 → Exit 15 - SR 676 (Wolf Trap) — Dulles Toll Road, eastbound
  - Entrance ramp at Exit 10 - SR 657: **$2.00**

## Calculation

$2.00 = **$2.00**

## Final price

**$2.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-008:v4 — expected $4.00</summary>

```markdown
### Route and fares

| Component | Facility | Fare |
|---|---|---:|
| Westbound: Exit 12 – SR 602 (Reston Pkwy) → Exit 10 – SR 657 | Dulles Toll Road — entrance ramp at Exit 12 | $2.00 |
|  | Dulles Toll Road — exit ramp at Exit 10 | $2.00 |
| **Total** |  | **$4.00** |

### Calculation

**$2.00 + $2.00 = $4.00**

### Final price

**$4.00** for travel at **7/29/2026 12:00 PM ET**.
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-019:v4 — expected $4.00</summary>

```markdown
| Component | Facility | Fare |
|---|---|---:|
| Entrance ramp at Exit 11 – SR 286 (Fairfax County Pkwy) | Dulles Toll Road | $2.00 |
| Exit ramp at Exit 12 – SR 602 (Reston Pkwy) | Dulles Toll Road | $2.00 |
| **Total** |  | **$4.00** |

**Direction:** Eastbound  
**Travel time:** 7/29/2026 12:00 PM ET
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-031:v4 — expected $6.00</summary>

```markdown
### Route and fares

| Component | Facility | Fare |
|---|---|---:|
| Exit 11 – SR 286 → Exit 18/19 – I-495/SR 123 (EB) | Dulles Toll Road — entrance ramp at Exit 11 | $2.00 |
|  | Dulles Toll Road — mainline plaza | $4.00 |
| **Total** |  | **$6.00** |

### Calculation

| Calculation | Total |
|---|---:|
| $2.00 + $4.00 | **$6.00** |
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-033:v4 — expected $6.00</summary>

```markdown
### Route and fares

| Component | Facility | Fare |
|---|---|---:|
| Exit 11 – SR 286 → I-66 / Dulles Toll Road junction | Dulles Toll Road — Entrance ramp at Exit 11 | $2.00 |
|  | Dulles Toll Road — Mainline plaza | $4.00 |
| **Total** |  | **$6.00** |

**Travel time:** 7/29/2026 12:00 PM ET  
**Calculation:** $2.00 + $4.00 = **$6.00**  
**Final price:** **$6.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-022:v5 — expected $4.00</summary>

```markdown
## Route and fares

- Exit 14 - SR 674 (Hunter Mill Rd) → Exit 10 - SR 657 — Dulles Toll Road, westbound
  - Entrance ramp at Exit 14 - SR 674 (Hunter Mill Rd): **$2.00**
  - Exit ramp at Exit 10 - SR 657: **$2.00**

## Calculation

**$2.00 + $2.00 = $4.00**

## Final price

**$4.00** for travel at **7/29/2026 12:00 PM ET**.
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-038:v5 — expected $2.00</summary>

```markdown
## Route and fares

- Exit 15 - SR 676 (Wolf Trap) → Exit 13 - SR 828 (Wiehle Ave), westbound on the Dulles Toll Road
  - Exit ramp at Exit 13 - SR 828 (Wiehle Ave): **$2.00**

## Calculation

$2.00 = **$2.00**

## Final price

**$2.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-011:v5 — expected $8.00</summary>

```markdown
**Route and fares**

- Exit 10 - SR 657 → Exit 16 - SR 7 (Leesburg Pike) — Dulles Toll Road, eastbound
  - Dulles Toll Road — Entrance ramp at Exit 10: **$2.00**
  - Dulles Toll Road — Mainline plaza: **$4.00**
  - Dulles Toll Road — Exit ramp at Exit 16: **$2.00**

**Calculation**

$2.00 + $4.00 + $2.00 = **$8.00**

**Final price**

**$8.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_toll_road-017:v5 — expected $6.00</summary>

```markdown
## Route and fares

- Exit 10 - SR 657 → I-66 / Dulles Toll Road junction — eastbound, Dulles Toll Road
  - Entrance ramp at Exit 10 - SR 657: **$2.00**
  - Mainline plaza: **$4.00**

## Calculation

**$2.00 + $4.00 = $6.00**

## Final price

**$6.00**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-032:v1 — expected $4.55</summary>

```markdown
## Route and fares

- Exit 6 - SR 772 (Ryan Rd) → Exit 2B - Compass Creek Pkwy — westbound, Dulles Greenway
  - Secondary plaza: **$4.55**
  - Rate period: **off_peak**

## Calculation

$4.55 = $4.55

## Final price

**$4.55**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-035:v1 — expected $5.10</summary>

```markdown
## Route and fares

- Exit 3 - SR 653 (Shreve Mill Rd) → Exit 6 - SR 772 (Ryan Rd), eastbound — Dulles Greenway
  - Secondary plaza: **$5.10**
  - Rate period: **peak**

## Calculation

$5.10 = $5.10

## Final price

**$5.10**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-015:v1 — expected $7.80</summary>

```markdown
**Route and fares**
- Exit 1 - US 15/SR 7 (Leesburg Bypass) → Route 28 (Dulles Toll Road / Dulles Greenway), eastbound
  - Dulles Greenway — Mainline plaza: **$5.80**
    - Rate period: **peak**
  - Dulles Toll Road — Mainline plaza: **$2.00**

**Calculation**

$5.80 + $2.00 = **$7.80**

**Final price**

**$7.80** for travel at **7/27/2026 7:30 AM ET**.
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-036:v1 — expected $4.55</summary>

```markdown
## Route and fares

- Exit 6 - SR 772 (Ryan Rd) → Exit 4 - SR 659 (Belmont Ridge Rd), westbound — Dulles Greenway
  - Secondary plaza: **$4.55**
  - Rate period: **off_peak**

## Calculation

$4.55 = $4.55

## Final price

**$4.55**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-006:v2 — expected $4.55</summary>

```markdown
**Route and fares**
- Exit 3 - SR 653 (Shreve Mill Rd) → Exit 2 - Battlefield Pkwy — Dulles Greenway, westbound
  - Secondary plaza: $4.55
  - Rate period: off_peak

**Calculation**

$4.55 = $4.55

**Final price**

**$4.55**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-036:v2 — expected $4.55</summary>

```markdown
## Route and fares

- Exit 6 - SR 772 (Ryan Rd) → Exit 4 - SR 659 (Belmont Ridge Rd), westbound, Dulles Greenway
  - Secondary plaza: **$4.55**
  - Rate period: **off_peak**

## Calculation

$4.55 = $4.55

## Final price

**$4.55**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-003:v2 — expected $5.10</summary>

```markdown
## Route and fares

- Exit 1 - US 15/SR 7 (Leesburg Bypass) → Exit 3 - SR 653 (Shreve Mill Rd) — eastbound, Dulles Greenway
  - Secondary plaza: **$5.10**
  - Rate period: **peak**

## Calculation

$5.10 = **$5.10**

## Final price

**$5.10**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-035:v2 — expected $5.10</summary>

```markdown
## Route and fares

- Exit 3 - SR 653 (Shreve Mill Rd) → Exit 6 - SR 772 (Ryan Rd), eastbound — Dulles Greenway
  - Secondary plaza: **$5.10**
  - Rate period: **peak**

## Calculation

**$5.10 = $5.10**

## Final price

**$5.10**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-021:v3 — expected $5.10</summary>

```markdown
## Route and fares

- Exit 2 - Battlefield Pkwy → Exit 5 - SR 901 (Claiborne Pkwy), eastbound, Dulles Greenway
  - Secondary plaza: **$5.10**
  - Rate period: **peak**

## Calculation

$5.10 = **$5.10**

## Final price

**$5.10**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-029:v3 — expected $7.80</summary>

```markdown
## Route and fares

- Exit 2 - Battlefield Pkwy → Route 28 (Dulles Toll Road / Dulles Greenway), eastbound
  - Dulles Greenway — Mainline plaza: **$5.80**
    - Rate period: **peak**
  - Dulles Toll Road — Mainline plaza: **$2.00**

## Calculation

**$5.80 + $2.00 = $7.80**

## Final price

**$7.80**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-003:v3 — expected $5.10</summary>

```markdown
**Route and fares**

- Exit 1 - US 15/SR 7 (Leesburg Bypass) → Exit 3 - SR 653 (Shreve Mill Rd), eastbound, Dulles Greenway
  - Secondary plaza: **$5.10**
  - Rate period: **peak**

**Calculation**

$5.10 = $5.10

**Final price**

**$5.10** at 7/27/2026 7:30 AM ET.
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-040:v3 — expected $4.55</summary>

```markdown
## Route and fares

- Exit 7 - SR 607 (Loudoun County Pkwy) → Exit 1 - US 15/SR 7 (Leesburg Bypass), westbound — Dulles Greenway
  - Secondary plaza: $4.55
  - Rate period: off_peak

## Calculation

$4.55 = $4.55

## Final price

**$4.55**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-037:v4 — expected $5.10</summary>

```markdown
### Route and fares

| Component | Details | Fare |
|---|---|---:|
| Dulles Greenway | Exit 3 – SR 653 (Shreve Mill Rd) → Exit 7 – SR 607 (Loudoun County Pkwy), EB; **peak** rate period | $5.10 |
| Toll item | Secondary plaza | $5.10 |

### Calculation

| Calculation | Total |
|---|---:|
| $5.10 | **$5.10** |

### Final price

**$5.10**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-039:v4 — expected $5.10</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| Dulles Greenway | Exit 3 – SR 653 (Shreve Mill Rd) → Exit 8 – SR 606 (Ox Rd), EB | — |
| Secondary plaza | Peak rate period | $5.10 |
| **Total** |  | **$5.10** |

**Calculation:** $5.10 = **$5.10**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-034:v4 — expected $4.55</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| Dulles Greenway | Exit 6 – SR 772 (Ryan Rd) → Exit 3 – SR 653 (Shreve Mill Rd), westbound; off-peak | $4.55 |
| **Total** |  | **$4.55** |

Travel time: 7/27/2026 7:30 AM ET
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-008:v4 — expected $4.55</summary>

```markdown
| Component | Details | Fare |
|---|---|---:|
| Route | Exit 3 – SR 653 (Shreve Mill Rd) → Exit 2B – Compass Creek Pkwy, westbound | — |
| Dulles Greenway — Secondary plaza | Rate period: off-peak | $4.55 |
| **Total** | **$4.55** | **$4.55** |
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-010:v5 — expected $4.55</summary>

```markdown
## Route and fares

- Exit 4 - SR 659 (Belmont Ridge Rd) → Exit 1 - US 15/SR 7 (Leesburg Bypass), westbound on the Dulles Greenway
  - Secondary plaza: **$4.55**
  - Rate period: **off_peak**

## Calculation

$4.55 = $4.55

## Final price

**$4.55**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-037:v5 — expected $5.10</summary>

```markdown
## Route and fares

- Exit 3 - SR 653 (Shreve Mill Rd) → Exit 7 - SR 607 (Loudoun County Pkwy), eastbound — Dulles Greenway
  - Rate period: peak
  - Secondary plaza: **$5.10**

## Calculation

$5.10 = $5.10

## Final price

**$5.10**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-024:v5 — expected $4.55</summary>

```markdown
## Route and fares

- Exit 5 - SR 901 (Claiborne Pkwy) → Exit 3 - SR 653 (Shreve Mill Rd), westbound — Dulles Greenway
  - Secondary plaza: **$4.55**
  - Rate period: **off_peak**

## Calculation

**$4.55 = $4.55**

## Final price

**$4.55**
```

</details>

<details>
<summary><strong>PASS SAMPLE</strong> — single_leg:dulles_greenway-005:v5 — expected $5.10</summary>

```markdown
## Route and fares

- Exit 1 - US 15/SR 7 (Leesburg Bypass) → Exit 4 - SR 659 (Belmont Ridge Rd), eastbound — Dulles Greenway
  - Secondary plaza: **$5.10**
  - Rate period: **peak**

## Calculation

**$5.10 = $5.10**

## Final price

**$5.10**
```

</details>

## Integrity

- Batch: `batch_6a7bac52ad608190b65511c6b687751e`
- Raw output SHA-256: `b7eec9b494418510042c21e8f438ff102fdad86a5c080440ea0722e93edf2cc4`
- Gate 4 packet SHA-256: `71daa439b69edb2f3fe4c82c6f0231c107664d4f66f01f695dadc53f68322527`

```bash
sha256sum -c gate4-packet.sha256
sha256sum gate4-packet.sha256
```
