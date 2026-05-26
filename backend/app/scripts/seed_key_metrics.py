"""Seed per-ticker key metrics for the current watchlist.

Idempotent — uses ON CONFLICT DO UPDATE on (ticker, metric_name). Re-running
refreshes definitions/targets but won't duplicate.

Run from inside the backend container:
    docker compose exec backend python -m app.scripts.seed_key_metrics

To add a new ticker, append to KEY_METRICS below and re-run.
"""

import asyncio
import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.key_metric import TickerKeyMetric

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# Hand-picked KPIs per ticker. Priority 1 = highest. Keep to 4-6 per name —
# more than that and the agent's output becomes noise.
KEY_METRICS: dict[str, list[dict]] = {
    "NVDA": [
        {
            "metric_name": "Data Center revenue YoY",
            "definition": "Year-over-year growth in Data Center segment revenue (Blackwell + Hopper + networking).",
            "why_it_matters": "Largest segment (~85% of revenue) and the primary AI growth engine. Inflects on each new GPU generation.",
            "target_or_threshold": ">40% YoY indicates strong AI demand",
            "priority": 1,
        },
        {
            "metric_name": "Non-GAAP gross margin",
            "definition": "Non-GAAP gross margin %. Excludes stock-based comp and acquisition charges.",
            "why_it_matters": "Tracks GPU pricing power vs HBM/CoWoS cost pressure. Below 70% would signal margin compression.",
            "target_or_threshold": "Mid-70s% by year-end is current management guide",
            "priority": 1,
        },
        {
            "metric_name": "Blackwell mix",
            "definition": "Share of Data Center compute revenue from Blackwell architecture (vs Hopper).",
            "why_it_matters": "Generational ramp speed. Blackwell carries higher ASPs and richer system attach (NVL72 racks).",
            "target_or_threshold": "Trending toward 100% as Hopper rolls off",
            "priority": 2,
        },
        {
            "metric_name": "China revenue",
            "definition": "Quarterly revenue attributed to China, net of H20 export-control headwinds.",
            "why_it_matters": "$50B addressable market at risk. Future guidance ex-China is the real demand signal.",
            "target_or_threshold": "Material upside requires US export-license relaxation",
            "priority": 2,
        },
        {
            "metric_name": "Networking revenue",
            "definition": "Spectrum-X / NVLink / InfiniBand networking attach revenue per quarter.",
            "why_it_matters": "Validates the rack-scale story — when customers buy full racks, networking grows faster than GPUs.",
            "target_or_threshold": "Outgrowing compute revenue = healthy mix shift",
            "priority": 3,
        },
    ],
    "AMD": [
        {
            "metric_name": "Data Center revenue YoY",
            "definition": "Year-over-year growth in Data Center segment (EPYC server CPUs + Instinct MI3xx/MI4xx GPUs).",
            "why_it_matters": "Primary AI competitive battleground vs NVDA and intel. Where the multiple expansion lives.",
            "target_or_threshold": "Management targets >60% annual data center growth over 3-5 years",
            "priority": 1,
        },
        {
            "metric_name": "MI3xx / MI4xx revenue or run-rate",
            "definition": "Quarterly Instinct GPU revenue or implied annual run-rate from management commentary.",
            "why_it_matters": "Direct measure of AI accelerator traction. MI450 generational ramp expected in 2H 2026.",
            "target_or_threshold": "Tens of billions in annual AI revenue by 2027 (mgmt guide)",
            "priority": 1,
        },
        {
            "metric_name": "Server CPU share gain",
            "definition": "EPYC share trajectory in server CPU market (revenue or unit share).",
            "why_it_matters": "Steady share take from Intel funds R&D for the AI fight. Fifth-gen TURIN is the current vehicle.",
            "target_or_threshold": "Server CPU TAM expanding to >$120B by 2030 (mgmt)",
            "priority": 2,
        },
        {
            "metric_name": "Non-GAAP gross margin",
            "definition": "Non-GAAP gross margin %. AMD reports both GAAP and non-GAAP; non-GAAP is the comparable measure.",
            "why_it_matters": "Data center mix shift is margin-accretive; client/gaming dilutes. Trajectory toward 56-57% is the bull case.",
            "target_or_threshold": "Above 55% non-GAAP indicates healthy mix",
            "priority": 2,
        },
        {
            "metric_name": "Embedded design wins",
            "definition": "Annual or quarterly value of embedded (Xilinx) design wins disclosed by management.",
            "why_it_matters": "Forward-looking backlog signal for the embedded segment, which has been a drag recently.",
            "target_or_threshold": "$17B+ annual = healthy",
            "priority": 4,
        },
    ],
    "MU": [
        {
            "metric_name": "HBM revenue",
            "definition": "Quarterly High Bandwidth Memory (HBM3E / HBM4) revenue.",
            "why_it_matters": "The single biggest growth driver — every AI GPU needs HBM and Micron is one of three suppliers. Sold out through 2026.",
            "target_or_threshold": "Sequentially up every quarter through 2026",
            "priority": 1,
        },
        {
            "metric_name": "DRAM ASP trend",
            "definition": "Average selling price trend for DRAM, blended across DDR/LPDDR/HBM mix.",
            "why_it_matters": "Memory is a commodity cycle business — ASP direction predicts gross margin direction with ~1Q lag.",
            "target_or_threshold": "Rising = bull cycle; falling = bear cycle",
            "priority": 1,
        },
        {
            "metric_name": "NAND ASP trend",
            "definition": "Average selling price trend for NAND flash, separately from DRAM.",
            "why_it_matters": "NAND has its own cycle. Weak NAND can offset strong DRAM and confuse the headline.",
            "target_or_threshold": "Stable-to-rising preferred",
            "priority": 2,
        },
        {
            "metric_name": "Capex / wafer capacity guidance",
            "definition": "Full-year capex guide and any commentary on wafer-start cuts/additions for DRAM and NAND.",
            "why_it_matters": "Industry supply discipline is the single biggest determinant of forward ASPs. Watch peer behavior too.",
            "target_or_threshold": "Disciplined capex from all three players = bullish",
            "priority": 2,
        },
        {
            "metric_name": "Inventory days",
            "definition": "Days of inventory on hand (DSI), trend QoQ.",
            "why_it_matters": "Falling DSI in a strong demand environment = tightness = ASP power. Rising DSI = oversupply risk.",
            "target_or_threshold": "Stable or falling preferred",
            "priority": 3,
        },
    ],
    "AVGO": [
        {
            "metric_name": "AI revenue (custom silicon + networking)",
            "definition": "Quarterly AI-related revenue: custom ASICs (XPUs for Google/Meta) plus AI networking silicon.",
            "why_it_matters": "The thesis — AVGO's hyperscaler ASIC business is the main alternative to NVDA in the largest customers' rosters.",
            "target_or_threshold": "Mgmt has guided $60-90B SAM by 2027",
            "priority": 1,
        },
        {
            "metric_name": "VMware operating margin",
            "definition": "Software segment operating margin, mostly driven by VMware post-acquisition.",
            "why_it_matters": "VMware integration thesis — Hock Tan's playbook is to ramp margins to 60%+.",
            "target_or_threshold": "60%+ steady-state",
            "priority": 2,
        },
        {
            "metric_name": "Semiconductor segment YoY",
            "definition": "Year-over-year growth in semiconductor solutions revenue.",
            "why_it_matters": "Cyclical wireless / broadband / storage businesses outside AI — the non-AI baseline.",
            "target_or_threshold": "Flat-to-positive = healthy cycle",
            "priority": 3,
        },
        {
            "metric_name": "Free cash flow per quarter",
            "definition": "Quarterly free cash flow, in absolute dollars.",
            "why_it_matters": "AVGO is a capital-return story — FCF directly funds dividends and buybacks.",
            "target_or_threshold": "Above $7B/quarter sustained",
            "priority": 3,
        },
    ],
    "GOOGL": [
        {
            "metric_name": "Search revenue YoY",
            "definition": "Year-over-year growth in Search & other ads revenue.",
            "why_it_matters": "The cash engine. AI disruption risk lives here — declining growth = AI search erosion thesis.",
            "target_or_threshold": "10%+ YoY indicates AI is additive not cannibalizing",
            "priority": 1,
        },
        {
            "metric_name": "Google Cloud revenue + operating margin",
            "definition": "GCP revenue YoY and segment operating margin.",
            "why_it_matters": "Second-largest opportunity. Margin expansion proves the cloud is genuinely durable, not just discounted compute.",
            "target_or_threshold": "30%+ YoY growth, 15%+ margin",
            "priority": 1,
        },
        {
            "metric_name": "Capex guidance",
            "definition": "Annual capex guide, especially AI infrastructure spending.",
            "why_it_matters": "Tells you the company's own conviction in AI demand. Step-ups indicate hyperscaler AI race intensifying.",
            "target_or_threshold": "Sustained increase = bullish on cloud demand",
            "priority": 2,
        },
        {
            "metric_name": "YouTube ads + subscriptions",
            "definition": "YouTube advertising revenue plus subscription revenue (Premium, NFL Sunday Ticket, etc).",
            "why_it_matters": "Second growth pillar; less AI-disruptable than Search.",
            "target_or_threshold": "10%+ YoY",
            "priority": 3,
        },
    ],
    "META": [
        {
            "metric_name": "Ad revenue YoY",
            "definition": "Year-over-year growth in family of apps ad revenue.",
            "why_it_matters": "Core monetization. AI-driven recommendation improvements are the current growth lever.",
            "target_or_threshold": "15%+ YoY = strong",
            "priority": 1,
        },
        {
            "metric_name": "Capex (AI infrastructure)",
            "definition": "Annual capex guide, especially the AI-infrastructure component.",
            "why_it_matters": "Meta's open-source Llama strategy depends on training infrastructure. Capex trajectory = AI commitment.",
            "target_or_threshold": "Sustained step-ups expected",
            "priority": 1,
        },
        {
            "metric_name": "Reality Labs operating loss",
            "definition": "Reality Labs segment operating loss per quarter.",
            "why_it_matters": "The market hates the magnitude. Narrowing losses (or a credible product traction signal) re-rates the stock.",
            "target_or_threshold": "Loss narrowing QoQ = bullish",
            "priority": 2,
        },
        {
            "metric_name": "DAP (Daily Active People) across family",
            "definition": "Family-of-apps daily active people, YoY change.",
            "why_it_matters": "Engagement growth = ad inventory growth. The denominator behind every other metric.",
            "target_or_threshold": "Up YoY",
            "priority": 3,
        },
    ],
    "AMZN": [
        {
            "metric_name": "AWS revenue YoY + operating margin",
            "definition": "AWS segment revenue growth and operating margin.",
            "why_it_matters": "Operating-income engine. Growth re-acceleration above 20% drives the multiple.",
            "target_or_threshold": "20%+ YoY growth, 35%+ margin = bullish",
            "priority": 1,
        },
        {
            "metric_name": "Retail operating margin (NA + Intl)",
            "definition": "North America + International retail segment operating margin (or absolute operating income).",
            "why_it_matters": "Decades of underperformance turning a corner — incremental margin improvement is asymmetric upside.",
            "target_or_threshold": "Mid-single-digit margin sustained",
            "priority": 2,
        },
        {
            "metric_name": "Advertising revenue YoY",
            "definition": "Advertising services revenue YoY growth.",
            "why_it_matters": "Highest-margin business, growing fast and silently. Becoming a meaningful slice of operating income.",
            "target_or_threshold": "20%+ YoY",
            "priority": 2,
        },
        {
            "metric_name": "Capex / AI infrastructure spend",
            "definition": "Annual capex guide and commentary on AI infrastructure investment.",
            "why_it_matters": "Tells you AWS's GPU/Trainium buildout pace, which gates near-term AWS revenue capacity.",
            "target_or_threshold": "Sustained step-ups",
            "priority": 3,
        },
    ],
    "TSLA": [
        {
            "metric_name": "Auto gross margin (ex-credits)",
            "definition": "Automotive segment gross margin excluding regulatory credit sales.",
            "why_it_matters": "The cleanest read on unit economics. Price cuts hit here first; FSD revenue lifts it.",
            "target_or_threshold": "20%+ ex-credits = strong",
            "priority": 1,
        },
        {
            "metric_name": "Vehicle deliveries YoY",
            "definition": "Total vehicle deliveries year-over-year.",
            "why_it_matters": "Volume × price = revenue. Volume growth funds the AI/robotics thesis.",
            "target_or_threshold": "Positive YoY required to defend growth narrative",
            "priority": 1,
        },
        {
            "metric_name": "Energy storage deployments (GWh)",
            "definition": "Quarterly energy storage deployments in gigawatt-hours.",
            "why_it_matters": "Highest-growth and most profitable segment. Megapack backlog through 2026+.",
            "target_or_threshold": "Up sequentially every quarter",
            "priority": 2,
        },
        {
            "metric_name": "FSD / robotaxi commentary",
            "definition": "Management commentary on FSD adoption, robotaxi rollout cities, regulatory progress.",
            "why_it_matters": "The whole optionality bull case. Watch for concrete dates, take-rate data, miles-per-intervention figures.",
            "target_or_threshold": "Concrete metrics > vibes",
            "priority": 2,
        },
        {
            "metric_name": "Free cash flow",
            "definition": "Quarterly free cash flow.",
            "why_it_matters": "Funds the AI / Optimus / next-gen vehicle bets without dilution.",
            "target_or_threshold": "Positive every quarter",
            "priority": 3,
        },
    ],
    "UBER": [
        {
            "metric_name": "Gross bookings YoY (Mobility + Delivery)",
            "definition": "Year-over-year gross bookings growth, broken out by segment.",
            "why_it_matters": "Top-of-funnel. Mobility growth = pricing power; Delivery growth = category expansion.",
            "target_or_threshold": "Mid-teens YoY constant currency",
            "priority": 1,
        },
        {
            "metric_name": "Adjusted EBITDA margin (% of bookings)",
            "definition": "Adjusted EBITDA as a percentage of gross bookings.",
            "why_it_matters": "The unit economics story — every percentage point of margin expansion adds billions of EBITDA at scale.",
            "target_or_threshold": "Trending toward mid-single-digits of bookings",
            "priority": 1,
        },
        {
            "metric_name": "Monthly Active Platform Consumers (MAPC)",
            "definition": "Monthly active platform consumers, YoY change.",
            "why_it_matters": "Network effects denominator — more users = better matching = lower take-rate needed.",
            "target_or_threshold": "Up YoY",
            "priority": 2,
        },
        {
            "metric_name": "AV / robotaxi partnership commentary",
            "definition": "Updates on Waymo, autonomous trips per week, and pipeline AV partners.",
            "why_it_matters": "AV story is the long-term re-rate driver. Watch trips/week trajectory in active markets.",
            "target_or_threshold": "Trips/week growing fast",
            "priority": 3,
        },
    ],
    "INTU": [
        {
            "metric_name": "Small Business & Self-Employed revenue YoY",
            "definition": "SBSE segment revenue YoY (QuickBooks, Mailchimp, payments, payroll).",
            "why_it_matters": "Largest segment and growth engine. Reflects SMB health + QBO platform expansion.",
            "target_or_threshold": "Mid-teens YoY",
            "priority": 1,
        },
        {
            "metric_name": "Consumer Group revenue (TurboTax)",
            "definition": "Consumer segment revenue, especially during Q2/Q3 (tax season).",
            "why_it_matters": "Tax season makes or breaks the year. Watch share vs free filers and pricing/mix.",
            "target_or_threshold": "Up YoY during tax season",
            "priority": 1,
        },
        {
            "metric_name": "Credit Karma revenue YoY",
            "definition": "Credit Karma segment revenue, sensitive to lending environment.",
            "why_it_matters": "Cyclical exposure to consumer lending. Recovery in CC/auto loans helps; recession hurts.",
            "target_or_threshold": "Returning to growth = bullish",
            "priority": 2,
        },
        {
            "metric_name": "GenAI / Intuit Assist commentary",
            "definition": "Management commentary on GenAI adoption, monetization mechanism, and platform usage.",
            "why_it_matters": "AI is both a moat (incumbent data advantage) and a threat (vertical AI agents). Watch concrete metrics.",
            "target_or_threshold": "Concrete adoption + monetization data > generic mentions",
            "priority": 2,
        },
        {
            "metric_name": "Operating margin",
            "definition": "Non-GAAP operating margin, full company.",
            "why_it_matters": "INTU is a high-quality compounder — margin expansion is the long-term re-rate driver.",
            "target_or_threshold": "Expanding YoY",
            "priority": 3,
        },
    ],
    "MRVL": [
        {
            "metric_name": "Data Center revenue YoY",
            "definition": "Data center segment revenue YoY (custom silicon for hyperscalers + optics).",
            "why_it_matters": "The AI custom-ASIC thesis — Marvell competes with AVGO for hyperscaler XPU sockets. AWS Trainium, Microsoft Maia.",
            "target_or_threshold": "40%+ YoY = strong",
            "priority": 1,
        },
        {
            "metric_name": "AI revenue mix",
            "definition": "Share of total revenue from AI-related products (custom silicon + AI networking optics).",
            "why_it_matters": "Mix shift to AI drives both growth and margin. Non-AI businesses are flat-to-declining.",
            "target_or_threshold": "Mgmt guides AI to majority of revenue medium-term",
            "priority": 1,
        },
        {
            "metric_name": "Non-GAAP gross margin",
            "definition": "Non-GAAP gross margin percentage.",
            "why_it_matters": "Custom ASIC business carries lower margins than catalog products — mix has been a headwind. Watch for stabilization.",
            "target_or_threshold": "Defending 60%+ non-GAAP",
            "priority": 2,
        },
        {
            "metric_name": "Hyperscaler customer concentration",
            "definition": "Disclosed customer concentration (e.g., AWS as % of revenue) and design-win pipeline beyond current tier-1s.",
            "why_it_matters": "Single-customer risk — losing a hyperscaler socket would be material. Diversification is bullish.",
            "target_or_threshold": "Expanding hyperscaler base = bullish",
            "priority": 3,
        },
    ],
}


async def _seed(db: AsyncSession) -> None:
    rows = []
    for ticker, metrics in KEY_METRICS.items():
        for m in metrics:
            rows.append({"ticker": ticker, **m})

    if not rows:
        logger.info("No key metrics to seed")
        return

    stmt = insert(TickerKeyMetric).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_key_metric_ticker_name",
        set_={
            "definition": stmt.excluded.definition,
            "why_it_matters": stmt.excluded.why_it_matters,
            "target_or_threshold": stmt.excluded.target_or_threshold,
            "priority": stmt.excluded.priority,
        },
    )
    await db.execute(stmt)
    await db.commit()

    per_ticker = {t: len(m) for t, m in KEY_METRICS.items()}
    logger.info("Seeded %d key metrics across %d tickers: %s",
                len(rows), len(KEY_METRICS), per_ticker)


async def main() -> None:
    async for db in get_db():
        await _seed(db)
        break


if __name__ == "__main__":
    asyncio.run(main())
