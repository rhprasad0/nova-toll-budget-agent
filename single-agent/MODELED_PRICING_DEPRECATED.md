# Missing-OD pricing prototype deprecated

The exploratory work for estimating the 16 I-95/495 OD products absent from
VDOT history has moved to the independent TollChat rewrite. Its authoritative
schema, restore test, and methodology now live under [`rewrite/`](../rewrite/):

- [database bootstrap](../rewrite/db/schema.sql);
- [database roles](../rewrite/db/roles.sql); and
- [missing-OD pricing method](../rewrite/docs/i95-missing-od-pricing.md).

Do not add or apply a single-agent migration for this model. New database and
modeled-pricing development belongs in the rewrite; the single-agent prototype
is deprecated.

This does **not** deprecate or retire the deployed single-agent application,
its live VDOT I-95 ingestion, or its retained historical data. The original
product remains operational while the rewrite develops independently.
