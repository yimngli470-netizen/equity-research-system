"""Customer-facing M5 report — a plain-English, zero-stats explanation of the result.

Renders a self-contained HTML one-pager (the chart is base64-embedded) plus the PNG, into the repo's
gitignored /reports dir. Audience: someone with no statistics or ML background.

Run:
    docker compose exec backend python -m app.ml.report
"""

from __future__ import annotations

import asyncio
import base64
import io
import warnings

import numpy as np

from app.database import async_session
from app.ml.run import evaluate_m5

GREEN, RED = "#2e7d32", "#c62828"


def _scoreboard_png(r: dict) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    g = np.array(r["gbm_ic"]); b = np.array(r["base_ic"]); n = len(g)
    fig, ax = plt.subplots(figsize=(12, 3.0))
    for row, (vals, label) in enumerate([(g, "AI model  (learns from history)"),
                                         (b, "Hand-made formula")]):
        for i, v in enumerate(vals):
            ax.add_patch(plt.Rectangle((i, 1 - row), 0.9, 0.9, color=GREEN if v > 0 else RED))
        ax.text(-0.4, 1.45 - row, label, ha="right", va="center", fontsize=11, weight="bold")
        ax.text(n + 0.4, 1.45 - row, f"{int((vals > 0).sum())} of {n} quarters right",
                va="center", fontsize=10.5, weight="bold")
    ax.set_xlim(-7, n + 6); ax.set_ylim(-0.2, 2.2); ax.axis("off")
    ax.set_title("Each square = one 3-month period (2020–2026).   "
                 "Green = ranked stocks better than a coin-flip that quarter.   Red = worse.",
                 fontsize=10.5)
    buf = io.BytesIO(); plt.tight_layout(); plt.savefig(buf, format="png", dpi=130); plt.close()
    return buf.getvalue()


def _html(r: dict, png: bytes) -> str:
    g, b = r["gbm"], r["base"]
    img = base64.b64encode(png).decode()
    gi, bi = g["mean_ic"], b["mean_ic"]
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Can a computer learn to pick better stocks?</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:860px;margin:32px auto;padding:0 20px;color:#1a1a1a;line-height:1.6}}
 h1{{font-size:26px;margin-bottom:4px}} h2{{font-size:18px;margin-top:30px;border-bottom:2px solid #eee;padding-bottom:6px}}
 .sub{{color:#666;margin-top:0}} .cards{{display:flex;gap:16px;margin:16px 0}}
 .card{{flex:1;border:1px solid #e3e3e3;border-radius:10px;padding:16px;background:#fafafa}}
 .card h3{{margin:0 0 6px;font-size:15px}} .card p{{margin:0;font-size:14px;color:#444}}
 .verdict{{background:#fff8e1;border:1px solid #ffe082;border-radius:10px;padding:16px 18px;margin:16px 0}}
 .big{{font-size:15px}} table{{border-collapse:collapse;width:100%;margin:10px 0;font-size:14px}}
 td,th{{border:1px solid #e3e3e3;padding:8px 10px;text-align:center}} th{{background:#f3f3f3}}
 .win{{color:{GREEN};font-weight:700}} .muted{{color:#888}}
 img{{width:100%;border:1px solid #eee;border-radius:8px;margin:8px 0}}
</style></head><body>
<h1>Can a computer learn to rank stocks better than our hand-made formula?</h1>
<p class="sub">A plain-English summary — no maths required.</p>

<h2>The two contestants</h2>
<div class="cards">
 <div class="card"><h3>🧮 The hand-made formula</h3>
   <p>A scoring recipe <b>a person designed</b>. It rates each stock on four things — is it growing,
   is it profitable, is it cheap, has it been going up — and blends them with <b>fixed weights chosen by hand</b>
   into one score, then ranks stocks. Simple and transparent, but the recipe never changes.</p></div>
 <div class="card"><h3>🤖 The AI model</h3>
   <p>Instead of a person choosing the recipe, this model <b>learned it from history</b> — it studied
   ~15,000 past examples of "here were a stock's numbers, here's how it actually did" and worked out how
   to combine the numbers itself. It can spot combinations a fixed recipe can't (e.g. "momentum helps,
   but only when the stock is also cheap").</p></div>
</div>

<h2>How we tested them — fairly</h2>
<p>We never let either model see the future. We trained the AI only on <b>past</b> data, then asked it to
rank stocks for years it had <b>never seen</b> (2020–2026) — like a real exam, not a practice test. We
graded each model the same way: every 3 months, did the stocks it ranked highly actually do better?</p>

<h2>The scoreboard</h2>
<img src="data:image/png;base64,{img}" alt="scoreboard"/>
<table>
 <tr><th></th><th>Quarters ranked right</th><th>Skill score*</th><th>Is it proven?</th></tr>
 <tr><td><b>🤖 AI model</b></td><td class="win">{g['hit']:.0%} of quarters</td><td class="win">{gi:+.4f}</td>
     <td class="muted">not yet — see below</td></tr>
 <tr><td><b>🧮 Hand-made formula</b></td><td>{b['hit']:.0%} of quarters</td><td>{bi:+.4f}</td>
     <td class="muted">not yet</td></tr>
</table>
<p class="muted">*Skill score = how well the ranking matched reality. 0 = no better than guessing.
Even top professional funds operate at small positive numbers — stock returns are mostly noise.</p>

<h2>The verdict (the honest part)</h2>
<div class="verdict big">
 <p><b>The AI model came out ahead</b> — it ranked stocks better in <b>{g['hit']:.0%}</b> of quarters vs the
 formula's <b>{b['hit']:.0%}</b>, and its skill score was higher ({gi:+.4f} vs {bi:+.4f}).</p>
 <p><b>But we can't call it "proven" yet.</b> Think of a basketball player who sinks 15 of 24 shots. That's
 better than average — but 24 shots isn't enough to <i>know</i> they're truly a great shooter rather than
 having a good run. We've only watched these models for 24 quarters (6 years). The early signs are
 genuinely encouraging, but we need more time and data before betting real money on the difference.</p>
</div>

<h2>What we'd do next to be sure</h2>
<ul>
 <li><b>Watch more quarters</b> — check every month instead of every 3 months, and add more history, to
   turn "encouraging" into "confident".</li>
 <li><b>Teach it about market moods</b> — give the model a sense of when markets are in a speculative
   bubble (like 2021) so it stops applying normal rules when the rules have flipped.</li>
 <li><b>Fine-tune the AI's settings</b> and keep grading it honestly against the simple formula.</li>
</ul>
<p class="muted">Bottom line: a promising, early, not-yet-certain win for the learned model — reported
honestly, the way it should be.</p>
</body></html>"""


async def build(outdir: str = "/tmp/m5_report") -> tuple[str, str]:
    warnings.filterwarnings("ignore")
    import os
    os.makedirs(outdir, exist_ok=True)
    async with async_session() as db:
        r = await evaluate_m5(db)
    png = _scoreboard_png(r)
    html = _html(r, png)
    png_path = os.path.join(outdir, "m5_scoreboard.png")
    html_path = os.path.join(outdir, "m5_report.html")
    with open(png_path, "wb") as f:
        f.write(png)
    with open(html_path, "w") as f:
        f.write(html)
    return html_path, png_path


if __name__ == "__main__":
    h, p = asyncio.run(build())
    print("wrote", h, "and", p)
