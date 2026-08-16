# -*- coding: utf-8 -*-
"""
调用 InnerStrategy 下 Alpha101 / Alpha158，对全市场长表执行 prepare_data，得到含全部 feature 列的 raw_df。

使用项目内 **AlphaLocal**（开源 vnpy 表达式层衍生实现，**单进程** ``prepare_data``），不依赖 pip 包 ``vnpy``。
polars 在算子内使用；行情仍可由 xtdata 提供。
"""
from __future__ import annotations

from typing import Any

import pandas as pd


def _import_polars():
    """延迟导入 polars；未安装时给出明确提示（与 pip install polars / requirements 一致）。"""
    try:
        import polars as pl  # noqa: PLC0415

        return pl
    except ImportError as exc:
        raise ImportError(
            "未安装 polars，无法计算 Alpha 因子。请在当前 Python 环境执行："
            " pip install polars\n（已写入 requirements.txt；若走代理失败请检查网络/关闭错误代理。）",
        ) from exc


def _ensure_base_columns_pl(df: Any, pl: Any) -> Any:
    """补全表达式中可能用到的列（polars DataFrame）。"""
    out = df
    if "turnover" not in out.columns:
        out = out.with_columns(pl.lit(0.0).alias("turnover"))
    if "vwap" not in out.columns and all(
        c in out.columns for c in ("high", "low", "close")
    ):
        out = out.with_columns(
            ((pl.col("high") + pl.col("low") + pl.col("close")) / 3.0).alias("vwap"),
        )
    return out


def _panel_to_polars(base_df: pd.DataFrame, pl: Any) -> Any:
    """pandas 行情长表 → vnpy 所需的 polars（列名保持一致）。"""
    return pl.from_pandas(base_df)


def prepare_alpha_pack_raw_df(
    pack: str,
    base_df: pd.DataFrame,
    train_period: tuple[str, str],
    valid_period: tuple[str, str],
    test_period: tuple[str, str],
    max_workers: int = 1,
    selected_features: list[str] | tuple[str, ...] | set[str] | None = None,
) -> pd.DataFrame:
    """
    对单个因子包计算 feature，返回 raw_df（pandas，含 datetime, vt_symbol, close 与各因子列）。

    pack: ``alpha_101`` 或 ``alpha_158``（与 inner_registry 一致）。
    selected_features: 仅计算这些特征名；为空时保持原行为（计算该包全部特征）。
    """
    pl = _import_polars()
    df = _ensure_base_columns_pl(_panel_to_polars(base_df, pl), pl)

    if pack == "alpha_101":
        from InnerStrategy.factors.alpha_101 import Alpha101  # noqa: PLC0415

        ds: Any = Alpha101(df, train_period, valid_period, test_period)
    elif pack == "alpha_158":
        from InnerStrategy.factors.alpha_158 import Alpha158  # noqa: PLC0415

        ds = Alpha158(df, train_period, valid_period, test_period)
    else:
        raise ValueError(f"不支持的因子包: {pack!r}")

    # 性能优化：若给定特征白名单，仅保留策略实际使用的表达式，避免整包全量计算。
    if selected_features is not None:
        selected = {str(x).strip() for x in selected_features if str(x).strip()}
        if not selected:
            raise ValueError("selected_features 为空，无法计算因子。")
        miss = sorted(selected - set(ds.feature_expressions.keys()))
        if miss:
            raise KeyError(f"{pack} 不存在特征列: {miss}")
        ds.feature_expressions = {
            name: expr for name, expr in ds.feature_expressions.items() if name in selected
        }

    try:
        ds.prepare_data(max_workers=max_workers)
    except TypeError:
        ds.prepare_data()
    # vnpy 产出为 polars，下游指标用 pandas
    return ds.raw_df.to_pandas()


def long_table_for_feature(
    raw_df: pd.DataFrame,
    feature_name: str,
    factor_column_alias: str = "_factor_value",
) -> pd.DataFrame:
    """
    从 raw_df 取单因子列，并计算次日持有收益 fwd_ret（按 symbol 对齐下一日 close）。
    """
    if feature_name not in raw_df.columns:
        raise KeyError(f"raw_df 中不存在特征列: {feature_name!r}")
    if "close" not in raw_df.columns:
        raise KeyError("raw_df 缺少 close，无法计算 forward return")

    t = raw_df[["datetime", "vt_symbol", "close", feature_name]].copy()
    t = t.rename(columns={feature_name: factor_column_alias})
    t = t.sort_values(["vt_symbol", "datetime"])
    # 按标的：下一日收盘 / 当日收盘 - 1
    t["fwd_ret"] = t.groupby("vt_symbol")["close"].shift(-1) / t["close"] - 1.0
    t = t.dropna(subset=[factor_column_alias, "fwd_ret"])
    return t
