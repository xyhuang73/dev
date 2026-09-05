"""从现有 Excel 报告提取统一收益摘要和净值序列。"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class PerformanceSummary:
    total_return: float | None = None
    annualized_return: float | None = None
    max_drawdown: float | None = None
    sharpe_ratio: float | None = None
    win_rate: float | None = None
    trade_success_rate: float | None = None
    total_round_trips: int = 0
    trade_days: int = 0
    benchmark_name: str = ""
    equity: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["datetime", "unit_nav", "drawdown"]))


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer(value: Any) -> int:
    number = _finite_float(value)
    return int(number) if number is not None else 0


def _read_report_parts(path: Path) -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame]:
    key_values: dict[str, Any] = {}
    wide_metrics: dict[str, Any] = {}
    equity = pd.DataFrame(columns=["datetime", "unit_nav", "drawdown"])
    with pd.ExcelFile(path) as workbook:
        for sheet in workbook.sheet_names:
            try:
                header = pd.read_excel(workbook, sheet_name=sheet, nrows=0)
            except Exception:  # noqa: BLE001 - 旧报告个别 sheet 损坏时继续寻找
                continue
            columns = {str(c) for c in header.columns}
            if {"key", "value"}.issubset(columns):
                table = pd.read_excel(workbook, sheet_name=sheet, usecols=["key", "value"])
                for key, value in table[["key", "value"]].itertuples(index=False, name=None):
                    if pd.notna(key):
                        key_values[str(key)] = value
            if {"datetime", "unit_nav"}.issubset(columns):
                optional = [name for name in ("drawdown", "benchmark_nav", "excess_nav", "benchmark_name") if name in columns]
                usecols = ["datetime", "unit_nav"] + optional
                equity = pd.read_excel(workbook, sheet_name=sheet, usecols=usecols)
            if "n_trade_dates" in columns:
                row = pd.read_excel(workbook, sheet_name=sheet, nrows=1)
                if not row.empty:
                    wide_metrics.update(row.iloc[0].to_dict())
    return key_values, wide_metrics, equity


def load_performance_summary(report_path: str | Path | None) -> PerformanceSummary | None:
    if not report_path:
        return None
    path = Path(report_path)
    if not path.is_file():
        return None
    key_values, wide_metrics, equity = _read_report_parts(path)
    if not equity.empty:
        equity = equity.copy()
        equity["datetime"] = pd.to_datetime(equity["datetime"], errors="coerce")
        equity["unit_nav"] = pd.to_numeric(equity["unit_nav"], errors="coerce")
        if "drawdown" in equity:
            equity["drawdown"] = pd.to_numeric(equity["drawdown"], errors="coerce")
        else:
            equity["drawdown"] = equity["unit_nav"] / equity["unit_nav"].cummax() - 1.0
        equity = equity.dropna(subset=["datetime", "unit_nav"]).sort_values("datetime", kind="mergesort")

    trade_days = len(equity)
    if trade_days == 0:
        trade_days = _integer(key_values.get("trade_days")) or _integer(wide_metrics.get("n_trade_dates"))
    total_return = _finite_float(key_values.get("simple_return_vs_initial_capital"))
    if total_return is None and not equity.empty:
        first = _finite_float(equity.iloc[0]["unit_nav"])
        last = _finite_float(equity.iloc[-1]["unit_nav"])
        if first and last is not None:
            total_return = last / first - 1.0
    annualized_return = _finite_float(key_values.get("annualized_return"))
    if annualized_return is None and total_return is not None and total_return > -1.0 and trade_days > 0:
        annualized_return = (1.0 + total_return) ** (252.0 / float(trade_days)) - 1.0
    total_round_trips = _integer(key_values.get("total_round_trips"))
    trade_success_rate = _finite_float(key_values.get("trade_success_rate"))
    if trade_success_rate is None and trade_days > 0:
        trade_success_rate = total_round_trips / float(trade_days)

    return PerformanceSummary(
        total_return=total_return,
        annualized_return=annualized_return,
        max_drawdown=_finite_float(key_values.get("max_drawdown")),
        sharpe_ratio=_finite_float(key_values.get("annualized_sharpe")),
        win_rate=_finite_float(key_values.get("all_round_trips_win_rate")),
        trade_success_rate=trade_success_rate,
        total_round_trips=total_round_trips,
        trade_days=trade_days,
        benchmark_name=(
            str(equity["benchmark_name"].dropna().iloc[0])
            if "benchmark_name" in equity and not equity["benchmark_name"].dropna().empty else ""
        ),
        equity=equity,
    )


def calculate_symbol_performance(
    bars: pd.DataFrame,
    trade_markers: pd.DataFrame,
) -> PerformanceSummary:
    """按单只股票的实际成交点重建全仓择时净值并计算展示指标。

    空仓期间净值不变；买入后按收盘价逐日盯市，卖出日按实际成交价结算。
    该口径用于 GUI 的单股诊断，不代表组合对该股票的资金贡献。
    """
    required_bar_columns = {"datetime", "close"}
    if bars.empty or not required_bar_columns.issubset(bars.columns):
        return PerformanceSummary()

    daily = bars[["datetime", "close"]].copy()
    daily["datetime"] = pd.to_datetime(daily["datetime"], errors="coerce").dt.normalize()
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = (
        daily.dropna(subset=["datetime", "close"])
        .loc[lambda frame: frame["close"] > 0]
        .drop_duplicates("datetime", keep="last")
        .sort_values("datetime", kind="mergesort")
        .reset_index(drop=True)
    )
    if daily.empty:
        return PerformanceSummary()

    marker_columns = {"datetime", "action", "price"}
    if trade_markers.empty or not marker_columns.issubset(trade_markers.columns):
        markers = pd.DataFrame(columns=["datetime", "action", "price"])
    else:
        markers = trade_markers[["datetime", "action", "price"]].copy()
        markers["datetime"] = pd.to_datetime(markers["datetime"], errors="coerce").dt.normalize()
        markers["action"] = markers["action"].astype(str).str.strip().str.upper()
        markers["price"] = pd.to_numeric(markers["price"], errors="coerce")
        markers = markers.loc[
            markers["action"].isin(["BUY", "SELL"]) & markers["price"].gt(0)
        ].dropna(subset=["datetime"]).sort_values("datetime", kind="mergesort")

    events_by_day = {
        date: list(group[["action", "price"]].itertuples(index=False, name=None))
        for date, group in markers.groupby("datetime", sort=False)
    }
    cash = 1.0
    shares = 0.0
    entry_value: float | None = None
    round_trip_returns: list[float] = []
    nav_values: list[float] = []
    for date, close in daily[["datetime", "close"]].itertuples(index=False, name=None):
        for action, price in events_by_day.get(date, []):
            price = float(price)
            if action == "BUY" and shares == 0.0:
                entry_value = cash
                shares = cash / price
                cash = 0.0
            elif action == "SELL" and shares > 0.0:
                cash = shares * price
                shares = 0.0
                if entry_value is not None and entry_value > 0.0:
                    round_trip_returns.append(cash / entry_value - 1.0)
                entry_value = None
        nav_values.append(cash + shares * float(close))

    nav = pd.Series(nav_values, dtype="float64")
    daily_returns = nav.pct_change()
    daily_returns.iloc[0] = nav.iloc[0] - 1.0
    running_peak = nav.cummax().clip(lower=1.0)
    drawdown = nav / running_peak - 1.0
    trade_days = len(daily)
    total_return = float(nav.iloc[-1] - 1.0)
    annualized_return = None
    if total_return > -1.0 and trade_days > 0:
        annualized_return = (1.0 + total_return) ** (252.0 / float(trade_days)) - 1.0
    return_std = float(daily_returns.std(ddof=1)) if trade_days > 1 else float("nan")
    sharpe_ratio = None
    if math.isfinite(return_std) and return_std > 0.0:
        sharpe_ratio = math.sqrt(252.0) * float(daily_returns.mean()) / return_std
    total_round_trips = len(round_trip_returns)
    win_rate = (
        sum(value > 0.0 for value in round_trip_returns) / float(total_round_trips)
        if total_round_trips else None
    )
    equity = pd.DataFrame(
        {
            "datetime": daily["datetime"].to_numpy(),
            "unit_nav": nav.to_numpy(),
            "drawdown": drawdown.to_numpy(),
        }
    )
    return PerformanceSummary(
        total_return=total_return,
        annualized_return=annualized_return,
        max_drawdown=abs(float(drawdown.min())),
        sharpe_ratio=sharpe_ratio,
        win_rate=win_rate,
        trade_success_rate=total_round_trips / float(trade_days),
        total_round_trips=total_round_trips,
        trade_days=trade_days,
        equity=equity,
    )


def build_nav_comparison(strategy_equity: pd.DataFrame, benchmark_bars: pd.DataFrame) -> pd.DataFrame:
    """按交易日对齐并生成策略、基准及相对超额净值（策略净值/基准净值）。"""
    if strategy_equity.empty:
        return pd.DataFrame(columns=["datetime", "strategy_nav", "benchmark_nav", "excess_nav"])
    embedded_columns = [name for name in ("benchmark_nav", "excess_nav") if name in strategy_equity.columns]
    strategy = strategy_equity[["datetime", "unit_nav", *embedded_columns]].copy()
    strategy["datetime"] = pd.to_datetime(strategy["datetime"], errors="coerce").dt.normalize()
    strategy["strategy_nav"] = pd.to_numeric(strategy["unit_nav"], errors="coerce")
    strategy = strategy.dropna(subset=["datetime", "strategy_nav"]).drop(columns=["unit_nav"])
    if not strategy.empty and float(strategy.iloc[0]["strategy_nav"]) != 0.0:
        strategy["strategy_nav"] = strategy["strategy_nav"] / float(strategy.iloc[0]["strategy_nav"])

    if "benchmark_nav" in strategy.columns and pd.to_numeric(strategy["benchmark_nav"], errors="coerce").notna().any():
        strategy["benchmark_nav"] = pd.to_numeric(strategy["benchmark_nav"], errors="coerce")
        if "excess_nav" not in strategy.columns:
            strategy["excess_nav"] = strategy["strategy_nav"] / strategy["benchmark_nav"]
        else:
            strategy["excess_nav"] = pd.to_numeric(strategy["excess_nav"], errors="coerce")
        return strategy[["datetime", "strategy_nav", "benchmark_nav", "excess_nav"]]

    benchmark = benchmark_bars[["datetime", "close"]].copy() if not benchmark_bars.empty else pd.DataFrame(columns=["datetime", "close"])
    benchmark["datetime"] = pd.to_datetime(benchmark["datetime"], errors="coerce").dt.normalize()
    benchmark["close"] = pd.to_numeric(benchmark["close"], errors="coerce")
    benchmark = benchmark.dropna(subset=["datetime", "close"]).drop_duplicates("datetime", keep="last")
    if not benchmark.empty and float(benchmark.iloc[0]["close"]) != 0.0:
        benchmark["benchmark_nav"] = benchmark["close"] / float(benchmark.iloc[0]["close"])
    else:
        benchmark["benchmark_nav"] = float("nan")
    comparison = strategy.merge(benchmark[["datetime", "benchmark_nav"]], on="datetime", how="left")
    comparison["benchmark_nav"] = comparison["benchmark_nav"].ffill()
    comparison["excess_nav"] = comparison["strategy_nav"] / comparison["benchmark_nav"]
    return comparison
