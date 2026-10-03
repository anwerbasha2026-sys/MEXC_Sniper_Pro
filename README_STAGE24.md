# Stage 25 — Paper entry-quality gate + persistent entry diagnostics

This stage keeps the Stage 24 LIVE safety layer and adds the same entry-quality checks to Paper Trading so Paper results are closer to the conditions that would be accepted by LIVE. LIVE remains fail-closed and requires the GUI ARM LIVE action.

## What changed
- Paper entries now check maximum spread (default 0.20%).
- Paper entries now check entry drift from the READY signal reference price (default 0.30%).
- Paper entries now check top-ask coverage of the configured Paper order (default 50%).
- Every confirmed signal stores an entry-check record in SQLite with reference price, ask, spread, drift, top-ask coverage, simulated slippage, and the exact rejection reason.
- Diagnostics now show how many Paper alerts were rejected by the entry guard and the last entry-check result.
- The signal journal stores the entry diagnostics while keeping the existing Stage 20/21/24 history compatible.
- Existing LIVE protections remain: 0.30% max estimated slippage, 0.20% max spread, 0.30% max entry drift, and 50% minimum top-ask coverage.

## Recommended validation
Run PAPER first and inspect Diagnostics. A signal can have a score >= 80 and still be rejected if the entry becomes too expensive or the top of the book is too thin. This is intentional.

## LIVE safety
LIVE is not automatically armed. The GUI ARM LIVE action and the exact confirmation phrase are still required. The hard LIVE order ceiling remains 10 USDT.
