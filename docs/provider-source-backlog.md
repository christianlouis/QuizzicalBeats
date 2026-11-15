# Provider-source backlog

The following discovery sources remain intentionally review-only. They need an
explicit access, API, and licensing decision before implementation is enabled;
no provider is activated by this backlog entry.

| Issue | Source | Decision needed before engineering |
| --- | --- | --- |
| [#248](https://github.com/christianlouis/QuizzicalBeats/issues/248) | Official German charts | Identify a permitted stable API/feed/export and document its terms and request limits. |
| [#249](https://github.com/christianlouis/QuizzicalBeats/issues/249) | RADIO BOB! airplay | Confirm an officially permitted playlist/history endpoint, cadence, caching, and usage rights. |
| [#250](https://github.com/christianlouis/QuizzicalBeats/issues/250) | Apple Music charts | Approve Apple developer-token ownership, secret handling, storefront scope, and API limits. |
| [#251](https://github.com/christianlouis/QuizzicalBeats/issues/251) | Last.fm signals | Approve API-key ownership, attribution/terms, caching limits, and interpretation of listener scores. |
| [#252](https://github.com/christianlouis/QuizzicalBeats/issues/252) | setlist.fm live staples | Approve API-key ownership, rate limits, attribution, and exact-recording resolution policy. |
| [#253](https://github.com/christianlouis/QuizzicalBeats/issues/253) | Billboard Hot 100 | Decide whether a licensed/official feed exists; otherwise record a no-go and choose an alternative. |

Once a source is approved, its adapter must remain fail-closed, fixture-tested,
and review-only until a controlled production refresh proves that the source
and its terms still hold.
