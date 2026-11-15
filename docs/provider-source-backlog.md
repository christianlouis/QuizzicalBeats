# Provider-source backlog

The following discovery sources remain intentionally review-only. This is a
functional backlog: each item needs a reachable source, configured credentials
where required, and a documented usage/attribution basis before implementation
is enabled. No provider is activated by this backlog entry.

| Issue | Source | Decision needed before engineering |
| --- | --- | --- |
| [#248](https://github.com/christianlouis/QuizzicalBeats/issues/248) | Official German charts | Identify a permitted stable API/feed/export and document its terms and request limits. |
| [#249](https://github.com/christianlouis/QuizzicalBeats/issues/249) | RADIO BOB! airplay | Confirm an officially permitted playlist/history endpoint, cadence, caching, and usage rights. |
| [#250](https://github.com/christianlouis/QuizzicalBeats/issues/250) | Apple Music charts | Check that an Apple developer account can mint a developer token, then configure secret handling, storefront scope, and request limits per [Apple's token documentation](https://developer.apple.com/documentation/applemusicapi/generating_developer_tokens). |
| [#251](https://github.com/Christianlouis/QuizzicalBeats/issues/251) | Last.fm signals | Check that a Last.fm API key is available and that the intended attribution, terms, caching limits, and listener-score interpretation fit the [Last.fm API](https://www.last.fm/api). |
| [#252](https://github.com/Christianlouis/QuizzicalBeats/issues/252) | setlist.fm live staples | Check setlist.fm API-key availability, rate limits, attribution, and exact-recording resolution against the [setlist.fm API documentation](https://www.setlist.fm/api/docs/1.0/index.html). |
| [#253](https://github.com/christianlouis/QuizzicalBeats/issues/253) | Billboard Hot 100 | Decide whether a licensed/official feed exists; otherwise record a no-go and choose an alternative. |

Once a source is reachable and configured, its adapter must remain fail-closed,
fixture-tested, and review-only until a controlled refresh proves that the
source and its documented terms still hold. Missing credentials, unavailable
endpoints, or unresolved licensing/access questions remain explicit blockers;
they are not silently bypassed.
