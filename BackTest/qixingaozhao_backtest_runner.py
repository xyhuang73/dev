# -*- coding: utf-8 -*-
"""
七星高照 ETF 轮动超级增强 — 向量回测实现。

流程:
    1) 通过 build_daily_market_panel 拉取 ETF 池 + 行情指数日线面板；
    2) 按交易日逐日运行动量评分与行情判断，得到每日目标持仓；
    3) 把目标持仓序列展开成逐笔交易记录，模拟收益；
    4) 输出 Excel 回测报告。
"""
from __future__ import annotations

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
    from .factor_market_panel import build_daily_market_panel  # noqa: PLC0415

    _log(progress, f"  拉取行情面板 ({len(codes)} 只, {start_date}~{end_date})...")
    df = build_daily_market_panel(start_date, end_date, max_symbols=0, stock_list=codes)
    _log(progress, f"  面板加载完成：{len(df)} 行 x {df['vt_symbol'].nunique()} 只")
    return df


def _panel_to_daily_dict(df: pd.DataFrame, codes: list[str]) -> dict[str, dict[str, list]]:
    """Convert long-format panel to {code: {'dates', 'closes', 'volumes'}} sorted ascending."""
    out: dict[str, dict[str, list]] = {}
    for code in codes:
        sub = df[df["vt_symbol"] == code].sort_values("datetime").reset_index(drop=True)
        if sub.empty:
            continue
        out[code] = {
            "dates": list(sub["datetime"]),
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


def _run_daily_simulation(strategy, etf_data, index_data, trade_dates, initial_capital, progress):
    p = strategy.params
    lookback = int(p['lookback_days'])
    regime_ma = int(p.get('weak_period_ma_lookback', 10))
    weak_max_days = int(p.get('weak_period_max_days', 20))
    profit_prot = bool(p.get('enable_profit_protection', True))
    profit_lookback = int(p.get('profit_protection_lookback', 1))
    profit_threshold = float(p.get('profit_protection_threshold', 0.05))
    is_weak = False
    weak_counter = 0
    positions = {}
    all_trades = []
    all_rounds = []
    LOT = 100
    total_days = len(trade_dates)
    for day_idx, date_key in enumerate(trade_dates):
        if day_idx % 60 == 0:
            pct = int(day_idx * 100 / total_days) if total_days else 0
            _log(progress, '  [%d/%d %d%%] %s ...' % (day_idx, total_days, pct, str(date_key.date())))
        if p.get('enable_regime_switch', True):
            idx_closes = {}
            for _code in REGIME_INDEXES.values():
                _d = index_data.get(_code)
                if _d is None:
                    continue
                sel = [float(c) for dt, c in zip(_d['dates'], _d['closes'])
                       if pd.Timestamp(dt).normalize() <= date_key]
                if sel:
                    idx_closes[_code] = sel
            newly_weak = regime_is_weak(idx_closes, ma_lookback=regime_ma)
            if not is_weak:
                if newly_weak:
                    is_weak = True
                    weak_counter = 0
            else:
                weak_counter += 1
                above = sum(
                    1 for _c, _cl in idx_closes.items()
                    if len(_cl) >= regime_ma and _cl[-1] >= _mean_values(_cl[-regime_ma:]))
                if above >= 3 or weak_counter >= weak_max_days:
                    is_weak = False
                    weak_counter = 0
        active_pool = strategy.get_active_pool(is_weak)
        all_candidates = list(set(active_pool + [DEFENSIVE_ETF]))
        closes_by_etf = {}
        volumes_by_etf = {}
        today_prices = {}
        today_vols = {}
        for code in all_candidates:
            d = etf_data.get(code)
            if d is None:
                continue
            hist_c = [float(c) for dt, c in zip(d['dates'], d['closes'])
                      if pd.Timestamp(dt).normalize() < date_key]
            hist_v = [float(v) for dt, v in zip(d['dates'], d['volumes'])
                      if pd.Timestamp(dt).normalize() < date_key]
            today_c = _get_close_on(d, date_key)
            if today_c is None or today_c <= 0:
                continue
            if len(hist_c) < lookback:
                continue
            closes_by_etf[code] = hist_c
            volumes_by_etf[code] = hist_v
            today_prices[code] = today_c
            today_vols[code] = sum(float(v) for dt, v in zip(d['dates'], d['volumes'])
                                   if pd.Timestamp(dt).normalize() == date_key)
        protected_sells = set()
        if profit_prot:
            for code, (entry_price, _edt, _sh) in list(positions.items()):
                d = etf_data.get(code)
                if d is None:
                    continue
                cp = _get_close_on(d, date_key)
                if cp is None:
                    continue
                recent = [float(c) for dt, c in zip(d['dates'], d['closes'])
                          if pd.Timestamp(dt).normalize() < date_key]
                if len(recent) < profit_lookback:
                    continue
                max_h = max(recent[-profit_lookback:])
                if max_h > 0 and cp <= max_h * (1.0 - profit_threshold):
                    protected_sells.add(code)
        _, target_codes = strategy.select_targets(
            active_pool, closes_by_etf, volumes_by_etf, today_prices, today_vols)
        target_codes = [c for c in target_codes if c not in protected_sells]
        if not target_codes and DEFENSIVE_ETF in today_prices:
            target_codes = [DEFENSIVE_ETF]
        target_set = set(target_codes)
        to_sell = (set(positions.keys()) - target_set) | (set(positions.keys()) & protected_sells)
        for code in list(to_sell):
            if code not in positions:
                continue
            entry_price, entry_dt, shares = positions.pop(code)
            d = etf_data.get(code)
            sell_price = (_get_close_on(d, date_key) if d else None) or entry_price
            pnl_cash = (sell_price - entry_price) * shares
            pnl_pct = (sell_price / entry_price - 1.0) if entry_price > 0 else float('nan')
            all_trades.append({'vt_symbol': code, 'datetime': date_key, 'action': 'sell',
                'price': sell_price, 'volume': shares, 'open_datetime': entry_dt,
                'open_price': entry_price, 'round_pnl_pct': pnl_pct, 'round_pnl_cash': pnl_cash,
                'is_regime_weak': is_weak, 'profit_protected': code in protected_sells})
            all_rounds.append({'vt_symbol': code, 'open_datetime': entry_dt,
                'open_price': entry_price, 'close_datetime': date_key,
                'close_price': sell_price, 'volume': shares,
                'hold_calendar_days': _calendar_days(entry_dt, date_key),
                'round_pnl_pct': pnl_pct, 'round_pnl_cash': pnl_cash,
                'win': bool(math.isfinite(pnl_pct) and pnl_pct > 0)})
        for code in list(target_set - set(positions.keys())):
            if code not in today_prices:
                continue
            buy_price = today_prices[code]
            positions[code] = (buy_price, date_key, LOT)
            all_trades.append({'vt_symbol': code, 'datetime': date_key, 'action': 'buy',
                'price': buy_price, 'volume': LOT,
                'is_regime_weak': is_weak, 'profit_protected': False})
    trades_df = pd.DataFrame(all_trades) if all_trades else pd.DataFrame()
    rounds_df = pd.DataFrame(all_rounds) if all_rounds else pd.DataFrame()
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
    cap = float(initial_capital) if initial_capital > 0 else float('nan')
    ret = total_pnl / cap if cap > 0 else float('nan')
    wins = int(rounds_df['win'].sum()) if n_round and 'win' in rounds_df.columns else 0
    win_rate = wins / n_round if n_round else float('nan')
    mean_pnl = float(rounds_df['round_pnl_pct'].mean()) if n_round else float('nan')
    portfolio = {
        'strategy': 'QixingaozhaoEtfRotationStrategy',
        'initial_capital_ui': cap, 'total_round_trips': n_round,
        'total_realized_pnl_cash': total_pnl, 'simple_return_vs_initial_capital': ret,
        'all_round_trips_win_rate': win_rate, 'all_round_trips_mean_pnl_pct': mean_pnl,
        'lookback_days': p['lookback_days'], 'holdings_num': p['holdings_num'],
        'enable_regime_switch': p['enable_regime_switch'],
        'enable_avoid_a_share': p['enable_avoid_a_share'],
        'enable_volume_check': p['enable_volume_check'],
        'enable_profit_protection': p['enable_profit_protection'],
        'note': 'Daily close-price rebalancing. No fees/slippage. Score=annualized_ret*R2.',
    }
    return trades_df, rounds_df, per_sym, portfolio


def _write_excel(job, trades_df, rounds_df, per_sym_df, portfolio, params, text_summary):
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
        text_df.to_excel(writer, sheet_name='文本报告', index=False)
    return path.resolve()


def run_qixingaozhao_backtest(job, *, progress=None):
    _log(progress, '========== 七星高照ETF轮动 向量回测 开始 ==========')
    strategy = QixingaozhaoEtfRotationStrategy()
    p = strategy.params
    all_codes = list(set(FULL_ETF_POOL + list(REGIME_INDEXES.values()) + [DEFENSIVE_ETF]))
    try:
        df = _fetch_panel(all_codes, job.start_date, job.end_date, progress)
    except Exception as exc:
        msg = '行情面板拉取失败: %s' % exc
        _log(progress, '[ERROR] ' + msg)
        return BacktestResult(False, msg)
    if df.empty:
        return BacktestResult(False, '行情面板为空，无法回测。')
    index_codes = set(REGIME_INDEXES.values())
    etf_data = _panel_to_daily_dict(
        df[~df['vt_symbol'].isin(index_codes)],
        [c for c in all_codes if c not in index_codes])
    index_data = _panel_to_daily_dict(
        df[df['vt_symbol'].isin(index_codes)], list(index_codes))
    start_ts = pd.Timestamp('%s-%s-%s' % (job.start_date[:4], job.start_date[4:6], job.start_date[6:8]))
    end_ts = pd.Timestamp('%s-%s-%s' % (job.end_date[:4], job.end_date[4:6], job.end_date[6:8]))
    all_dates = sorted(set(pd.Timestamp(dt).normalize() for dt in df['datetime']))
    trade_dates = [d for d in all_dates if start_ts <= d <= end_ts]
    if not trade_dates:
        return BacktestResult(False, '回测区间内无有效交易日，请扩大日期范围或检查数据。')
    _log(progress, '  回测交易日数：%d，起止：%s~%s' % (
        len(trade_dates), str(trade_dates[0].date()), str(trade_dates[-1].date())))
    trades_df, rounds_df, per_sym_df, portfolio = _run_daily_simulation(
        strategy, etf_data, index_data, trade_dates, job.initial_capital, progress)
    n_round = portfolio['total_round_trips']
    total_pnl = portfolio['total_realized_pnl_cash']
    ret = portfolio['simple_return_vs_initial_capital']
    win_rate = portfolio['all_round_trips_win_rate']
    ret_str = ('%.2f%%' % (ret * 100)) if math.isfinite(ret) else 'N/A'
    wr_str = ('%.1f%%' % (win_rate * 100)) if math.isfinite(win_rate) else 'N/A'
    text_lines = [
        '七星高照 ETF 轮动超级增强 - 向量回测报告',
        '回测区间: %s ~ %s' % (job.start_date, job.end_date),
        '初始资金: %.2f' % job.initial_capital,
        '动量回看: %d日  持仓数: %d只' % (p['lookback_days'], p['holdings_num']),
        '防御ETF: ' + DEFENSIVE_ETF, '',
        '完整开平回合数: %d' % n_round,
        '总已实现盈亏(元): %.2f' % total_pnl,
        '简单收益率(盈亏/初始资金): ' + ret_str,
        '胜率: ' + wr_str, '',
        '策略参数:',
    ] + ['  %s: %s' % (k, v) for k, v in sorted(p.items())]
    text_summary = '\n'.join(text_lines)
    _log(progress, text_summary)
    try:
        excel_path = _write_excel(job, trades_df, rounds_df, per_sym_df, portfolio, p, text_summary)
        _log(progress, '  Excel 报告已写入: ' + str(excel_path))
    except Exception as exc:
        _log(progress, '  [WARN] Excel 写入失败: ' + str(exc))
        excel_path = None
    _log(progress, '========== 七星高照ETF轮动 向量回测 完成 ==========')
    return BacktestResult(ok=True, message=text_summary,
                          excel_path=str(excel_path) if excel_path else None)


def _write_excel(job, trades_df, rounds_df, per_sym_df, portfolio, params, text_summary):
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
        text_df.to_excel(writer, sheet_name='文本报告', index=False)
    return path.resolve()


def run_qixingaozhao_backtest(job, *, progress=None):
    _log(progress, '========== 七星高照ETF轮动 向量回测 开始 ==========')
    strategy = QixingaozhaoEtfRotationStrategy()
    p = strategy.params
    all_codes = list(set(FULL_ETF_POOL + list(REGIME_INDEXES.values()) + [DEFENSIVE_ETF]))
    try:
        df = _fetch_panel(all_codes, job.start_date, job.end_date, progress)
    except Exception as exc:
        msg = '行情面板拉取失败: %s' % exc
        _log(progress, '[ERROR] ' + msg)
        return BacktestResult(False, msg)
    if df.empty:
        return BacktestResult(False, '行情面板为空，无法回测。')
    index_codes = set(REGIME_INDEXES.values())
    etf_data = _panel_to_daily_dict(
        df[~df['vt_symbol'].isin(index_codes)],
        [c for c in all_codes if c not in index_codes])
    index_data = _panel_to_daily_dict(
        df[df['vt_symbol'].isin(index_codes)], list(index_codes))
    start_ts = pd.Timestamp('%s-%s-%s' % (job.start_date[:4], job.start_date[4:6], job.start_date[6:8]))
    end_ts = pd.Timestamp('%s-%s-%s' % (job.end_date[:4], job.end_date[4:6], job.end_date[6:8]))
    all_dates = sorted(set(pd.Timestamp(dt).normalize() for dt in df['datetime']))
    trade_dates = [d for d in all_dates if start_ts <= d <= end_ts]
    if not trade_dates:
        return BacktestResult(False, '回测区间内无有效交易日，请扩大日期范围或检查数据。')
    _log(progress, '  回测交易日数：%d，起止：%s~%s' % (
        len(trade_dates), str(trade_dates[0].date()), str(trade_dates[-1].date())))
    trades_df, rounds_df, per_sym_df, portfolio = _run_daily_simulation(
        strategy, etf_data, index_data, trade_dates, job.initial_capital, progress)
    n_round = portfolio['total_round_trips']
    total_pnl = portfolio['total_realized_pnl_cash']
    ret = portfolio['simple_return_vs_initial_capital']
    win_rate = portfolio['all_round_trips_win_rate']
    ret_str = ('%.2f%%' % (ret * 100)) if math.isfinite(ret) else 'N/A'
    wr_str = ('%.1f%%' % (win_rate * 100)) if math.isfinite(win_rate) else 'N/A'
    text_lines = [
        '七星高照 ETF 轮动超级增强 - 向量回测报告',
        '回测区间: %s ~ %s' % (job.start_date, job.end_date),
        '初始资金: %.2f' % job.initial_capital,
        '动量回看: %d日  持仓数: %d只' % (p['lookback_days'], p['holdings_num']),
        '防御ETF: ' + DEFENSIVE_ETF, '',
        '完整开平回合数: %d' % n_round,
        '总已实现盈亏(元): %.2f' % total_pnl,
        '简单收益率(盈亏/初始资金): ' + ret_str,
        '胜率: ' + wr_str, '',
        '策略参数:',
    ] + ['  %s: %s' % (k, v) for k, v in sorted(p.items())]
    text_summary = '\n'.join(text_lines)
    _log(progress, text_summary)
    try:
        excel_path = _write_excel(job, trades_df, rounds_df, per_sym_df, portfolio, p, text_summary)
        _log(progress, '  Excel 报告已写入: ' + str(excel_path))
    except Exception as exc:
        _log(progress, '  [WARN] Excel 写入失败: ' + str(exc))
        excel_path = None
    _log(progress, '========== 七星高照ETF轮动 向量回测 完成 ==========')
    return BacktestResult(ok=True, message=text_summary,
                          excel_path=str(excel_path) if excel_path else None)
