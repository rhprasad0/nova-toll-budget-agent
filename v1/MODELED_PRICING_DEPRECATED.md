# Missing-OD pricing prototype deprecated

The exploratory work for estimating the 16 I-95/495 OD products absent from
VDOT history has moved to TollChat v2. Its authoritative schema, restore test,
and methodology now live under [`v2/`](../v2/):

- [database bootstrap](../v2/db/schema.sql);
- [database roles](../v2/db/roles.sql); and
- [missing-OD pricing method](../v2/docs/i95-missing-od-pricing.md).

Do not add or apply a v1 migration for this model. New database and
modeled-pricing development belongs in v2; the v1 prototype is deprecated.

This does **not** deprecate or retire the deployed v1 application,
its live VDOT I-95 ingestion, or its retained historical data. The original
product remains operational while v2 develops independently.
