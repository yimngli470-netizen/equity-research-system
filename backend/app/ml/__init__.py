"""M5 ML track — the supervised ranker and its panel.

Deliberately thin and separate from the live app: the ML layer assembles a point-in-time panel from
the SAME functions the deterministic backtest uses (`app.backtest.panel`), so any learned model is
measured on identical footing to the hand-screen baseline (mean rank-IC +0.0174).
"""
