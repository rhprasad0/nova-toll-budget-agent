# TollChat privacy notice — draft

**Owner/legal review and telemetry verification required before public launch.**

TollChat receives the trip details a user submits. It does not create user accounts or intentionally store chat history in its database. The service sets a random, unreadable `HttpOnly` browser cookie; the backend stores only its SHA-256 hash and a synthetic runtime identifier. Sessions idle after 15 minutes and have a maximum lifetime of 60 minutes. Reset immediately revokes the session credential, and fixed-lifetime records are removed later by DynamoDB TTL.

AWS and the model provider may process request and response content to operate the service. Before public launch, the owner must document and verify provider retention settings, CloudWatch retention, redaction, fixed retention periods, and any legally required disclosures. Until then, users must not submit personal, confidential, or payment information.

TollChat does not offer individualized record lookup or deletion because it has no accounts or stable user identity. A copied session cookie acts as a bearer credential until reset or expiry, so users should not copy it or use TollChat on an untrusted device. Operational records expire under fixed retention controls; legal approval of those controls remains required before public launch.
