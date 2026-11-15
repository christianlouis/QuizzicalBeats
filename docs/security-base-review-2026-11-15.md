# Docker base-image security review (2026-11-15)

This is a source review of the open Snyk issues; it is not a deployment or a
claim about a currently running image.

| Issue | Finding | Official status checked 2026-11-15 |
| --- | --- | --- |
| [#255](https://github.com/christianlouis/QuizzicalBeats/issues/255) | Aggregate Snyk alert | Review split into the individual CVEs below. |
| [#256](https://github.com/christianlouis/QuizzicalBeats/issues/256) | `perl` CVEs 2026-57433, 2026-57432, 2026-13221 | Debian marks all three fixed in Trixie at `5.40.1-6+deb13u1`: [57433](https://security-tracker.debian.org/tracker/CVE-2026-57433), [57432](https://security-tracker.debian.org/tracker/CVE-2026-57432), [13221](https://security-tracker.debian.org/tracker/CVE-2026-13221). |
| [#257](https://github.com/christianlouis/QuizzicalBeats/issues/257) | SQLite CVEs 2026-50812 and 2026-50813 | Debian still marks Trixie vulnerable (`3.46.1-7+deb13u2`) for [50812](https://security-tracker.debian.org/tracker/CVE-2026-50812) and [50813](https://security-tracker.debian.org/tracker/CVE-2026-50813); no safe dependency change is inferred from this review. |

The Dockerfile uses the official `python:3.11-slim` base. A rebuild and image
scan are still required to establish the exact runtime package inventory.
