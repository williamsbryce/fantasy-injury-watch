# Fantasy Injury Watch
Public, passwordless, read-only fantasy injury dashboard at https://williamsbryce.github.io/fantasy-injury-watch/.

## User-approved configuration (November 17, 2026)
- GitHub Pages report is intentionally **public**, with no passphrase on the website. The user explicitly accepted public roster-injury visibility to reduce friction.
- MFL API credentials and Resend API key remain GitHub Secrets and never reach the website.
- One MFL league, CFFL Dynasty, 2026, franchise 0001. Only active roster players are monitored; MFL IR/taxi excluded.
- MFL official injury designations are authoritative for this app's statuses, but they are not official kickoff inactive reports.
- An optional RotoWire **public NFL news page** provides recent matching injury and practice headlines, with a public NFL RSS fallback. A dated headline and publisher link appear only when there is a verified player-name match and an injury-specific item. Not all injured players have recent news; the application never invents an update.
- Each injury card links to the MFL player-news page. Access to article content on MFL's private league page may require a logged-in session.
- Recurring injury emails configured through `EMAIL_ENABLED=true`; Thursday after **5:00 p.m.** Saskatchewan and Sunday after **10:30 a.m.** Saskatchewan, with additional scheduled checks at those times (UTC 23:00 Thursday / 16:30 Sunday). Urgent designation changes still trigger during scheduled polls. Resend delivery verified 2026-11-17; GitHub Actions timing is best-effort.
- Roster/news reports are **public JSON**; prior encrypted report migrated once using the legacy secret before removal from the branch. Historical git commits retain the old encrypted payload.
- No roster edits, no lineup modifications, no auto-substitution.

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
