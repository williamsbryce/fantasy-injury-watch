# Fantasy Injury Watch: Decision and Progress Log

Updated: November 17, 2026

## User-approved direction
- Extremely streamlined, email-first injury monitoring dashboard.
- All fantasy leagues eventually, MFL first, then another MFL league and Sleeper.
- No projections, player search, large statistics header, or unnecessary dashboard navigation.
- No live lineup modification or credential exposure in public frontend.

## Implemented in this package
- Simple one-page iPhone/desktop UI with action/watch statuses and source timestamps.
- PBKDF2 + AES-GCM encrypted report file served on GitHub Pages, decrypted only in browser after passphrase entry.
- Official MFL read-only export client; joins roster, players, injuries by MFL player IDs.
- Excludes MFL IR/taxi players from active injury alerts to reduce noise.
- Stop on incomplete roster, unknown franchise, missing player identity mapping, missing injury feed.
- GitHub Actions schedule, safe encrypted report commit, optional Resend email.
- Automated tests using synthetic MFL fixtures, not live data.

## Not yet done
- No live MFL sync has run. Real feed shape and authorization must be verified with actual private league API responses.
- GitHub repository `williamsbryce/fantasy-injury-watch` is accessible through the connected GitHub integration with push permissions. Code installation initiated. GitHub Pages still needs configuration and the MFL API secret.
- GitHub secrets and environment variables have not been configured.
- Resend sender verification and email recipient not configured; no real email sent.
- Official inactive verification, news source links, starters/lineup status, and other leagues are not implemented.
- No changes to fantasy lineups will be performed.

## Next execution steps
1. Repository created and GitHub connector access granted. Commit project files.
2. Upload project to repo; configure the user's league identifiers as GitHub Actions variables and API key/passphrase as Secrets.
3. Run workflow manually, inspect logs, validate actual MFL roster and injury semantics.
4. Configure Resend and send a controlled test email, then confirm Thursday/Sunday schedule.
5. Add a second MFL league and Sleeper adapter only after first connection is reliable.

## Key architecture tradeoffs
- GitHub Pages is public, so actual private franchise roster reports are encrypted, adding a password step for the website. Email remains the default quick-alert channel.
- GitHub Actions schedules may be late, making this suitable for informative monitoring, not guaranteed last-minute inactive protection.
- MFL injury feed offers designations but cannot alone guarantee up-to-the-minute official NFL inactives.
