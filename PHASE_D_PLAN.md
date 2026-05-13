# Phase D — Multi-Strategy Ensemble Plan

Generated v6.37 by Plan agent.

## Goal
Replace single STRATEGY_MODE=BOTH (ADX hard-gate) with regime-weighted signal selection that adapts to market state with confidence-based sizing.

## Module Changes

### New
- `bot_v7/ensemble.py` (~120 lines):
  - `select_signal(d_sig, mr_sig, regime) -> chosen_sig`
  - `regime_size_mult(regime, confidence) -> float` (multiplier 0.5~1.0)
  - `should_close_on_regime_shift(pos, current_regime) -> bool`
  - Decision logger to journal
- `backtest/strategies/ensemble.py` — wrap D + MR_v5 + regime classifier
- `backtest/sweep_ensemble.py` — grid-search regime thresholds

### Modified
- `bot_v7/runner.py` (~40 LoC):
  - Call `ensemble.select_signal` after both evaluators
  - Pass regime to `_try_open` and `_manage`
  - Store `entry_regime` on position dict
  - Add `/ensemble` Telegram command
  - Auto-rollback check (every 120 loops)
  - Shadow-mode logging
- `bot_v7/config.py` (~10 lines):
  - `ENSEMBLE_MODE` env: `off | shadow | on`
  - Confidence thresholds, size multipliers
  - Auto-rollback PnL/win-rate gates

### Unchanged
- `bot_v7/strategy.py` (signals stay pure)
- `bot_v7/regime.py` (already returns confidence)

## Regime → Strategy Mapping

| Regime | Confidence | Active | Size |
|---|---|---|---|
| trending | ≥0.7 | D / D_INV only | 1.0× |
| trending | 0.5~0.7 | D preferred, MR fallback | 0.75× |
| ranging | ≥0.6 | MR only | 1.0× |
| mixed | 0.4 | both, MR preferred | 0.5× |
| unknown | - | conservative | 0.6× |

## Rollout Phases

1. **Phase 0** (current) — regime classifier observation only ✓
2. **Phase 1** — `ENSEMBLE_MODE=shadow` log decisions vs BOTH baseline (1 week)
3. **Phase 2** — `ENSEMBLE_MODE=on` + MAX_TOTAL_MARGIN=0.45 cap (1 week)
4. **Phase 3** — full size MAX_TOTAL_MARGIN=0.90

## Monitoring

- `/ensemble` command: 24h decision distribution, win-rate per regime bucket
- Auto-rollback: PnL < -3% OR win-rate < 30% over 3 days with N≥10 trades

## Implementation Order

When user wants to start:
1. Build `ensemble.py` core functions
2. Wire shadow mode in runner (1 week observation)
3. Activate small-size live (1 week)
4. Full size + monitor
5. Backtest ensemble version (parallel track)

## Out of scope (later)

- Cross-asset ensemble (BTC trending → ETH/SOL D weight)
- Dynamic threshold learning (regime cutoffs auto-tune from sweep)
- Multi-tier confidence (instead of binary trending/ranging)
