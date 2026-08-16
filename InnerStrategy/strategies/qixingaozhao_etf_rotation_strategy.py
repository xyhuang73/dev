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
    "enable_profit_protection": True,
    "profit_protection_lookback": 1,
    "profit_protection_threshold": 0.05,
    "enable_regime_switch": True,
    "weak_period_ma_lookback": 10,
    "weak_period_max_days": 20,
    "enable_avoid_a_share": True,
    "min_score_threshold": 0,
    "max_score_threshold": 100.0,
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

    # ------------------------------------------------------------------
    # Public interface used by the backtest runner
    # ------------------------------------------------------------------

    def get_active_pool(self, is_weak: bool) -> list[str]:
        """Return the ETF pool appropriate for the current market regime."""
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
