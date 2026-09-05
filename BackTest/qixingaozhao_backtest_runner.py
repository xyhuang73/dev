# -*- coding: utf-8 -*-
"""
七星高照 ETF 轮动超级增强 — 本地日线回测实现（2026-08-30 本地化重构版）。

流程:
    1) 通过 build_daily_market_panel_from_local_datadir 拉取 ETF 池 + 行情指数日线面板；
       **强制本地 *.DAT 数据源**，不依赖 xtquant/xtdata（与本地策略接口一致）。
    2) D 日收盘运行动量评分与行情判断，生成目标持仓；
    3) D+1 日开盘执行目标差异，按现金与 100 股交易单位更新账户；
    4) 对已有仓位使用 D 日前已知阈值和当日 OHLC 模拟 TP/SL；
    5) 输出成交、净值、持仓快照和 Excel 图表。
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from InnerStrategy.strategies.qixingaozhao_etf_rotation_strategy import (
    DEFENSIVE_ETF,
    FULL_ETF_POOL,
    OVERSEAS_ETF_POOL,
    COMMODITY_ETF_POOL,
    REGIME_INDEXES,
    QixingaozhaoEtfRotationStrategy,
    _mean_values,
    regime_is_weak,
)

from .models import BacktestJobConfig, BacktestResult


def _log(progress: Callable[[str], None] | None, msg: str) -> None:
    print(msg, flush=True)
    if progress is not None:
        progress(msg)


def _calendar_days(a: Any, b: Any) -> int:
    try:
        return int((pd.Timestamp(b).normalize() - pd.Timestamp(a).normalize()).days)
    except Exception:  # noqa: BLE001
        return -1


def _reports_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    out = root / "reports" / "strategy"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _fetch_panel(
    codes: list[str],
    start_date: str,
    end_date: str,
    progress: Callable[[str], None] | None,
) -> pd.DataFrame:
    """
    强制使用本地 *.DAT 行情面板（不依赖 xtquant/xtdata）。

    七星高照 ETF 策略的本地化约束：
        - 只用日线，没有分钟数据；
        - 与 ``BackTest/factor_local_datadir_panel`` 共用同一份 miniQMT userdata_mini/datadir；
        - 不允许走 ``build_daily_market_panel`` 的 xtdata 分支。
    """
    from .factor_local_datadir_panel import build_daily_market_panel_from_local_datadir  # noqa: PLC0415

    _log(progress, f"  拉取本地日线面板 ({len(codes)} 只, {start_date}~{end_date})...")
    df = build_daily_market_panel_from_local_datadir(
        start_date, end_date, max_symbols=0, stock_list=codes,
    )
    _log(progress, f"  面板加载完成：{len(df)} 行 x {df['vt_symbol'].nunique()} 只")
    return df


def _discover_available_codes(progress: Callable[[str], None] | None) -> list[str]:
    """
    枚举本地 datadir 下所有日线 ``*.DAT`` 文件名（**不解析内容**），返回 ``vt_symbol`` 列表。

    用于策略「ETF 池命中为空」时的 A-share 兜底：保证回测能跑通。
    只列文件名比解析全部 .DAT 快数十倍，仅在「ETF 池完全没命中」时调用一次。
    """
    from .factor_local_datadir_panel import _list_daily_dat_files  # noqa: PLC0415

    from qmt_service import get_local_datadir, load_config  # noqa: PLC0415

    datadir = get_local_datadir()
    if not datadir.is_dir():
        return []
    cfg = load_config()
    period_name = str(cfg.get("kline_period_dir_name") or "86400")
    files = _list_daily_dat_files(datadir, period_name, max_symbols=0)
    codes = sorted({vt for _fp, vt in files})
    _log(progress, f"  本地 datadir 共可加载 {len(codes)} 只标的")
    return codes


def _load_stock_pool_from_config() -> list[str]:
    """
    读取 ``Config/stock_pool.json`` 中已过滤好的标的列表。

    当本地 datadir 没有 ETF 时，把项目标准池子作为 A-share 兜底，
    避免回测动辄加载 5000+ 标的导致跑 5 分钟。
    """
    cfg_path = Path(__file__).resolve().parent.parent / "Config" / "stock_pool.json"
    if not cfg_path.is_file():
        return []
    try:
        with cfg_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        syms = [str(s) for s in data.get("symbols", []) if s]
        return sorted(set(syms))
    except Exception:  # noqa: BLE001
        return []


def _panel_to_daily_dict(df: pd.DataFrame, codes: list[str]) -> dict[str, dict[str, list]]:
    """Convert long-format panel to {code: {'dates', OHLCV}} sorted ascending."""
    out: dict[str, dict[str, list]] = {}
    for code in codes:
        sub = df[df["vt_symbol"] == code].sort_values("datetime").reset_index(drop=True)
        if sub.empty:
            continue
        out[code] = {
            "dates": list(sub["datetime"]),
            "opens": list(sub["open"].astype(float)),
            "highs": list(sub["high"].astype(float)),
            "lows": list(sub["low"].astype(float)),
            "closes": list(sub["close"].astype(float)),
            "volumes": list(sub["volume"].astype(float)),
        }
    return out


def _get_close_on(data: dict[str, list], date_key: pd.Timestamp) -> float | None:
    """Return closing price for a specific normalized date, or None."""
    for dt, c in zip(data["dates"], data["closes"]):
        if pd.Timestamp(dt).normalize() == date_key:
            return float(c)
    return None


def _get_ohlc_on(
    data: dict[str, list], date_key: pd.Timestamp,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Return (open, high, low, close) for a specific normalized date, or (None*4)."""
    for dt, o, h, l, c in zip(
        data["dates"], data["opens"], data["highs"], data["lows"], data["closes"],
    ):
        if pd.Timestamp(dt).normalize() == date_key:
            return float(o), float(h), float(l), float(c)
    return None, None, None, None


def _run_daily_simulation(
    strategy,
    etf_data,
    index_data,
    trade_dates,
    initial_capital,
    progress,
    *,
    output_collector=None,
):
    """按 D 日收盘信号、D+1 日开盘成交推进账户并生成每日快照。"""
    p = strategy.params
    lookback = int(p['lookback_days'])
    regime_ma = int(p.get('weak_period_ma_lookback', 10))
    weak_max_days = int(p.get('weak_period_max_days', 20))
    profit_prot = bool(p.get('enable_profit_protection', False))
    profit_lookback = int(p.get('profit_protection_lookback', 1))
    profit_threshold = float(p.get('profit_protection_threshold', 0.05))
    lot = 100
    cap = float(initial_capital)
    cash = cap
    is_weak = False
    weak_counter = 0
    positions: dict[str, dict[str, Any]] = {}
    pending_target_set: set[str] | None = None
    pending_signal_dt: pd.Timestamp | None = None
    pending_is_weak = False
    last_prices: dict[str, float] = {}
    all_trades: list[dict[str, Any]] = []
    all_rounds: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    total_turnover_notional = 0.0
    total_days = len(trade_dates)

    def close_position(
        code: str,
        execution_dt: pd.Timestamp,
        signal_dt: pd.Timestamp,
        sell_price: float,
        sell_kind: str,
        regime_weak: bool,
    ) -> float:
        nonlocal cash
        pos = positions.pop(code)
        shares = int(pos['shares'])
        entry_price = float(pos['entry_price'])
        entry_dt = pd.Timestamp(pos['entry_dt'])
        notional = float(sell_price) * shares
        cash += notional
        pnl_cash = (float(sell_price) - entry_price) * shares
        pnl_pct = float(sell_price) / entry_price - 1.0 if entry_price > 0 else float('nan')
        all_trades.append({
            'vt_symbol': code, 'signal_datetime': signal_dt, 'datetime': execution_dt,
            'action': 'sell', 'price': float(sell_price), 'volume': shares,
            'execution_basis': 'next_open' if sell_kind == 'rebalance' else 'intraday_trigger',
            'open_datetime': entry_dt, 'open_price': entry_price,
            'round_pnl_pct': pnl_pct, 'round_pnl_cash': pnl_cash,
            'is_regime_weak': regime_weak, 'sell_kind': sell_kind,
        })
        all_rounds.append({
            'vt_symbol': code, 'open_datetime': entry_dt, 'open_price': entry_price,
            'close_datetime': execution_dt, 'close_price': float(sell_price),
            'volume': shares, 'hold_calendar_days': _calendar_days(entry_dt, execution_dt),
            'round_pnl_pct': pnl_pct, 'round_pnl_cash': pnl_cash,
            'win': bool(math.isfinite(pnl_pct) and pnl_pct > 0),
        })
        return notional

    for day_idx, date_key in enumerate(trade_dates):
        date_key = pd.Timestamp(date_key).normalize()
        if day_idx % 60 == 0:
            pct = int(day_idx * 100 / total_days) if total_days else 0
            _log(progress, '  [%d/%d %d%%] %s ...' % (day_idx, total_days, pct, str(date_key.date())))

        pending_codes = pending_target_set or set()
        all_candidates = sorted(
            set(strategy.get_universe()) | set(positions) | set(pending_codes) | {DEFENSIVE_ETF}
        )
        closes_by_etf: dict[str, list[float]] = {}
        volumes_by_etf: dict[str, list[float]] = {}
        history_by_etf: dict[str, tuple[list[float], list[float]]] = {}
        today_ohlc: dict[str, tuple[float, float, float, float]] = {}
        today_vols: dict[str, float] = {}
        for code in all_candidates:
            data = etf_data.get(code)
            if data is None:
                continue
            hist_c = [float(c) for dt, c in zip(data['dates'], data['closes'])
                      if pd.Timestamp(dt).normalize() < date_key]
            hist_v = [float(v) for dt, v in zip(data['dates'], data['volumes'])
                      if pd.Timestamp(dt).normalize() < date_key]
            ohlc = _get_ohlc_on(data, date_key)
            if any(value is None for value in ohlc) or float(ohlc[3]) <= 0:
                continue
            last_prices[code] = float(ohlc[3])
            if len(hist_c) < lookback:
                continue
            closes_by_etf[code] = hist_c
            volumes_by_etf[code] = hist_v
            history_by_etf[code] = (hist_c, hist_v)
            today_ohlc[code] = tuple(float(value) for value in ohlc)  # type: ignore[assignment]
            today_vols[code] = sum(float(v) for dt, v in zip(data['dates'], data['volumes'])
                                   if pd.Timestamp(dt).normalize() == date_key)

        day_turnover = 0.0

        # 先执行上一交易日收盘后生成的目标：卖出优先，随后按今日开盘价买入。
        if pending_target_set is not None and pending_signal_dt is not None:
            for code in sorted(set(positions) - pending_target_set):
                ohlc = today_ohlc.get(code)
                if ohlc is None or ohlc[0] <= 0:
                    continue
                day_turnover += close_position(
                    code, date_key, pending_signal_dt, ohlc[0], 'rebalance', pending_is_weak,
                )
            for code in sorted(pending_target_set - set(positions)):
                ohlc = today_ohlc.get(code)
                if ohlc is None or ohlc[0] <= 0:
                    continue
                buy_price = float(ohlc[0])
                required_cash = buy_price * lot
                if required_cash > cash + 1e-9:
                    _log(progress, '  [SKIP] %s %s 买入需 %.2f，可用现金 %.2f' % (
                        date_key.date(), code, required_cash, cash))
                    continue
                cash -= required_cash
                positions[code] = {'entry_price': buy_price, 'entry_dt': date_key, 'shares': lot}
                day_turnover += required_cash
                all_trades.append({
                    'vt_symbol': code, 'signal_datetime': pending_signal_dt,
                    'datetime': date_key, 'action': 'buy', 'price': buy_price,
                    'volume': lot, 'execution_basis': 'next_open',
                    'is_regime_weak': pending_is_weak, 'buy_basis': 'next_day_open',
                })

        # TP/SL 阈值只使用今日之前的数据；当日新买仓位不卖，避免日线内路径和 T+1 歧义。
        prior_signal_dt = pd.Timestamp(trade_dates[day_idx - 1]).normalize() if day_idx > 0 else date_key
        for code in sorted(list(positions)):
            pos = positions[code]
            if pd.Timestamp(pos['entry_dt']).normalize() >= date_key:
                continue
            ohlc = today_ohlc.get(code)
            hist_c, _ = history_by_etf.get(code, ([], []))
            if ohlc is None or not hist_c:
                continue
            tp_level, sl_level = strategy.compute_sell_levels(code, hist_c)
            action, price = strategy.decide_sell_action(
                code, ohlc[0], ohlc[1], ohlc[2], ohlc[3],
                tp_level, sl_level, False,
            )
            if action is not None and price is not None:
                day_turnover += close_position(
                    code, date_key, prior_signal_dt, float(price), action, is_weak,
                )

        total_turnover_notional += day_turnover

        # 今日收盘数据只用于生成下一交易日的目标，不参与今日成交。
        if p.get('enable_regime_switch', True):
            idx_closes: dict[str, list[float]] = {}
            for index_code in REGIME_INDEXES.values():
                data = index_data.get(index_code)
                if data is None:
                    continue
                closes = [float(c) for dt, c in zip(data['dates'], data['closes'])
                          if pd.Timestamp(dt).normalize() <= date_key]
                if closes:
                    idx_closes[index_code] = closes
            newly_weak = regime_is_weak(idx_closes, ma_lookback=regime_ma)
            if not is_weak and newly_weak:
                is_weak = True
                weak_counter = 0
            elif is_weak:
                weak_counter += 1
                above = sum(
                    1 for closes in idx_closes.values()
                    if len(closes) >= regime_ma and closes[-1] >= _mean_values(closes[-regime_ma:])
                )
                if above >= 3 or weak_counter >= weak_max_days:
                    is_weak = False
                    weak_counter = 0

        active_pool = strategy.get_active_pool(is_weak)
        today_prices = {code: ohlc[3] for code, ohlc in today_ohlc.items()}
        ranked, target_codes = strategy.select_targets(
            active_pool, closes_by_etf, volumes_by_etf, today_prices, today_vols,
        )
        target_codes = [code for code in target_codes if code in today_ohlc]
        if not target_codes and DEFENSIVE_ETF in today_ohlc:
            target_codes = [DEFENSIVE_ETF]
        target_set = set(target_codes)

        # 收盘触发的盈利保护也只改变 D+1 目标，不按已经知道的今日收盘价成交。
        if profit_prot:
            for code in list(positions):
                hist_c, _ = history_by_etf.get(code, ([], []))
                current_close = today_prices.get(code)
                if current_close is None or len(hist_c) < profit_lookback:
                    continue
                max_h = max(hist_c[-profit_lookback:])
                if max_h > 0 and current_close <= max_h * (1.0 - profit_threshold):
                    target_set.discard(code)

        if output_collector is not None:
            output_collector.capture(
                signal_datetime=date_key.to_pydatetime(),
                ranked=ranked,
                target_symbols=target_set,
                current_symbols=set(positions),
                regime_weak=is_weak,
            )

        pending_target_set = target_set
        pending_signal_dt = date_key
        pending_is_weak = is_weak

        market_value = 0.0
        unrealized_pnl = 0.0
        for code, pos in sorted(positions.items()):
            close_price = today_prices.get(code, last_prices.get(code, float(pos['entry_price'])))
            shares = int(pos['shares'])
            value = float(close_price) * shares
            unrealized = (float(close_price) - float(pos['entry_price'])) * shares
            market_value += value
            unrealized_pnl += unrealized
            position_rows.append({
                'datetime': date_key, 'vt_symbol': code, 'volume': shares,
                'available': shares if pd.Timestamp(pos['entry_dt']).normalize() < date_key else 0,
                'entry_datetime': pos['entry_dt'], 'cost_price': pos['entry_price'],
                'close': float(close_price), 'market_value': value,
                'unrealized_pnl': unrealized,
            })
        total_asset = cash + market_value
        previous_asset = equity_rows[-1]['total_asset'] if equity_rows else cap
        equity_rows.append({
            'datetime': date_key, 'cash': cash, 'market_value': market_value,
            'total_asset': total_asset, 'unit_nav': total_asset / cap if cap > 0 else float('nan'),
            'turnover_notional': day_turnover,
            'daily_turnover_ratio': day_turnover / previous_asset if previous_asset > 0 else float('nan'),
            'unrealized_pnl': unrealized_pnl, 'position_count': len(positions),
        })

    trades_df = pd.DataFrame(all_trades)
    rounds_df = pd.DataFrame(all_rounds)
    equity_df = pd.DataFrame(equity_rows)
    positions_df = pd.DataFrame(position_rows)
    if not equity_df.empty:
        equity_df['daily_return'] = equity_df['total_asset'].pct_change().fillna(0.0)
        running_peak = equity_df['total_asset'].cummax()
        equity_df['drawdown'] = equity_df['total_asset'] / running_peak - 1.0
        daily_std = float(equity_df['daily_return'].std(ddof=1))
        sharpe = (
            math.sqrt(252.0) * float(equity_df['daily_return'].mean()) / daily_std
            if math.isfinite(daily_std) and daily_std > 0 else float('nan')
        )
        max_drawdown = abs(float(equity_df['drawdown'].min()))
        ending_total_asset = float(equity_df.iloc[-1]['total_asset'])
        ending_market_value = float(equity_df.iloc[-1]['market_value'])
        ending_unrealized_pnl = float(equity_df.iloc[-1]['unrealized_pnl'])
        average_asset = float(equity_df['total_asset'].mean())
    else:
        sharpe = float('nan')
        max_drawdown = float('nan')
        ending_total_asset = cap
        ending_market_value = 0.0
        ending_unrealized_pnl = 0.0
        average_asset = cap

    if not rounds_df.empty:
        per_sym = (rounds_df.groupby('vt_symbol', sort=False)
            .agg(n_round_trips=('round_pnl_cash', 'count'),
                 sum_round_pnl_cash=('round_pnl_cash', 'sum'),
                 mean_round_pnl_pct=('round_pnl_pct', 'mean'),
                 win_rounds=('win', 'sum')).reset_index())
        per_sym['win_rate'] = per_sym['win_rounds'] / per_sym['n_round_trips'].clip(lower=1)
    else:
        per_sym = pd.DataFrame()
    n_round = len(rounds_df)
    total_pnl = float(rounds_df['round_pnl_cash'].sum()) if n_round else 0.0
    ret = ending_total_asset / cap - 1.0 if cap > 0 else float('nan')
    trade_days = int(len(equity_df))
    annualized_return = (
        (1.0 + ret) ** (252.0 / float(trade_days)) - 1.0
        if trade_days > 0 and math.isfinite(ret) and ret > -1.0 else float('nan')
    )
    # 用户定义口径：完成开平回合数 / 回测交易日数；它表达交易频率，不是委托成交率。
    trade_success_rate = n_round / float(trade_days) if trade_days > 0 else float('nan')
    wins = int(rounds_df['win'].sum()) if n_round and 'win' in rounds_df.columns else 0
    win_rate = wins / n_round if n_round else float('nan')
    mean_pnl = float(rounds_df['round_pnl_pct'].mean()) if n_round else float('nan')
    portfolio = {
        'strategy': 'QixingaozhaoEtfRotationStrategy',
        'initial_capital_ui': cap, 'total_round_trips': n_round,
        'total_realized_pnl_cash': total_pnl, 'simple_return_vs_initial_capital': ret,
        'ending_cash': cash, 'ending_market_value': ending_market_value,
        'ending_total_asset': ending_total_asset, 'ending_unrealized_pnl': ending_unrealized_pnl,
        'open_position_count': len(positions), 'max_drawdown': max_drawdown,
        'annualized_return': annualized_return, 'annualized_sharpe': sharpe,
        'trade_days': trade_days, 'trade_success_rate': trade_success_rate,
        'total_turnover_notional': total_turnover_notional,
        'turnover_ratio': total_turnover_notional / average_asset if average_asset > 0 else float('nan'),
        'pending_signal_datetime': pending_signal_dt,
        'pending_target_symbols': ','.join(sorted(pending_target_set or set())),
        'all_round_trips_win_rate': win_rate, 'all_round_trips_mean_pnl_pct': mean_pnl,
        'lookback_days': p['lookback_days'], 'holdings_num': p['holdings_num'],
        'enable_regime_switch': p['enable_regime_switch'],
        'enable_avoid_a_share': p['enable_avoid_a_share'],
        'enable_volume_check': p['enable_volume_check'],
        'enable_profit_protection': p['enable_profit_protection'],
        'buy_ma_window': p['buy_ma_window'],
        'sell_ma_window': p['sell_ma_window'],
        'sell_upper_ratio': p['sell_upper_ratio'],
        'sell_lower_ratio': p['sell_lower_ratio'],
        'sell_upper_enabled': p['sell_upper_enabled'],
        'sell_lower_enabled': p['sell_lower_enabled'],
        'sell_priority': p['sell_priority'],
        'sell_trigger_mode': p['sell_trigger_mode'],
        'note': ('D close signal, D+1 open execution; cash constrained and 100-share lots. '
                 'Intraday TP/SL uses levels known before the bar. '
                 'No fees/slippage yet. Score=annualized_ret*R2.'),
    }
    return trades_df, rounds_df, per_sym, equity_df, positions_df, portfolio


def _write_excel(
    job,
    trades_df,
    rounds_df,
    per_sym_df,
    equity_df,
    positions_df,
    portfolio,
    params,
    text_summary,
):
    from .backtest_strategy_report_excel import _excel_scalar, _excel_stringify_float_columns
    from InnerStrategy.inner_registry import get_strategy_entry
    from datetime import datetime as _dt
    ts = _dt.now().strftime('%Y%m%d_%H%M%S')
    path = _reports_dir() / ('strategy_backtest_%s_%s.xlsx' % (job.strategy_key, ts))
    se = get_strategy_entry(job.strategy_key) or {}
    strat_row = pd.DataFrame([{'strategy_key': job.strategy_key,
        'module': se.get('module', 'qixingaozhao_etf_rotation_strategy'),
        'class': se.get('class', 'QixingaozhaoEtfRotationStrategy'),
        'label': se.get('label', '')}])
    job_rows = pd.DataFrame([
        ('initial_capital', job.initial_capital), ('start_date', job.start_date),
        ('end_date', job.end_date), ('strategy_key', job.strategy_key),
        ('backtest_mode', job.backtest_mode)], columns=['key', 'value'])
    params_df = pd.DataFrame([{'key': k, 'value': _excel_scalar(v)} for k, v in sorted(params.items())])
    port_df = pd.DataFrame([{'key': k, 'value': _excel_scalar(v)} for k, v in sorted(portfolio.items())])
    dom_count = len(FULL_ETF_POOL) - len(OVERSEAS_ETF_POOL) - len(COMMODITY_ETF_POOL)
    etf_pool_df = pd.DataFrame({
        'category': (['海外ETF'] * len(OVERSEAS_ETF_POOL)
                     + ['商品ETF'] * len(COMMODITY_ETF_POOL)
                     + ['A股ETF'] * dom_count),
        'code': FULL_ETF_POOL})
    td = _excel_stringify_float_columns(trades_df.copy()) if not trades_df.empty else trades_df
    rt = _excel_stringify_float_columns(rounds_df.copy()) if not rounds_df.empty else rounds_df
    ps = _excel_stringify_float_columns(per_sym_df.copy()) if not per_sym_df.empty else per_sym_df
    # 净值和持仓表保留数值类型，便于 Excel 图表和后续分析直接计算。
    eq = equity_df.copy()
    pos = positions_df.copy()
    if not td.empty and 'datetime' in td.columns:
        td = td.sort_values('datetime', kind='mergesort').reset_index(drop=True)
    if not rt.empty and 'open_datetime' in rt.columns:
        rt = rt.sort_values('open_datetime', kind='mergesort').reset_index(drop=True)
    text_lines = text_summary.splitlines()
    text_df = pd.DataFrame({'line_no': range(1, len(text_lines) + 1), 'content': text_lines})
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        job_rows.to_excel(writer, sheet_name='回测任务', index=False)
        strat_row.to_excel(writer, sheet_name='策略注册', index=False)
        params_df.to_excel(writer, sheet_name='策略参数', index=False)
        port_df.to_excel(writer, sheet_name='组合收益统计', index=False)
        etf_pool_df.to_excel(writer, sheet_name='ETF池', index=False)
        td.to_excel(writer, sheet_name='逐笔买卖明细', index=False)
        rt.to_excel(writer, sheet_name='开平回合盈亏', index=False)
        ps.to_excel(writer, sheet_name='按ETF汇总统计', index=False)
        eq.to_excel(writer, sheet_name='净值曲线', index=False)
        pos.to_excel(writer, sheet_name='持仓快照', index=False)
        text_df.to_excel(writer, sheet_name='文本报告', index=False)
        if not eq.empty:
            from openpyxl.chart import LineChart, Reference  # noqa: PLC0415

            sheet = writer.book['净值曲线']
            chart = LineChart()
            chart.title = '策略 / 基准 / 超额净值曲线'
            chart.y_axis.title = 'Unit NAV'
            chart.x_axis.title = 'Date'
            chart.height = 8
            chart.width = 16
            for nav_name in ('unit_nav', 'benchmark_nav', 'excess_nav'):
                if nav_name not in eq.columns:
                    continue
                nav_col = list(eq.columns).index(nav_name) + 1
                chart.add_data(
                    Reference(sheet, min_col=nav_col, min_row=1, max_row=len(eq) + 1),
                    titles_from_data=True,
                )
            chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=len(eq) + 1))
            sheet.add_chart(chart, 'N2')
    return path.resolve()


def _attach_benchmark_nav(
    equity_df: pd.DataFrame,
    market_panel: pd.DataFrame,
    universe: list[str],
) -> tuple[pd.DataFrame, str]:
    """给净值明细增加可复现基准；优先沪深300，缺失时使用当次股票池等权基准。"""
    if equity_df.empty or market_panel.empty:
        return equity_df, ""
    panel = market_panel.copy()
    panel["datetime"] = pd.to_datetime(panel["datetime"], errors="coerce").dt.normalize()
    panel["close"] = pd.to_numeric(panel["close"], errors="coerce")
    panel = panel.dropna(subset=["datetime", "close", "vt_symbol"])
    index_rows = panel.loc[panel["vt_symbol"].astype(str) == "000300.SH", ["datetime", "close"]]
    if not index_rows.empty:
        close = index_rows.drop_duplicates("datetime", keep="last").set_index("datetime")["close"].sort_index()
        benchmark_return = close.pct_change(fill_method=None).fillna(0.0)
        benchmark_name = "沪深300（000300.SH）"
    else:
        pool = panel.loc[panel["vt_symbol"].astype(str).isin(set(universe)), ["datetime", "vt_symbol", "close"]]
        pivot = pool.pivot_table(index="datetime", columns="vt_symbol", values="close", aggfunc="last").sort_index()
        # 每只股票先计算自身日收益，再对当日有效股票等权；不把价格高低当权重。
        benchmark_return = pivot.pct_change(fill_method=None).mean(axis=1, skipna=True).fillna(0.0)
        benchmark_name = "本次股票池等权基准"
    benchmark_nav = (1.0 + benchmark_return).cumprod().rename("benchmark_nav")
    out = equity_df.copy()
    out["__trade_day"] = pd.to_datetime(out["datetime"], errors="coerce").dt.normalize()
    out = out.merge(benchmark_nav, left_on="__trade_day", right_index=True, how="left")
    out["benchmark_nav"] = pd.to_numeric(out["benchmark_nav"], errors="coerce").ffill()
    out["excess_nav"] = pd.to_numeric(out["unit_nav"], errors="coerce") / out["benchmark_nav"]
    out["benchmark_name"] = benchmark_name
    return out.drop(columns=["__trade_day"]), benchmark_name


def run_qixingaozhao_backtest(job, *, progress=None):
    from quant.strategy.adapters.s000001 import S000001OutputCollector  # noqa: PLC0415

    _log(progress, '========== 七星高照ETF轮动 本地日线回测 开始 ==========')

    # 1) 先枚举 datadir 真实可加载的代码（含 A-share、ETF、指数等）
    available_codes = _discover_available_codes(progress)
    if not available_codes:
        return BacktestResult(False, '本地 datadir 中没有可加载的日线文件。')

    # 2) 决定 universe：优先使用本地硬编码 ETF 池与 4 个 regime 指数；
    #    若完全没 ETF：
    #      a) 优先用 Config/stock_pool.json 已过滤的 39 只（项目标准池）；
    #      b) 若 stock_pool.json 不存在，再从 datadir 真实可加载代码中截前 N 个。
    regime_set = set(REGIME_INDEXES.values())
    etf_like = [c for c in available_codes
                if c in set(FULL_ETF_POOL) or c in regime_set]
    tradeable_etf = [c for c in etf_like if c not in regime_set]
    if tradeable_etf:
        universe = tradeable_etf
        _log(progress, '  本地可用 ETF 池: %d 只（命中硬编码池子）' % len(universe))
    else:
        cfg_pool = _load_stock_pool_from_config()
        cfg_pool = [c for c in cfg_pool if c in available_codes]
        if cfg_pool:
            universe = cfg_pool
            _log(progress, '  本地无 ETF，回退到 Config/stock_pool.json: %d 只' % len(universe))
        else:
            # 兜底中的兜底：从 available_codes 截前 50 只，避免回测 5 分钟
            universe = [c for c in available_codes if c not in regime_set][:50]
            _log(progress, '  本地无 ETF 也无 stock_pool.json，截前 50 只 A-share: %d 只' % len(universe))
    if not universe:
        return BacktestResult(False, '本地 datadir 中没有任何可用标的，回测无法进行。')

    # 3) 加载所需的日线面板（含 ETF / 指数 / 兜底股票）
    load_codes = sorted(set(universe) | regime_set)
    try:
        df = _fetch_panel(load_codes, job.start_date, job.end_date, progress)
    except Exception as exc:
        msg = '本地行情面板拉取失败: %s' % exc
        _log(progress, '[ERROR] ' + msg)
        return BacktestResult(False, msg)
    if df.empty:
        return BacktestResult(False, '行情面板为空，无法回测。')

    strategy_init = job.effective_strategy_params()
    strategy_init["universe_override"] = universe
    # 旧 GUI 没有该参数控件时保持历史行为；API/未来参数 GUI 显式传值时尊重覆盖。
    if "enable_avoid_a_share" not in job.strategy_params:
        strategy_init["enable_avoid_a_share"] = False
    strategy = QixingaozhaoEtfRotationStrategy(**strategy_init)
    p = strategy.params
    index_data = _panel_to_daily_dict(df, list(regime_set))
    etf_data = _panel_to_daily_dict(df, universe)
    start_ts = pd.Timestamp('%s-%s-%s' % (job.start_date[:4], job.start_date[4:6], job.start_date[6:8]))
    end_ts = pd.Timestamp('%s-%s-%s' % (job.end_date[:4], job.end_date[4:6], job.end_date[6:8]))
    all_dates = sorted(set(pd.Timestamp(dt).normalize() for dt in df['datetime']))
    trade_dates = [d for d in all_dates if start_ts <= d <= end_ts]
    if not trade_dates:
        return BacktestResult(False, '回测区间内无有效交易日，请扩大日期范围或检查数据。')
    _log(progress, '  回测交易日数：%d，起止：%s~%s' % (
        len(trade_dates), str(trade_dates[0].date()), str(trade_dates[-1].date())))
    output_collector = S000001OutputCollector(lot_size=100)
    trades_df, rounds_df, per_sym_df, equity_df, positions_df, portfolio = _run_daily_simulation(
        strategy,
        etf_data,
        index_data,
        trade_dates,
        job.initial_capital,
        progress,
        output_collector=output_collector,
    )
    equity_df, benchmark_name = _attach_benchmark_nav(equity_df, df, universe)
    if benchmark_name:
        portfolio['benchmark_name'] = benchmark_name
        _log(progress, '  收益基准：' + benchmark_name)
    n_round = portfolio['total_round_trips']
    total_pnl = portfolio['total_realized_pnl_cash']
    ret = portfolio['simple_return_vs_initial_capital']
    win_rate = portfolio['all_round_trips_win_rate']
    max_drawdown = portfolio['max_drawdown']
    annualized_return = portfolio['annualized_return']
    sharpe = portfolio['annualized_sharpe']
    trade_success_rate = portfolio['trade_success_rate']
    turnover_ratio = portfolio['turnover_ratio']
    ret_str = ('%.2f%%' % (ret * 100)) if math.isfinite(ret) else 'N/A'
    wr_str = ('%.1f%%' % (win_rate * 100)) if math.isfinite(win_rate) else 'N/A'
    text_lines = [
        '七星高照 ETF 轮动超级增强 - 本地日线回测报告',
        '回测区间: %s ~ %s' % (job.start_date, job.end_date),
        '初始资金: %.2f' % job.initial_capital,
        '动量回看: %d日  持仓数: %d只' % (p['lookback_days'], p['holdings_num']),
        '防御ETF: ' + DEFENSIVE_ETF,
        '本地可用池子: %d 只（%s）' % (
            len(universe), 'ETF命中' if tradeable_etf else 'A-share兜底'),
        '成交时序: D 日收盘生成目标，D+1 日开盘执行（100 股/手，受现金约束）',
        '卖出价基准: %d日均价 × %.3f / %.3f（止盈/止损）' % (
            int(p.get('sell_ma_window', 12)),
            float(p.get('sell_upper_ratio', 1.15)),
            float(p.get('sell_lower_ratio', 0.9)),
        ),
        'TP/SL 触发模式: %s，触发优先级: %s' % (
            p.get('sell_trigger_mode', 'tp_sl'),
            p.get('sell_priority', 'lower_first'),
        ),
        '',
        '完整开平回合数: %d' % n_round,
        '总已实现盈亏(元): %.2f' % total_pnl,
        '期末未实现盈亏(元): %.2f' % portfolio['ending_unrealized_pnl'],
        '期末总资产(元): %.2f' % portfolio['ending_total_asset'],
        '总收益率(期末总资产/初始资金): ' + ret_str,
        '年化收益率: ' + (('%.2f%%' % (annualized_return * 100)) if math.isfinite(annualized_return) else 'N/A'),
        '最大回撤: ' + (('%.2f%%' % (max_drawdown * 100)) if math.isfinite(max_drawdown) else 'N/A'),
        '年化夏普(无风险利率=0): ' + (('%.4f' % sharpe) if math.isfinite(sharpe) else 'N/A'),
        '交易成功率(完整回合/交易日): ' + (
            ('%.2f%%' % (trade_success_rate * 100)) if math.isfinite(trade_success_rate) else 'N/A'),
        '双边换手率(买卖成交额/平均总资产): ' + (
            ('%.2f%%' % (turnover_ratio * 100)) if math.isfinite(turnover_ratio) else 'N/A'),
        '胜率: ' + wr_str, '',
        '策略参数:',
    ] + ['  %s: %s' % (k, v) for k, v in sorted(p.items())]
    text_summary = '\n'.join(text_lines)
    _log(progress, text_summary)
    try:
        excel_path = _write_excel(
            job, trades_df, rounds_df, per_sym_df, equity_df, positions_df,
            portfolio, p, text_summary,
        )
        _log(progress, '  Excel 报告已写入: ' + str(excel_path))
    except Exception as exc:
        _log(progress, '  [WARN] Excel 写入失败: ' + str(exc))
        excel_path = None
    _log(progress, '========== 七星高照ETF轮动 本地日线回测 完成 ==========')
    return BacktestResult(
        ok=True,
        message=text_summary,
        excel_path=str(excel_path) if excel_path else None,
        signal_frame=output_collector.signal_frame,
        target_positions=output_collector.target_positions,
    )
