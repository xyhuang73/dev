# -*- coding: utf-8 -*-
"""
衍生自 vnpy vnpy/alpha/dataset/ta_function.py（MIT）。
TA-Lib 为可选：Alpha101/158 默认表达式未使用 ta_rsi/ta_atr 时，可不安装 talib。
"""
from __future__ import annotations

import polars as pl
import pandas as pd

from .utility import DataProxy

try:
    import talib
except ImportError:
    talib = None  # type: ignore[assignment]


def to_pd_series(feature: DataProxy) -> pd.Series:
    return feature.df.to_pandas().set_index(["datetime", "vt_symbol"])["data"]


def to_pl_dataframe(series: pd.Series) -> pl.DataFrame:
    return pl.from_pandas(series.reset_index().rename(columns={0: "data"}))


def ta_rsi(close: DataProxy, window: int) -> DataProxy:
    if talib is None:
        raise ImportError("表达式使用了 ta_rsi，请安装 TA-Lib：pip install TA-Lib")
    close_: pd.Series = to_pd_series(close)
    result: pd.Series = talib.RSI(close_, timeperiod=window)  # type: ignore[union-attr]
    df: pl.DataFrame = to_pl_dataframe(result)
    return DataProxy(df)


def ta_atr(high: DataProxy, low: DataProxy, close: DataProxy, window: int) -> DataProxy:
    if talib is None:
        raise ImportError("表达式使用了 ta_atr，请安装 TA-Lib：pip install TA-Lib")
    high_: pd.Series = to_pd_series(high)
    low_: pd.Series = to_pd_series(low)
    close_: pd.Series = to_pd_series(close)
    result: pd.Series = talib.ATR(high_, low_, close_, timeperiod=window)  # type: ignore[union-attr]
    df: pl.DataFrame = to_pl_dataframe(result)
    return DataProxy(df)
