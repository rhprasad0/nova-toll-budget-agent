# TollChat privacy notice

TollChat receives the trip details a user submits. It does not create user accounts or intentionally store chat history in its database. The service sets a random, unreadable `HttpOnly` browser cookie; the backend stores only its SHA-256 hash and a synthetic runtime identifier. Sessions idle after 15 minutes and have a maximum lifetime of 60 minutes. Reset immediately revokes the session credential, and fixed-lifetime records are removed later by DynamoDB TTL.

AWS retains application-visible messages, answers, tool activity, and safety-check results for 30 days to operate, secure, debug, and improve TollChat. OpenAI processes and stores response data for at least 30 days; TollChat does not use this content to train models. Users must not submit personal, confidential, payment, credential, or unnecessarily precise location information. Privacy requests go to `contact@tollchat.ai`.

TollChat does not offer individualized record lookup or deletion because it has no accounts or stable user identity. A copied session cookie acts as a bearer credential until reset or expiry, so users should not copy it or use TollChat on an untrusted device. Operational records expire under the fixed retention controls above.
