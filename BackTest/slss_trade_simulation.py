# -*- coding: utf-8 -*-
"""
SLSS 等权合成因子下的逐标的交易模拟（两种决策层，由 ``Config/slss_strategy.json`` 的 ``decision_mode`` 决定）。

1) ``threshold``（默认）：与 ``StratifiedLongShortSharpeEqualWeightStrategy`` 阈值模式一致::
    - 当日 ``slss_composite`` 有效且 > buy_threshold、当前空仓 → 以当日收盘价买入 fixed_lot 股；
    - 当日信号有效且 < sell_threshold、当前持仓 → 以当日收盘价卖出 fixed_lot 股。

2) ``cross_section_rank``：按交易日全截面排名分桶（多 / 空 / 中性）::
    - 合成值从高到低排序，名次 <= ``cross_section_long_top_n`` → 目标多头；
    - 名次 >= ``cross_section_short_min_rank`` → 目标空头（即「前 (short_min_rank-1) 名之外」）；
    - 其余名次 → 目标空仓；逐日调仓，以收盘价成交（模拟未扣费）。

说明（threshold）::
    Alpha 等权后的 ``slss_composite`` 量纲常远小于 JSON 里设的 buy_threshold，**raw 模式可能整段无成交**。
    若 raw 下无任何完整开平回合且 ``trade_simulation.enable_rolling_z_fallback=true``，
    则改用逐标的 rolling z-score（窗口与阈值见 ``Config/slss_strategy.json``），并在 ``portfolio`` 中写明 ``threshold_mode``。

A 股现货（``a_share_cash_stock_rules``）::
    - 截面目标 **-1（做空）** 在现货规则下 **清零为 0**（不做融券式卖开）；
    - **T+1**：多头 **卖出平仓** 仅允许在 **买入开仓日之后** 的交易日（日 K 用日历日 ``normalize`` 比较，与交易所 T+1 一致方向）。
    未实现：涨跌停、集合竞价、手续费、融券券池；两融做空请将该开关置为 ``false`` 并自担模型与合规风险。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from InnerStrategy.slss_cross_section import compute_cross_section_target_side
from InnerStrategy.slss_strategy_config import (
    SLSS_STRATEGY_JSON_PATH,
    load_slss_strategy_config,
)
from .factor_selection_snapshot_store import load_factor_selection_snapshot

from .models import BacktestJobConfig


def _a_share_norm_dt(dt: Any) -> pd.Timestamp:
    """日 K 与 A 股 T+1 判断：统一到日历日 00:00（naive）。"""
    return pd.Timestamp(dt).normalize()


def _a_share_can_sell_long_after_buy(
    *,
    bar_dt: Any,
    long_entry_dt: Any | None,
    cash_rules: bool,
    pos: int,
    entry_is_short: bool,
) -> bool:
    """
    A 股普通账户 T+1：当日买入的股票当日不得再卖出。

    日频收盘价模型下，用「当前 K 线日期 > 多头开仓 K 线日期」近似；融券/两融回转不在此开关内。
    """
    if not cash_rules or pos <= 0:
        return True
    if entry_is_short:
        return True
    if long_entry_dt is None:
        return True
    return _a_share_norm_dt(bar_dt) > _a_share_norm_dt(long_entry_dt)


def _notional_weighted_round_return_metrics(rounds_df: pd.DataFrame, total_pnl_cash: float) -> dict[str, Any]:
    """
    按各完整回合的「开仓名义本金」|open_price|×volume（元）加权，得到组合层面的平均本金收益率。

    数学上：sum(round_pnl_cash) / sum(|open_price|×volume) = Σ w_i·r_i，
    其中 w_i = 名义_i / Σ名义_i，r_i = 该回合现金盈亏率（与 round_pnl_pct 一致，多空均已按代码定义）。
    与 ``simple_return_vs_initial_capital``（盈亏加总 ÷ 界面初始资金）量纲不同，后者不反映名义规模。
    """
    if rounds_df.empty or "open_price" not in rounds_df.columns or "volume" not in rounds_df.columns:
        return {
            "sum_round_open_notional_cny": 0.0,
            "nominal_weighted_avg_round_return_on_notional": float("nan"),
        }
    op = pd.to_numeric(rounds_df["open_price"], errors="coerce")
    vol = pd.to_numeric(rounds_df["volume"], errors="coerce")
    notion = (op.abs() * vol).to_numpy(dtype=float, copy=False)
    mask = np.isfinite(notion) & (notion > 1e-12)
    sum_nom = float(np.sum(notion[mask])) if np.any(mask) else 0.0
    if sum_nom <= 1e-12:
        return {
            "sum_round_open_notional_cny": sum_nom,
            "nominal_weighted_avg_round_return_on_notional": float("nan"),
        }
    return {
        "sum_round_open_notional_cny": sum_nom,
        "nominal_weighted_avg_round_return_on_notional": float(total_pnl_cash / sum_nom),
    }


def _diagnostics_slss(merged: pd.DataFrame) -> dict[str, Any]:
    """全样本 slss_composite 分布，便于报告解释「为何 raw 无成交」。"""
    s = pd.to_numeric(merged["slss_composite"], errors="coerce")
    fin = s[np.isfinite(s)]
    if fin.empty:
        return {
            "slss_finite_rows": 0,
            "slss_global_min": float("nan"),
            "slss_global_max": float("nan"),
            "slss_global_p50": float("nan"),
            "slss_global_p90": float("nan"),
        }
    return {
        "slss_finite_rows": int(fin.shape[0]),
        "slss_global_min": float(fin.min()),
        "slss_global_max": float(fin.max()),
        "slss_global_p50": float(fin.quantile(0.5)),
        "slss_global_p90": float(fin.quantile(0.9)),
    }


def _rolling_z_by_symbol(df: pd.DataFrame, col: str, win: int, min_periods: int) -> pd.Series:
    """按 vt_symbol 对 col 做滚动 z-score（用于 raw 无成交时的备用信号）。"""
    return df.groupby("vt_symbol", sort=False)[col].transform(
        lambda s: (s - s.rolling(win, min_periods=min_periods).mean())
        / (s.rolling(win, min_periods=min_periods).std() + 1e-12),
    )


def _simulate_with_signal(
    work: pd.DataFrame,
    job: BacktestJobConfig,
    *,
    signal_col: str,
    buy_threshold: float,
    sell_threshold: float,
    fixed_lot: int,
    threshold_mode: str,
    a_share_cash_stock_rules: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """
    核心状态机：按 ``signal_col`` 与阈值开平；逐笔记录 ``slss_composite_raw``（原始合成值）。

    ``a_share_cash_stock_rules``：多头遵守 T+1，当日买入不得当日卖出平仓（仅阈值多头路径）。
    """
    lot = max(1, int(fixed_lot))
    all_trades: list[dict[str, Any]] = []
    all_rounds: list[dict[str, Any]] = []

    for sym, g in work.groupby("vt_symbol", sort=False):
        g2 = g.sort_values("datetime", kind="mergesort").reset_index(drop=True)
        pos = 0
        entry_price = 0.0
        entry_dt: Any = None
        entry_is_short = False
        trade_seq = 0
        for _, row in g2.iterrows():
            dt = row["datetime"]
            close = float(row["close"])
            sig_rule = row[signal_col]
            raw_c = row["slss_composite"] if "slss_composite" in row.index else float("nan")
            if not math.isfinite(close):
                continue
            if not np.isfinite(sig_rule):
                continue

            if pos == 0 and float(sig_rule) > float(buy_threshold):
                pos = 1
                entry_price = close
                entry_dt = dt
                entry_is_short = False
                trade_seq += 1
                all_trades.append(
                    {
                        "vt_symbol": sym,
                        "datetime": dt,
                        "action": "买入开仓",
                        "price": close,
                        "volume": lot,
                        "signal_for_rule": float(sig_rule),
                        "signal_column": signal_col,
                        "slss_composite_raw": float(raw_c) if np.isfinite(raw_c) else None,
                        "threshold_mode": threshold_mode,
                        "position_after_shares": lot,
                        "trade_seq": trade_seq,
                    },
                )
            elif pos == 1 and float(sig_rule) < float(sell_threshold):
                # A 股 T+1：买入开仓当日不允许再卖出平仓（阈值模式仅多头）
                if not _a_share_can_sell_long_after_buy(
                    bar_dt=dt,
                    long_entry_dt=entry_dt,
                    cash_rules=a_share_cash_stock_rules,
                    pos=pos,
                    entry_is_short=entry_is_short,
                ):
                    continue
                pos = 0
                pnl_pct = (close / entry_price - 1.0) if entry_price > 1e-12 else float("nan")
                pnl_cash = (close - entry_price) * float(lot)
                trade_seq += 1
                all_trades.append(
                    {
                        "vt_symbol": sym,
                        "datetime": dt,
                        "action": "卖出平仓",
                        "price": close,
                        "volume": lot,
                        "signal_for_rule": float(sig_rule),
                        "signal_column": signal_col,
                        "slss_composite_raw": float(raw_c) if np.isfinite(raw_c) else None,
                        "threshold_mode": threshold_mode,
                        "position_after_shares": 0,
                        "trade_seq": trade_seq,
                        "open_datetime": entry_dt,
                        "open_price": entry_price,
                        "round_pnl_pct": pnl_pct,
                        "round_pnl_cash": pnl_cash,
                    },
                )
                all_rounds.append(
                    {
                        "vt_symbol": sym,
                        "threshold_mode": threshold_mode,
                        "open_datetime": entry_dt,
                        "open_price": entry_price,
                        "close_datetime": dt,
                        "close_price": close,
                        "volume": lot,
                        "hold_calendar_days": _calendar_days(entry_dt, dt),
                        "round_pnl_pct": pnl_pct,
                        "round_pnl_cash": pnl_cash,
                        "win": bool(np.isfinite(pnl_pct) and pnl_pct > 0),
                    },
                )
                entry_dt = None
                entry_price = 0.0
                entry_is_short = False

    trades_df = pd.DataFrame(all_trades)
    rounds_df = pd.DataFrame(all_rounds)

    if rounds_df.empty:
        per_sym = pd.DataFrame(
            columns=[
                "vt_symbol",
                "n_buy_open",
                "n_sell_close",
                "n_round_trips",
                "sum_round_pnl_cash",
                "mean_round_pnl_pct",
                "win_rounds",
                "win_rate_rounds",
            ],
        )
    else:
        per_sym = (
            rounds_df.groupby("vt_symbol", sort=False)
            .agg(
                n_round_trips=("round_pnl_cash", "count"),
                sum_round_pnl_cash=("round_pnl_cash", "sum"),
                mean_round_pnl_pct=("round_pnl_pct", "mean"),
                win_rounds=("win", "sum"),
            )
            .reset_index()
        )
        if not trades_df.empty:
            buy_counts = (
                trades_df.loc[trades_df["action"] == "买入开仓", ["vt_symbol"]]
                .groupby("vt_symbol")
                .size()
                .reset_index(name="n_buy_open")
            )
            sell_counts = (
                trades_df.loc[trades_df["action"] == "卖出平仓", ["vt_symbol"]]
                .groupby("vt_symbol")
                .size()
                .reset_index(name="n_sell_close")
            )
            per_sym = per_sym.merge(buy_counts, on="vt_symbol", how="left").merge(sell_counts, on="vt_symbol", how="left")
        else:
            per_sym["n_buy_open"] = 0
            per_sym["n_sell_close"] = 0
        per_sym["n_buy_open"] = per_sym["n_buy_open"].fillna(0).astype(int)
        per_sym["n_sell_close"] = per_sym["n_sell_close"].fillna(0).astype(int)
        per_sym["win_rate_rounds"] = np.where(
            per_sym["n_round_trips"] > 0,
            per_sym["win_rounds"] / per_sym["n_round_trips"],
            float("nan"),
        )

    n_round = int(len(rounds_df))
    n_buy_all = int(len(trades_df[trades_df["action"] == "买入开仓"])) if not trades_df.empty else 0
    n_sell_all = int(len(trades_df[trades_df["action"] == "卖出平仓"])) if not trades_df.empty else 0
    total_pnl = float(rounds_df["round_pnl_cash"].sum()) if n_round else 0.0
    cap = float(job.initial_capital) if math.isfinite(float(job.initial_capital)) and float(job.initial_capital) > 0 else 0.0
    ret_on_capital = (total_pnl / cap) if cap > 1e-12 else float("nan")
    wins = int(rounds_df["win"].sum()) if n_round and "win" in rounds_df.columns else 0
    win_rate_all = (wins / n_round) if n_round else float("nan")
    mean_round_pct = float(rounds_df["round_pnl_pct"].mean()) if n_round else float("nan")
    # 按开仓名义本金加权的组合平均回合收益率（见 _notional_weighted_round_return_metrics 说明）
    nw_metrics = _notional_weighted_round_return_metrics(rounds_df, total_pnl)

    portfolio: dict[str, Any] = {
        "threshold_mode": threshold_mode,
        "signal_column_used": signal_col,
        "buy_threshold_applied": buy_threshold,
        "sell_threshold_applied": sell_threshold,
        "fixed_lot_per_order": lot,
        "a_share_cash_stock_rules": bool(a_share_cash_stock_rules),
        "initial_capital_ui": cap,
        "n_symbols_in_panel": int(work["vt_symbol"].nunique()),
        "n_symbols_with_any_round_trip": int(rounds_df["vt_symbol"].nunique()) if n_round else 0,
        "total_buy_orders": n_buy_all,
        "total_sell_orders": n_sell_all,
        "total_round_trips": n_round,
        "total_realized_pnl_cash": total_pnl,
        "simple_return_vs_initial_capital": ret_on_capital,
        "note": (
            "simple_return_vs_initial_capital = sum(各票已实现回合现金盈亏)/界面初始资金；"
            "未扣手续费/滑点。若 threshold_mode 含 rolling_z，则开平信号来自逐标的滚动 z，"
            "与 CTA 上 raw slss_composite 使用 JSON buy_threshold 的绝对阈值量纲不同，"
            "仅供全市场报告在 raw 无回合时仍产生可审阅的逐笔样本。"
            + (
                " a_share_cash_stock_rules=true：阈值多头遵守 T+1（买入开仓当日不卖出平仓）。"
                if a_share_cash_stock_rules
                else ""
            )
        ),
        "all_round_trips_win_rate": win_rate_all,
        "all_round_trips_mean_pnl_pct": mean_round_pct,
        **nw_metrics,
        "notional_weighting_note": (
            "nominal_weighted_avg_round_return_on_notional = sum(round_pnl_cash)/sum(|open_price|×volume)，"
            "为各回合收益率按开仓名义加权的组合指标；simple_return_vs_initial_capital 仍为盈亏加总÷界面初始资金。"
        ),
    }

    return trades_df, rounds_df, per_sym, portfolio


def _simulate_cross_section_buckets(
    work: pd.DataFrame,
    job: BacktestJobConfig,
    *,
    long_top_n: int,
    short_min_rank: int,
    long_require_close_positive: bool,
    long_require_composite_positive: bool,
    short_bottom_n: int,
    short_or_negative_composite: bool,
    a_share_cash_stock_rules: bool,
    fixed_lot: int,
    mode_label: str,
    allow_long_buy: bool,
    force_sell_long: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """
    截面排名分桶：每日按 ``slss_composite`` 排序后，逐标的将仓位调向 +lot / 0 / -lot（多 / 平 / 空）。

    多头/空头附加条件由 ``Config/slss_strategy.json`` 的 ``cross_section_*`` 传入，与 ``compute_cross_section_target_side`` 一致。
    """
    lot = max(1, int(fixed_lot))
    wk = work.copy()
    wk["_cs_target"] = compute_cross_section_target_side(
        wk,
        value_col="slss_composite",
        long_top_n=long_top_n,
        short_min_rank=short_min_rank,
        long_require_close_positive=long_require_close_positive,
        long_require_composite_positive=long_require_composite_positive,
        short_bottom_n=short_bottom_n,
        short_or_negative_composite=short_or_negative_composite,
    )
    # A 股现货：禁止截面做空目标（-1→0），与真实不可裸卖空账户一致
    if a_share_cash_stock_rules:
        wk["_cs_target"] = wk["_cs_target"].where(wk["_cs_target"] >= 0, 0).astype(np.int8)

    all_trades: list[dict[str, Any]] = []
    all_rounds: list[dict[str, Any]] = []

    for sym, g in wk.groupby("vt_symbol", sort=False):
        g2 = g.sort_values("datetime", kind="mergesort").reset_index(drop=True)
        pos = 0  # +lot 多头；-lot 空头；0 空仓
        entry_price = 0.0
        entry_dt: Any = None
        entry_is_short = False
        trade_seq = 0

        for _, row in g2.iterrows():
            dt = row["datetime"]
            close = float(row["close"])
            if not math.isfinite(close):
                continue
            want = int(row["_cs_target"])
            raw_c = row["slss_composite"] if "slss_composite" in row.index else float("nan")
            # 门控：禁止买入时将多头目标钳制为 0；强平时优先让多头回到 0。
            if (not allow_long_buy) and want == 1:
                want = 0
            if force_sell_long and pos > 0:
                want = 0

            # 目标多头：先平空再开多
            if want == 1:
                if pos < 0:
                    trade_seq += 1
                    pnl_pct = (
                        (entry_price - close) / entry_price
                        if entry_is_short and entry_price > 1e-12
                        else float("nan")
                    )
                    pnl_cash = (entry_price - close) * float(lot)
                    all_trades.append(
                        {
                            "vt_symbol": sym,
                            "datetime": dt,
                            "action": "买入平仓",
                            "price": close,
                            "volume": lot,
                            "signal_for_rule": float(want),
                            "signal_column": "_cs_target",
                            "slss_composite_raw": float(raw_c) if np.isfinite(raw_c) else None,
                            "threshold_mode": mode_label,
                            "position_after_shares": 0,
                            "trade_seq": trade_seq,
                            "open_datetime": entry_dt,
                            "open_price": entry_price,
                            "round_pnl_pct": pnl_pct,
                            "round_pnl_cash": pnl_cash,
                        },
                    )
                    all_rounds.append(
                        {
                            "vt_symbol": sym,
                            "threshold_mode": mode_label,
                            "round_side": "空",
                            "open_datetime": entry_dt,
                            "open_price": entry_price,
                            "close_datetime": dt,
                            "close_price": close,
                            "volume": lot,
                            "hold_calendar_days": _calendar_days(entry_dt, dt),
                            "round_pnl_pct": pnl_pct,
                            "round_pnl_cash": pnl_cash,
                            "win": bool(np.isfinite(pnl_pct) and pnl_pct > 0),
                        },
                    )
                    pos = 0
                    entry_dt = None
                    entry_price = 0.0
                    entry_is_short = False
                if pos == 0:
                    trade_seq += 1
                    pos = lot
                    entry_price = close
                    entry_dt = dt
                    entry_is_short = False
                    all_trades.append(
                        {
                            "vt_symbol": sym,
                            "datetime": dt,
                            "action": "买入开仓",
                            "price": close,
                            "volume": lot,
                            "signal_for_rule": float(want),
                            "signal_column": "_cs_target",
                            "slss_composite_raw": float(raw_c) if np.isfinite(raw_c) else None,
                            "threshold_mode": mode_label,
                            "position_after_shares": lot,
                            "trade_seq": trade_seq,
                        },
                    )
            # 目标空头：先平多再开空
            elif want == -1:
                if pos > 0:
                    # T+1：当日买多不得当日平多（与 want 其它分支同一根 K 上不再强行卖开）
                    if not _a_share_can_sell_long_after_buy(
                        bar_dt=dt,
                        long_entry_dt=entry_dt,
                        cash_rules=a_share_cash_stock_rules,
                        pos=pos,
                        entry_is_short=entry_is_short,
                    ):
                        continue
                    trade_seq += 1
                    pnl_pct = (close / entry_price - 1.0) if not entry_is_short and entry_price > 1e-12 else float("nan")
                    pnl_cash = (close - entry_price) * float(lot)
                    all_trades.append(
                        {
                            "vt_symbol": sym,
                            "datetime": dt,
                            "action": "卖出平仓",
                            "price": close,
                            "volume": lot,
                            "signal_for_rule": float(want),
                            "signal_column": "_cs_target",
                            "slss_composite_raw": float(raw_c) if np.isfinite(raw_c) else None,
                            "threshold_mode": mode_label,
                            "position_after_shares": 0,
                            "trade_seq": trade_seq,
                            "open_datetime": entry_dt,
                            "open_price": entry_price,
                            "round_pnl_pct": pnl_pct,
                            "round_pnl_cash": pnl_cash,
                        },
                    )
                    all_rounds.append(
                        {
                            "vt_symbol": sym,
                            "threshold_mode": mode_label,
                            "round_side": "多",
                            "open_datetime": entry_dt,
                            "open_price": entry_price,
                            "close_datetime": dt,
                            "close_price": close,
                            "volume": lot,
                            "hold_calendar_days": _calendar_days(entry_dt, dt),
                            "round_pnl_pct": pnl_pct,
                            "round_pnl_cash": pnl_cash,
                            "win": bool(np.isfinite(pnl_pct) and pnl_pct > 0),
                        },
                    )
                    pos = 0
                    entry_dt = None
                    entry_price = 0.0
                    entry_is_short = False
                if pos == 0:
                    trade_seq += 1
                    pos = -lot
                    entry_price = close
                    entry_dt = dt
                    entry_is_short = True
                    all_trades.append(
                        {
                            "vt_symbol": sym,
                            "datetime": dt,
                            "action": "卖出开仓",
                            "price": close,
                            "volume": lot,
                            "signal_for_rule": float(want),
                            "signal_column": "_cs_target",
                            "slss_composite_raw": float(raw_c) if np.isfinite(raw_c) else None,
                            "threshold_mode": mode_label,
                            "position_after_shares": -lot,
                            "trade_seq": trade_seq,
                        },
                    )
            # 目标空仓
            else:
                if pos > 0:
                    if not _a_share_can_sell_long_after_buy(
                        bar_dt=dt,
                        long_entry_dt=entry_dt,
                        cash_rules=a_share_cash_stock_rules,
                        pos=pos,
                        entry_is_short=entry_is_short,
                    ):
                        continue
                    trade_seq += 1
                    pnl_pct = (close / entry_price - 1.0) if not entry_is_short and entry_price > 1e-12 else float("nan")
                    pnl_cash = (close - entry_price) * float(lot)
                    all_trades.append(
                        {
                            "vt_symbol": sym,
                            "datetime": dt,
                            "action": "卖出平仓",
                            "price": close,
                            "volume": lot,
                            "signal_for_rule": float(want),
                            "signal_column": "_cs_target",
                            "slss_composite_raw": float(raw_c) if np.isfinite(raw_c) else None,
                            "threshold_mode": mode_label,
                            "position_after_shares": 0,
                            "trade_seq": trade_seq,
                            "open_datetime": entry_dt,
                            "open_price": entry_price,
                            "round_pnl_pct": pnl_pct,
                            "round_pnl_cash": pnl_cash,
                        },
                    )
                    all_rounds.append(
                        {
                            "vt_symbol": sym,
                            "threshold_mode": mode_label,
                            "round_side": "多",
                            "open_datetime": entry_dt,
                            "open_price": entry_price,
                            "close_datetime": dt,
                            "close_price": close,
                            "volume": lot,
                            "hold_calendar_days": _calendar_days(entry_dt, dt),
                            "round_pnl_pct": pnl_pct,
                            "round_pnl_cash": pnl_cash,
                            "win": bool(np.isfinite(pnl_pct) and pnl_pct > 0),
                        },
                    )
                    pos = 0
                    entry_dt = None
                    entry_price = 0.0
                    entry_is_short = False
                elif pos < 0:
                    trade_seq += 1
                    pnl_pct = (
                        (entry_price - close) / entry_price
                        if entry_is_short and entry_price > 1e-12
                        else float("nan")
                    )
                    pnl_cash = (entry_price - close) * float(lot)
                    all_trades.append(
                        {
                            "vt_symbol": sym,
                            "datetime": dt,
                            "action": "买入平仓",
                            "price": close,
                            "volume": lot,
                            "signal_for_rule": float(want),
                            "signal_column": "_cs_target",
                            "slss_composite_raw": float(raw_c) if np.isfinite(raw_c) else None,
                            "threshold_mode": mode_label,
                            "position_after_shares": 0,
                            "trade_seq": trade_seq,
                            "open_datetime": entry_dt,
                            "open_price": entry_price,
                            "round_pnl_pct": pnl_pct,
                            "round_pnl_cash": pnl_cash,
                        },
                    )
                    all_rounds.append(
                        {
                            "vt_symbol": sym,
                            "threshold_mode": mode_label,
                            "round_side": "空",
                            "open_datetime": entry_dt,
                            "open_price": entry_price,
                            "close_datetime": dt,
                            "close_price": close,
                            "volume": lot,
                            "hold_calendar_days": _calendar_days(entry_dt, dt),
                            "round_pnl_pct": pnl_pct,
                            "round_pnl_cash": pnl_cash,
                            "win": bool(np.isfinite(pnl_pct) and pnl_pct > 0),
                        },
                    )
                    pos = 0
                    entry_dt = None
                    entry_price = 0.0
                    entry_is_short = False

    trades_df = pd.DataFrame(all_trades)
    rounds_df = pd.DataFrame(all_rounds)

    if rounds_df.empty:
        per_sym = pd.DataFrame(
            columns=[
                "vt_symbol",
                "n_buy_open",
                "n_sell_close",
                "n_short_open",
                "n_buy_cover",
                "n_round_trips",
                "sum_round_pnl_cash",
                "mean_round_pnl_pct",
                "win_rounds",
                "win_rate_rounds",
            ],
        )
    else:
        per_sym = (
            rounds_df.groupby("vt_symbol", sort=False)
            .agg(
                n_round_trips=("round_pnl_cash", "count"),
                sum_round_pnl_cash=("round_pnl_cash", "sum"),
                mean_round_pnl_pct=("round_pnl_pct", "mean"),
                win_rounds=("win", "sum"),
            )
            .reset_index()
        )
        if not trades_df.empty:
            def _cnt(act: str) -> pd.DataFrame:
                sub = trades_df.loc[trades_df["action"] == act, ["vt_symbol"]]
                if sub.empty:
                    return pd.DataFrame(columns=["vt_symbol", "n"])
                return sub.groupby("vt_symbol").size().reset_index(name="n")

            buy_open = _cnt("买入开仓").rename(columns={"n": "n_buy_open"})
            sell_close = _cnt("卖出平仓").rename(columns={"n": "n_sell_close"})
            short_open = _cnt("卖出开仓").rename(columns={"n": "n_short_open"})
            buy_cover = _cnt("买入平仓").rename(columns={"n": "n_buy_cover"})
            per_sym = (
                per_sym.merge(buy_open, on="vt_symbol", how="left")
                .merge(sell_close, on="vt_symbol", how="left")
                .merge(short_open, on="vt_symbol", how="left")
                .merge(buy_cover, on="vt_symbol", how="left")
            )
        else:
            per_sym["n_buy_open"] = 0
            per_sym["n_sell_close"] = 0
            per_sym["n_short_open"] = 0
            per_sym["n_buy_cover"] = 0
        for c in ("n_buy_open", "n_sell_close", "n_short_open", "n_buy_cover"):
            if c in per_sym.columns:
                per_sym[c] = per_sym[c].fillna(0).astype(int)
            else:
                per_sym[c] = 0
        per_sym["win_rate_rounds"] = np.where(
            per_sym["n_round_trips"] > 0,
            per_sym["win_rounds"] / per_sym["n_round_trips"],
            float("nan"),
        )

    n_round = int(len(rounds_df))
    n_buy_all = int(len(trades_df[trades_df["action"] == "买入开仓"])) if not trades_df.empty else 0
    n_sell_all = int(len(trades_df[trades_df["action"] == "卖出平仓"])) if not trades_df.empty else 0
    n_short_all = int(len(trades_df[trades_df["action"] == "卖出开仓"])) if not trades_df.empty else 0
    n_cover_all = int(len(trades_df[trades_df["action"] == "买入平仓"])) if not trades_df.empty else 0
    total_pnl = float(rounds_df["round_pnl_cash"].sum()) if n_round else 0.0
    cap = float(job.initial_capital) if math.isfinite(float(job.initial_capital)) and float(job.initial_capital) > 0 else 0.0
    ret_on_capital = (total_pnl / cap) if cap > 1e-12 else float("nan")
    wins = int(rounds_df["win"].sum()) if n_round and "win" in rounds_df.columns else 0
    win_rate_all = (wins / n_round) if n_round else float("nan")
    mean_round_pct = float(rounds_df["round_pnl_pct"].mean()) if n_round else float("nan")
    nw_metrics = _notional_weighted_round_return_metrics(rounds_df, total_pnl)

    # 组合摘要中文说明：与 JSON 截面附加条件一致
    _long_note = f"名次<={long_top_n}"
    if long_require_close_positive:
        _long_note += "、close>0"
    if long_require_composite_positive:
        _long_note += "、slss_composite>0"
    if short_bottom_n > 0:
        _short_note = f"名次最差 {short_bottom_n} 只（当日有效样本内合成最低的一段）"
    else:
        _short_note = f"名次>={short_min_rank}"
    if short_or_negative_composite:
        _short_note += "；或（非多头时）slss_composite<0"
    _cs_note = (
        "截面排名模式：每日按 slss_composite 全市场排序；"
        f"多头：{_long_note}；空头：{_short_note}；其余平仓。"
        "未扣手续费/滑点；A 股融券可得性未建模。"
    )
    if not allow_long_buy:
        _cs_note += " selection门控：N 因子未全部 feasible，已禁止多头新开仓。"
    if force_sell_long:
        _cs_note += " selection门控：not_feasible>N/3，已有多头按规则优先平仓。"
    # 现货账户：与实盘一致的信号钳制与 T+1 说明写入 note，便于报告归档
    if bool(a_share_cash_stock_rules):
        _cs_note += (
            " A股现货（a_share_cash_stock_rules）：截面目标 -1 已置为 0（不做裸卖空）；"
            "多头卖出仅允许在买入开仓日之后的日历日（日 K 近似 T+1）。"
        )

    portfolio: dict[str, Any] = {
        "threshold_mode": mode_label,
        "signal_column_used": "_cs_target(-1/0/1)",
        "cross_section_long_top_n": long_top_n,
        "cross_section_short_min_rank": short_min_rank,
        "cross_section_long_require_close_positive": long_require_close_positive,
        "cross_section_long_require_composite_positive": long_require_composite_positive,
        "cross_section_short_bottom_n": short_bottom_n,
        "cross_section_short_or_negative_composite": short_or_negative_composite,
        "a_share_cash_stock_rules": bool(a_share_cash_stock_rules),
        "buy_threshold_applied": None,
        "sell_threshold_applied": None,
        "fixed_lot_per_order": lot,
        "initial_capital_ui": cap,
        "n_symbols_in_panel": int(wk["vt_symbol"].nunique()),
        "n_symbols_with_any_round_trip": int(rounds_df["vt_symbol"].nunique()) if n_round else 0,
        "total_buy_orders": n_buy_all,
        "total_sell_orders": n_sell_all,
        "total_short_open_orders": n_short_all,
        "total_cover_orders": n_cover_all,
        "total_round_trips": n_round,
        "total_realized_pnl_cash": total_pnl,
        "simple_return_vs_initial_capital": ret_on_capital,
        "note": _cs_note,
        "all_round_trips_win_rate": win_rate_all,
        "all_round_trips_mean_pnl_pct": mean_round_pct,
        **nw_metrics,
        "notional_weighting_note": (
            "nominal_weighted_avg_round_return_on_notional = sum(round_pnl_cash)/sum(|open_price|×volume)，"
            "为各回合收益率按开仓名义加权的组合指标；simple_return_vs_initial_capital 仍为盈亏加总÷界面初始资金。"
        ),
    }

    return trades_df, rounds_df, per_sym, portfolio


def simulate_slss_trades(
    merged: pd.DataFrame,
    job: BacktestJobConfig,
    *,
    strategy_config=None,
    buy_threshold: float | None = None,
    sell_threshold: float | None = None,
    fixed_lot: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """
    对含 ``datetime, vt_symbol, close, slss_composite`` 的宽表逐标的回放。

    Returns:
        (逐笔买卖明细, 开平回合明细, 按股票汇总, 组合级统计字典)
    """
    need = {"datetime", "vt_symbol", "close", "slss_composite"}
    miss = need - set(merged.columns)
    if miss:
        raise ValueError(f"simulate_slss_trades 缺少列: {miss}")

    cfg = strategy_config or load_slss_strategy_config(overrides=job.effective_strategy_params())
    lot = int(fixed_lot) if fixed_lot is not None else int(cfg.fixed_lot)
    tsim = cfg.trade_simulation
    # selection 门控：与策略侧一致，快照缺失按不通过处理。
    snap = load_factor_selection_snapshot()
    fac_map = snap.get("factors") if isinstance(snap, dict) else {}
    if not isinstance(fac_map, dict):
        fac_map = {}
    n = int(len(cfg.bundle_factor_ids))
    false_cnt = 0
    true_cnt = 0
    for fid in cfg.bundle_factor_ids:
        rec = fac_map.get(str(fid))
        feasible = bool(isinstance(rec, dict) and rec.get("selection_feasible") is True)
        if feasible:
            true_cnt += 1
        else:
            false_cnt += 1
    selection_allow_buy = bool(n > 0 and true_cnt == n)
    selection_force_sell = bool(false_cnt * 3 > n) if n > 0 else False

    work = merged.copy()
    work = work.sort_values(["vt_symbol", "datetime"], kind="mergesort").reset_index(drop=True)
    diag = _diagnostics_slss(work)

    # 截面排名：每日全市场分桶，逐标的调仓（与 JSON decision_mode=cross_section_rank 一致）
    if cfg.decision_mode == "cross_section_rank":
        mode = (
            f"cross_section_rank_long{cfg.cross_section_long_top_n}"
            f"_shortMinRank{cfg.cross_section_short_min_rank}"
        )
        trades_cs, rounds_cs, per_sym_cs, port_cs = _simulate_cross_section_buckets(
            work,
            job,
            long_top_n=int(cfg.cross_section_long_top_n),
            short_min_rank=int(cfg.cross_section_short_min_rank),
            long_require_close_positive=bool(cfg.cross_section_long_require_close_positive),
            long_require_composite_positive=bool(cfg.cross_section_long_require_composite_positive),
            short_bottom_n=int(cfg.cross_section_short_bottom_n),
            short_or_negative_composite=bool(cfg.cross_section_short_or_negative_composite),
            a_share_cash_stock_rules=bool(cfg.a_share_cash_stock_rules),
            fixed_lot=lot,
            mode_label=mode,
            allow_long_buy=selection_allow_buy,
            force_sell_long=selection_force_sell,
        )
        port_cs.update(diag)
        port_cs["selection_allow_buy"] = selection_allow_buy
        port_cs["selection_force_sell"] = selection_force_sell
        port_cs["selection_false_count"] = false_cnt
        port_cs["selection_total_n"] = n
        port_cs["slss_strategy_config_path"] = str(SLSS_STRATEGY_JSON_PATH)
        return trades_cs, rounds_cs, per_sym_cs, port_cs

    bt = float(buy_threshold) if buy_threshold is not None else float(cfg.buy_threshold)
    st = float(sell_threshold) if sell_threshold is not None else float(cfg.sell_threshold)
    if not selection_allow_buy:
        # 不允许买入时把开仓阈值置为 +inf，避免产生新买单。
        bt = float("inf")
    if selection_force_sell:
        # 强平时把平仓阈值置为 +inf，使已有多头在首个有效信号日即触发卖出平仓。
        st = float("inf")

    # 1) 与 CTA 一致的 raw 合成值 + 配置中的固定阈值
    raw_mode = f"raw_slss_composite_vs_{bt}_{st}"
    trades, rounds, per_sym, port = _simulate_with_signal(
        work,
        job,
        signal_col="slss_composite",
        buy_threshold=bt,
        sell_threshold=st,
        fixed_lot=lot,
        threshold_mode=raw_mode,
        a_share_cash_stock_rules=bool(cfg.a_share_cash_stock_rules),
    )
    port.update(diag)
    port["selection_allow_buy"] = selection_allow_buy
    port["selection_force_sell"] = selection_force_sell
    port["selection_false_count"] = false_cnt
    port["selection_total_n"] = n
    port["raw_buy_threshold_config"] = bt
    port["raw_sell_threshold_config"] = st
    port["slss_strategy_config_path"] = str(SLSS_STRATEGY_JSON_PATH)

    if port["total_round_trips"] > 0:
        return trades, rounds, per_sym, port

    if not tsim.enable_rolling_z_fallback:
        port["fallback_rolling_z_note"] = "配置 trade_simulation.enable_rolling_z_fallback=false，未启用滚动 z 备用，逐笔可能为空。"
        return trades, rounds, per_sym, port

    # 2) 全样本常无成交：用逐标的滚动 z 作信号，避免报告逐笔表为空（参数见 Config/slss_strategy.json）
    work["_sig_roll_z"] = _rolling_z_by_symbol(
        work,
        "slss_composite",
        tsim.rolling_window,
        tsim.rolling_min_periods,
    )
    z_mode = (
        f"rolling_z_win{tsim.rolling_window}_minp{tsim.rolling_min_periods}_"
        f"buyZ{tsim.fallback_buy_z}_sellZ{tsim.fallback_sell_z}_after_zero_raw_trades"
    )
    trades2, rounds2, per_sym2, port2 = _simulate_with_signal(
        work,
        job,
        signal_col="_sig_roll_z",
        buy_threshold=float(tsim.fallback_buy_z),
        sell_threshold=float(tsim.fallback_sell_z),
        fixed_lot=lot,
        threshold_mode=z_mode,
        a_share_cash_stock_rules=bool(cfg.a_share_cash_stock_rules),
    )
    port2.update(diag)
    port2["raw_buy_threshold_config"] = bt
    port2["raw_sell_threshold_config"] = st
    port2["slss_strategy_config_path"] = str(SLSS_STRATEGY_JSON_PATH)
    port2["fallback_rolling_z_note"] = (
        "原始 slss_composite 在配置阈值下无完整开平回合（常见为 Alpha 特征量纲偏小）；"
        f"已按 slss_strategy.json 中 trade_simulation 启用滚动 z："
        f"window={tsim.rolling_window}, min_periods={tsim.rolling_min_periods}, "
        f"buy_z={tsim.fallback_buy_z}, sell_z={tsim.fallback_sell_z}。"
    )
    return trades2, rounds2, per_sym2, port2


def _calendar_days(a: Any, b: Any) -> int:
    """开仓日至平仓日的日历天间隔（含端点近似为日期差）。"""
    try:
        da = pd.Timestamp(a).normalize()
        db = pd.Timestamp(b).normalize()
        return int((db - da).days)
    except Exception:  # noqa: BLE001
        return -1


def portfolio_summary_rows(portfolio: dict[str, Any]) -> pd.DataFrame:
    """组合统计字典 → 两列键值表，便于写入 Excel。"""
    return pd.DataFrame(
        [{"key": k, "value": portfolio[k]} for k in sorted(portfolio.keys())],
    )
