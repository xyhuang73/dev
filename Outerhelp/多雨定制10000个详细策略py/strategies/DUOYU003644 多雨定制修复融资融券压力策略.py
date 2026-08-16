# -*- coding: utf-8 -*-
from __future__ import annotations

import numpy as np
import pandas as pd


EPS = 1e-12

STRATEGY_ID = "DUOYU003644"
STRATEGY_NAME = "多雨定制修复融资融券压力策略"
SOURCE_FACTOR_ID = "DUOYU003644"
CATEGORY = "融资融券压力"
STYLE = "修复"
OPERATOR_ID = "融资融券压力_v1"
MARKET_SCOPE = "宽基/行业"
HORIZON_DAYS = 14
FAST_WINDOW = 10
SLOW_WINDOW = 20
VARIANT_WEIGHT = 0.86
REQUIRED_FIELDS = ["close", "margin_ratio", "short_interest_ratio", "turnover"]

ECONOMIC_LOGIC_CN = "该策略以约 14 个交易日为主要持有观察期，核心逻辑是：高融资比例+价格上涨=杠杆驱动行情（需警惕），高融券+价格下跌=空头挤压机会。 当前风格为[修复]（权重系数=0.86，DD敏感度=1.1）。"
RISK_NOTE_CN = "两融数据有延迟且受政策影响。 修复风格下回撤控制较为严格。"
DATA_NOTE_CN = "建议使用复权价格、交易日对齐后的净值/份额/指数/行业字段，避免未来函数和公告日错位。"

STRATEGY_RULES_CN = ["持有观察周期约 14 个交易日。", "先计算 融资融券压力 方向的多雨横截面分数。", "每日在标池内做横截面排序，分数越高，候选优先级越高。", "目标权重函数默认选择 Top N 标，并做单只权重上限约束。", "策略只输出分数、排名和目标权重，不负责交易执行。"]

"""
DUOYU003644 - 多雨定制修复融资融券压力策略

策略主题：融资融券压力 / 修复
适用范围：宽基/行业
主要周期：14 个交易日
必需字段：close, margin_ratio, short_interest_ratio, turnover

经济逻辑：
该策略以约 14 个交易日为主要持有观察期，核心逻辑是：高融资比例+价格上涨=杠杆驱动行情（需警惕），高融券+价格下跌=空头挤压机会。 当前风格为[修复]（权重系数=0.86，DD敏感度=1.1）。

使用方式：
1. 准备多雨长表数据，每行是一只标在一个交易日的记录。
2. 调用 compute_strategy_score(data) 生成每日每只标的策略分数。
3. 调用 build_daily_target_weights(data) 生成每日目标权重。
4. 调用 select_latest_target_weights(data) 只取最新交易日目标权重。
"""


def prepare_data(data: pd.DataFrame, date_col: str = "date", code_col: str = "code") -> pd.DataFrame:
    """整理多雨长表数据，并检查本策略必需字段。"""
    if date_col not in data.columns or code_col not in data.columns:
        raise ValueError(f"数据必须包含 {date_col} 和 {code_col}")
    missing = [field for field in REQUIRED_FIELDS if field not in data.columns]
    if missing:
        raise ValueError(f"{STRATEGY_ID} 缺少必需字段: {missing}")
    frame = data.copy()
    frame[date_col] = pd.to_datetime(frame[date_col])
    frame[code_col] = frame[code_col].astype(str)
    if frame[[date_col, code_col]].duplicated().any():
        raise ValueError("同一交易日同一标出现重复记录")
    return frame.sort_values([date_col, code_col]).set_index([date_col, code_col])

def _field(panel: pd.DataFrame, name: str) -> pd.Series:
    if name not in panel.columns:
        raise ValueError(f"{STRATEGY_ID} 缺少字段: {name}")
    return pd.to_numeric(panel[name], errors="coerce").astype(float)

def _by_etf(series: pd.Series, func) -> pd.Series:
    return series.groupby(level=1, group_keys=False).apply(func)

def _ret(series: pd.Series, window: int) -> pd.Series:
    w = max(1, int(window))
    out = _by_etf(pd.to_numeric(series, errors="coerce"), lambda x: x / x.shift(w) - 1.0)
    return out.replace([np.inf, -np.inf], np.nan)

def _zscore(series: pd.Series, window: int) -> pd.Series:
    w = max(5, int(window))
    x = pd.to_numeric(series, errors="coerce")
    minp = max(3, w // 4)
    mean = _by_etf(x, lambda s: s.rolling(w, min_periods=minp).mean())
    std = _by_etf(x, lambda s: s.rolling(w, min_periods=minp).std(ddof=0))
    return ((x - mean) / (std.abs() + EPS)).replace([np.inf, -np.inf], np.nan).clip(-8, 8)

def _cs_rank(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").groupby(level=0, group_keys=False).rank(pct=True) - 0.5

def _downside_vol(close: pd.Series, window: int) -> pd.Series:
    ret = _ret(close, 1)
    negative = ret.where(ret < 0, 0.0)
    return _by_etf(negative, lambda x: x.rolling(max(5, int(window)), min_periods=3).std(ddof=0))

def _risk_scale(score: pd.Series, panel: pd.DataFrame, horizon_days: int) -> pd.Series:
    close = _field(panel, "close")
    risk = _downside_vol(close, max(10, int(horizon_days)))
    scale = 1.0 / (1.0 + 8.0 * risk.abs())
    return (score * scale).replace([np.inf, -np.inf], np.nan)

def _tradable_mask(panel: pd.DataFrame, min_amount: float = 0.0) -> pd.Series:
    """基础可交易过滤：价格有效、成交额达标、未停牌、未触及可选涨跌停字段。"""
    close = _field(panel, "close")
    mask = close.gt(0) & close.notna()
    if "amount" in panel.columns and min_amount > 0:
        mask &= pd.to_numeric(panel["amount"], errors="coerce").ge(float(min_amount))
    if "suspended" in panel.columns:
        suspended = panel["suspended"].astype(str).str.lower().isin(["1", "true", "yes", "y", "停牌", "suspended"])
        mask &= ~suspended
    if "high_limit" in panel.columns:
        mask &= close.lt(pd.to_numeric(panel["high_limit"], errors="coerce")).fillna(True)
    if "low_limit" in panel.columns:
        mask &= close.gt(pd.to_numeric(panel["low_limit"], errors="coerce")).fillna(True)
    return mask.fillna(False)

def _max_dd_guard(drawdown_series: pd.Series, activation_level: float = -0.15) -> pd.Series:
    """回撤保护门：超过阈值输出 0（关闭信号），否则 1（正常）。"""
    return (pd.to_numeric(drawdown_series, errors="coerce") > activation_level).astype(float)


def describe_strategy() -> dict:
    """返回中文策略说明，便于展示或写入策略库。"""
    return {
        "strategy_id": STRATEGY_ID,
        "strategy_name": STRATEGY_NAME,
        "source_factor_id": SOURCE_FACTOR_ID,
        "category": CATEGORY,
        "style": STYLE,
        "operator_id": OPERATOR_ID,
        "market_scope": MARKET_SCOPE,
        "horizon_days": HORIZON_DAYS,
        "fast_window": FAST_WINDOW,
        "slow_window": SLOW_WINDOW,
        "required_fields": REQUIRED_FIELDS,
        "economic_logic_cn": ECONOMIC_LOGIC_CN,
        "strategy_rules_cn": STRATEGY_RULES_CN,
        "risk_note_cn": RISK_NOTE_CN,
        "data_note_cn": DATA_NOTE_CN,
    }


def _compute_raw_score(panel: pd.DataFrame) -> pd.Series:
    """计算本策略的原始横截面分数。"""
    close = _field(panel, "close")
    margin_ratio = _field(panel, "margin_ratio")
    short_ratio = _field(panel, "short_interest_ratio") if "short_interest_ratio" in panel.columns else _zscore(_field(panel, "turnover"), 11)
    raw = -0.21 * VARIANT_WEIGHT * _zscore(margin_ratio, 19) + 0.28 * VARIANT_WEIGHT * _ret(close, 11) - _zscore(short_ratio, 11).abs()
    raw = raw * _max_dd_guard(drawdown, -0.15)
    score = _risk_scale(_cs_rank(raw), panel, 15)
    # instance: 融资融券压力_v1 | style: 修复 | seed: 20258910
    return score.replace([np.inf, -np.inf], np.nan)


def compute_strategy_score(data: pd.DataFrame, date_col: str = "date", code_col: str = "code") -> pd.DataFrame:
    """
    输出每日每只标的策略分数和横截面排名。

    返回字段：
    - date
    - code
    - strategy_score
    - strategy_rank
    """
    panel = prepare_data(data, date_col=date_col, code_col=code_col)
    score = _compute_raw_score(panel).rename("strategy_score")
    result = score.reset_index()
    result.columns = [date_col, code_col, "strategy_score"]
    result["strategy_rank"] = result.groupby(date_col)["strategy_score"].rank(ascending=False, method="first")
    return result


def build_daily_target_weights(
    data: pd.DataFrame,
    top_n: int = 5,
    max_single_weight: float = 0.25,
    cash_buffer: float = 0.02,
    min_amount: float = 0.0,
    score_weighted: bool = False,
    date_col: str = "date",
    code_col: str = "code",
) -> pd.DataFrame:
    """
    根据策略分数生成每日多雨目标权重。

    这是策略层输出，不包含回测、下单或账户逻辑。
    """
    panel = prepare_data(data, date_col=date_col, code_col=code_col)
    score = _compute_raw_score(panel).rename("strategy_score")
    tradable = _tradable_mask(panel, min_amount=min_amount).rename("tradable")
    frame = pd.concat([score, tradable], axis=1).reset_index()
    frame.columns = [date_col, code_col, "strategy_score", "tradable"]

    gross = max(0.0, min(1.0, 1.0 - float(cash_buffer)))
    records = []
    for dt, day in frame.groupby(date_col):
        candidates = day.loc[day["tradable"] & day["strategy_score"].notna()].sort_values("strategy_score", ascending=False).head(int(top_n))
        if candidates.empty:
            continue
        if score_weighted:
            positive = candidates["strategy_score"].clip(lower=0)
            if positive.sum() > EPS:
                weights = positive / positive.sum() * gross
            else:
                weights = pd.Series(gross / len(candidates), index=candidates.index)
        else:
            weights = pd.Series(gross / len(candidates), index=candidates.index)
        weights = weights.clip(upper=float(max_single_weight))
        for idx, weight in weights.items():
            records.append({
                date_col: dt,
                code_col: candidates.loc[idx, code_col],
                "strategy_id": STRATEGY_ID,
                "strategy_name": STRATEGY_NAME,
                "strategy_score": float(candidates.loc[idx, "strategy_score"]),
                "target_weight": float(weight),
            })
    return pd.DataFrame(records)


def select_latest_target_weights(
    data: pd.DataFrame,
    top_n: int = 5,
    max_single_weight: float = 0.25,
    cash_buffer: float = 0.02,
    min_amount: float = 0.0,
    score_weighted: bool = False,
    date_col: str = "date",
    code_col: str = "code",
) -> pd.DataFrame:
    """只输出最新交易日的多雨目标权重。"""
    weights = build_daily_target_weights(
        data=data,
        top_n=top_n,
        max_single_weight=max_single_weight,
        cash_buffer=cash_buffer,
        min_amount=min_amount,
        score_weighted=score_weighted,
        date_col=date_col,
        code_col=code_col,
    )
    if weights.empty:
        return weights
    latest_date = weights[date_col].max()
    return weights.loc[weights[date_col].eq(latest_date)].sort_values("target_weight", ascending=False).reset_index(drop=True)
