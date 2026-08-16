# -*- coding: utf-8 -*-
"""
衍生自 vnpy vnpy/alpha/dataset/template.py（MIT License, https://github.com/vnpy/vnpy ）。

与上游差异::
    - ``prepare_data`` 默认单线程；``max_workers>1`` 时用 **线程池** 并行计算各特征（不用 ``multiprocessing``，
      以降低与 Qt/miniQMT 同进程时子进程触发原生库崩溃的风险）。
    - 若自定义因子包中 **后序特征依赖前序特征列**，须保持 ``max_workers=1``，否则可能算错。
    - ``show_feature_performance`` / ``show_signal_performance`` 内 **延迟 import alphalens**，避免未安装时影响因子计算。
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import cast

import pandas as pd
import polars as pl
from collections.abc import Callable
from tqdm import tqdm

from ..logger import logger
from .utility import (
    Segment,
    calculate_by_expression,
    calculate_by_polars,
    to_datetime,
)


class AlphaDataset:
    """Alpha dataset template class（本地单进程版）。"""

    def __init__(
        self,
        df: pl.DataFrame,
        train_period: tuple[str, str],
        valid_period: tuple[str, str],
        test_period: tuple[str, str],
        process_type: str = "append",
    ) -> None:
        self.df: pl.DataFrame = df
        self.result_df: pl.DataFrame
        self.raw_df: pl.DataFrame
        self.infer_df: pl.DataFrame
        self.learn_df: pl.DataFrame

        self.data_periods: dict[Segment, tuple[str, str]] = {
            Segment.TRAIN: train_period,
            Segment.VALID: valid_period,
            Segment.TEST: test_period,
        }

        self.feature_expressions: dict[str, str | pl.expr.expr.Expr] = {}
        self.feature_results: dict[str, pl.DataFrame] = {}
        self.label_expression: str = ""

        self.process_type: str = process_type
        self.infer_processors: list = []
        self.learn_processors: list = []

    def add_feature(
        self,
        name: str,
        expression: str | pl.expr.expr.Expr | None = None,
        result: pl.DataFrame | None = None,
    ) -> None:
        if expression is not None and result is not None:
            raise ValueError("Only one of 'expression' or 'result' can be provided")
        if expression is not None:
            self.feature_expressions[name] = expression
        elif result is not None:
            self.feature_results[name] = result

    def set_label(self, expression: str) -> None:
        self.label_expression = expression

    def add_processor(self, task: str, processor: Callable[[pl.DataFrame], None]) -> None:
        if task == "infer":
            self.infer_processors.append(processor)
        else:
            self.learn_processors.append(processor)

    def prepare_data(self, filters: dict | None = None, max_workers: int | None = None) -> None:
        """
        计算全部特征与 label。

        Args:
            max_workers: ``None``、``1`` 或小于 ``1`` 时 **顺序** 单线程计算；大于 ``1`` 时使用
                ``ThreadPoolExecutor`` 对 **各特征表达式** 并行求值（因子与因子之间并行）。
                各特征须仅依赖 ``self.df`` 中已有列（如行情列）；若存在「后一列依赖前一列因子」的链式定义，
                必须设为 ``1``。

        说明:
            采用多 **线程** 而非多进程，避免 ``multiprocessing`` 与 Qt/原生库混用时的典型崩溃；Polars 在
            计算时多在底层释放 GIL，线程并行通常仍有收益。内存约为「单线程 × 并行度」量级的峰值风险，请酌情调 ``max_workers``。
        """
        workers = 1 if max_workers is None or max_workers < 1 else int(max_workers)

        expressions: list[tuple[str, str | pl.expr.expr.Expr]] = list(self.feature_expressions.items())
        if self.label_expression:
            expressions.append(("label", self.label_expression))

        args: list[tuple[pl.DataFrame, str, str | pl.expr.expr.Expr]] = [
            (self.df, name, expression) for name, expression in expressions
        ]
        if workers == 1:
            logger.info("开始计算表达式因子特征（单线程顺序）")
            results = [calculate_feature(arg) for arg in tqdm(args, total=len(args))]
        else:
            logger.info("开始计算表达式因子特征（ThreadPoolExecutor，max_workers=%d）", workers)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                # map 按输入顺序产出结果，与 with_columns 列顺序一致
                results = list(tqdm(executor.map(calculate_feature, args), total=len(args)))

        self.result_df = self.df.with_columns(results)

        logger.info("开始合并结果数据因子特征")
        label_exist: bool = "label" in self.result_df
        for name, feature_result in tqdm(self.feature_results.items()):
            feature_result = feature_result.rename({"data": name})
            self.result_df = self.result_df.join(feature_result, on=["datetime", "vt_symbol"], how="left")

        if label_exist:
            cols: list[str] = [col for col in self.result_df.columns if col != "label"] + ["label"]
            self.result_df = self.result_df.select(cols).sort(["datetime", "vt_symbol"])

        raw_df = self.result_df.fill_null(float("nan"))

        if filters:
            logger.info("开始筛选成分股数据")
            dfs: list[pl.DataFrame] = []
            for vt_symbol, ranges in tqdm(filters.items(), total=len(filters)):
                for start, end in ranges:
                    temp_df = raw_df.filter(
                        (pl.col("vt_symbol") == vt_symbol)
                        & (pl.col("datetime") >= pl.lit(start))
                        & (pl.col("datetime") <= pl.lit(end)),
                    )
                    dfs.append(temp_df)
            raw_df = pl.concat(dfs)

        # 原 vnpy 写法只保留 datetime/vt_symbol + 因子列（raw_df.columns[self.df.width:]），会丢掉 open/high/low/close 等行情列。
        # 本项目全因子截面评价需在 long_table_for_feature 中用 close 算 fwd_ret，故 raw_df 保留完整列。
        self.raw_df = raw_df.sort(["datetime", "vt_symbol"])
        self.infer_df = self.raw_df
        self.learn_df = self.raw_df

    def process_data(self) -> None:
        for processor in self.infer_processors:
            self.infer_df = processor(df=self.infer_df)
        if self.process_type == "append":
            self.learn_df = self.infer_df
        for processor in self.learn_processors:
            self.learn_df = processor(df=self.learn_df)

    def fetch_raw(self, segment: Segment) -> pl.DataFrame:
        start, end = self.data_periods[segment]
        return query_by_time(self.raw_df, start, end)

    def fetch_infer(self, segment: Segment) -> pl.DataFrame:
        start, end = self.data_periods[segment]
        return query_by_time(self.infer_df, start, end)

    def fetch_learn(self, segment: Segment) -> pl.DataFrame:
        start, end = self.data_periods[segment]
        return query_by_time(self.learn_df, start, end)

    def show_feature_performance(self, name: str) -> None:
        from alphalens.tears import create_full_tear_sheet  # noqa: PLC0415
        from alphalens.utils import get_clean_factor_and_forward_returns  # noqa: PLC0415

        starts: list[datetime] = []
        ends: list[datetime] = []
        for period in self.data_periods.values():
            starts.append(to_datetime(period[0]))
            ends.append(to_datetime(period[1]))
        start: datetime = min(starts)
        end: datetime = max(ends)

        result_df: pl.DataFrame = query_by_time(self.result_df, start, end)
        learn_df: pl.DataFrame = query_by_time(self.learn_df, start, end)
        merged_df = (
            result_df.select(["datetime", "vt_symbol", "close"]).join(
                learn_df.select(["datetime", "vt_symbol", name]),
                on=["datetime", "vt_symbol"],
                how="inner",
            )
        )
        merged_df = merged_df.fill_nan(None).drop_nulls()
        feature_df: pd.DataFrame = merged_df.select(["datetime", "vt_symbol", name]).to_pandas()
        feature_df.set_index(["datetime", "vt_symbol"], inplace=True)
        feature_s: pd.Series = feature_df[name]
        price_df: pd.DataFrame = merged_df.select(["datetime", "vt_symbol", "close"]).to_pandas()
        price_df = price_df.pivot(index="datetime", columns="vt_symbol", values="close")
        clean_data: pd.DataFrame = get_clean_factor_and_forward_returns(feature_s, price_df, quantiles=10)
        create_full_tear_sheet(clean_data)

    def show_signal_performance(self, signal: pl.DataFrame) -> None:
        from alphalens.tears import create_full_tear_sheet  # noqa: PLC0415
        from alphalens.utils import get_clean_factor_and_forward_returns  # noqa: PLC0415

        start: datetime = cast(datetime, signal["datetime"].min())
        end: datetime = cast(datetime, signal["datetime"].max())
        df: pl.DataFrame = query_by_time(self.result_df, start, end)
        signal_df: pd.DataFrame = signal.to_pandas()
        signal_df.set_index(["datetime", "vt_symbol"], inplace=True)
        signal_s: pd.Series = signal_df["signal"]
        price_df: pd.DataFrame = df.select(["datetime", "vt_symbol", "close"]).to_pandas()
        price_df = price_df.pivot(index="datetime", columns="vt_symbol", values="close")
        clean_data: pd.DataFrame = get_clean_factor_and_forward_returns(
            signal_s,
            price_df,
            max_loss=1.0,
            quantiles=10,
        )
        create_full_tear_sheet(clean_data)


def query_by_time(df: pl.DataFrame, start: datetime | str = "", end: datetime | str = "") -> pl.DataFrame:
    if start:
        start = to_datetime(start)
        df = df.filter(pl.col("datetime") >= start)
    if end:
        end = to_datetime(end)
        df = df.filter(pl.col("datetime") <= end)
    return df.sort(["datetime", "vt_symbol"])


def calculate_feature(args: tuple[pl.DataFrame, str, str | pl.expr.expr.Expr]) -> pl.Series:
    df, name, expression = args
    t0 = time.time()
    if isinstance(expression, pl.expr.expr.Expr):
        result = calculate_by_polars(df, expression)["data"].alias(name)
    else:
        result = calculate_by_expression(df, expression)["data"].alias(name)
    logger.info("Feature %s took %.2fs", name, time.time() - t0)
    return result
