# Fantasy Injury Watch

An email-first fantasy football injury monitor. **Read-only.** It cannot change MFL lineups. The site shows only injured rostered players, not projections or team performance data.

## Current project status (2026-11-17)

- Prepared one configurable MFL league (2026 by default); set the league and franchise IDs as GitHub repository variables before running.
- MFL parser, injury classification, encrypted dashboard, alert email client and GitHub Actions workflow implemented.
- Unit tests pass with **synthetic fixtures only**. Actual MFL access and email delivery have NOT yet been validated.
- GitHub repository access is now granted. Source files have been prepared for upload. No live sync or deployment has run.
- Pending: MFL credentials in Secrets, repository variables, registered API client name, GitHub Pages configuration, first live test, and then optional Resend email setup.

## How it works

1. GitHub Actions requests only the MFL `rosters`, `players`, and `injuries` exports.
2. The worker intersects injuries with your current franchise's roster by MFL player ID. Players already on MFL injured reserve or taxi squads are excluded to reduce unnecessary alerts. A missing feed, unknown franchise, or unmatched player ID causes an error instead of a false all-clear.
3. Optional Resend emails are sent for new *Out/Inactive/IR* status changes and one consolidated Thursday/Sunday summary after approximately 9 a.m. Saskatchewan time (scheduled GitHub Actions can run late).
4. A fresh **encrypted** report is written to `site/data/report.enc.json`. Only ciphertext is committed and served through GitHub Pages.
5. Enter your private dashboard passphrase in the website to decrypt locally in your browser. The passphrase is not stored or transmitted by the website.

## Set up in GitHub

1. The repository is `williamsbryce/fantasy-injury-watch`. Source code is installed separately from your older World Cup project. Never upload a raw roster JSON or any secret. Public GitHub Pages will serve only an encrypted report.
2. Settings → Secrets and variables → Actions → Repository secrets:
   - `MFL_API_KEY`: MFL owner API key for **this** league and season. Do not paste it into chat, HTML, code, issue descriptions or commits. Because the original key was shared in chat, rotating it is the safer practice.
   - `REPORT_PASSPHRASE`: A **unique, strong passphrase at least 16 characters long**. Remember it: it is required to open your dashboard. If changed, the existing encrypted state must be reset and alert deduplication will restart.
   - (When ready for emails) `RESEND_API_KEY`: created in Resend.
3. Settings → Secrets and variables → Actions → Repository variables (not secrets):
   - `MFL_LEAGUE_ID`: the five-digit league ID from your MFL URL.
   - `MFL_FRANCHISE_ID`: your four-digit franchise ID.
   - `MFL_LEAGUE_NAME`: the friendly league name shown after unlocking the dashboard.
   - `MFL_SEASON`: `2026`.
   - `MFL_CLIENT_NAME`: your registered MFL API client identifier. MFL says unregistered clients may be throttled. Register in MyFantasyLeague's API client setup page.
   - `ALERT_FROM`: verified Resend sending address.
   - `ALERT_TO`: the email address you want alerts delivered to.
4. Settings → Pages → Build and deployment → **Source: GitHub Actions**. The site is not live until you choose this and run the workflow successfully.
5. Actions tab → **Injury Watch (read-only)** → **Run workflow**. Review the job results. If GitHub Actions permissions block committing the encrypted status, allow read/write workflow permissions under repository Settings → Actions → General.
6. Open the Pages URL (after a successful deployment). Enter the dashboard passphrase. Confirm it shows the actual current injuries and the real sync timestamp.
7. For Resend, create an account at https://resend.com, verify a sender domain (or use a supported test sender to your own verified email), then configure the three email settings above and run the workflow again. Verify one real email before relying on alerts.

### Security limitations

- **Never put `MFL_API_KEY` in front-end code.** Only GitHub Actions reads it.
- The encrypted report file is publicly downloadable; it is protected by AES-256-GCM with PBKDF2-SHA256 (310,000 iterations) and a strong passphrase. Weak/reused passphrases create risk. The decrypted roster is visible in the browser you unlock.
- Emails reveal the private player alerts to your email provider and recipient mailbox. Be aware of this before enabling email.
- GitHub Actions scheduling is **best-effort**, not guaranteed at kickoff. This is **not** a substitute for official NFL inactive reports or a last-minute lineup safeguard. Recurring jobs are skipped until required league ID variables exist.
- MFL's injury feed is not a verified official NFL inactive feed and may lag team announcements. Alerts contain data sourced from MFL, not independently verified news articles.
- This version cannot establish who is a *starter* before kickoff. It monitors active-roster players, including bench players, but excludes MFL IR/taxi; starter detection requires a separately verified MFL lineup response.
- No automated lineup writes, purchases, or league setting changes exist in this code.

## Local testing

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

To do an actual sync locally, set environment variables `MFL_API_KEY`, `REPORT_PASSPHRASE`, `MFL_LEAGUE_ID`, and `MFL_FRANCHISE_ID` in your shell (never check them in) and run `python -m src.main`.

## Architecture decisions and next steps

| Decision | Current choice |
|---|---|
| Hosting | Existing GitHub ecosystem, GitHub Pages + GitHub Actions |
| Data source | MFL official read-only export API |
| First team | One MFL league configured through GitHub variables; no league identifiers committed |
| Privacy | Encrypted report served on public Pages, decrypted client-side |
| Notifications | Resend free plan, not activated until configured |
| Scheduled monitoring | GitHub Actions, not guaranteed real-time |
| Auto lineup modifications | Intentionally omitted |
| Follow-up | Add GitHub secrets/variables, run and verify actual feed shapes, connect email, add remaining leagues |

The initial worker supports **one league**. For additional leagues, the next iteration will support separate MFL API keys per league or a Sleeper read-only adapter. Do not assume this initial one-key worker supports multiple leagues yet.
