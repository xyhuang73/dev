"""S000002 SLSS 策略的统一信号和目标仓位适配器。"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from InnerStrategy.slss_cross_section import compute_cross_section_target_side
from InnerStrategy.slss_strategy_config import SlssStrategyConfig
from quant.engine.contracts import (
    SignalDirection,
    SignalFrame,
    SignalRecord,
    TargetPosition,
    TargetPositionRecord,
)


def _rolling_z_by_symbol(df: pd.DataFrame, col: str, win: int, min_periods: int) -> pd.Series:
    return df.groupby("vt_symbol", sort=False)[col].transform(
        lambda series: (series - series.rolling(win, min_periods=min_periods).mean())
        / (series.rolling(win, min_periods=min_periods).std() + 1e-12),
    )


def _cross_section_outputs(
    frame: pd.DataFrame,
    cfg: SlssStrategyConfig,
    *,
    allow_long_buy: bool,
    force_sell_long: bool,
) -> tuple[SignalFrame, TargetPosition]:
    raw_side = compute_cross_section_target_side(
        frame,
        value_col="slss_composite",
        long_top_n=cfg.cross_section_long_top_n,
        short_min_rank=cfg.cross_section_short_min_rank,
        long_require_close_positive=cfg.cross_section_long_require_close_positive,
        long_require_composite_positive=cfg.cross_section_long_require_composite_positive,
        short_bottom_n=cfg.cross_section_short_bottom_n,
        short_or_negative_composite=cfg.cross_section_short_or_negative_composite,
    )
    signals: list[SignalRecord] = []
    targets: list[TargetPositionRecord] = []
    lot = int(cfg.fixed_lot)
    for row_position, (_, row) in enumerate(frame.iterrows()):
        dt = pd.Timestamp(row["datetime"]).to_pydatetime()
        symbol = str(row["vt_symbol"])
        score_value = row["slss_composite"]
        score = float(score_value) if np.isfinite(score_value) else None
        side = int(raw_side.iloc[row_position])
        direction = {
            1: SignalDirection.LONG,
            -1: SignalDirection.SHORT,
            0: SignalDirection.FLAT,
        }[side]
        signals.append(SignalRecord(dt, symbol, score, direction, "slss_cross_section_rank"))

        executable_side = side
        reasons = ["cross_section_target"]
        if cfg.a_share_cash_stock_rules and executable_side < 0:
            executable_side = 0
            reasons.append("a_share_long_only_short_clamped")
        if executable_side > 0 and not allow_long_buy:
            executable_side = 0
            reasons.append("factor_selection_gate_blocks_buy")
        if executable_side > 0 and force_sell_long:
            executable_side = 0
            reasons.append("factor_selection_gate_forces_exit")
        targets.append(
            TargetPositionRecord(
                dt,
                symbol,
                target_volume=executable_side * lot,
                reason=";".join(reasons),
            ),
        )
    return SignalFrame.from_records(signals), TargetPosition.from_records(targets)


def _threshold_outputs(
    frame: pd.DataFrame,
    cfg: SlssStrategyConfig,
    *,
    signal_column_used: str,
    allow_long_buy: bool,
    force_sell_long: bool,
) -> tuple[SignalFrame, TargetPosition]:
    work = frame.copy().sort_values(["vt_symbol", "datetime"], kind="mergesort")
    if signal_column_used == "_sig_roll_z":
        tsim = cfg.trade_simulation
        work[signal_column_used] = _rolling_z_by_symbol(
            work,
            "slss_composite",
            tsim.rolling_window,
            tsim.rolling_min_periods,
        )
        buy_threshold = float(tsim.fallback_buy_z)
        sell_threshold = float(tsim.fallback_sell_z)
    else:
        signal_column_used = "slss_composite"
        buy_threshold = float(cfg.buy_threshold)
        sell_threshold = float(cfg.sell_threshold)
    if not allow_long_buy:
        buy_threshold = float("inf")
    if force_sell_long:
        sell_threshold = float("inf")

    signals: list[SignalRecord] = []
    targets: list[TargetPositionRecord] = []
    lot = int(cfg.fixed_lot)
    for symbol, group in work.groupby("vt_symbol", sort=False):
        desired_volume = 0
        for _, row in group.iterrows():
            rule_value = row[signal_column_used]
            if not np.isfinite(rule_value):
                continue
            dt = pd.Timestamp(row["datetime"]).to_pydatetime()
            raw_value = row["slss_composite"]
            score = float(raw_value) if np.isfinite(raw_value) else None
            reason = f"{signal_column_used}={float(rule_value):.8g}"
            if desired_volume == 0 and float(rule_value) > buy_threshold:
                desired_volume = lot
                direction = SignalDirection.LONG
                reason += f";above_buy_threshold={buy_threshold:.8g}"
            elif desired_volume > 0 and float(rule_value) < sell_threshold:
                desired_volume = 0
                direction = SignalDirection.EXIT
                reason += f";below_sell_threshold={sell_threshold:.8g}"
            else:
                direction = SignalDirection.FLAT
            signals.append(SignalRecord(dt, str(symbol), score, direction, reason))
            targets.append(
                TargetPositionRecord(
                    dt,
                    str(symbol),
                    target_volume=desired_volume,
                    reason=f"threshold_target;source={signal_column_used}",
                ),
            )
    return SignalFrame.from_records(signals), TargetPosition.from_records(targets)


def build_s000002_outputs(
    merged: pd.DataFrame,
    cfg: SlssStrategyConfig,
    portfolio_stats: dict[str, Any],
) -> tuple[SignalFrame, TargetPosition]:
    """将 SLSS 宽表转换为统一合同，并复用实际回测采用的信号模式。"""
    required = {"datetime", "vt_symbol", "slss_composite"}
    missing = required - set(merged.columns)
    if missing:
        raise ValueError(f"S000002 输出适配缺少列: {sorted(missing)}")
    work = merged.loc[pd.to_numeric(merged["slss_composite"], errors="coerce").notna()].copy()
    work = work.reset_index(drop=True)
    allow_long_buy = bool(portfolio_stats.get("selection_allow_buy", True))
    force_sell_long = bool(portfolio_stats.get("selection_force_sell", False))
    if cfg.decision_mode == "cross_section_rank":
        return _cross_section_outputs(
            work,
            cfg,
            allow_long_buy=allow_long_buy,
            force_sell_long=force_sell_long,
        )
    return _threshold_outputs(
        work,
        cfg,
        signal_column_used=str(portfolio_stats.get("signal_column_used") or "slss_composite"),
        allow_long_buy=allow_long_buy,
        force_sell_long=force_sell_long,
    )
