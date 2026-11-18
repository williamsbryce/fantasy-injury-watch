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
