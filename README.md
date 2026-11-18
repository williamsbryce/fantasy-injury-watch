# Fantasy Injury Watch
Public, passwordless, read-only fantasy injury dashboard at https://williamsbryce.github.io/fantasy-injury-watch/.

## User-approved configuration (November 17, 2026)
- GitHub Pages report is intentionally **public**, with no passphrase on the website. The user explicitly accepted public roster-injury visibility to reduce friction.
- MFL API credentials and Resend API key remain GitHub Secrets and never reach the website.
- One MFL league, CFFL Dynasty, 2026, franchise 0001. Only active roster players are monitored; MFL IR/taxi excluded.
- MFL official injury designations are authoritative for this app's statuses, but they are not official kickoff inactive reports.
- An optional RotoWire NFL RSS feed provides **latest matching practice and injury headlines**. Headline, publisher, date and source link appear only if matched by player name and relevant terms. RSS feed is short and cannot guarantee every player has a news item. The app never invents news.
- Each injury card links to the MFL player-news page. Access to article content on MFL's private league page may require a logged-in session.
- Recurring injury emails configured through `EMAIL_ENABLED=true`; Thursday/Sunday after 9 a.m. Saskatchewan and urgent designation changes during scheduled polls. Delivery through Resend verified 2026-11-17; GitHub Actions timing is best-effort.
- Roster/news reports are **public JSON**; prior encrypted report migrated once using the legacy secret before removal from the branch. Historical git commits retain the old encrypted payload.
- No roster edits, no lineup modifications, no auto-substitution.

## Operating details
- MFL read-only API exports: `rosters`, `players`, `injuries`. Missing feed or invalid roster identity fails closed, preserves last working report and warns if stale.
- Public news RSS is optional: failure never suppresses actual MFL injury designations.
- News can be stale or absent if the RSS feed only includes the five newest updates. The MFL link is provided as a secondary source.
- GitHub Actions controls synchronization and GitHub Pages deployment.
- Run tests: `python -m pip install -r requirements.txt && python -m unittest discover -s tests -v`.

## Follow-ups
- Monitor first scheduled Thursday/Sunday and urgent real alerts.
- Validate live news matching against actual injured players.
- Later add second MFL league/Sleeper and official NFL inactives separately.
