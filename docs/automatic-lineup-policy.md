# Automatic CFFL lineup guard: user-approved policy (November 18, 2026)

## Scope

CFFL Dynasty 2026, league `40298`, franchise `0001`, current NFL week.
The only permitted automatic mutation is to replace a **confirmed Out or
Inactive** player who is ALREADY selected as a starter. Never optimize healthy
starters, never build a new lineup, and never select free agents.

## Replacement decision

1. Authenticate as the owner, obtain the 17 current starters from MFL's native
   lineup form and cross-check the active roster, current injury designation,
   players and current NFL schedule.
2. For each Out/Inactive starter whose own game has not kicked off, consider
   only an MFL-selectable, currently rostered, **same-position** player whose
   game is still ahead and who has no injury flag. Skip Questionable, Doubtful,
   unknown practice designations, IR, and taxi squad.
3. Rank eligible candidates by **mean fantasy points under CFFL's scoring**,
   using their **last three recorded weekly scores** from the previous six
   completed NFL weeks. A missing score does **not** become zero; a player
   with only one recorded score can be chosen if highest. Use observed-game
   count then player ID to break ties.
4. If some Out starters have no eligible replacement, replace each one that
   does. Email unresolved names separately. If zero eligible changes, never POST.
5. Re-fetch the native HTML right before submission; abort if the owner's
   selected starters have changed in the meantime. Build a full native POST
   retaining all 17 positions/unchanged players, hidden form state and submit
   controls; one POST maximum.
6. Re-fetch MFL and require the saved lineup to match the exact proposal
   before claiming success. Never automatically restore or retry a write;
   an ambiguous result triggers an urgent email.

## Timing

- Run only the single pregame window for the **earliest Thursday game** and
  the **earliest Sunday game** of the current NFL week.
- Hourly lightweight checks ask ESPN for the current schedule and skip MFL
  entirely unless the next kickoff is **35 through under 95 minutes away**.
  A half-open 60-minute gate allows at most one nominal hourly check per day.
- This adapts to Saskatchewan's year-round UTC-6 offset, Eastern daylight
  saving transitions, international Sunday games, and holiday Thursday games.
- GitHub Actions schedules are best-effort; a seriously delayed or missed
  schedule can miss the window. No second afternoon/night game check is
  authorized by this policy. Late Out designations after the first Sunday
  check can therefore be missed.

## Notifications

- **Successful substitutions:** email the exact players removed/added, recent
  scoring average and sample size, plus any unresolved Out starters.
- **No suitable replacement:** urgent email naming unresolved players.
- **Feed, login, schedule, form-validation or readback error:** urgent
  do-not-assume-success email. A post-write verification failure reports an
  **unverified write**, not an unchanged lineup.
- **No Out starters:** no email; routine Injury Watch digest remains separate.
- Use existing private GitHub Resend secret and ALERT_FROM / ALERT_TO variables.
  Never output a cookie, secret, raw private HTML or user login in workflow logs.

## Implementation

- Pure ranking: `src/recent_scores.py`, `src/auto_lineup_policy.py`.
- Dynamic kickoff gate: `src/auto_lineup_schedule.py`.
- Orchestration: `src/auto_lineup_guard.py`.
- Proven MFL form writer: `src/mfl_native_lineup.py`. The MFL
  `/import?TYPE=lineup` endpoint returned HTTP 200 but didn't save this
  league's lineup; the authenticated `/2026/lineup` POST was verified live
  and must be retained.
- Regression tests: `tests/test_auto_lineup_guard.py`,
  `tests/test_auto_lineup_integration.py`,
  `tests/test_native_mfl_lineup.py`.
- Owner's final rules: skip Questionable; same-position only; partial swaps
  allowed; rank by recent scoring; Thursday and earliest Sunday only.
- Current season is hard-coded **2026** as a deliberate safety boundary. Review
  for 2027 rather than silently acting on the wrong season.

## Validation

- Actual 2026 Week 11 authenticated MFL lineup and franchise ownership verified.
- Native one-way Cedric Gray -> Anthony Hill Jr. change was saved and verified
  on 2026-11-18 in the authorized test run 44388198234.
- Live read-only current-week check confirmed ESPN Week 11, 26 scheduled NFL
  teams, and historical CFFL `playerScores` records for Weeks 10 (1,038)
  and 9 (1,105), workflow 44408445290.
- No production automatic Out substitution has been exercised against a
  *real* Out starter. Synthetic integration tests cover a verified write,
  partial substitutions, owner changes, and readback failure.
