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

## Still required before production activation
1. Query a current-week `weeklyResults` export in a controlled,
   read-only GitHub workflow to determine whether MFL exposes an
   owner's **submitted current-week lineup** before games. Confirm that
   the current API key has sufficient *read* permissions.
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
