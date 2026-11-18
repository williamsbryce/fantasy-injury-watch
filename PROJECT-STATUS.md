# Fantasy Injury Watch progress

## November 17, 2026 deployment: passwordless dashboard and injury news
- User approved eliminating the site passphrase in exchange for intentionally public roster/injury information. GitHub Pages now uses a public JSON report and opens directly with no password. MFL and Resend API keys remain server-side GitHub Secrets.
- Previous encrypted report was migrated once so the existing notification digest state could be preserved. Old encrypted report removed from active branch, although historical Git commits remain.
- MFL private-league player news page redirects to login for unauthenticated visitors. Each rostered injury player has a direct MFL player-news link for the user's logged-in browser.
- Added optional public RotoWire headlines from https://www.rotowire.com/football/news.php, with NFL RSS fallback. Match injury-specific updates by exact player name, show the dated headline and publisher link without scraping subscriber-only commentary.
- Verified live Josh Jacobs RotoWire headline “Could be back for Week 12” dated November 17. One match among seven currently rostered injury alerts; other alerts correctly show no recent match and retain MFL links.
- Latest completed live MFL injury sync was November 17 at 6:21 p.m. Saskatchewan, reporting seven injuries. Later intermittent MFL injuries API throttling/errors do not turn the report into a false all-clear; cached injury timestamp is retained.
- Added a fallback that updates public news headlines and MFL links on cached injury records if live MFL synchronization fails. It does not send notifications or change the injury data freshness timestamp.
- Automated parser, email, migration and public news tests passed in the GitHub workflow. GitHub Pages deployed current public report successfully in workflow run 44207630809 even when the source sync subsequently failed.
- Resend test email was delivered, and repository variable EMAIL_ENABLED=true was verified. The first scheduled Thursday/Sunday injury summary has not yet been confirmed.
- Returned MFL sync to scheduled/manual only; removed temporary HTML/RSS diagnostic workflow.
- No write access to fantasy rosters, player substitutions or starting lineups is implemented.

## Ongoing constraints
- RotoWire public news is neither exhaustive nor a substitute for official NFL inactive confirmations; some injury cards will only have MFL status and an MFL news link.
- GitHub Actions scheduling is best-effort; MFL calls may be throttled or fail intermittently.
- Main site: https://williamsbryce.github.io/fantasy-injury-watch/
