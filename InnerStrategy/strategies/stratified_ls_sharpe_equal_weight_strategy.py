# -*- coding: utf-8 -*-
"""
SLSS 日线 CTA：多因子合成 ``slss_composite``；决策层由 ``Config/slss_strategy.json`` 的 ``decision_mode`` 决定。

- ``threshold``：合成值与 buy/sell 阈值比较（原仅做多开平）。
- ``cross_section_rank``：与向量回测一致，按交易日对股票池截面排名——
  名次 <= ``cross_section_long_top_n`` 做多（可选再要求 ``close>0``、``slss_composite>0``）；
  空头可为「名次 >= short_min_rank」或「当日名次最差 short_bottom_n 只」，并可选「或 slss_composite<0」；
  其余平仓。单标的实例依赖全市场面板预计算当日目标方向。

``a_share_cash_stock_rules``（见 JSON）：为 true 时按 A 股现货近似处理——截面不做 -1 裸卖空、多头卖平遵守日历日 T+1。

参数见 ``Config/slss_strategy.json``；预计算依赖 VeighNa ``history_data`` 与因子行情面板（截面模式）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from vnpy.trader.constant import Interval
from vnpy.trader.object import BarData, OrderData, TickData, TradeData
from vnpy_ctastrategy import BarGenerator, CtaTemplate, StopOrder

from InnerStrategy.inner_registry import get_factor_entry

from InnerStrategy.slss_bundle_constants import (
    BUNDLE_FACTOR_IDS,
    STRATIFIED_LONG_SHORT_SHARPE_OBJECTIVE_EN,
)
from InnerStrategy.slss_cross_section import compute_cross_section_target_side
from InnerStrategy.slss_strategy_config import compute_slss_composite_series, load_slss_strategy_config

_INIT_SLSS = load_slss_strategy_config()


def _noop_progress(_: str) -> None:
    """股票池构建等回调占位（不在 UI 线程输出）。"""
    return


def _bar_dt_key(dt: datetime) -> pd.Timestamp:
    """将 bar 时间戳规范为日历日索引，便于与因子长表对齐。"""
    t = dt.replace(tzinfo=None) if dt.tzinfo else dt
    return pd.Timestamp(t).normalize()


def _bars_to_ohlcv_df(bars: list[Any], vt_symbol: str) -> pd.DataFrame:
    """回测历史 BarData 列表 → Alpha 所需的 pandas 长表（单标的）。"""
    rows: list[dict[str, Any]] = []
    for bar in bars:
        rows.append(
            {
                "datetime": bar.datetime,
                "open": float(bar.open_price),
                "high": float(bar.high_price),
                "low": float(bar.low_price),
                "close": float(bar.close_price),
                "volume": float(bar.volume),
                "vt_symbol": vt_symbol,
            },
        )
    pdf = pd.DataFrame(rows)
    if pdf.empty:
        return pdf
    return pdf.sort_values("datetime").reset_index(drop=True)


class StratifiedLongShortSharpeEqualWeightStrategy(CtaTemplate):
    """
    阈值模式：买入 slss_composite > buy_threshold；多头平仓 composite < sell_threshold。
    截面模式：每日按全池合成值排名，目标为多头 / 空头 / 空仓（见 JSON cross_section_*）。
    """

    author = "MinQMT-F3"

    # 缺省来自 ``Config/slss_strategy.json``；回测器 setting 可覆盖
    decision_mode: str = _INIT_SLSS.decision_mode
    cross_section_long_top_n: int = _INIT_SLSS.cross_section_long_top_n
    cross_section_short_min_rank: int = _INIT_SLSS.cross_section_short_min_rank
    cross_section_long_require_close_positive: bool = _INIT_SLSS.cross_section_long_require_close_positive
    cross_section_long_require_composite_positive: bool = _INIT_SLSS.cross_section_long_require_composite_positive
    cross_section_short_bottom_n: int = _INIT_SLSS.cross_section_short_bottom_n
    cross_section_short_or_negative_composite: bool = _INIT_SLSS.cross_section_short_or_negative_composite
    a_share_cash_stock_rules: bool = _INIT_SLSS.a_share_cash_stock_rules
    buy_threshold: float = _INIT_SLSS.buy_threshold
    sell_threshold: float = _INIT_SLSS.sell_threshold
    fixed_lot: int = _INIT_SLSS.fixed_lot
    alpha_prepare_workers: int = _INIT_SLSS.alpha_prepare_workers

    slss_composite: float = 0.0
    cs_target: int = 0

    parameters = [
        "decision_mode",
        "cross_section_long_top_n",
        "cross_section_short_min_rank",
        "cross_section_long_require_close_positive",
        "cross_section_long_require_composite_positive",
        "cross_section_short_bottom_n",
        "cross_section_short_or_negative_composite",
        "a_share_cash_stock_rules",
        "buy_threshold",
        "sell_threshold",
        "fixed_lot",
        "alpha_prepare_workers",
    ]
    variables = ["slss_composite", "cs_target"]

    def on_init(self) -> None:
        """初始化 BarGenerator，并按决策模式预计算信号字典。"""
        self.write_log(
            f"{self.__class__.__name__} 初始化 | 目标函数英文名={STRATIFIED_LONG_SHORT_SHARPE_OBJECTIVE_EN} | "
            f"decision_mode={self.decision_mode}",
        )
        self.bg = BarGenerator(self.on_bar)
        self._composite_by_day: dict[pd.Timestamp, float] = {}
        self._cs_target_by_day: dict[pd.Timestamp, int] = {}
        # 因子评估门控：全量可行才允许买；不通过超过 1/3 时触发多头强平。
        self._selection_allow_buy: bool = False
        self._selection_force_sell: bool = False
        self._selection_false_count: int = 0
        self._selection_total_n: int = 0
        # A 股 T+1：记录最近一次「买入开仓」的日历日；卖出平仓须严格晚于该日
        self._long_open_buy_day: pd.Timestamp | None = None
        self._refresh_selection_gate()

        dm = str(self.decision_mode).strip().lower()
        if dm == "cross_section_rank":
            self._build_cross_section_lookup_from_panel()
        else:
            self._build_slss_lookup_from_engine_history()

        warm = 30
        self.load_bar(warm, interval=Interval.DAILY, use_database=True)

    def _refresh_selection_gate(self) -> None:
        """
        读取最近的 selection 快照并生成门控状态。

        规则：
        - N 个因子全部 selection_feasible=True 才允许买入；
        - selection_feasible=False 的个数 > N/3 时，触发多头强平。
        """
        try:
            from BackTest.factor_selection_snapshot_store import load_factor_selection_snapshot  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            self.write_log(f"读取因子评估快照模块失败: {type(exc).__name__}: {exc}")
            self._selection_allow_buy = False
            self._selection_force_sell = False
            self._selection_false_count = 0
            self._selection_total_n = 0
            return
        snap = load_factor_selection_snapshot()
        fac_map = snap.get("factors") if isinstance(snap, dict) else {}
        if not isinstance(fac_map, dict):
            fac_map = {}
        n = int(len(BUNDLE_FACTOR_IDS))
        false_cnt = 0
        true_cnt = 0
        for fid in BUNDLE_FACTOR_IDS:
            rec = fac_map.get(str(fid))
            feasible = bool(isinstance(rec, dict) and rec.get("selection_feasible") is True)
            if feasible:
                true_cnt += 1
            else:
                # 快照缺失也按不通过处理，保证门控保守生效。
                false_cnt += 1
        self._selection_total_n = n
        self._selection_false_count = false_cnt
        self._selection_allow_buy = bool(n > 0 and true_cnt == n)
        # “大于 1/3” 用整式比较避免浮点误差。
        self._selection_force_sell = bool(false_cnt * 3 > n) if n > 0 else False
        self.write_log(
            "因子评估门控："
            f"N={n}, feasible={true_cnt}, not_feasible={false_cnt}, "
            f"allow_buy={self._selection_allow_buy}, force_sell={self._selection_force_sell}。"
        )

    def _resolve_factor_specs(self) -> list[tuple[str, str]] | None:
        """从注册表解析因子包与列名；失败返回 None。"""
        specs: list[tuple[str, str]] = []
        for fid in BUNDLE_FACTOR_IDS:
            ent = get_factor_entry(fid)
            if not ent:
                self.write_log(f"注册表中找不到因子 {fid}，已跳过该列。")
                continue
            specs.append((str(ent["pack"]), str(ent["feature"])))
        if not specs:
            self.write_log("无有效因子规格。")
            return None
        return specs

    def _build_cross_section_lookup_from_panel(self) -> None:
        """
        截面排名：拉取与向量 SLSS 一致的股票池日线面板，算合成值与当日目标方向（-1/0/1），
        仅保留当前 ``vt_symbol`` 的日历日映射。
        """
        eng = self.cta_engine
        hist: list[Any] | None = getattr(eng, "history_data", None)
        if not hist:
            self.write_log("未找到 history_data：跳过截面预计算。")
            return

        base_one = _bars_to_ohlcv_df(hist, self.vt_symbol)
        if base_one.empty or len(base_one) < 5:
            self.write_log("历史 K 线过少，跳过截面预计算。")
            return

        from BackTest.factor_evaluation_config import load_factor_evaluation_json  # noqa: PLC0415
        from BackTest.factor_evaluation_settings import read_max_symbols_from_eval_cfg  # noqa: PLC0415
        from BackTest.factor_market_panel import build_daily_market_panel, iso_period_triple, load_sector_stock_list  # noqa: PLC0415
        from BackTest.stock_pool_builder import build_factor_evaluation_stock_pool  # noqa: PLC0415
        from BackTest.vector_slss_runner import (  # noqa: PLC0415
            _merge_alpha_packs_for_bundle,
            attach_base_ohlcv_to_merged,
        )

        eval_cfg = load_factor_evaluation_json()
        # max_symbols 统一由 GUI 的 spinBox_max_symbols 写入配置后读取，不再使用代码常量兜底。
        max_symbols = read_max_symbols_from_eval_cfg(eval_cfg)
        pool_syms, _pool_meta = build_factor_evaluation_stock_pool(eval_cfg, progress=_noop_progress)
        syms: list[str]
        if pool_syms:
            syms = list(pool_syms)
        else:
            syms = list(load_sector_stock_list(max_symbols) or [])
        if self.vt_symbol not in syms:
            syms.insert(0, self.vt_symbol)
        if max_symbols > 0:
            syms = syms[:max_symbols]

        t0 = pd.to_datetime(base_one["datetime"].min())
        t1 = pd.to_datetime(base_one["datetime"].max())
        start_yyyymmdd = t0.strftime("%Y%m%d")
        end_yyyymmdd = t1.strftime("%Y%m%d")

        try:
            base_panel = build_daily_market_panel(
                start_yyyymmdd,
                end_yyyymmdd,
                max_symbols,
                stock_list=syms,
            )
        except Exception as exc:  # noqa: BLE001
            self.write_log(f"截面行情面板失败: {type(exc).__name__}: {exc}")
            return

        if base_panel.empty or self.vt_symbol not in set(base_panel["vt_symbol"].astype(str).unique()):
            self.write_log("面板为空或当前标的未出现在面板中，跳过截面预计算。")
            return

        train_p, valid_p, test_p = iso_period_triple(start_yyyymmdd, end_yyyymmdd)
        mw = max(1, int(self.alpha_prepare_workers))

        try:
            merged = _merge_alpha_packs_for_bundle(
                base_panel,
                train_p,
                valid_p,
                test_p,
                max_workers=mw,
            )
        except Exception as exc:  # noqa: BLE001
            self.write_log(f"截面 Alpha 合并失败: {type(exc).__name__}: {exc}")
            return

        # 与向量 SLSS 一致：用原始行情列覆盖 merged，避免 close 被污染为近 0 导致成交价与盈亏失真
        merged = attach_base_ohlcv_to_merged(merged, base_panel)

        specs = self._resolve_factor_specs()
        if specs is None:
            return
        feat_cols: list[str] = [f for _, f in specs]
        miss_feat = [c for c in feat_cols if c not in merged.columns]
        if miss_feat:
            self.write_log(f"合并后仍缺少特征列 {miss_feat}，终止截面预计算。")
            return

        _cfg = load_slss_strategy_config()
        merged = merged.copy()
        merged["slss_composite"] = compute_slss_composite_series(merged, feat_cols, _cfg)
        merged["_cs_target"] = compute_cross_section_target_side(
            merged,
            value_col="slss_composite",
            long_top_n=int(self.cross_section_long_top_n),
            short_min_rank=int(self.cross_section_short_min_rank),
            long_require_close_positive=bool(self.cross_section_long_require_close_positive),
            long_require_composite_positive=bool(self.cross_section_long_require_composite_positive),
            short_bottom_n=int(self.cross_section_short_bottom_n),
            short_or_negative_composite=bool(self.cross_section_short_or_negative_composite),
        )
        # 与向量回测一致：现货账户不允许截面做空指令
        if bool(_cfg.a_share_cash_stock_rules):
            merged["_cs_target"] = merged["_cs_target"].where(merged["_cs_target"] >= 0, 0).astype(np.int8)

        sub = merged.loc[merged["vt_symbol"].astype(str) == str(self.vt_symbol)].copy()
        days = pd.to_datetime(sub["datetime"]).dt.normalize()
        for d, comp, tg in zip(days, sub["slss_composite"].to_numpy(), sub["_cs_target"].to_numpy()):
            dk = pd.Timestamp(d)
            if np.isfinite(comp):
                self._composite_by_day[dk] = float(comp)
            if tg in (-1, 0, 1):
                self._cs_target_by_day[dk] = int(tg)

        self.write_log(
            f"SLSS 截面目标已预计算：{len(self._cs_target_by_day)} 日（当前标的 {self.vt_symbol}），"
            f"long_top={int(self.cross_section_long_top_n)}, short_min_rank={int(self.cross_section_short_min_rank)}, "
            f"short_bottom_n={int(self.cross_section_short_bottom_n)}, "
            f"req_close+={bool(self.cross_section_long_require_close_positive)}, "
            f"req_comp+={bool(self.cross_section_long_require_composite_positive)}, "
            f"short_or_neg={bool(self.cross_section_short_or_negative_composite)}。",
        )

    def _build_slss_lookup_from_engine_history(self) -> None:
        """
        从 ``cta_engine.history_data`` 构建「日 → 等权合成值」映射（阈值决策模式）。

        说明：标准 CtaBacktesting 在 ``run_backtesting`` 前已 ``load_data``，此处可取全样本；
        若属性不存在或为空，则保持空映射（例如实盘引擎未实现同名字段）。
        """
        eng = self.cta_engine
        hist: list[Any] | None = getattr(eng, "history_data", None)
        if not hist:
            self.write_log("未找到 history_data：跳过因子预计算（常见于非回测引擎）。")
            return

        base_df = _bars_to_ohlcv_df(hist, self.vt_symbol)
        if base_df.empty or len(base_df) < 5:
            self.write_log("历史 K 线过少，跳过因子预计算。")
            return

        from BackTest.factor_alpha_runner import prepare_alpha_pack_raw_df  # noqa: PLC0415
        from BackTest.factor_market_panel import iso_period_triple  # noqa: PLC0415

        t0 = pd.to_datetime(base_df["datetime"].min())
        t1 = pd.to_datetime(base_df["datetime"].max())
        start_yyyymmdd = t0.strftime("%Y%m%d")
        end_yyyymmdd = t1.strftime("%Y%m%d")
        train_p, valid_p, test_p = iso_period_triple(start_yyyymmdd, end_yyyymmdd)
        mw = max(1, int(self.alpha_prepare_workers))

        specs = self._resolve_factor_specs()
        if specs is None:
            return

        need_158 = any(p == "alpha_158" for p, _ in specs)
        need_101 = any(p == "alpha_101" for p, _ in specs)
        # 仅准备策略配置引用的因子列，避免整包全量计算。
        feats158 = sorted({f for p, f in specs if p == "alpha_158"})
        feats101 = sorted({f for p, f in specs if p == "alpha_101"})

        merged: pd.DataFrame | None = None
        try:
            if need_158:
                merged = prepare_alpha_pack_raw_df(
                    "alpha_158",
                    base_df,
                    train_p,
                    valid_p,
                    test_p,
                    max_workers=mw,
                    selected_features=feats158,
                )
            if need_101:
                raw101 = prepare_alpha_pack_raw_df(
                    "alpha_101",
                    base_df,
                    train_p,
                    valid_p,
                    test_p,
                    max_workers=mw,
                    selected_features=feats101,
                )
                cols101 = ["datetime", "vt_symbol"] + feats101
                miss = [c for c in cols101 if c not in raw101.columns]
                if miss:
                    raise KeyError(f"alpha_101 结果缺少列: {miss}")
                sub101 = raw101[cols101]
                if merged is None:
                    merged = sub101.copy()
                else:
                    merged = merged.merge(sub101, on=["datetime", "vt_symbol"], how="left")
            if merged is None:
                self.write_log("未请求任何因子包，终止预计算。")
                return
        except Exception as exc:  # noqa: BLE001 — 预计算失败时记录并放弃信号
            self.write_log(f"因子预计算失败: {type(exc).__name__}: {exc}")
            return

        feat_cols: list[str] = [f for _, f in specs]
        miss_feat = [c for c in feat_cols if c not in merged.columns]
        if miss_feat:
            self.write_log(f"合并后仍缺少特征列 {miss_feat}，终止预计算。")
            return

        _cfg = load_slss_strategy_config()
        comp_ser = compute_slss_composite_series(merged, feat_cols, _cfg)
        days = pd.to_datetime(merged["datetime"]).dt.normalize()
        for d, v in zip(days, comp_ser.to_numpy()):
            if np.isfinite(v):
                self._composite_by_day[pd.Timestamp(d)] = float(v)

        self.write_log(f"SLSS 等权信号已预计算 {len(self._composite_by_day)} 个交易日。")

    def on_start(self) -> None:
        """策略启动。"""
        self.write_log("策略启动")
        self.put_event()

    def on_stop(self) -> None:
        """策略停止。"""
        self.write_log("策略停止")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        """Tick 聚合到 BarGenerator（日线回测通常不触发）。"""
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        """按决策模式读取预计算信号并发单。"""
        self.cancel_all()

        key = _bar_dt_key(bar.datetime)
        dm = str(self.decision_mode).strip().lower()

        if dm == "cross_section_rank":
            self._on_bar_cross_section(bar, key)
        else:
            self._on_bar_threshold(bar, key)

        self.put_event()

    def _on_bar_threshold(self, bar: BarData, key: pd.Timestamp) -> None:
        """绝对阈值：仅多头开平（与原策略一致）。"""
        raw_v = self._composite_by_day.get(key)
        if raw_v is None or not np.isfinite(raw_v):
            self.slss_composite = float("nan")
            self.cs_target = 0
            return

        self.slss_composite = float(raw_v)
        self.cs_target = 0
        # 门控触发强平：已有多头时优先卖出，不再进入买入路径。
        if self._selection_force_sell and self.pos > 0:
            if bool(self.a_share_cash_stock_rules) and self._long_open_buy_day is not None and key <= self._long_open_buy_day:
                return
            self.sell(bar.close_price, abs(self.pos))
            self._long_open_buy_day = None
            return
        # 未满足“全部可行”时禁止新买入，但允许后续卖出平仓。
        allow_buy_now = bool(self._selection_allow_buy)

        if allow_buy_now and self.pos == 0 and self.slss_composite > float(self.buy_threshold):
            self.buy(bar.close_price, float(self.fixed_lot))
            self._long_open_buy_day = key
        elif self.pos > 0 and self.slss_composite < float(self.sell_threshold):
            if bool(self.a_share_cash_stock_rules) and self._long_open_buy_day is not None and key <= self._long_open_buy_day:
                return
            self.sell(bar.close_price, abs(self.pos))
            self._long_open_buy_day = None

    def _on_bar_cross_section(self, bar: BarData, key: pd.Timestamp) -> None:
        """截面分桶：目标多头 / 空头 / 空仓，必要时同一根 K 线内先平再开。"""
        raw_v = self._composite_by_day.get(key)
        if raw_v is not None and np.isfinite(raw_v):
            self.slss_composite = float(raw_v)
        else:
            self.slss_composite = float("nan")

        want = self._cs_target_by_day.get(key)
        if want is None or want not in (-1, 0, 1):
            self.cs_target = 0
            return

        # A 股现货：截面空头目标在实盘中不可执行（无券不裸卖空），与向量侧 _cs_target 钳制一致
        if bool(self.a_share_cash_stock_rules) and int(want) == -1:
            want = 0
        # 门控：不允许买入时，把多头目标钳制为中性；强平时同样不允许继续多头。
        if (not self._selection_allow_buy) and int(want) == 1:
            want = 0

        self.cs_target = int(want)
        lot = float(self.fixed_lot)

        # 门控强平：若存在多头，先按 A 股规则尝试卖平；该分支不再执行开仓。
        if self._selection_force_sell and self.pos > 0:
            if bool(self.a_share_cash_stock_rules) and self._long_open_buy_day is not None and key <= self._long_open_buy_day:
                return
            self.sell(bar.close_price, abs(self.pos))
            self._long_open_buy_day = None
            return

        if self.cs_target == 1:
            if self.pos < 0:
                self.cover(bar.close_price, abs(self.pos))
            if self.pos == 0:
                self.buy(bar.close_price, lot)
                self._long_open_buy_day = key
        elif self.cs_target == -1:
            if self.pos > 0:
                if bool(self.a_share_cash_stock_rules) and self._long_open_buy_day is not None and key <= self._long_open_buy_day:
                    pass
                else:
                    self.sell(bar.close_price, abs(self.pos))
                    self._long_open_buy_day = None
            if self.pos == 0:
                self.short(bar.close_price, lot)
        else:
            if self.pos > 0:
                if bool(self.a_share_cash_stock_rules) and self._long_open_buy_day is not None and key <= self._long_open_buy_day:
                    pass
                else:
                    self.sell(bar.close_price, abs(self.pos))
                    self._long_open_buy_day = None
            elif self.pos < 0:
                self.cover(bar.close_price, abs(self.pos))

    def on_order(self, order: OrderData) -> None:
        """委托回报（本策略无需额外处理）。"""
        return

    def on_trade(self, trade: TradeData) -> None:
        """成交回报（本策略无需额外处理）。"""
        return

    def on_stop_order(self, stop_order: StopOrder) -> None:
        """停止单（未使用）。"""
        return
