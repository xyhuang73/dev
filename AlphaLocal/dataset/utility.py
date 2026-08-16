# -*- coding: utf-8 -*-
"""
衍生自 vnpy（MIT License, https://github.com/vnpy/vnpy ）vnpy/alpha/dataset/utility.py
本地副本：供 MiniQMT 回测在无 ``import vnpy`` 时使用；逻辑与上游一致，仅做包路径调整。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Union

import polars as pl


class DataProxy:
    """Feature data proxy"""

    def __init__(self, df: pl.DataFrame) -> None:
        self.name: str = df.columns[-1]
        self.df: pl.DataFrame = df.rename({self.name: "data"})

    def result(self, s: pl.Series) -> "DataProxy":
        result: pl.DataFrame = self.df[["datetime", "vt_symbol"]].with_columns(s.alias("data"))
        return DataProxy(result)

    def __add__(self, other: Union["DataProxy", int, float]) -> "DataProxy":
        if isinstance(other, DataProxy):
            s: pl.Series = self.df["data"] + other.df["data"]
        else:
            s = self.df["data"] + other
        return self.result(s)

    def __sub__(self, other: Union["DataProxy", int, float]) -> "DataProxy":
        if isinstance(other, DataProxy):
            s = self.df["data"] - other.df["data"]
        else:
            s = self.df["data"] - other
        return self.result(s)

    def __mul__(self, other: Union["DataProxy", int, float]) -> "DataProxy":
        if isinstance(other, DataProxy):
            s = self.df["data"] * other.df["data"]
        else:
            s = self.df["data"] * other
        return self.result(s)

    def __rmul__(self, other: Union["DataProxy", int, float]) -> "DataProxy":
        if isinstance(other, DataProxy):
            s = self.df["data"] * other.df["data"]
        else:
            s = self.df["data"] * other
        return self.result(s)

    def __truediv__(self, other: Union["DataProxy", int, float]) -> "DataProxy":
        if isinstance(other, DataProxy):
            s = self.df["data"] / other.df["data"]
        else:
            s = self.df["data"] / other
        return self.result(s)

    def __abs__(self) -> "DataProxy":
        """供 ``abs(proxy)`` 与 cs_scale 等调用。"""
        s = self.df["data"].abs()
        return self.result(s)

    def __gt__(self, other: Union["DataProxy", int, float]) -> "DataProxy":
        if isinstance(other, DataProxy):
            s = self.df["data"] > other.df["data"]
        else:
            s = self.df["data"] > other
        return self.result(s.cast(pl.Int32))

    def __ge__(self, other: Union["DataProxy", int, float]) -> "DataProxy":
        if isinstance(other, DataProxy):
            s = self.df["data"] >= other.df["data"]
        else:
            s = self.df["data"] >= other
        return self.result(s.cast(pl.Int32))

    def __lt__(self, other: Union["DataProxy", int, float]) -> "DataProxy":
        if isinstance(other, DataProxy):
            s = self.df["data"] < other.df["data"]
        else:
            s = self.df["data"] < other
        return self.result(s.cast(pl.Int32))

    def __le__(self, other: Union["DataProxy", int, float]) -> "DataProxy":
        if isinstance(other, DataProxy):
            s = self.df["data"] <= other.df["data"]
        else:
            s = self.df["data"] <= other
        return self.result(s.cast(pl.Int32))

    def __eq__(self, other: Union["DataProxy", int, float]) -> "DataProxy":  # type: ignore[override]
        if isinstance(other, DataProxy):
            s = self.df["data"] == other.df["data"]
        else:
            s = self.df["data"] == other
        return self.result(s.cast(pl.Int32))


def calculate_by_expression(df: pl.DataFrame, expression: str) -> pl.DataFrame:
    """Execute calculation based on expression（与 vnpy 一致）。"""
    from .ts_function import (  # noqa: PLC0415
        ts_delay,
        ts_min,
        ts_max,
        ts_argmax,
        ts_argmin,
        ts_rank,
        ts_sum,
        ts_mean,
        ts_std,
        ts_slope,
        ts_quantile,
        ts_rsquare,
        ts_resi,
        ts_corr,
        ts_less,
        ts_greater,
        ts_log,
        ts_abs,
        ts_delta,
        ts_cov,
        ts_decay_linear,
        ts_product,
    )
    from .cs_function import cs_rank, cs_mean, cs_std, cs_sum, cs_scale  # noqa: PLC0415
    from .ta_function import ta_rsi, ta_atr  # noqa: PLC0415
    from .math_function import (  # noqa: PLC0415
        less,
        greater,
        log,
        abs,
        sign,
        pow1,
        pow2,
        quesval,
        quesval2,
    )

    d: dict = locals()
    for column in df.columns:
        if column in {"datetime", "vt_symbol"}:
            continue
        column_df = df[["datetime", "vt_symbol", column]]
        d[column] = DataProxy(column_df)

    other: DataProxy = eval(expression, {}, d)
    return other.df


def calculate_by_polars(df: pl.DataFrame, expression: pl.expr.expr.Expr) -> pl.DataFrame:
    return df.select(["datetime", "vt_symbol", expression.alias("data")])


def to_datetime(arg: datetime | str) -> datetime:
    if isinstance(arg, str):
        fmt: str = "%Y-%m-%d" if "-" in arg else "%Y%m%d"
        return datetime.strptime(arg, fmt)
    return arg


class Segment(Enum):
    TRAIN = 1
    VALID = 2
    TEST = 3
