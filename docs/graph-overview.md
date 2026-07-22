# NOVA Toll Graph — Visual Overview

A plain-language map of what this agent prices and how the pieces fit. For the
full inventory and citations see [`graph-network-audit.md`](graph-network-audit.md);
for the technical design see [`toll-graph-spec.md`](toll-graph-spec.md).

## The 5-second glance

Three toll corridors, stitched together by two free interchange ramps. A few
nearby toll roads are **not** modeled (no live feed), shown greyed out.

```mermaid
flowchart LR
  subgraph covered["Priced live by the agent"]
    A["I-95 / 395 Express Lanes<br/>34 access points"]
    B["I-495 Capital Beltway<br/>Express Lanes<br/>18 access points"]
    C["I-66 Inside the Beltway<br/>8 toll zones"]
    A <==>|"Springfield interchange<br/>(free connector)"| B
    B <==>|"Beltway / I-66 interchange<br/>(free connector)"| C
  end
  subgraph notcov["Not in the graph (no live feed)"]
    D["Dulles Toll Road<br/>flat rate"]
    E["Dulles Greenway<br/>flat rate"]
    F["I-66 Outside the Beltway<br/>dynamic, no public feed"]
  end
  classDef grey stroke-dasharray:5 5,color:#888;
  class D,E,F grey;
```

**Takeaway:** the agent knows live prices on the I-95/395 and I-495 Express
Lanes and I-66 inside the Beltway. It does *not* live-price the Dulles Toll
Road, the Greenway, or I-66 outside the Beltway.

## Drill down: all 60 access points

Every node in the graph, grouped by area. Two things to read carefully:

- **Within the express corridors, no lines are drawn between access points** —
  that's deliberate. Every pair of access points is a *single priced trip* (an
  OD pair) looked up live, not a chain of segments you add up. Drawing all 317
  of those would be a meaningless hairball.
- **The only lines shown are real physical links:** the 5 free ramps that
  connect the corridors (dotted, "free"), plus I-66's toll zones, which *are* a
  fixed gantry sequence you pass through in order.

```mermaid
flowchart TB
  subgraph I95["I-95 / 395 Express Lanes · 34 access points"]
    subgraph I95a["Stafford"]
      s1["Garrisonville Rd (610)"]
      s2["Rt 17 / 95 NB"]
      s3["Rt 17 / 95 SB"]
      s4["Old Courthouse Rd"]
    end
    subgraph I95b["Quantico / S. Prince William"]
      q1["Quantico"]
      q2["Russell Rd"]
      q3["Joplin Rd (619)"]
      q4["Dumfries Rd (234)"]
      q5["Dale Blvd"]
      q6["I-95 S near Dale Blvd"]
    end
    subgraph I95c["Woodbridge / Prince William"]
      w1["Cardinal"]
      w2["Opitz"]
      w3["Gordon Blvd (123)"]
      w4["Prince William Pkwy (294)"]
      w5["US 1"]
    end
    subgraph I95d["Springfield / Fairfax"]
      f1["Fairfax County Pkwy (286)"]
      f2["Newington"]
      f3["Lorton"]
      f4["Alban"]
      f5["I-95 S / Ft Belvoir"]
      f6["Franconia-Springfield Pkwy (289)"]
      f7["Franconia Rd (644)"]
      f8["Turkeycock"]
      f9["I-95 S near Backlick Rd"]
      f10(["I-495 (Springfield) — junction"])
      f11["Telegraph Rd"]
    end
    subgraph I95e["Arlington / Pentagon / DC"]
      a1["I-395/95"]
      a2["I-395 N"]
      a3["Seminary Rd"]
      a4["Shirlington Circle"]
      a5["Washington Blvd / Pentagon"]
      a6["Pentagon"]
      a7["DC/Pentagon/Washington Blvd"]
      a8["Washington DC"]
    end
  end

  subgraph I495["I-495 Capital Beltway Express Lanes · 18 access points"]
    subgraph I495a["Springfield end (HOV / HOT ramps)"]
      e1["I-395-95-495"]
      e2["I-395-95 HOV"]
      e3["I-395-495 HOV"]
      e4["I-95 HOV"]
      e5["I-495 HOV"]
    end
    subgraph I495b["Central / Tysons"]
      t1["Braddock Rd"]
      t2["Gallows Rd"]
      t3(["I-66 — junction"])
      t4["Route 7"]
      t5["Rt 267"]
      t6["Westpark Dr"]
      t7["Westpark Dr (B)"]
      t8["Westpark Dr (C)"]
      t9["Jones Branch Dr"]
      t10["Jones Branch Dr / Rt 267"]
      t11["Lee Hwy"]
    end
    subgraph I495c["North / Maryland"]
      n1["I-495 N"]
      n2["I-495 near MD"]
    end
  end

  subgraph I66["I-66 Inside the Beltway · 8 toll zones"]
    subgraph I66EB["Eastbound: Beltway → Rosslyn"]
      eb1["Capital Beltway Beginning"] --> eb2["Lee Highway"] --> eb3["Fairfax Drive"] --> eb4["Spout Run Parkway"]
    end
    subgraph I66WB["Westbound: Rosslyn → Beltway"]
      wb1["Glebe Road"] --> wb2["Sycamore Street"] --> wb3["Leesburg Pike"] --> wb4["Capital Beltway End"]
    end
  end

  %% free junction connectors — the only inter-corridor links
  f10 -. free .-> e2
  e4 -. free .-> f10
  e3 -. free .-> f10
  t3 -. free .-> eb1
  wb4 -. free .-> t3

  classDef jct stroke-width:3px;
  class f10,t3 jct;
```

**Notes for reading the drill-down:**

- The two **bold-outlined** nodes — *I-495 (Springfield)* and *I-66* — are the
  junction points where corridors meet.
- **Westpark Dr / (B) / (C)** are three graph nodes for the *same physical
  Exit 46* — they exist only to carry the distinct priced trips the feed lists
  separately, not because there are three Westpark locations.
- I-66's zone order is physical (you pass Beltway Beginning → Lee Hwy → Fairfax
  Dr → Spout Run heading east); the express-lane groupings are just geographic —
  their internal pricing is trip-by-trip, not sequential.
