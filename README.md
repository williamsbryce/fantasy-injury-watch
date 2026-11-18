# Fantasy Injury Watch
Public, passwordless fantasy injury dashboard at https://williamsbryce.github.io/fantasy-injury-watch/.

## User-approved configuration (November 17, 2026)
- GitHub Pages report is intentionally **public**, with no passphrase on the website. The user explicitly accepted public roster-injury visibility to reduce friction.
- MFL API credentials and Resend API key remain GitHub Secrets and never reach the website.
- One MFL league, CFFL Dynasty, 2026, franchise 0001. Only active roster players are monitored; MFL IR/taxi excluded.
- MFL official injury designations are authoritative for this app's statuses, but they are not official kickoff inactive reports.
- An optional RotoWire **public NFL news page** provides recent matching injury and practice headlines, with a public NFL RSS fallback. A dated headline and publisher link appear only when there is a verified player-name match and an injury-specific item. Not all injured players have recent news; the application never invents an update.
- Each injury card links to the MFL player-news page. Access to article content on MFL's private league page may require a logged-in session.
- Recurring injury emails configured through `EMAIL_ENABLED=true`; Thursday after **5:00 p.m.** Saskatchewan and Sunday after **10:30 a.m.** Saskatchewan, with additional scheduled checks at those times (UTC 23:00 Thursday / 16:30 Sunday). Urgent designation changes still trigger during scheduled polls. Resend delivery verified 2026-11-17; GitHub Actions timing is best-effort.
- Roster/news reports are **public JSON**; prior encrypted report migrated once using the legacy secret before removal from the branch. Historical git commits retain the old encrypted payload.
- The dashboard itself remains read-only; a separate scheduled owner-authenticated lineup guard can replace confirmed Out/Inactive starters. No waiver, roster ownership, or healthy-starter optimization is allowed.

## Automatic lineup guard (November 18, 2026)
- Enabled separately in GitHub Actions: `.github/workflows/automatic-cffl-out-starter.yml` on the default branch. This workflow checks the NFL schedule before accessing MFL and can submit a single verified native-form lineup change at the pregame window.
- At most one nominal authenticated check about an hour before the earliest **Thursday** game and earliest **Sunday** game. GitHub's schedule itself runs at additional hourly candidate times to handle changing kickoff times and daylight saving; outside the due window it makes **no MFL requests**.
- Only currently selected **Out/Inactive** starters are eligible for removal. Use the highest average of the **last three recorded completed MFL league-scored weeks**, over at most six historical weeks, among healthy, actively rostered, same-position bench options whose NFL games have not begun. Questionable and Doubtful are excluded.
- If two starters are Out and only one has a valid replacement, fix the one and email about the other. Preserve all healthy starters. Do not retry or roll back ambiguous writes.
- A write is successful only when the saved authenticated MFL lineup matches the exact 17-player proposal. Send a Resend email about successful swaps, unresolved Out starters, or failures.
- The live automatic guard is limited to the **2026 season**, **CFFL league 40298**, **franchise 0001**. Its source is pinned to a tested commit. Manual dispatch of the workflow is read-only.
- Limitations: GitHub Actions schedules can run late or be missed; later Sunday games and late Out declarations after the one check are **not** covered; first live automatic swap for an actual Out starter and post-Thursday locked-player form behavior are not yet field-validated.
- Policy and detailed design: `docs/automatic-lineup-policy.md` on branch `feature/out-starter-guard`. Existing injury dashboard sync and digest are separate from lineup writes.

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
