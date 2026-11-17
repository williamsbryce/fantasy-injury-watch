# Fantasy Injury Watch: Decision and Progress Log

Updated: November 17, 2026 (post first live run)

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
- Live MFL sync now completed successfully: seven real injury items returned for CFFL Dynasty (2026 league 40298, franchise 0001).
- GitHub repository and GitHub Pages deployment are working. Latest successful deployment: November 17, 2026, following workflow reliability improvements.
- Read-only MFL API key, report passphrase and league variables are configured as GitHub Secrets/variables. Email-specific configuration remains pending.
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

## First live run result (November 17, 2026)
- First MFL read-only live synchronization succeeded and encrypted 7 injury alerts for the first league.
- GitHub Pages artifact upload succeeded but deployment immediately afterward could not find artifact metadata, despite the artifact being present.
- A rerun shortly afterward failed because MFL returned an API error for its injuries export. The cause of that error has not been independently established; do not claim credentials were wrong or rate limiting is confirmed.
- Updated MFL client to use bounded retries and longer pacing, without logging authentication material.
- Split Pages deployment into a separate job and added an indexing delay. Deploy from the last encrypted successful report, even when a subsequent feed check fails. A failed sync still fails its job and sends failure notifications, appropriately.
- Live email delivery and real dashboard viewing are not yet verified. No lineup writes.

## Verification of corrected run
- Run https://github.com/williamsbryce/fantasy-injury-watch/actions/runs/44126586138 completed successfully (both sync and deploy jobs).
- New MFL transient-error retries recovered from an injuries-feed error; final real report contained 7 injury items.
- Ten automated tests passed. GitHub Pages reported success and environment URL https://williamsbryce.github.io/fantasy-injury-watch/.
- Website end-user passphrase unlock and separate email delivery are still to be checked.

## Email setup preparation (November 17, 2026)
- Dashboard passphrase unlock confirmed by user.
- Added a manual Run workflow test-email input. This sends exactly one test message, without marking the Thursday/Sunday digest as sent or enabling lineup modifications.
- Email remains inactive until the user creates Resend account, supplies GitHub RESEND_API_KEY Secret, ALERT_FROM and ALERT_TO variables, and explicitly runs a test.

## November 17: user verified live dashboard; notification prep
- User confirmed that live displayed CFFL injuries match the actual roster.
- Disabled automatic email delivery by default using EMAIL_ENABLED; manual single test is still available.
- Removed push-triggered MFL sync to reduce redundant requests during development. Scheduled/manual runs remain enabled.
- Added safe diagnostic classification of intermittent MFL API errors without disclosing error payloads or API keys.
- Added regression tests for the email activation gate and error classifier; these newly added tests have not yet been executed in a GitHub Actions run.
- Next user steps: register MFL API client and add GitHub MFL_CLIENT_NAME variable, create a Resend account and sending-only API key, configure ALERT_FROM / ALERT_TO, then run manual Send one test email.
- Ongoing email alerts should only be enabled after an actual inbox delivery succeeds and sender-domain setup is confirmed.
