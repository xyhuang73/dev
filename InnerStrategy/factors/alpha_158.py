# -*- coding: utf-8 -*-
# 归档说明：自 F2_VeighNa0411/VeighNa/vnpy/alpha/dataset/datasets/ 复制，供 MiniQMT 工程引用。
# 依赖：polars；AlphaDataset 使用项目内 AlphaLocal（衍生自开源 vnpy，与 pip vnpy 解耦）。
import polars as pl

from AlphaLocal import AlphaDataset

# 时序窗口与公式常数由同目录 ``alpha_158_parameters.json`` 配置（与批量因子评估参数分离）
from BackTest.factor_single_parameters_settings import alpha158_formula_params, alpha158_ts_windows


class Alpha158(AlphaDataset):
    """158 basic factors from Qlib"""

    def __init__(
        self,
        df: pl.DataFrame,
        train_period: tuple[str, str],
        valid_period: tuple[str, str],
        test_period: tuple[str, str]
    ) -> None:
        super().__init__(
            df=df,
            train_period=train_period,
            valid_period=valid_period,
            test_period=test_period,
        )

        # 分位、防零除、log(volume+1) 偏移等（与 alpha158_ts_windows 并列管理）
        af = alpha158_formula_params()
        eps = float(af.get("eps") or 1e-12)
        qh = float(af.get("quantile_high") or 0.8)
        ql = float(af.get("quantile_low") or 0.2)
        log_vol_off = float(af.get("log_volume_offset") or 1.0)

        # Candlestick pattern features
        self.add_feature("kmid", "(close - open) / open")
        self.add_feature("klen", "(high - low) / open")
        self.add_feature("kmid_2", f"(close - open) / (high - low + {eps})")
        self.add_feature("kup", "(high - ts_greater(open, close)) / open")
        self.add_feature("kup_2", f"(high - ts_greater(open, close)) / (high - low + {eps})")
        self.add_feature("klow", "(ts_less(open, close) - low) / open")
        self.add_feature("klow_2", f"((ts_less(open, close) - low) / (high - low + {eps}))")
        self.add_feature("ksft", "(close * 2 - high - low) / open")
        self.add_feature("ksft_2", f"(close * 2 - high - low) / (high - low + {eps})")

        # Price change features
        for field in ["open", "high", "low", "vwap"]:
            self.add_feature(f"{field}_0", f"{field} / close")

        # Time series features（窗口日数来自 alpha_158_parameters.json）
        windows: list[int] = alpha158_ts_windows()

        for w in windows:
            self.add_feature(f"roc_{w}", f"ts_delay(close, {w}) / close")

        for w in windows:
            self.add_feature(f"ma_{w}", f"ts_mean(close, {w}) / close")

        for w in windows:
            self.add_feature(f"std_{w}", f"ts_std(close, {w}) / close")

        for w in windows:
            self.add_feature(f"beta_{w}", f"ts_slope(close, {w}) / close")

        for w in windows:
            self.add_feature(f"rsqr_{w}", f"ts_rsquare(close, {w})")

        for w in windows:
            self.add_feature(f"resi_{w}", f"ts_resi(close, {w}) / close")

        for w in windows:
            self.add_feature(f"max_{w}", f"ts_max(high, {w}) / close")

        for w in windows:
            self.add_feature(f"min_{w}", f"ts_min(low, {w}) / close")

        for w in windows:
            self.add_feature(f"qtlu_{w}", f"ts_quantile(close, {w}, {qh}) / close")

        for w in windows:
            self.add_feature(f"qtld_{w}", f"ts_quantile(close, {w}, {ql}) / close")

        for w in windows:
            self.add_feature(f"rank_{w}", f"ts_rank(close, {w})")

        for w in windows:
            self.add_feature(f"rsv_{w}", f"(close - ts_min(low, {w})) / (ts_max(high, {w}) - ts_min(low, {w}) + {eps})")

        for w in windows:
            self.add_feature(f"imax_{w}", f"ts_argmax(high, {w}) / {w}")

        for w in windows:
            self.add_feature(f"imin_{w}", f"ts_argmin(low, {w}) / {w}")

        for w in windows:
            self.add_feature(f"imxd_{w}", f"(ts_argmax(high, {w}) - ts_argmin(low, {w})) / {w}")

        for w in windows:
            self.add_feature(f"corr_{w}", f"ts_corr(close, ts_log(volume + {log_vol_off}), {w})")

        for w in windows:
            self.add_feature(
                f"cord_{w}",
                f"ts_corr(close / ts_delay(close, 1), ts_log(volume / ts_delay(volume, 1) + {log_vol_off}), {w})",
            )

        for w in windows:
            self.add_feature(f"cntp_{w}", f"ts_mean(close > ts_delay(close, 1), {w})")

        for w in windows:
            self.add_feature(f"cntn_{w}", f"ts_mean(close < ts_delay(close, 1), {w})")

        for w in windows:
            self.add_feature(f"cntd_{w}", f"ts_mean(close > ts_delay(close, 1), {w}) - ts_mean(close < ts_delay(close, 1), {w})")

        for w in windows:
            self.add_feature(
                f"sump_{w}",
                f"ts_sum(ts_greater(close - ts_delay(close, 1), 0), {w}) / (ts_sum(ts_abs(close - ts_delay(close, 1)), {w}) + {eps})",
            )

        for w in windows:
            self.add_feature(
                f"sumn_{w}",
                f"ts_sum(ts_greater(ts_delay(close, 1) - close, 0), {w}) / (ts_sum(ts_abs(close - ts_delay(close, 1)), {w}) + {eps})",
            )

        for w in windows:
            self.add_feature(
                f"sumd_{w}",
                f"(ts_sum(ts_greater(close - ts_delay(close, 1), 0), {w}) - ts_sum(ts_greater(ts_delay(close, 1) - close, 0), {w})) / (ts_sum(ts_abs(close - ts_delay(close, 1)), {w}) + {eps})",
            )

        for w in windows:
            self.add_feature(f"vma_{w}", f"ts_mean(volume, {w}) / (volume + {eps})")

        for w in windows:
            self.add_feature(f"vstd_{w}", f"ts_std(volume, {w}) / (volume + {eps})")

        for w in windows:
            self.add_feature(
                f"wvma_{w}",
                f"ts_std(ts_abs(close / ts_delay(close, 1) - 1) * volume, {w}) / (ts_mean(ts_abs(close / ts_delay(close, 1) - 1) * volume, {w}) + {eps})",
            )

        for w in windows:
            self.add_feature(
                f"vsump_{w}",
                f"ts_sum(ts_greater(volume - ts_delay(volume, 1), 0), {w}) / (ts_sum(ts_abs(volume - ts_delay(volume, 1)), {w}) + {eps})",
            )

        for w in windows:
            self.add_feature(
                f"vsumn_{w}",
                f"ts_sum(ts_greater(ts_delay(volume, 1) - volume, 0), {w}) / (ts_sum(ts_abs(volume - ts_delay(volume, 1)), {w}) + {eps})",
            )

        for w in windows:
            self.add_feature(
                f"vsumd_{w}",
                f"(ts_sum(ts_greater(volume - ts_delay(volume, 1), 0), {w}) - ts_sum(ts_greater(ts_delay(volume, 1) - volume, 0), {w})) / (ts_sum(ts_abs(volume - ts_delay(volume, 1)), {w}) + {eps})",
            )

        # Set label
        self.set_label("ts_delay(close, -3) / ts_delay(close, -1) - 1")
