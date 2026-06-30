"""M5 report — a professional, learning-oriented write-up of the LightGBM screen-ranker.

Audience: the system owner learning ML + stats from the project. So it (a) names and defines the
real terms (rank-IC, t-stat, purged walk-forward, embargo…), and (b) is emphatic about WHERE M5
fits — it ranks the universe; it does NOT grade the LLM signal or the DCF price target.

Self-contained HTML (charts base64-embedded) written to /tmp by default.

Run:
    docker compose exec backend python -m app.ml.report
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import warnings

import numpy as np

from app.database import async_session
from app.ml.run import evaluate_m5

GREEN, RED, NAVY = "#2e7d32", "#c62828", "#16324f"

# Published reference: the hand-screen over ALL 36 periods (2017–2026), from backtest_runs id=1.
REF_IC, REF_T = 0.0174, 1.14


def _scoreboard_png(r: dict) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    g = np.array(r["gbm_ic"]); b = np.array(r["base_ic"]); n = len(g)
    fig, ax = plt.subplots(figsize=(12, 2.8))
    for row, (vals, label) in enumerate([(g, "LightGBM (learned ranker)"), (b, "Hand-screen (fixed weights)")]):
        for i, v in enumerate(vals):
            ax.add_patch(plt.Rectangle((i, 1 - row), 0.9, 0.9, color=GREEN if v > 0 else RED))
        ax.text(-0.4, 1.45 - row, label, ha="right", va="center", fontsize=11, weight="bold")
        ax.text(n + 0.4, 1.45 - row, f"IC>0 in {int((vals > 0).sum())}/{n}", va="center", fontsize=10.5, weight="bold")
    ax.set_xlim(-7.5, n + 5); ax.set_ylim(-0.2, 2.2); ax.axis("off")
    ax.set_title("Per-quarter sign of rank-IC (2020–2026).  Green = IC>0 (ranking beat chance that quarter), Red = IC<0.", fontsize=10)
    buf = io.BytesIO(); plt.tight_layout(); plt.savefig(buf, format="png", dpi=130); plt.close(); return buf.getvalue()


def _ic_chart_png(r: dict) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dates, g, b = r["test_dates"], r["gbm_ic"], r["base_ic"]
    x = np.arange(len(dates)); w = 0.4
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(x - w / 2, g, w, color="#1565c0", label=f"LightGBM  (mean {r['gbm']['mean_ic']:+.4f}, t={r['gbm']['t']:.2f})")
    ax.bar(x + w / 2, b, w, color="#9e9e9e", label=f"Hand-screen  (mean {r['base']['mean_ic']:+.4f}, t={r['base']['t']:.2f})")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(x[::2]); ax.set_xticklabels([dates[i][:7] for i in range(0, len(dates), 2)], rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("rank-IC"); ax.set_title("Out-of-sample rank-IC by quarter — LightGBM vs hand-screen (same 24 periods)")
    ax.legend(fontsize=9)
    buf = io.BytesIO(); plt.tight_layout(); plt.savefig(buf, format="png", dpi=130); plt.close(); return buf.getvalue()


def _per_fold(r: dict) -> list[tuple[int, str, str, float]]:
    ic = dict(zip(r["test_dates"], r["gbm_ic"]))
    out = []
    for k, a, z in r["folds"]:
        vals = [ic[d] for d in r["test_dates"] if a <= d <= z]
        out.append((k, a[:7], z[:7], float(np.mean(vals)) if vals else float("nan")))
    return out


def _imp_bars(r: dict) -> str:
    items = sorted(r["importances"].items(), key=lambda kv: -kv[1])
    mx = max(v for _, v in items) or 1
    rows = ""
    for name, v in items:
        pct = v / mx * 100
        rows += (f'<div class="ib"><span class="ibn">{name}</span>'
                 f'<span class="ibbar"><span style="width:{pct:.0f}%"></span></span></div>')
    return rows


STYLE = """<style>
 :root{--navy:#16324f;--ink:#1a1f24;--muted:#5b6b7a;--line:#e4e9ee;--green:#2e7d32;--red:#c62828}
 *{box-sizing:border-box} body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,sans-serif;color:var(--ink);
   max-width:880px;margin:36px auto;padding:0 22px;line-height:1.62;font-size:15px}
 h1{font-size:25px;color:var(--navy);margin-bottom:2px} h2{font-size:18px;color:var(--navy);margin-top:34px;
   border-bottom:2px solid var(--line);padding-bottom:6px} h3{font-size:15px;margin:18px 0 4px}
 .sub{color:var(--muted);margin-top:2px;font-size:14px}
 .def{border-left:3px solid var(--navy);background:#f6f9fc;padding:10px 14px;margin:12px 0;border-radius:0 6px 6px 0;font-size:14px}
 .def b{color:var(--navy)}
 table{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px} td,th{border:1px solid var(--line);padding:8px 10px}
 th{background:#f3f6f9;text-align:left;color:var(--navy)} td.n{text-align:right;font-variant-numeric:tabular-nums}
 .win{color:var(--green);font-weight:700} .neg{color:var(--red);font-weight:700} .muted{color:var(--muted)}
 img{width:100%;border:1px solid var(--line);border-radius:8px;margin:10px 0}
 .verdict{background:#fff8e1;border:1px solid #ffe082;border-radius:8px;padding:14px 18px;margin:14px 0}
 .fit td:first-child{font-weight:700;color:var(--navy)}
 .ib{display:flex;align-items:center;gap:10px;margin:3px 0;font-size:13px}
 .ibn{width:120px;color:var(--muted)} .ibbar{flex:1;background:#eef2f6;border-radius:4px;height:12px;overflow:hidden}
 .ibbar span{display:block;height:100%;background:#2e7d32}
 code{background:#eef2f6;padding:1px 5px;border-radius:4px;font-size:13px}
 .pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600}
 .p-yes{background:#e7f5e9;color:var(--green)} .p-no{background:#fdeaea;color:var(--red)}
</style>"""


def _html(r: dict, scoreboard: bytes, icchart: bytes) -> str:
    g, b = r["gbm"], r["base"]
    n = len(r["test_dates"])
    sb = base64.b64encode(scoreboard).decode()
    icc = base64.b64encode(icchart).decode()
    folds = "".join(
        f"<tr><td>Fold {k}</td><td>{a} &#8594; {z}</td>"
        f"<td class='n {'win' if m>0 else 'neg'}'>{m:+.4f}</td></tr>"
        for k, a, z, m in _per_fold(r)
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>M5 — Learned Stock-Ranking Model: Method, Results &amp; Scope</title>{STYLE}</head><body>

<h1>M5 — A Learned Stock-Ranking Model</h1>
<p class="sub">Method, results, and — importantly — what it does and does <i>not</i> measure. Internal research note.</p>

<h2>0 &middot; Read first: where this fits (and what it is NOT)</h2>
<p>The equity-research system emits <b>three different kinds of output</b>, each judged by a <b>different</b>
method. M5 (this report) is only the first one. Do not read M5's result as a verdict on the other two.</p>
<table class="fit">
 <tr><th>Output</th><th>Example</th><th>How its quality is judged</th><th>Back-testable?</th></tr>
 <tr><td>&#9312; Screen-rank<br><span class="muted">(quant composite)</span></td><td>"UBER sits ~60th pct of the universe"</td>
     <td><b>This report.</b> Cross-sectional <code>rank-IC</code> over history (LightGBM vs hand-screen)</td>
     <td><span class="pill p-yes">Yes</span></td></tr>
 <tr><td>&#9313; LLM decision<br><span class="muted">(signal + confidence)</span></td><td><b>"REDUCE"</b></td>
     <td>Thesis journal &#8594; grading &#8594; <b>calibration</b> (Brier score, reliability curve), <i>prospectively</i></td>
     <td><span class="pill p-no">No</span></td></tr>
 <tr><td>&#9314; Valuation<br><span class="muted">(DCF / price target)</span></td><td><b>"$64 in 12 months"</b></td>
     <td><b>Forecast accuracy</b> (forecast vs actual) + target-vs-realized, <i>prospectively</i></td>
     <td><span class="pill p-no">No</span></td></tr>
</table>
<div class="def"><b>Why &#9313; and &#9314; can't be back-tested.</b> Replaying the LLM over 2019 is fake — its training data
already "knows" how 2019 ended. And the price target is built from <i>forward</i> forecasts. So their track
records can only accrue <b>going forward</b>, by journaling today's calls and grading them as they come due.
That is a <i>different machine</i> (the accountability loop) from M5. <b>M5 says nothing about whether today's
UBER "REDUCE" or "$64" is right.</b></div>

<h2>1 &middot; Purpose &amp; idea of LightGBM here</h2>
<p>The screen-rank &#9312; is currently a <b>hand-screen</b>: a person chose fixed category weights (growth 20 %,
valuation 20 %, …) and the score is a weighted average of percentile-ranked features. M5 asks: <b>can a model
<i>learn</i> a better combination from history than the hand-set weights?</b></p>
<div class="def"><b>LightGBM</b> = a <b>gradient-boosted decision-tree</b> model: it builds hundreds of small
decision trees in sequence, each correcting the errors of the ones before it. It's the standard choice for
<i>tabular</i> data (rows &times; columns of numbers) because it captures <b>non-linearities</b> and <b>interactions</b>
("momentum helps, but only when the stock is also cheap") that a fixed weighted-average cannot — while staying
interpretable and data-efficient. We deliberately give it the <i>same</i> percentile-ranked features as the
hand-screen, so the only thing being tested is whether it <b>combines</b> them better.</div>

<h2>2 &middot; Method (and the terms)</h2>
<div class="def"><b>Point-in-time panel.</b> One row per (stock, quarter) = the features knowable <i>on that date</i>
&#8594; the stock's forward return. Fundamentals are gated by a 75-day reporting lag so no figure is used before it
was filed. <b>Avoiding this "lookahead" is failure-mode #1 in quant ML.</b></div>
<div class="def"><b>Label</b> (the answer key) = the stock's <b>forward 63-day excess return vs SPY</b> (&#8776;3 months,
market-relative). Features are <b>cross-sectionally rank-transformed</b> (each turned into its 0–1 percentile
within that date) — which removes outliers and keeps a feature's meaning stable across years.</div>
<div class="def"><b>Purged walk-forward cross-validation (CV).</b> Never shuffle time-series — that trains on the
future. Instead train on the <b>past</b>, test on the strictly-<b>later</b> block, slide forward. The <b>embargo</b>
drops the training rows whose forward-return window would overlap the test period (here, 1 quarter), so no future
leaks across the seam. We get <b>{n} truly out-of-sample (OOS) quarters</b>, 2020–2026.</div>

<h2>3 &middot; The metrics, defined (with our values)</h2>
<div class="def"><b>rank-IC (Information Coefficient).</b> The Spearman (rank) correlation, each quarter, between
the model's predicted ranking and the actual forward-return ranking. <b>+1</b> = perfect order, <b>0</b> = no skill,
<b>&#8722;1</b> = backwards. Reality is noisy: <b>0.02–0.05 is a genuinely good factor signal</b>; 0.3 would mean a bug.</div>
<div class="def"><b>t-stat.</b> Is the average IC real, or luck? <code>t = mean_IC / (std_IC / &#8730;periods)</code>.
Rule of thumb: <b>|t| &gt; 2 &#8776; 95 % confident it isn't luck.</b> With few periods, even a positive IC can have a
small (unconvincing) t-stat.</div>
<div class="def"><b>hit rate.</b> Share of quarters with IC &gt; 0 — a simple consistency check (50 % = coin-flip).</div>

<h2>4 &middot; Result ({n} OOS quarters, 2020–2026, true out-of-sample)</h2>
<table>
 <tr><th>Model</th><th>mean rank-IC</th><th>t-stat</th><th>hit rate</th></tr>
 <tr><td><b>LightGBM (learned)</b></td><td class="n win">{g['mean_ic']:+.4f}</td><td class="n">{g['t']:.2f}</td><td class="n">{g['hit']:.0%}</td></tr>
 <tr><td>Hand-screen (same periods)</td><td class="n">{b['mean_ic']:+.4f}</td><td class="n">{b['t']:.2f}</td><td class="n">{b['hit']:.0%}</td></tr>
 <tr><td class="muted">Hand-screen (all 36 periods, reference)</td><td class="n muted">{REF_IC:+.4f}</td><td class="n muted">{REF_T:.2f}</td><td class="n muted">—</td></tr>
</table>
<img src="data:image/png;base64,{icc}" alt="rank-IC by quarter"/>
<img src="data:image/png;base64,{sb}" alt="scoreboard"/>

<h3>Per-fold IC — note the regime dependence</h3>
<table>{folds}</table>
<p class="muted">Fold 2 (2021) is negative: the model, trained on pre-2021 "normal" markets, applied the usual
rules into the speculative-bubble year where they inverted. This <b>non-stationarity</b> is the core difficulty —
and the motivation for adding regime features (roadmap M3).</p>

<h3>Feature importance (avg across folds)</h3>
{_imp_bars(r)}
<p class="muted">Momentum and growth lead; <code>earnings_yield</code> (the E/P feature we built to replace the
2 %-coverage P/E) is heavily used — the feature-engineering paid off.</p>

<h2>5 &middot; Verdict — promising, not proven</h2>
<div class="verdict">
 <p>Over the same {n} OOS quarters, LightGBM beat the hand-screen on every measure: higher rank-IC
 (<b>{g['mean_ic']:+.4f}</b> vs {b['mean_ic']:+.4f}) and a higher hit rate (<b>{g['hit']:.0%}</b> vs {b['hit']:.0%}).</p>
 <p>But its <b>t-stat is {g['t']:.2f}</b>, well below 2 — so the edge, and the gap over the hand-screen, are
 <b>not statistically significant</b>. <b>Analogy:</b> a player who sinks {int(g['hit']*n)} of {n} shots is above
 average, but {n} shots isn't enough to <i>prove</i> they're a great shooter. <b>Encouraging, not yet conclusive.</b></p>
</div>

<h2>6 &middot; What would raise the t-stat toward "proven"</h2>
<ul>
 <li><b>More periods</b> — monthly rebalance (~3&times; the data) directly increases statistical power; longer history;
   and historical index constituents to remove survivorship bias.</li>
 <li><b>Regime features (M3)</b> — give the model a "what market regime is this?" input so it can stop applying
   normal rules in abnormal years like 2021.</li>
 <li><b>Tuning</b> (nested time-split) and a <b>ranking objective</b> (LightGBM <code>lambdarank</code>), since we
   only care about order.</li>
</ul>
<p class="muted">Scope reminder: everything here concerns output &#9312; only. The trustworthiness of a specific
"REDUCE / $64" call is the accountability loop's job (&#9313; and &#9314;), measured prospectively — not by M5.</p>
</body></html>"""


async def build(outdir: str = "/tmp/m5_report") -> tuple[str, str]:
    warnings.filterwarnings("ignore")
    os.makedirs(outdir, exist_ok=True)
    async with async_session() as db:
        r = await evaluate_m5(db)
    sb, icc = _scoreboard_png(r), _ic_chart_png(r)
    html = _html(r, sb, icc)
    html_path = os.path.join(outdir, "m5_report.html")
    png_path = os.path.join(outdir, "m5_scoreboard.png")
    with open(html_path, "w") as f:
        f.write(html)
    with open(png_path, "wb") as f:
        f.write(sb)
    return html_path, png_path


if __name__ == "__main__":
    h, p = asyncio.run(build())
    print("wrote", h, "and", p)
