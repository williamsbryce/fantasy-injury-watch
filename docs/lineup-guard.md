# Out-starter lineup safeguard (development branch)

## Goal
Detect when a player marked **Out** or **Inactive** remains in an already
submitted starting lineup for CFFL Dynasty, then identify possible bench
replacements. Eventually the owner may authorize automated substitution.
No code in this branch calls MFL's write API or changes a lineup.

## What is implemented
- `src/lineup_guard.py` parses the starting-player IDs returned by the
  MFL `weeklyResults` export for a specified week/franchise.
- It cross-checks those IDs against the current active roster and the MFL
  injury feed and identifies starters with unavailable injury designations.
- It lists *preliminary* bench candidates at the same position, putting
  players without an injury designation ahead of flagged players.
- It preserves MFL player IDs with leading zeroes and refuses to infer
  starters from the `rosters` feed.
- Empty or missing lineups are **not** reported as healthy; inconsistent
  roster/lineup identity causes an error.
- Tests are synthetic; real league `weeklyResults` access has **not**
  been verified, and this module is **not** wired into the live sync.

## Agreed user policy (November 17, 2026)
- The owner reports MFL already prevents changing players whose game has locked. Do not make building a separate lock manager a prerequisite for the initial feature.
- Only run the lineup safety check roughly one hour before Thursday kickoff and one hour before Sunday early-game kickoff, rather than continuously auto-adjusting the roster.
- If a player in the current submitted starting lineup is confirmed **Out** or **Inactive**, preserve all other starters and replace only that player with the eligible bench player who has the **highest league scoring average**.
- Exclude candidates on bye weeks, on injured reserve or taxi squad, themselves Out/Inactive, or otherwise ineligible under league starting-position rules.
- Never rebuild a lineup from scratch or change a healthy starter. If no eligible candidate exists or the currently submitted lineup cannot be read accurately, make no change and notify the owner.
- The MFL website's UI restrictions are user-reported; authenticated API write semantics and full-lineup preservation still require verification before automatic writes can be safely enabled.

## Confirmed owner policy (November 17, 2026)
- Run one final pregame check about **one hour before Thursday kickoff**, and **one hour before Sunday noon Saskatchewan kickoffs**. This is separate from the digest email schedule.
- On the **submitted** starting lineup, replace only a starter confirmed **Out/Inactive**. Do not optimize or rearrange healthy starters.
- Select the eligible bench player with the **highest MFL league-scored points per game average** (to be verified through the `playerScores` AVG export). The replacement must satisfy league-specific starting slots, have an NFL game remaining that week, not be on bye and not be Out/Inactive.
- MFL is responsible for enforcing locked-player rules, with league cutoff understood as five minutes before each player's kickoff. Do not build a separate owner-facing lock-management interface.
- Nevertheless, the application must preserve **every other** current starter when making a full-lineup import; stop and alert if the league refuses the change, data is stale, or no safe replacement is available.
- Automatic lineup writing is **not active** and must not be enabled until real pregame data, complete import semantics and write authentication are verified.

## Verified MFL pregame read finding (November 17, 2026)
- The owner confirmed Week 12 starting lineup was already submitted.
- Live API tests authenticated with the existing league-level `MFL_API_KEY` showed `weeklyResults?W=12` had the owner franchise but **no starters**. Week 11 returned 17 submitted starters. `liveScoring?W=12` likewise exposed matchups but no starters.
- The native MFL **Starting Lineups** web report uses `options?L=40298&O=06&WEEK=12&F=0001`. An unauthenticated GitHub-hosted fetch is redirected to league web HTML with login messaging and **no table or player rows**. League API key alone is insufficient for this private pregame HTML page.
- The next dependency is a **separate authenticated owner session**, stored only in GitHub Actions Secrets and used server-side, to read pregame starting lineups. MFL's login endpoint can issue a session cookie; do not store any owner credential or cookie in the public repo or public dashboard.
- Until a real pregame lineup is retrieved and checked against the owner's submitted list, automatic writes must remain disabled. Never interpret missing starters as a blank user lineup.
- MFL `playerScores?W=AVG` returned 1,599 scoring-average records, each with a numeric score and player ID. MFL `league` export returned eight starting-position rule entries; MFL `nflSchedule?W=12` returned 16 games with team IDs and kickoff data. These are sufficient inputs for designing replacement selection once the lineup read is solved.

## Owner-login live verification (November 17, 2026)
- The owner added `MFL_OWNER_USERNAME` and `MFL_OWNER_PASSWORD` as GitHub Actions Secrets. Verified the login API returns a temporary `MFL_USER_ID` cookie, never printed or committed. The trusted PR diagnostic workflow runs read-only.
- MFL's authenticated `options?O=06` Starting Lineups overview returns league-level report tables but **does not expose current starter player IDs** in this league.
- A linked `options?O=07&F=0001` page returns 57 **franchise roster** player IDs. These are **not** the submitted starting lineup and must not be treated as starters.
- Authenticated `options?O=02` Submit Lineup HTML returns only the page shell, ten non-player checkbox controls, **zero HTML forms and zero player links**. Tested with `F`/`WEEK` present and absent. This is not yet a dependable lineup source.
- MFL's documented `myleagues` read path did not return a parseable `myleagues` root through either tested route; **this does not prove a user/franchise mismatch**. Account-to-franchise authorization remains unverified.
- Current blocker: obtain the **exact Submit Lineup page URL from the owner's signed-in browser**, without credentials or tokens, then determine which authenticated endpoint supplies that page's actual starter IDs. If the HTML is client-rendered, inspect the loading endpoint. Do not assume the form exists server-side.
- The user was told that owner login works, but **the live Week 12 lineup has not been extracted**. Do not merge automatic lineup writes. Last successful GitHub Actions owner diagnostic was read-only.

## Actual owner lineup URL: verified (November 18, 2026 UTC)
- Owner provided the exact signed-in MFL URL: `https://www46.myfantasyleague.com/2026/lineup?L=40298&FRANCHISE=0001`.
- This is the **correct** pregame lineup read endpoint. Prior `options?O=02` tests were targeting the wrong page.
- Authenticated read-only GET returns a POST form with **17 checked player selections**. The strict `src/submitted_lineup.py` parser successfully extracted 17 unique numeric starting player IDs and 53 selectable numeric player IDs without logging the IDs or any personal credentials. This matches the owner's submitted lineup count.
- Pure replacement planner in `src/lineup_replacements.py` filters out non-active roster entries, injury-flagged players, and teams without an NFL game, choosing the highest MFL league average from selectable same-position bench players. It creates a full proposed starter list while preserving every unchanged starter. All synthetic unit tests passed; the planner is **not wired into an active lineup writer**.
- GitHub Actions runs read-only, no POST to MFL lineup import. It does not write starting lineups or alter the live dashboard or alerts.
- The full live simulation is **not verified end-to-end yet** because MFL's `nflSchedule` export intermittently returns an error both with and without an API key. The separate MFL injuries export also intermittently fails, although one successful authenticated retry was verified. Keep automatic writes disabled.
- Next steps: obtain a dependable week's NFL team schedule/bye lookup, validate the lineup constraints and cached/fresh source timestamps, and implement a tightly gated lineup import with full-list preservation plus post-write verification. The import must never be enabled without tested success/failure handling and a manual stop switch.

## Correct current-week verification (November 18, 2026 UTC)
- Independent ESPN scoreboard Week 12 check retrieved **16 scheduled NFL games** and all 32 NFL teams; MFL legacy team abbreviations are now normalized and actual kickoff times are available for candidate screening. Four associated offline schedule tests passed.
- **Critical correction:** The user-supplied bare `/2026/lineup?L=40298&FRANCHISE=0001` URL currently defaults to **Week 11**, whose submitted lineup has 17 checked starters. The hidden `WEEK` field is 11. Those are NOT confirmed Week 12 starters.
- Authenticated `/2026/lineup?L=40298&FRANCHISE=0001&WEEK=12` and the `W=12` variation both return hidden form `WEEK=12` but **zero checked starters**. Owner previously believed Week 12 lineup had been submitted, so this must be resolved with owner before any test or automatic swap.
- The dry-run code now requires the form's week to equal the requested week before using its player IDs. It rejects both blank and stale lineups; no writes were attempted. Do not treat any prior 17-starter dry-run as Week 12 verification.
- The current main branch injury dashboard and all email summaries remain separate and unchanged. The feature branch has not been merged.
- Next requested action: owner should inspect the signed-in Week 12 lineup form, submit a valid set of starters, then intentionally test a known Out player in that week (well before kickoff). Obtain explicit approval of the exact target and eligible replacement before implementing/running a one-off write.
- Note: MFL injury export intermittently fails, so live automatic operation must also address freshness and fail closed. A one-off approved write test may independently verify the manually designated target, but should not bypass source checks for unattended automation.

## Still required before production activation
1. Retrieve the owner's **submitted upcoming starting lineup** through an authenticated MFL Starting Lineups report or equivalent source. Compare the result to the owner's known Week 12 lineup before relying on it; the league API key and pregame weeklyResults did not return starter IDs.
2. Fetch the league's actual starting-position limits and scoring/
   projections, then validate every proposed replacement against
   league-specific positions, FLEX/IDP rules and bye/game locks.
3. Verify NFL game starts and official inactive news independently.
   A missing injury record is **not** proof the player will play.
4. Ensure a proposed replacement leaves every other selected starter
   unchanged. Re-fetch the latest lineup immediately before any update,
   detect concurrent edits, and refuse changes if the read is stale.
5. Confirm user policy: alert only, approval before swapping, or
   automatic swap solely for confirmed Out/Inactive starters. Establish
   the deadline and an unambiguous replacement ranking rule.
6. Any future authenticated write must happen in server-side code with
   owner permission and audit logging, never through the public
   GitHub Pages site. MFL lineup import requires a valid owner session
   and sends the **complete** `STARTERS` list, replacing the week's
   previous lineup. API success must be checked from the response body.

## Related but separate: no lineup submitted
Some leagues begin each week with no starting lineup. Detecting and
restoring a previously approved or previous-week lineup is a distinct
feature. This first detector deliberately does not make up a lineup when
none has been submitted.
