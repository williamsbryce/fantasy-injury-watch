# Fantasy Injury Watch
Public, passwordless fantasy injury dashboard at https://williamsbryce.github.io/fantasy-injury-watch/.

## User-approved configuration (November 17, 2026)
- GitHub Pages report is intentionally **public**, with no passphrase on the website. The user explicitly accepted public roster-injury visibility to reduce friction.
- MFL API credentials and Resend API key remain GitHub Secrets and never reach the website.
- One MFL league, CFFL Dynasty, 2026, franchise 0001. Only active roster players are monitored; MFL IR/taxi excluded.
- MFL official injury designations are authoritative for this app's statuses, but they are not official kickoff inactive reports.
- An optional RotoWire **public NFL news page** provides recent matching injury and practice headlines, with a public NFL RSS fallback. A dated headline and publisher link appear only when there is a verified player-name match and an injury-specific item. Not all injured players have recent news; the application never invents an update.
- Each injury card links to the MFL player-news page. Access to article content on MFL's private league page may require a logged-in session.
- Recurring injury digests are handled by **`.github/workflows/scheduled-digest.yml`**, independent of injury polling. Nominal times remain **Thursday 5:00 p.m.** and **Sunday 10:30 a.m.** Saskatchewan (UTC-6). Multiple retry checks run through those days and the following day until 6 p.m. SK, mitigating skipped or late GitHub schedules. GitHub Actions start times are still best-effort, not exact-time guarantees. The dedicated flow uses the last verified injury report and clearly warns if it is over six hours old. It durably snapshots the outgoing HTML/text message, uses a stable Resend idempotency key, records provider acceptance in `site/data/digest-delivery.json`, and logs an accepted-email event. The separate MFL injury workflow continues urgent and missing-lineup alerts but **does not send scheduled digests**, preventing duplicate routes.
- Roster/news reports are **public JSON**; prior encrypted report migrated once using the legacy secret before removal from the branch. Historical git commits retain the old encrypted payload.
- The dashboard itself remains read-only; a separate scheduled owner-authenticated lineup guard can replace confirmed Out/Inactive starters. No waiver, roster ownership, or healthy-starter optimization is allowed.

## Scheduled injury email reliability fix (November 22, 2026)
- Fixed the missed Sunday summary caused by both a skipped GitHub scheduler window and prior coupling of summary delivery to successful MFL injury retrieval.
- **2026-11-22 Sunday digest:** Resend accepted the recovery message at **12:28 p.m. Saskatchewan**, GitHub Actions run [45055256180](https://github.com/williamsbryce/fantasy-injury-watch/actions/runs/45055256180), and the public Event Log recorded acceptance. Inbox delivery is not guaranteed by provider acceptance alone.
- The delivery ledger contains no API keys or recipient addresses. Prepared summaries include only roster injury information already public on the dashboard.
- `python -m unittest discover -s tests -p 'test_digest_delivery.py' -v` verifies due-window semantics, retrying the exact prepared payload, next-day recovery and duplicate suppression.
- Scheduled monitoring can still be delayed or missed by GitHub; if stronger delivery-time guarantees are required, use an external scheduler or monitored email-delivery service.

## Official NFL game-day checker (November 22, 2026)
- **Purpose:** monitor actual pregame availability, not just MFL injury designations. An MFL Questionable player can still be eligible to suit up once the official NFL team inactive list is released.
- **Primary official source:** NFL.com's current-week Sunday inactive list. The checker validates the NFL season/week, verifies each team has a complete plausible inactive list, and matches names within the same team. Unknown or incomplete official lists remain **Pending**, not automatically Active. It does not imply a player actually took a snap.
- **Roster:** independently reads MFL rosters and the current weekly starter selection, without relying on MFL injuries. It checks all verified fantasy starters and injured rostered players; if MFL cannot be reached it falls back to only cached injured players. It does not publish the unrelated healthy bench roster. MFL IR players are never reported as NFL eligible solely by omission from an inactive list.
- **Schedule:** `.github/workflows/nfl-game-day.yml`, approximately every 15 minutes on Sundays starting around 9 a.m. Saskatchewan, with evening coverage. GitHub cron remains best effort; NFL inactive lists typically appear about 90 minutes before kickoff. A missing list remains Pending on the dashboard and does not send a routine email. Only an officially confirmed Inactive player in the verified current MFL starting lineup may trigger an urgent game-day email, and only more than 10 minutes before kickoff.
- **Alerts:** only officially confirmed **Inactive** players in the verified current fantasy starting lineup generate an urgent email, subject `BAWs Fantasy Injury Watch | STARTER OUT`, and never at/after kickoff (requires more than 10 minutes of lead time). Eligible, Pending, injured bench and later game-status updates are dashboard-only. The fixed outgoing payload uses Resend idempotency and a persistent accepted-email record. If MFL's current lineup cannot be verified, alerts fail closed rather than guessing based on cached positions.
- **Safety boundary:** this feature is a **read-only NFL monitor** and does not change MFL lineup submissions or the separate automatic swap policy. The MFL polling job no longer emails on routine designation changes. Thursday/Sunday scheduled digests, verified substitution messages and pregame missing-lineup warnings remain separate. Confirmed eligible is distinct from verified participation/snaps, which would require a postgame boxscore or snap-count feed.
- **Verified live:** On Sunday November 22, 2026, NFL.com did not list Tennessee LB Anthony Hill Jr. as inactive against Dallas. The monitor marked him Eligible despite an MFL Questionable neck designation; a game-day status email was accepted by Resend and reached the configured Gmail inbox at 12:34 p.m. SK.

## Automatic lineup guard (November 18, 2026)
- Enabled separately in GitHub Actions: `.github/workflows/automatic-cffl-out-starter.yml` on the default branch. This workflow checks the NFL schedule before accessing MFL and can submit a single verified native-form lineup change at the pregame window.
- At most one nominal authenticated check about an hour before the earliest **Thursday** game and earliest **Sunday** game. GitHub's schedule itself runs at additional hourly candidate times to handle changing kickoff times and daylight saving; outside the due window it makes **no MFL requests**.
- Only currently selected **Out/Inactive** starters are eligible for removal. Use the highest average of the **last three recorded completed MFL league-scored weeks**, over at most six historical weeks, among healthy, actively rostered, same-position bench options whose NFL games have not begun. Questionable and Doubtful are excluded.
- If two starters are Out and only one has a valid replacement, fix the one and email about the other. Preserve all healthy starters. Do not retry or roll back ambiguous writes.
- A write is successful only when the saved authenticated MFL lineup matches the exact 17-player proposal. Send a Resend email about successful swaps, unresolved Out starters, or failures.
- The live automatic guard is limited to the **2026 season**, **CFFL league 40298**, **franchise 0001**. Its source is pinned to a tested commit. Manual dispatch of the workflow is read-only.
- Limitations: GitHub Actions schedules can run late or be missed; later Sunday games and late Out declarations after the one check are **not** covered; first live automatic swap for an actual Out starter and post-Thursday locked-player form behavior are not yet field-validated.
- Policy and detailed design: `docs/automatic-lineup-policy.md` on branch `feature/out-starter-guard`. Existing injury dashboard sync and digest are separate from lineup writes.

## Event log (November 18, 2026)
- Dashboard tab: https://williamsbryce.github.io/fantasy-injury-watch/#event-log
- Stores up to 200 UTC-timestamped, publicly visible operational records in `site/data/events.json`. Timestamps display in America/Regina on the website.
- Incoming events are written by GitHub Actions through `src/audit_log.py` using optimistic concurrency, an allowlisted event schema and deduplicated run IDs. The dashboard fetches the live public history from GitHub directly because commits made by GitHub's workflow token do not start additional publication runs.
- Injury-monitoring emails are recorded **only after Resend accepts the request**, which does not establish inbox delivery. Lineup guard records successful pregame checks, attempted submissions, exact saved-lineup verification, unresolved Out starters, and accepted notification emails.
- The automated guard now checks audit persistence before a live MFL lineup POST. Sensitive email addresses, credentials, MFL cookies and private response content are intentionally omitted from the public history. Recorded lineup player names are visible to visitors because this is a public dashboard.
- Logging started with a genuine activation event on November 18, 2026. No historic emails or lineup changes were retroactively invented. A maximum of 200 recent records is retained.

## Operating details
- MFL read-only API exports: `rosters`, `players`, `injuries`. Missing feed or invalid roster identity fails closed, preserves last working report and warns if stale.
- External news sources are optional: failure never suppresses or overwrites previously verified MFL injury designations. When a live MFL refresh fails, a separate step can update headline links without changing the last MFL sync timestamp.
- News coverage can be incomplete or delayed. The public webpage supplies more than the RSS feed's five latest updates, but this is still not an exhaustive official practice-participation feed. An MFL player-news link is always available.
- GitHub Actions controls synchronization and GitHub Pages deployment. MFL polls occur on a schedule or manual dispatch, not on every code change, to avoid needless throttling.
- Run tests: `python -m pip install -r requirements.txt && python -m unittest discover -s tests -v`.

## Follow-ups
- Monitor first scheduled Thursday/Sunday and urgent real alerts.
- Live headline matching verified for Josh Jacobs (November 17, 2026), one matching RotoWire item among seven rostered injury designations. Other players still have MFL news links; do not assume absence of news means healthy.
- Later add second MFL league/Sleeper and official NFL inactives separately.
