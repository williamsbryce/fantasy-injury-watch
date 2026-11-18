# Fantasy Injury Watch progress

## November 17, 2026
- User chose to remove the dashboard passphrase; GitHub Pages data is now designed to be public. API secrets remain only server-side.
- MFL login-only player news pages cannot be fetched unauthenticated. MFL player-specific news links can be opened by the signed-in user.
- Public RotoWire RSS verified in a GitHub Actions probe (HTTP 200, latest five NFL player articles including practice reports). Incorporated headline-only matching, links and dates, with cautious language that the feed is not exhaustive.
- Public JSON migration preserves notification deduplication from the last valid encrypted snapshot, avoiding false new-urgent alerts.
- Resend test email previously delivered and EMAIL_ENABLED=true verified by a separate workflow.
- Source changes must be tested in GitHub Actions and a real deployment validated before claiming the update is live.
