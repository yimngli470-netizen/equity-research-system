"""Compute derived financial metrics from raw quarterly data.

These are calculated on-the-fly — not stored in a separate table.
Used as context input for AI agents and the quant feature engine.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import Financial
from app.models.price import DailyPrice
from app.models.valuation import Valuation


@dataclass
class QuarterMetrics:
    """Computed metrics for a single quarter."""

    period: str
    period_end_date: date

    # Raw (passed through for convenience)
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    eps: float | None = None
    free_cash_flow: float | None = None

    # Margins
    gross_margin: float | None = None
    operating_margin: float | None = None
    profit_margin: float | None = None
    fcf_margin: float | None = None

    # Growth (QoQ)
    revenue_qoq: float | None = None
    gross_profit_qoq: float | None = None
    operating_income_qoq: float | None = None
    net_income_qoq: float | None = None
    eps_qoq: float | None = None

    # Growth (YoY)
    revenue_yoy: float | None = None
    gross_profit_yoy: float | None = None
    operating_income_yoy: float | None = None
    net_income_yoy: float | None = None
    eps_yoy: float | None = None

    # Margin changes
    gross_margin_change_qoq: float | None = None
    operating_margin_change_qoq: float | None = None
    gross_margin_change_yoy: float | None = None
    operating_margin_change_yoy: float | None = None

    # Efficiency
    operating_leverage: float | None = None  # op income growth / revenue growth
    fcf_conversion: float | None = None  # FCF / net income


@dataclass
class ComputedSnapshot:
    """Full computed metrics for a ticker — all quarters + current valuation."""

    ticker: str
    quarters: list[QuarterMetrics] = field(default_factory=list)
    valuation: dict | None = None
    latest_price: float | None = None
    price_1m_ago: float | None = None
    price_3m_ago: float | None = None
    price_12m_ago: float | None = None
    momentum_1m: float | None = None
    momentum_3m: float | None = None
    momentum_12m: float | None = None


def _growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior)


def _margin(part: float | None, whole: float | None) -> float | None:
    if part is None or whole is None or whole == 0:
        return None
    return part / whole


def _compute_quarter(
    current: Financial,
    prev_q: Financial | None,
    prev_y: Financial | None,
) -> QuarterMetrics:
    """Compute metrics for one quarter given prior quarter and year-ago quarter."""
    m = QuarterMetrics(
        period=current.period,
        period_end_date=current.period_end_date,
        revenue=current.revenue,
        gross_profit=current.gross_profit,
        operating_income=current.operating_income,
        net_income=current.net_income,
        eps=current.eps,
        free_cash_flow=current.free_cash_flow,
    )

    # Margins
    m.gross_margin = _margin(current.gross_profit, current.revenue)
    m.operating_margin = _margin(current.operating_income, current.revenue)
    m.profit_margin = _margin(current.net_income, current.revenue)
    m.fcf_margin = _margin(current.free_cash_flow, current.revenue)

    # FCF conversion
    m.fcf_conversion = _margin(current.free_cash_flow, current.net_income)

    # QoQ growth
    if prev_q:
        m.revenue_qoq = _growth(current.revenue, prev_q.revenue)
        m.gross_profit_qoq = _growth(current.gross_profit, prev_q.gross_profit)
        m.operating_income_qoq = _growth(current.operating_income, prev_q.operating_income)
        m.net_income_qoq = _growth(current.net_income, prev_q.net_income)
        m.eps_qoq = _growth(current.eps, prev_q.eps)

        # Margin changes QoQ
        prev_gm = _margin(prev_q.gross_profit, prev_q.revenue)
        prev_om = _margin(prev_q.operating_income, prev_q.revenue)
        if m.gross_margin is not None and prev_gm is not None:
            m.gross_margin_change_qoq = m.gross_margin - prev_gm
        if m.operating_margin is not None and prev_om is not None:
            m.operating_margin_change_qoq = m.operating_margin - prev_om

        # Operating leverage
        if m.revenue_qoq and m.revenue_qoq != 0:
            oi_growth = _growth(current.operating_income, prev_q.operating_income)
            if oi_growth is not None:
                m.operating_leverage = oi_growth / m.revenue_qoq

    # YoY growth
    if prev_y:
        m.revenue_yoy = _growth(current.revenue, prev_y.revenue)
        m.gross_profit_yoy = _growth(current.gross_profit, prev_y.gross_profit)
        m.operating_income_yoy = _growth(current.operating_income, prev_y.operating_income)
        m.net_income_yoy = _growth(current.net_income, prev_y.net_income)
        m.eps_yoy = _growth(current.eps, prev_y.eps)

        prev_gm = _margin(prev_y.gross_profit, prev_y.revenue)
        prev_om = _margin(prev_y.operating_income, prev_y.revenue)
        if m.gross_margin is not None and prev_gm is not None:
            m.gross_margin_change_yoy = m.gross_margin - prev_gm
        if m.operating_margin is not None and prev_om is not None:
            m.operating_margin_change_yoy = m.operating_margin - prev_om

    return m


async def get_computed_metrics(db: AsyncSession, ticker: str) -> ComputedSnapshot:
    """Build the full computed metrics snapshot for a ticker.

    This is the primary data package that gets passed to AI agents as context.
    """
    # Fetch all quarters, ordered newest first
    result = await db.execute(
        select(Financial)
        .where(Financial.ticker == ticker)
        .order_by(Financial.period_end_date.desc())
        .limit(8)
    )
    financials = result.scalars().all()

    # Compute metrics for each quarter
    quarters = []
    for i, current in enumerate(financials):
        prev_q = financials[i + 1] if i + 1 < len(financials) else None
        prev_y = financials[i + 4] if i + 4 < len(financials) else None
        quarters.append(_compute_quarter(current, prev_q, prev_y))

    # Fetch latest valuation
    val_result = await db.execute(
        select(Valuation)
        .where(Valuation.ticker == ticker)
        .order_by(Valuation.date.desc())
        .limit(1)
    )
    val = val_result.scalar_one_or_none()
    valuation_dict = None
    if val:
        valuation_dict = {
            "forward_pe": val.forward_pe,
            "trailing_pe": val.trailing_pe,
            "peg_ratio": val.peg_ratio,
            "price_to_sales": val.price_to_sales,
            "price_to_book": val.price_to_book,
            "ev_to_revenue": val.ev_to_revenue,
            "ev_to_ebitda": val.ev_to_ebitda,
            "trailing_eps": val.trailing_eps,
            "forward_eps": val.forward_eps,
            "earnings_growth": val.earnings_growth,
            "revenue_growth": val.revenue_growth,
            "gross_margins": val.gross_margins,
            "operating_margins": val.operating_margins,
            "profit_margins": val.profit_margins,
            "market_cap": val.market_cap,
            "enterprise_value": val.enterprise_value,
        }

    # Fetch price momentum
    price_result = await db.execute(
        select(DailyPrice)
        .where(DailyPrice.ticker == ticker)
        .order_by(DailyPrice.date.desc())
        .limit(253)
    )
    prices = price_result.scalars().all()

    snapshot = ComputedSnapshot(
        ticker=ticker,
        quarters=quarters,
        valuation=valuation_dict,
    )

    if prices:
        snapshot.latest_price = prices[0].close
        if len(prices) >= 22:
            snapshot.price_1m_ago = prices[21].close
            snapshot.momentum_1m = _growth(prices[0].close, prices[21].close)
        if len(prices) >= 64:
            snapshot.price_3m_ago = prices[63].close
            snapshot.momentum_3m = _growth(prices[0].close, prices[63].close)
        if len(prices) >= 253:
            snapshot.price_12m_ago = prices[252].close
            snapshot.momentum_12m = _growth(prices[0].close, prices[252].close)

    return snapshot


def format_for_llm(snapshot: ComputedSnapshot) -> str:
    """Format the computed snapshot as a readable text block for LLM context.

    This is what gets injected into agent prompts.
    """
    lines = [f"=== {snapshot.ticker} Financial Overview ===\n"]

    # Price & Momentum
    if snapshot.latest_price:
        lines.append(f"Current Price: ${snapshot.latest_price:.2f}")
        if snapshot.momentum_1m is not None:
            lines.append(f"  1M Momentum: {snapshot.momentum_1m:+.1%}")
        if snapshot.momentum_3m is not None:
            lines.append(f"  3M Momentum: {snapshot.momentum_3m:+.1%}")
        if snapshot.momentum_12m is not None:
            lines.append(f"  12M Momentum: {snapshot.momentum_12m:+.1%}")
        lines.append("")

    # Valuation
    if snapshot.valuation:
        v = snapshot.valuation
        lines.append("Valuation Multiples:")
        if v["forward_pe"]:
            lines.append(f"  Forward P/E: {v['forward_pe']:.1f}x")
        if v["trailing_pe"]:
            lines.append(f"  Trailing P/E: {v['trailing_pe']:.1f}x")
        if v["peg_ratio"]:
            lines.append(f"  PEG Ratio: {v['peg_ratio']:.2f}")
        if v["price_to_sales"]:
            lines.append(f"  P/S: {v['price_to_sales']:.1f}x")
        if v["ev_to_revenue"]:
            lines.append(f"  EV/Revenue: {v['ev_to_revenue']:.1f}x")
        if v["ev_to_ebitda"]:
            lines.append(f"  EV/EBITDA: {v['ev_to_ebitda']:.1f}x")
        if v["forward_eps"]:
            lines.append(f"  Forward EPS: ${v['forward_eps']:.2f}")
        if v["trailing_eps"]:
            lines.append(f"  Trailing EPS: ${v['trailing_eps']:.2f}")
        if v["market_cap"]:
            lines.append(f"  Market Cap: ${v['market_cap']/1e9:.1f}B")
        lines.append("")

    # Quarterly Results
    if snapshot.quarters:
        lines.append("Quarterly Results (most recent first):")
        lines.append(f"{'Quarter':<12} {'Revenue':>12} {'Gross Mgn':>10} {'Op Mgn':>10} {'Net Inc':>12} {'EPS':>8} {'Rev YoY':>10} {'Rev QoQ':>10}")
        lines.append("-" * 96)
        for q in snapshot.quarters:
            rev = f"${q.revenue/1e9:.2f}B" if q.revenue else "N/A"
            gm = f"{q.gross_margin:.1%}" if q.gross_margin is not None else "N/A"
            om = f"{q.operating_margin:.1%}" if q.operating_margin is not None else "N/A"
            ni = f"${q.net_income/1e9:.2f}B" if q.net_income else "N/A"
            eps = f"${q.eps:.2f}" if q.eps is not None else "N/A"
            ryoy = f"{q.revenue_yoy:+.1%}" if q.revenue_yoy is not None else "N/A"
            rqoq = f"{q.revenue_qoq:+.1%}" if q.revenue_qoq is not None else "N/A"
            lines.append(f"{q.period:<12} {rev:>12} {gm:>10} {om:>10} {ni:>12} {eps:>8} {ryoy:>10} {rqoq:>10}")

        lines.append("")

        # Margin trends narrative
        latest = snapshot.quarters[0]
        if latest.gross_margin_change_qoq is not None:
            direction = "expanded" if latest.gross_margin_change_qoq > 0 else "contracted"
            lines.append(f"Gross margin {direction} {abs(latest.gross_margin_change_qoq):.1%} QoQ")
        if latest.operating_margin_change_qoq is not None:
            direction = "expanded" if latest.operating_margin_change_qoq > 0 else "contracted"
            lines.append(f"Operating margin {direction} {abs(latest.operating_margin_change_qoq):.1%} QoQ")
        if latest.operating_leverage is not None:
            lines.append(f"Operating leverage: {latest.operating_leverage:.2f}x (>1 = positive leverage)")
        if latest.fcf_conversion is not None:
            lines.append(f"FCF conversion: {latest.fcf_conversion:.1%} of net income")

    return "\n".join(lines)
