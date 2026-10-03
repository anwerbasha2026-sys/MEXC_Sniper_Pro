# Stage 26 Windows - Reduced Conditions Release

This release keeps the same trading logic, persistent Paper Trading journal,
Max DD/risk tracking, signal journal, stablecoin exclusion, and LIVE safety
lock. Only signal-capture and PAPER entry guards are relaxed.

## Reduced scanner conditions
- Strong/trigger score: 65
- Ready score: 55
- Reset score: 50
- Confirmations: 1
- Cooldown: 20 seconds
- Stale data limit: 5000 ms

## Reduced PAPER entry guards
- Max spread: 0.40%
- Max entry drift: 0.60%
- Minimum top-ask coverage: 25%

## Safety
- PAPER mode remains the default.
- LIVE remains fail-closed and runtime locked.
- Stablecoin exclusion remains enabled.
- Stop-loss/take-profit values are unchanged.
