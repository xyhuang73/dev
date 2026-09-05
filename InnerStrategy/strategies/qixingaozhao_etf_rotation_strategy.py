# -*- coding: utf-8 -*-
"""
七星高照 ETF 轮动超级增强 — 本地回测版

来源：Outerhelp/多雨定制10000个详细策略py/strategies/Qixingaozhao.py（QMT 单文件版）
改造：移除所有 QMT 原生 API，改用项目内置本地行情面板，
      暴露 QixingaozhaoEtfRotationStrategy 类供 BackTest 向量引擎驱动。

核心逻辑与原版完全一致：
- 动量得分 = 年化收益率（加权线性回归 log 价格）× R²（趋势稳定性）
- 过滤：短期动量、成交量放量（量比 × 年化收益双重门限）、近3日单日跌幅、溢价率（回测跳过）
- 行情判断：多指数均线上下 → 正常期 / 走弱期，走弱期切换到海外+商品 ETF 子池
- 防御 ETF：511010.SH（国债 ETF）
- 每日 13:09 卖出 / 13:10 买入，日线回测用收盘价换仓
"""
from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Pure-Python helpers (no external deps beyond stdlib)
# ---------------------------------------------------------------------------

def _is_nan(v: Any) -> bool:
    try:
        if v is None:
            return True
        fv = float(v)
        return fv != fv or math.isnan(fv)
    except (TypeError, ValueError):
        return True


def _to_list(data: Any) -> list:
    if data is None:
        return []
    if hasattr(data, "tolist"):
        return list(data.tolist())
    if hasattr(data, "values"):
        vals = data.values
        return list(vals.tolist()) if hasattr(vals, "tolist") else list(vals)
    return list(data)


def _mean_values(series_or_list: Any) -> float:
    vals = [float(v) for v in _to_list(series_or_list) if not _is_nan(v)]
    return sum(vals) / len(vals) if vals else 0.0


def _max_values(series_or_list: Any) -> float | None:
    vals = [float(v) for v in _to_list(series_or_list) if not _is_nan(v)]
    return max(vals) if vals else None


def _linspace(start: float, stop: float, num: int) -> list[float]:
    if num <= 1:
        return [float(start)]
    step = (stop - start) / (num - 1)
    return [start + i * step for i in range(num)]


def _weighted_polyfit(x: list, y: list, weights: list) -> tuple[float, float]:
    sw = sum(weights)
    sx = sum(w * xi for w, xi in zip(weights, x))
    sy = sum(w * yi for w, yi in zip(weights, y))
    sxx = sum(w * xi * xi for w, xi in zip(weights, x))
    sxy = sum(w * xi * yi for w, xi, yi in zip(weights, x, y))
    denom = sw * sxx - sx * sx
    if denom == 0:
        return 0.0, y[0] if y else 0.0
    slope = (sw * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / sw
    return slope, intercept


def compute_momentum_score(
    price_series: list[float],
    lookback_days: int,
) -> tuple[float, float, float]:
    """Weighted log-linear regression momentum.

    Returns (annualized_return, r_squared, score).
    score = annualized_return * r_squared  (same as original QMT version).
    """
    recent = price_series[-(lookback_days + 1):]
    if len(recent) < 3:
        return float("nan"), float("nan"), float("nan")
    y = [math.log(p) for p in recent if p > 0]
    if len(y) < 3:
        return float("nan"), float("nan"), float("nan")
    x = list(range(len(y)))
    weights = _linspace(1, 2, len(y))
    slope, intercept = _weighted_polyfit(x, y, weights)
    annualized = math.exp(slope * 250) - 1

    y_mean = sum(w * yi for w, yi in zip(weights, y)) / sum(weights)
    ss_res = sum(w * (yi - (slope * xi + intercept)) ** 2 for w, xi, yi in zip(weights, x, y))
    ss_tot = sum(w * (yi - y_mean) ** 2 for w, yi in zip(weights, y))
    r2 = 1.0 - ss_res / ss_tot if ss_tot != 0 else 0.0
    return annualized, r2, annualized * r2


def check_single_day_drop(price_series: list[float], loss_threshold: float = 0.97) -> bool:
    """Return True if any of the last 3 daily returns is below loss_threshold (i.e. a large drop)."""
    if len(price_series) < 4:
        return False
    d1 = price_series[-1] / price_series[-2] if price_series[-2] > 0 else 1.0
    d2 = price_series[-2] / price_series[-3] if price_series[-3] > 0 else 1.0
    d3 = price_series[-3] / price_series[-4] if price_series[-4] > 0 else 1.0
    return min(d1, d2, d3) < loss_threshold


# ---------------------------------------------------------------------------
# Strategy parameters (mirrors init_global_vars in the original QMT file)
# ---------------------------------------------------------------------------

# ETF pools — identical to the original
OVERSEAS_ETF_POOL: list[str] = [
    "513100.SH", "513290.SH", "513500.SH", "159529.SZ", "513400.SH",
    "513520.SH", "513030.SH", "513080.SH", "513310.SH", "513730.SH",
    "159792.SZ", "513130.SH", "513050.SH", "159920.SZ", "513690.SH",
    "511380.SH", "511010.SH", "511220.SH",
]

COMMODITY_ETF_POOL: list[str] = [
    "518880.SH", "159980.SZ", "159985.SZ", "501018.SH",
    "161226.SZ", "159981.SZ", "512400.SH",
]

DOMESTIC_ETF_POOL: list[str] = [
    "510300.SH", "510500.SH", "510050.SH", "510210.SH", "159915.SZ",
    "588080.SH", "512100.SH", "563360.SH", "563300.SH", "512890.SH",
    "159967.SZ", "588020.SH", "512040.SH", "159201.SZ", "515790.SH",
    "563230.SH", "515880.SH", "512660.SH", "561380.SH", "159667.SZ",
    "159559.SZ", "159819.SZ", "159381.SZ", "159732.SZ", "159995.SZ",
    "512220.SH",
]

FULL_ETF_POOL: list[str] = OVERSEAS_ETF_POOL + COMMODITY_ETF_POOL + DOMESTIC_ETF_POOL

REGIME_INDEXES: dict[str, str] = {
    "沪深300": "000300.SH",
    "深证综指": "399101.SZ",
    "创业板指": "399006.SZ",
    "中证A500": "000510.SH",
}

DEFENSIVE_ETF: str = "511010.SH"

# Default strategy parameters
DEFAULT_PARAMS: dict[str, Any] = {
    "lookback_days": 25,
    "holdings_num": 1,
    "loss": 0.97,
    "enable_volume_check": True,
    "volume_lookback": 5,
    "volume_threshold": 3.6,
    "volume_return_limit": 1,
    "use_short_momentum_filter": True,
    "short_lookback_days": 10,
    "short_momentum_threshold": 0.0,
    # 老的「最大回撤类」盈利保护 —— 已被下方 TP/SL 机制取代，默认关闭；
    # 若坚持使用，可单独置 True，但仅在 TP/SL 未触发时才会触发卖出。
    "enable_profit_protection": False,
    "profit_protection_lookback": 1,
    "profit_protection_threshold": 0.05,
    "enable_regime_switch": True,
    "weak_period_ma_lookback": 10,
    "weak_period_max_days": 20,
    "enable_avoid_a_share": True,
    "min_score_threshold": 0,
    "max_score_threshold": 100.0,
    # === 本地化交易价格参数（2026-08-30 重构，日线、无分钟行情）===
    # 买入基准：取最近 buy_ma_window 个交易日的收盘价（默认 1 = 昨日收盘）。
    "buy_ma_window": 1,
    # 卖出基准均价窗口：取最近 sell_ma_window 个交易日的均价。
    "sell_ma_window": 12,
    # 止盈/止损倍数（基于 sell_ma_window 日均价）。
    "sell_upper_ratio": 1.15,
    "sell_lower_ratio": 0.9,
    # 是否启用止盈/止损（可独立开关）。
    "sell_upper_enabled": True,
    "sell_lower_enabled": True,
    # 同日 TP/SL 同时触发时的优先级：
    #   lower_first - 保守：先打止损（更早离场）
    #   upper_first - 激进：先打止盈
    #   by_open     - 用今日 open 推断先后（开在 TP 上方→先打 SL；开在 SL 下方→先打 TP；中间→保守）
    "sell_priority": "lower_first",
    # 触发模式：
    #   tp_sl  - 同时启用 TP/SL（默认）
    #   tp_only- 只看 TP
    #   sl_only- 只看 SL
    "sell_trigger_mode": "tp_sl",
}


# ---------------------------------------------------------------------------
# Core scoring engine (stateless, pandas-free)
# ---------------------------------------------------------------------------

def score_etf(
    etf: str,
    hist_closes: list[float],
    hist_volumes: list[float],
    current_price: float,
    today_vol: float,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Compute momentum score for a single ETF.

    Returns a metrics dict or None if the ETF is filtered out.
    All logic mirrors ``calculate_momentum_metrics`` from the original QMT file.
    """
    p = params or DEFAULT_PARAMS
    lookback = int(p["lookback_days"])
    short_lookback = int(p["short_lookback_days"])
    volume_lookback = int(p["volume_lookback"])

    price_series = list(hist_closes) + [float(current_price)]

    # near-3-day large-drop filter
    if check_single_day_drop(price_series, float(p["loss"])):
        return None

    # short-term momentum filter
    if len(price_series) >= short_lookback + 1:
        short_ret = price_series[-1] / price_series[-(short_lookback + 1)] - 1
        short_ann = (1 + short_ret) ** (250 / short_lookback) - 1
    else:
        short_ann = 0.0

    if p["use_short_momentum_filter"] and short_ann < float(p["short_momentum_threshold"]):
        return None

    # volume放量 + 年化收益双重门限 filter
    if p["enable_volume_check"] and len(hist_volumes) >= volume_lookback:
        past_vols = hist_volumes[-volume_lookback:]
        if not any(_is_nan(v) or float(v) == 0 for v in past_vols):
            avg_vol = _mean_values(past_vols)
            if avg_vol > 0 and today_vol > 0:
                vol_ratio = today_vol / avg_vol
                if vol_ratio > float(p["volume_threshold"]):
                    # compute annualized return for this ETF using lookback window
                    _ann, _r2, _ = compute_momentum_score(price_series, lookback)
                    if not _is_nan(_ann) and _ann > float(p["volume_return_limit"]):
                        return None

    # main momentum score
    ann, r2, score = compute_momentum_score(price_series, lookback)
    if _is_nan(score):
        return None

    return {
        "etf": etf,
        "annualized_returns": ann,
        "r_squared": r2,
        "score": score,
        "current_price": current_price,
        "short_annualized": short_ann,
    }


def rank_etf_pool(
    pool: list[str],
    closes_by_etf: dict[str, list[float]],
    volumes_by_etf: dict[str, list[float]],
    today_prices: dict[str, float],
    today_vols: dict[str, float],
    *,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Rank all ETFs in pool by momentum score, highest first."""
    p = params or DEFAULT_PARAMS
    results: list[dict[str, Any]] = []
    for etf in pool:
        if etf not in closes_by_etf or etf not in today_prices:
            continue
        hist_closes = closes_by_etf[etf]
        hist_volumes = volumes_by_etf.get(etf, [])
        current_price = today_prices[etf]
        today_vol = today_vols.get(etf, 0.0)
        m = score_etf(etf, hist_closes, hist_volumes, current_price, today_vol, params=p)
        if m is None:
            continue
        lo = float(p.get("min_score_threshold", 0))
        hi = float(p.get("max_score_threshold", 100.0))
        if lo < m["score"] < hi:
            results.append(m)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def regime_is_weak(
    index_closes_by_code: dict[str, list[float]],
    *,
    ma_lookback: int = 10,
    min_below: int = 3,
) -> bool:
    """
    Return True if >= min_below of the 4 regime indexes are below their MA.

    Mirrors ``regime_check`` from the original: enter weak period when >=3 of 4 indexes break below MA.
    """
    below = 0
    for code, closes in index_closes_by_code.items():
        if len(closes) < ma_lookback:
            continue
        recent = closes[-ma_lookback:]
        ma = _mean_values(recent)
        if recent[-1] < ma:
            below += 1
    return below >= min_below


# ---------------------------------------------------------------------------
# Strategy class — thin wrapper exposing the class name the registry scans for
# ---------------------------------------------------------------------------

class QixingaozhaoEtfRotationStrategy:
    """
    七星高照 ETF 轮动超级增强 — 本地回测策略类。

    不依赖 VeighNa CtaTemplate；由 BackTest/qixingaozhao_backtest_runner.py
    中的向量引擎直接调用 ``run_backtest_on_panel`` 类方法。
    """

    author = "MinQMT-F3 (移植自多雨定制 Qixingaozhao.py)"

    # Mutable default params; runner can override via constructor kwargs.
    OVERSEAS_ETF_POOL = OVERSEAS_ETF_POOL
    COMMODITY_ETF_POOL = COMMODITY_ETF_POOL
    DOMESTIC_ETF_POOL = DOMESTIC_ETF_POOL
    FULL_ETF_POOL = FULL_ETF_POOL
    REGIME_INDEXES = REGIME_INDEXES
    DEFENSIVE_ETF = DEFENSIVE_ETF
    DEFAULT_PARAMS = DEFAULT_PARAMS

    def __init__(self, **param_overrides: Any) -> None:
        self.params: dict[str, Any] = dict(DEFAULT_PARAMS)
        self.params.update(param_overrides)
        # 允许 runner 在加载完本地 datadir 后注入实际可用的标的池
        # （七星高照 ETF 池是默认值；若 datadir 中根本没有 ETF，
        # 则 runner 会把本地真实存在的 A-share 等可用代码注入到这里，
        # 让策略能跑通——这是「股票信息用本地的数据输入」语义的实现）。
        self.universe_override: list[str] | None = param_overrides.get("universe_override")

    # ------------------------------------------------------------------
    # Public interface used by the backtest runner
    # ------------------------------------------------------------------

    def get_universe(self) -> list[str]:
        """返回实际可用的全量标的池（universe_override 优先，否则用硬编码 ETF 池）。"""
        if self.universe_override:
            return list(self.universe_override)
        return list(FULL_ETF_POOL)

    def get_active_pool(self, is_weak: bool) -> list[str]:
        """Return the tradable pool appropriate for the current market regime.

        优先用 ``universe_override``（本地 datadir 真实存在的代码）；
        否则按原 ETF 池子规则：
          - 走弱期：海外 + 商品
          - 正常期：完整 ETF 池
        """
        if self.universe_override:
            # 本地无 ETF 时，回退到 universe_override 全量；
            # 走弱/正常期不再区分 ETF 类别（避免把仅有的几只 A-share 全过滤掉）。
            return list(self.universe_override)
        if not self.params.get("enable_avoid_a_share", True):
            return list(FULL_ETF_POOL)
        if is_weak:
            return list(OVERSEAS_ETF_POOL) + list(COMMODITY_ETF_POOL)
        return list(FULL_ETF_POOL)

    def select_targets(
        self,
        pool: list[str],
        closes_by_etf: dict[str, list[float]],
        volumes_by_etf: dict[str, list[float]],
        today_prices: dict[str, float],
        today_vols: dict[str, float],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """
        Rank pool and return (ranked_metrics_list, selected_etf_codes).

        Falls back to DEFENSIVE_ETF when no candidate passes all filters.
        """
        ranked = rank_etf_pool(
            pool, closes_by_etf, volumes_by_etf, today_prices, today_vols,
            params=self.params,
        )
        n = int(self.params.get("holdings_num", 1))
        selected = [m["etf"] for m in ranked[:n]]
        if not selected:
            if DEFENSIVE_ETF in today_prices and today_prices[DEFENSIVE_ETF] > 0:
                selected = [DEFENSIVE_ETF]
        return ranked, selected

    # ------------------------------------------------------------------
    # 本地化交易价格（无分钟行情：日线开盘→收盘中间过程用 OHLC 近似触发）
    # ------------------------------------------------------------------

    def compute_buy_level(
        self,
        etf: str,
        closes: list[float],
    ) -> float | None:
        """
        买入价位 = 最近 ``buy_ma_window`` 个交易日的均价（默认 1 = 昨日收盘）。

        本地化语义：原始 QMT 在 13:10 按分钟 close 买入；本地无分钟数据，
        退化为「按 buy_ma_window 日均价/收盘成交」。回测侧直接 fill 该价位。
        """
        win = max(1, int(self.params.get("buy_ma_window", 1)))
        if not closes or len(closes) < win:
            return None
        base = float(closes[-win])
        return base if base > 0 else None

    def compute_sell_levels(
        self,
        etf: str,
        closes: list[float],
    ) -> tuple[float | None, float | None]:
        """
        (止盈位, 止损位) = (``sell_ma_window`` 日均价 × upper_ratio, × lower_ratio)。

        本地化语义：原始 QMT 在 13:09 按分钟 close 卖出；本地无分钟数据，
        退化为按 12 日均价 × 倍数（1.15 / 0.9）成交。两个倍数均为参数。
        """
        win = max(1, int(self.params.get("sell_ma_window", 12)))
        if not closes or len(closes) < win:
            return None, None
        ma = sum(float(c) for c in closes[-win:]) / win
        if ma <= 0:
            return None, None
        up_r = float(self.params.get("sell_upper_ratio", 1.15))
        lo_r = float(self.params.get("sell_lower_ratio", 0.9))
        return ma * up_r, ma * lo_r

    def decide_sell_action(
        self,
        etf: str,
        today_open: float | None,
        today_high: float | None,
        today_low: float | None,
        today_close: float | None,
        tp_level: float | None,
        sl_level: float | None,
        rebalance_sell: bool,
    ) -> tuple[str | None, float | None]:
        """
        根据今日 OHLC 与 TP/SL 阈值，决定卖出行为与成交价。

        触发判定：
            - TP 触发：``today_high >= tp_level``（止盈上限被日 K 最高价触及）
            - SL 触发：``today_low  <= sl_level``（止损下限被日 K 最低价触及）
            - 同日同时触发：按 ``sell_priority`` 决定优先级
            - 都未触发但需要 rebalance：用 ``today_close`` 卖出
            - 都未触发且无需 rebalance：返回 (None, None)，runner 视为继续持有

        返回：
            ('tp', price) | ('sl', price) | ('rebalance', price) | (None, None)
        """
        p = self.params
        upper_enabled = bool(p.get("sell_upper_enabled", True))
        lower_enabled = bool(p.get("sell_lower_enabled", True))
        trigger_mode = str(p.get("sell_trigger_mode", "tp_sl"))

        if not upper_enabled:
            tp_level = None
        if not lower_enabled:
            sl_level = None

        tp_hit = (
            tp_level is not None
            and today_high is not None
            and float(today_high) >= float(tp_level)
        )
        sl_hit = (
            sl_level is not None
            and today_low is not None
            and float(today_low) <= float(sl_level)
        )

        consider_tp = trigger_mode in ("tp_sl", "tp_only") and tp_hit
        consider_sl = trigger_mode in ("tp_sl", "sl_only") and sl_hit

        if consider_tp and consider_sl:
            priority = str(p.get("sell_priority", "lower_first"))
            if priority == "upper_first":
                return "tp", float(tp_level)
            if priority == "by_open":
                if today_open is not None:
                    # 开在 TP 上方 → 必先跌穿 SL
                    if float(today_open) > float(tp_level):
                        return "sl", float(sl_level)
                    # 开在 SL 下方 → 必先冲过 TP
                    if float(today_open) < float(sl_level):
                        return "tp", float(tp_level)
                # open 在 [SL, TP] 区间内走保守路径
                return "sl", float(sl_level)
            # default: lower_first
            return "sl", float(sl_level)

        if consider_tp:
            return "tp", float(tp_level)
        if consider_sl:
            return "sl", float(sl_level)

        if rebalance_sell and today_close is not None and float(today_close) > 0:
            return "rebalance", float(today_close)

        return None, None
