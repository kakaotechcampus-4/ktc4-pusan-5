"""누적 손익을 단일 분기로 변환한다. EPS·ROE는 원천 결산월 기준을 보존한다."""

from decimal import Decimal

from app.schemas.stock import Resource
from app.schemas.stock_investment import Growth, InvestmentPoint


def shift(period: str, months: int) -> str:
    year, month = map(int, period.split("-"))
    index = year * 12 + month - 1 + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def growth(current, previous, *, earnings=True) -> Growth:
    if current is None or previous is None:
        return Growth()
    if previous == 0:
        return Growth(status="zero_base")
    if earnings:
        if previous < 0:
            if current > 0:
                return Growth(status="turned_profit")
            return Growth(
                status="loss_narrowed"
                if current > previous
                else "loss_widened"
                if current < previous
                else "loss_unchanged"
            )
        if current < 0:
            return Growth(status="turned_loss")
    if previous < 0:
        return Growth()
    return Growth(value=(current - previous) / previous * 100, status="value")


def single_quarter(rows, period, field, annual_periods):
    row = rows.get(period)
    if row is None or row.fiscal_year_end_month is None:
        return None
    month = int(period[-2:])
    elapsed = (month - row.fiscal_year_end_month) % 12 or 12
    if elapsed not in (3, 6, 9, 12):
        return None
    # 현재 결산월로 과거 회계연도를 단정하지 않는다. 전년도 연간 결산도 확인한다.
    if shift(period, -elapsed) not in annual_periods:
        return None
    value = getattr(row, field)
    if value is None:
        return None
    value = Decimal(str(value))
    if elapsed == 3:
        return value
    previous = rows.get(shift(period, -3))
    if previous is None or previous.fiscal_year_end_month != row.fiscal_year_end_month:
        return None
    before = getattr(previous, field)
    return value - Decimal(str(before)) if before is not None else None


def investment_summary(
    income: Resource, ratios: Resource, annual: Resource
) -> Resource[list[InvestmentPoint]]:
    incomes = {row.fiscal_period: row for row in income.data or []}
    ratio_rows = {row.fiscal_period: row for row in ratios.data or []}
    annual_periods = {row.fiscal_period for row in annual.data or []}
    periods = sorted(incomes.keys() | ratio_rows.keys())[-8:]
    points = []
    for period in periods:
        ratio = ratio_rows.get(period)
        current = {
            field: single_quarter(incomes, period, field, annual_periods)
            for field in ("revenue", "operating_profit", "net_income")
        }
        previous = {
            field: single_quarter(incomes, shift(period, -12), field, annual_periods)
            for field in current
        }
        points.append(
            InvestmentPoint(
                fiscal_period=period,
                revenue_growth=growth(current["revenue"], previous["revenue"], earnings=False),
                operating_profit_growth=growth(
                    current["operating_profit"], previous["operating_profit"]
                ),
                net_income_growth=growth(current["net_income"], previous["net_income"]),
                operating_profit=current["operating_profit"],
                net_income=current["net_income"],
                eps_cumulative=ratio.eps if ratio else None,
                roe=ratio.roe if ratio else None,
                debt_ratio=ratio.debt_ratio if ratio else None,
            )
        )
    resources = [income, ratios, annual]
    errors = any(item.status in ("stale", "unavailable") for item in resources)
    pending = any(item.status == "pending" for item in resources)
    refreshing = any(item.refreshing for item in resources)
    retries = [
        item.retry_after_seconds for item in resources if item.retry_after_seconds is not None
    ]
    timestamps = [item.collected_at for item in resources if item.collected_at]
    status = (
        ("stale" if errors else "ready")
        if points
        else "pending"
        if pending
        else "unavailable"
        if errors
        else "empty"
    )
    return Resource(
        status=status,
        data=points if points or status == "empty" else None,
        refreshing=refreshing,
        collected_at=min(timestamps) if points and timestamps else None,
        retry_after_seconds=min(retries) if retries else None,
    )
