# Gate 3 — 1,000-row single-leg smoke review

**Nothing has been uploaded and no model has been called.**

| Check | Result |
| --- | ---: |
| Canonical single-leg fixtures | 200 |
| Batch requests | 1,000 |
| Unapproved production-payload differences | 0 |
| Maximum output tokens | 2,048,000 |
| Conservative maximum cost | **$47.18** |

The spend ceiling assumes every response uses all 2,048 output tokens and every
request-body UTF-8 byte is a separately billed explicit-cache-write input token.
That deliberately overcounts JSON/control fields and ignores cache-read savings.

## Approved production differences

* Batch envelope added
* streaming removed
* response storage disabled
* tool schemas retained but `tool_choice` set to `none`
* trace metadata added

## Verification

```bash
sha256sum -c gate3-packet.sha256
sha256sum gate3-packet.sha256
```

**Gate 3 packet SHA-256:** `f8a120c199a6d5f39d5cb8af5257fda089c13f4c0fa8c52cca0f16516ad99247`

Approving this packet authorizes only upload/submission of this exact 1,000-row
single-leg Batch file. The run must still pause for Gate 4 audit before another
stratum is rendered or submitted.
