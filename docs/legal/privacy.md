# TollChat privacy notice — draft

**Owner/legal review and telemetry verification required before public launch.**

TollChat receives the trip details a user submits and a random browser-generated session identifier. The application does not create user accounts or intentionally store chat history in its database. A runtime session idles after 15 minutes and has a maximum lifetime of 60 minutes; the browser stores the identifier in session storage until the tab session ends or the user starts a new chat.

AWS and the model provider may process request and response content to operate the service. Before public launch, the owner must document and verify provider retention settings, CloudWatch retention, redaction, deletion contacts, and any legally required disclosures. Until then, users must not submit personal, confidential, or payment information.

Deletion and privacy requests: contact [contact@tollchat.ai](mailto:contact@tollchat.ai). The final policy must state which records can be located and deleted using a session identifier.
