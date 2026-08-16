# -*- coding: utf-8 -*-
# 归档说明：自 F2_VeighNa0411/VeighNa/vnpy/alpha/dataset/datasets/ 复制，供 MiniQMT 工程引用。
# 依赖：polars；AlphaDataset 使用项目内 AlphaLocal（衍生自开源 vnpy，与 pip vnpy 解耦）。
# 公式内可调数值由同目录 ``alpha_101_parameters.json`` 覆盖，缺省见 BackTest/alpha_101_formula_defaults.py。
import polars as pl

from AlphaLocal import AlphaDataset

from .alpha_101_parameters import alpha101_params


class Alpha101(AlphaDataset):
    """101 basic factors from WorldQuant"""

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

        returns_expr: str = "(close / ts_delay(close, 1) - 1)"
        ap = alpha101_params()
        r = returns_expr
        # 依次注册 Alpha1–101：窗宽与常数由 ap 提供（JSON 覆盖，缺省见 alpha_101_formula_defaults）

        p = ap["alpha1"]
        self.add_feature(
            "alpha1",
            f"(cs_rank(ts_argmax(pow1(quesval({p['q0']}, {r}, close, ts_std({r}, {p['n_std']})), {p['pow_n']}), {p['n_argmax']})) - {p['half']})",
        )

        p = ap["alpha2"]
        self.add_feature(
            "alpha2",
            f"(-1) * ts_corr(cs_rank(ts_delta(log(volume), {p['n_delta_vol']})), cs_rank((close - open) / open), {p['n_corr']})",
        )

        p = ap["alpha3"]
        self.add_feature("alpha3", f"ts_corr(cs_rank(open), cs_rank(volume), {p['n_corr']}) * -1")

        p = ap["alpha4"]
        self.add_feature("alpha4", f"-1 * ts_rank(cs_rank(low), {p['n_rank']})")

        p = ap["alpha5"]
        self.add_feature(
            "alpha5",
            f"cs_rank((open - (ts_sum(vwap, {p['n_sum_vwap']}) / {p['n_sum_vwap']}))) * (-1 * abs(cs_rank((close - vwap))))",
        )

        p = ap["alpha6"]
        self.add_feature("alpha6", f"(-1) * ts_corr(open, volume, {p['n_corr']})")

        p = ap["alpha7"]
        self.add_feature(
            "alpha7",
            f"quesval2(ts_mean(volume, {p['n_vol_mean']}), volume, (-1 * ts_rank(abs(close - ts_delay(close, {p['n_delay_close']})), {p['n_rank']})) * sign(ts_delta(close, {p['n_delta_close']})), {p['else_v']})",
        )

        p = ap["alpha8"]
        self.add_feature(
            "alpha8",
            f"-1 * cs_rank(((ts_sum(open, {p['n_sum']}) * ts_sum({r}, {p['n_sum']})) - ts_delay((ts_sum(open, {p['n_sum']}) * ts_sum({r}, {p['n_sum']})), {p['n_delay']})))",
        )

        p = ap["alpha9"]
        self.add_feature(
            "alpha9",
            f"quesval(0, ts_min(ts_delta(close, 1), {p['n_bound']}), ts_delta(close, 1), quesval(0, ts_max(ts_delta(close, 1), {p['n_bound']}), (-1 * ts_delta(close, 1)), ts_delta(close, 1)))",
        )

        p = ap["alpha10"]
        self.add_feature(
            "alpha10",
            f"cs_rank(quesval(0, ts_min(ts_delta(close, 1), {p['n_bound']}), ts_delta(close, 1), quesval(0, ts_max(ts_delta(close, 1), {p['n_bound']}), (-1 * ts_delta(close, 1)), ts_delta(close, 1))))",
        )

        p = ap["alpha11"]
        self.add_feature(
            "alpha11",
            f"(cs_rank(ts_max(vwap - close, {p['n_extreme']})) + cs_rank(ts_min(vwap - close, {p['n_extreme']}))) * cs_rank(ts_delta(volume, {p['n_delta_vol']}))",
        )

        p = ap["alpha12"]
        self.add_feature(
            "alpha12",
            f"sign(ts_delta(volume, {p['n_delta_vol']})) * (-1 * ts_delta(close, {p['n_delta_close']}))",
        )

        p = ap["alpha13"]
        self.add_feature("alpha13", f"-1 * cs_rank(ts_cov(cs_rank(close), cs_rank(volume), {p['n_cov']}))")

        p = ap["alpha14"]
        self.add_feature(
            "alpha14",
            f"(-1 * cs_rank(({r}) - ts_delay({r}, {p['n_delay_ret']}))) * ts_corr(open, volume, {p['n_corr']})",
        )

        p = ap["alpha15"]
        self.add_feature(
            "alpha15",
            f"-1 * ts_sum(cs_rank(ts_corr(cs_rank(high), cs_rank(volume), {p['n_corr_inner']})), {p['n_sum_outer']})",
        )

        p = ap["alpha16"]
        self.add_feature("alpha16", f"-1 * cs_rank(ts_cov(cs_rank(high), cs_rank(volume), {p['n_cov']}))")

        p = ap["alpha17"]
        self.add_feature(
            "alpha17",
            f"(-1 * cs_rank(ts_rank(close, {p['n_rank_close']}))) * cs_rank(close - {p['k_delay2']} * ts_delay(close, {p['n_delay1']}) + ts_delay(close, {p['n_delay2']})) * cs_rank(ts_rank(volume / ts_mean(volume, {p['n_vol_mean']}), {p['n_rank_vol']}))",
        )

        p = ap["alpha18"]
        self.add_feature(
            "alpha18",
            f"-1 * cs_rank((ts_std(abs(close - open), {p['n_std']}) + (close - open)) + ts_corr(close, open, {p['n_corr']}))",
        )

        p = ap["alpha19"]
        self.add_feature(
            "alpha19",
            f"(-1 * sign(ts_delta(close, {p['n_delta']}) + (close - ts_delay(close, {p['n_delay']})))) * (cs_rank(ts_sum({r}, {p['n_sum_ret']}) + 1) + 1)",
        )

        p = ap["alpha20"]
        self.add_feature(
            "alpha20",
            f"(-1 * cs_rank(open - ts_delay(high, {p['n_delay_h']}))) * cs_rank(open - ts_delay(close, {p['n_delay_c']})) * cs_rank(open - ts_delay(low, {p['n_delay_l']}))",
        )

        # Alpha21 (the innermost original was >=1, implemented as >1)
        p = ap["alpha21"]
        self.add_feature(
            "alpha21",
            f"quesval2((ts_mean(close, {p['n_mean_long']}) + ts_std(close, {p['n_mean_long']})), ts_mean(close, {p['n_mean_short']}), -1, quesval2(ts_mean(close, {p['n_mean_short']}), (ts_mean(close, {p['n_mean_long']}) - ts_std(close, {p['n_mean_long']})), 1, quesval({p['q_in']}, (volume / ts_mean(volume, {p['n_vol_mean']})), 1, -1)))",
        )

        p = ap["alpha22"]
        self.add_feature(
            "alpha22",
            f"-1 * ts_delta(ts_corr(high, volume, {p['n_corr']}), {p['n_delta_corr']}) * cs_rank(ts_std(close, {p['n_std_close']}))",
        )

        p = ap["alpha23"]
        self.add_feature(
            "alpha23",
            f"quesval2(ts_mean(high, {p['n_mean_high']}), high, -1 * ts_delta(high, {p['n_delta_high']}), {p['else_v']})",
        )

        # Alpha24 (the original condition was <=0.05, implemented as <0.05)
        p = ap["alpha24"]
        self.add_feature(
            "alpha24",
            f"quesval({p['q_thresh']}, ts_delta(ts_sum(close, {p['n_sum']}) / {p['n_sum']}, {p['n_sum']}) / ts_delay(close, {p['n_delay_close']}), (-1 * ts_delta(close, {p['n_delta_close']})), (-1 * (close - ts_min(close, {p['n_min_close']}))))",
        )

        p = ap["alpha25"]
        self.add_feature("alpha25", f"cs_rank( (-1 * {r}) * ts_mean(volume, {p['n_vol_mean']}) * vwap * (high - close) )")

        p = ap["alpha26"]
        self.add_feature(
            "alpha26",
            f"-1 * ts_max(ts_corr(ts_rank(volume, {p['n_rank']}), ts_rank(high, {p['n_rank']}), {p['n_corr']}), {p['n_ts_max']})",
        )

        p = ap["alpha27"]
        self.add_feature(
            "alpha27",
            f"quesval({p['q_thresh']}, cs_rank(ts_mean(ts_corr(cs_rank(volume), cs_rank(vwap), {p['n_corr']}), {p['n_mean']})), {p['v_neg']}, {p['v_pos']})",
        )

        p = ap["alpha28"]
        self.add_feature(
            "alpha28",
            f"cs_scale(ts_corr(ts_mean(volume, {p['n_vol_mean']}), low, {p['n_corr']}) + (high + low) / 2 - close)",
        )

        p = ap["alpha29"]
        self.add_feature(
            "alpha29",
            f"ts_min(ts_product(cs_rank(cs_rank(cs_scale(log(ts_sum(ts_min(cs_rank(cs_rank((-1 * cs_rank(ts_delta((close - {p['lit_close_minus']}), {p['n_delta_close']}))))), {p['n_min_inner']}), {p['n_sum_inner']}))))), {p['n_min_mid']}), {p['n_min_outer']}) + ts_rank(ts_delay((-1 * {r}), {p['n_delay_ret']}), {p['n_rank']})",
        )

        p = ap["alpha30"]
        self.add_feature(
            "alpha30",
            f"((cs_rank(sign(close - ts_delay(close, 1)) + sign(ts_delay(close, 1) - ts_delay(close, 2)) + sign(ts_delay(close, 2) - ts_delay(close, 3))) * -1 + 1) * ts_sum(volume, {p['n_sum_vol_short']})) / ts_sum(volume, {p['n_sum_vol_long']})",
        )

        p = ap["alpha31"]
        self.add_feature(
            "alpha31",
            f"(cs_rank(cs_rank(cs_rank(ts_decay_linear((-1) * cs_rank(cs_rank(ts_delta(close, {p['n_delta_long']}))), {p['n_decay']})))) + cs_rank((-1) * ts_delta(close, {p['n_delta_short']}))) + sign(cs_scale(ts_corr(ts_mean(volume, {p['n_vol_mean']}), low, {p['n_corr']})))",
        )

        p = ap["alpha32"]
        self.add_feature(
            "alpha32",
            f"cs_scale((ts_sum(close, {p['n_sum_close']}) / {p['n_sum_close']} - close)) + ({p['k_scale_corr']} * cs_scale(ts_corr(vwap, ts_delay(close, {p['n_delay_close']}), {p['n_corr']})))",
        )

        self.add_feature("alpha33", "cs_rank((-1) * (open / close * -1 + 1))")

        p = ap["alpha34"]
        self.add_feature(
            "alpha34",
            f"cs_rank((cs_rank(ts_std({r}, {p['n_std_short']}) / ts_std({r}, {p['n_std_long']})) * -1 + 1) + (cs_rank(ts_delta(close, {p['n_delta_close']})) * -1 + 1))",
        )

        p = ap["alpha35"]
        self.add_feature(
            "alpha35",
            f"(ts_rank(volume, {p['n_rank_vol']}) * (ts_rank((close + high - low), {p['n_rank_hlc']}) * -1 + 1)) * (ts_rank({r}, {p['n_rank_ret']}) * -1 + 1)",
        )

        p = ap["alpha36"]
        self.add_feature(
            "alpha36",
            f"(((({p['w1']} * cs_rank(ts_corr((close - open), ts_delay(volume, 1), {p['n_corr1']}))) + ({p['w2']} * cs_rank((open - close)))) + ({p['w3']} * cs_rank(ts_rank(ts_delay((-1) * {r}, {p['n_delay_ret']}), {p['n_rank_ret']})))) + cs_rank(abs(ts_corr(vwap, ts_mean(volume, {p['n_vol_mean']}), {p['n_corr_vw']})))) + ({p['w4']} * cs_rank(((ts_sum(close, {p['n_sum_close']}) / {p['n_sum_close']} - open) * (close - open))))",
        )

        p = ap["alpha37"]
        self.add_feature(
            "alpha37",
            f"cs_rank(ts_corr(ts_delay((open - close), {p['n_delay_oc']}), close, {p['n_corr']})) + cs_rank((open - close))",
        )

        p = ap["alpha38"]
        self.add_feature(
            "alpha38",
            f"((-1) * cs_rank(ts_rank(close, {p['n_rank_close']}))) * cs_rank((close / open))",
        )

        p = ap["alpha39"]
        self.add_feature(
            "alpha39",
            f"((-1) * cs_rank((ts_delta(close, {p['n_delta']}) * (cs_rank(ts_decay_linear((volume / ts_mean(volume, {p['n_vol_mean']})), {p['n_decay']})) * -1 + 1)))) * (cs_rank(ts_sum({r}, {p['n_sum_ret']})) + 1)",
        )

        p = ap["alpha40"]
        self.add_feature(
            "alpha40",
            f"((-1) * cs_rank(ts_std(high, {p['n_std_high']}))) * ts_corr(high, volume, {p['n_corr']})",
        )

        p = ap["alpha41"]
        self.add_feature("alpha41", f"pow1((high * low), {p['pow_exp']}) - vwap")

        self.add_feature("alpha42", "cs_rank((vwap - close)) / cs_rank((vwap + close))")

        p = ap["alpha43"]
        self.add_feature(
            "alpha43",
            f"ts_rank((volume / ts_mean(volume, {p['n_vol_mean']})), {p['n_rank_vol']}) * ts_rank((-1) * ts_delta(close, {p['n_delta_close']}), {p['n_rank_delta']})",
        )

        p = ap["alpha44"]
        self.add_feature("alpha44", f"(-1) * ts_corr(high, cs_rank(volume), {p['n_corr']})")

        p = ap["alpha45"]
        self.add_feature(
            "alpha45",
            f"(-1) * cs_rank(ts_sum(ts_delay(close, {p['n_delay_close']}), {p['n_sum_delay']}) / {p['n_sum_delay']}) * ts_corr(close, volume, {p['n_corr_cv']}) * cs_rank(ts_corr(ts_sum(close, {p['n_sum_a']}), ts_sum(close, {p['n_sum_b']}), {p['n_corr_ss']}))",
        )

        p = ap["alpha46"]
        self.add_feature(
            "alpha46",
            f"quesval({p['q_outer']}, ((ts_delay(close, {p['n_delay_long']}) - ts_delay(close, {p['n_delay_mid']})) / {p['n_div']} - (ts_delay(close, {p['n_delay_mid']}) - close) / {p['n_div']}), {p['v_else_outer']}, quesval({p['q_inner']}, ((ts_delay(close, {p['n_delay_long']}) - ts_delay(close, {p['n_delay_mid']})) / {p['n_div']} - (ts_delay(close, {p['n_delay_mid']}) - close) / {p['n_div']}), (-1) * (close - ts_delay(close, {p['n_delay_ret']})), {p['v_else_inner']}))",
        )

        p = ap["alpha47"]
        self.add_feature(
            "alpha47",
            f"((cs_rank(pow1(close, {p['pow_close']})) * volume / ts_mean(volume, {p['n_vol_mean']})) * (high * cs_rank(high - close)) / (ts_sum(high, {p['n_sum_high']}) / {p['n_sum_high']})) - cs_rank(vwap - ts_delay(vwap, {p['n_delay_vwap']}))",
        )

        # Alpha48 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha48", "(ts_corr(ts_delta(close, 1), ts_delta(ts_delay(close, 1), 1), 250) * ts_delta(close, 1)) / close / ts_sum(pow1((ts_delta(close, 1) / ts_delay(close, 1)), 2), 250)")

        p = ap["alpha49"]
        self.add_feature(
            "alpha49",
            f"quesval({p['q_thresh']}, ((ts_delay(close, {p['n_delay_long']}) - ts_delay(close, {p['n_delay_mid']})) / {p['n_div']} - (ts_delay(close, {p['n_delay_mid']}) - close) / {p['n_div']}), (-1) * (close - ts_delay(close, {p['n_delay_ret']})), {p['v_else']})",
        )

        p = ap["alpha50"]
        self.add_feature(
            "alpha50",
            f"(-1) * ts_max(cs_rank(ts_corr(cs_rank(volume), cs_rank(vwap), {p['n_corr']})), {p['n_ts_max']})",
        )

        p = ap["alpha51"]
        self.add_feature(
            "alpha51",
            f"quesval({p['q_thresh']}, ((ts_delay(close, {p['n_delay_long']}) - ts_delay(close, {p['n_delay_mid']})) / {p['n_div']} - (ts_delay(close, {p['n_delay_mid']}) - close) / {p['n_div']}), (-1) * (close - ts_delay(close, {p['n_delay_ret']})), {p['v_else']})",
        )

        p = ap["alpha52"]
        self.add_feature(
            "alpha52",
            f"(((-1) * ts_min(low, {p['n_min_low']})) + ts_delay(ts_min(low, {p['n_min_low']}), {p['n_delay_min']})) * cs_rank((ts_sum({r}, {p['n_sum_ret_long']}) - ts_sum({r}, {p['n_sum_ret_short']})) / {p['n_div_ret']}) * ts_rank(volume, {p['n_rank_vol']})",
        )

        p = ap["alpha53"]
        self.add_feature(
            "alpha53",
            f"(-1) * ts_delta(((close - low) - (high - close)) / (close - low), {p['n_delta']})",
        )

        p = ap["alpha54"]
        self.add_feature(
            "alpha54",
            f"((-1) * ((low - close) * pow1(open, {p['pow_open']}))) / ((low - high) * pow1(close, {p['pow_close']}))",
        )

        p = ap["alpha55"]
        self.add_feature(
            "alpha55",
            f"(-1) * ts_corr(cs_rank((close - ts_min(low, {p['n_extreme']})) / (ts_max(high, {p['n_extreme']}) - ts_min(low, {p['n_extreme']}))), cs_rank(volume), {p['n_corr']})",
        )

        # Alpha56 (missing `cap` field, cannot be implemented)
        # original formula: (0 - (1 * (rank((sum(returns, 10) / sum(sum(returns, 2), 3))) * rank((returns * cap)))))

        p = ap["alpha57"]
        self.add_feature(
            "alpha57",
            f"-1 * ((close - vwap) / ts_decay_linear(cs_rank(ts_argmax(close, {p['n_argmax']})), {p['n_decay']}))",
        )

        # Alpha58 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha58", "(-1) * ts_rank(ts_decay_linear(ts_corr(vwap, volume, 4), 8), 6)")

        # Alpha59 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha59", "(-1) * ts_rank(ts_decay_linear(ts_corr(((vwap * 0.728317) + (vwap * (1 - 0.728317))), volume, 4), 16), 8)")

        p = ap["alpha60"]
        self.add_feature(
            "alpha60",
            f"- 1 * (({p['k_scale']} * cs_scale(cs_rank((((close - low) - (high - close)) / (high - low)) * volume))) - cs_scale(cs_rank(ts_argmax(close, {p['n_argmax']}))))",
        )

        p = ap["alpha61"]
        self.add_feature(
            "alpha61",
            f"quesval2(cs_rank(vwap - ts_min(vwap, {p['n_min_vwap']})), cs_rank(ts_corr(vwap, ts_mean(volume, {p['n_vol_mean']}), {p['n_corr']})), {p['v1']}, {p['v0']})",
        )

        p = ap["alpha62"]
        self.add_feature(
            "alpha62",
            f"(cs_rank(ts_corr(vwap, ts_sum(ts_mean(volume, {p['n_vol_mean']}), {p['n_sum_mean_vol']}), {p['n_corr']})) < cs_rank((cs_rank(open) + cs_rank(open)) < (cs_rank((high + low) / 2) + cs_rank(high)))) * -1",
        )

        # Alpha63 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha63", "(cs_rank(ts_decay_linear(ts_delta(close, 2), 8)) - cs_rank(ts_decay_linear(ts_corr(vwap * 0.318108 + open * 0.681892, ts_sum(ts_mean(volume, 180), 37), 14), 12))) * -1")

        p = ap["alpha64"]
        self.add_feature(
            "alpha64",
            f"(cs_rank(ts_corr(ts_sum(((open * {p['w_open']}) + (low * (1 - {p['w_open']}))), {p['n_sum_oh']}), ts_sum(ts_mean(volume, {p['n_vol_mean']}), {p['n_sum_vm']}), {p['n_corr']})) < cs_rank(ts_delta((((high + low) / 2 * {p['w_hl']}) + (vwap * (1 - {p['w_hl']}))), {p['n_delta']}))) * -1",
        )

        p = ap["alpha65"]
        self.add_feature(
            "alpha65",
            f"(cs_rank(ts_corr(((open * {p['w_open']}) + (vwap * (1 - {p['w_open']}))), ts_sum(ts_mean(volume, {p['n_vol_mean']}), {p['n_sum_vm']}), {p['n_corr']})) < cs_rank(open - ts_min(open, {p['n_min_open']}))) * -1",
        )

        p = ap["alpha66"]
        self.add_feature(
            "alpha66",
            f"(cs_rank(ts_decay_linear(ts_delta(vwap, {p['n_delta_vwap']}), {p['n_decay_a']})) + ts_rank(ts_decay_linear((((low * {p['w_low_a']}) + (low * (1 - {p['w_low_a']}))) - vwap) / (open - ((high + low) / 2)), {p['n_decay_b']}), {p['n_rank_b']})) * -1",
        )

        # Alpha67 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha67", "pow2(cs_rank(high - ts_min(high, 2)), cs_rank(ts_corr(vwap, ts_mean(volume, 20), 6))) * -1")

        p = ap["alpha68"]
        self.add_feature(
            "alpha68",
            f"(ts_rank(ts_corr(cs_rank(high), cs_rank(ts_mean(volume, {p['n_vol_mean']})), {p['n_corr_inner']}), {p['n_rank_outer']}) < cs_rank(ts_delta((close * {p['w_close']} + low * (1 - {p['w_close']})), {p['n_delta']}))) * -1",
        )

        # Alpha69 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha69", "pow2(cs_rank(ts_max(ts_delta(vwap, 3), 5)), ts_rank(ts_corr(close * 0.490655 + vwap * 0.509345, ts_mean(volume, 20), 5), 9)) * -1")

        # Alpha70 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha70", "pow2(cs_rank(ts_delta(vwap, 1)), ts_rank(ts_corr(close, ts_mean(volume, 50), 18), 18)) * -1")

        p = ap["alpha71"]
        self.add_feature(
            "alpha71",
            f"ts_greater(ts_rank(ts_decay_linear(ts_corr(ts_rank(close, {p['n_rank_close']}), ts_rank(ts_mean(volume, {p['n_vol_mean']}), {p['n_mean_sum']}), {p['n_corr']}), {p['n_decay_first']}), {p['n_rank_first']}), ts_rank(ts_decay_linear(pow1(cs_rank((low + open) - (vwap + vwap)), {p['pow_inner']}), {p['n_decay_second']}), {p['n_rank_second']}))",
        )

        p = ap["alpha72"]
        self.add_feature(
            "alpha72",
            f"cs_rank(ts_decay_linear(ts_corr((high + low) / 2, ts_mean(volume, {p['n_vol_mean']}), {p['n_corr_a']}), {p['n_decay_a']})) / cs_rank(ts_decay_linear(ts_corr(ts_rank(vwap, {p['n_rank_vwap']}), ts_rank(volume, {p['n_rank_vol']}), {p['n_corr_b']}), {p['n_decay_b']}))",
        )

        p = ap["alpha73"]
        self.add_feature(
            "alpha73",
            f"ts_greater(cs_rank(ts_decay_linear(ts_delta(vwap, {p['n_delta_vwap']}), {p['n_decay_a']})), ts_rank(ts_decay_linear((ts_delta(open * {p['w_open']} + low * (1 - {p['w_open']}), {p['n_delta_combo']}) / (open * {p['w_open']} + low * (1 - {p['w_open']}))) * -1, {p['n_decay_b']}), {p['n_rank_b']})) * -1",
        )

        p = ap["alpha74"]
        self.add_feature(
            "alpha74",
            f"quesval2(cs_rank(ts_corr(close, ts_sum(ts_mean(volume, {p['n_vol_mean']}), {p['n_sum_vm']}), {p['n_corr_a']})), cs_rank(ts_corr(cs_rank(high * {p['w_high']} + vwap * (1 - {p['w_high']})), cs_rank(volume), {p['n_corr_b']})), {p['v1']}, {p['v0']}) * -1",
        )

        p = ap["alpha75"]
        self.add_feature(
            "alpha75",
            f"quesval2(cs_rank(ts_corr(vwap, volume, {p['n_corr_a']})), cs_rank(ts_corr(cs_rank(low), cs_rank(ts_mean(volume, {p['n_vol_mean']})), {p['n_corr_b']})), {p['v1']}, {p['v0']})",
        )

        # Alpha76 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha76", "ts_greater(cs_rank(ts_decay_linear(ts_delta(vwap, 1), 12)), ts_rank(ts_decay_linear(ts_rank(ts_corr(low, ts_mean(volume, 81), 8), 20), 17), 19)) * -1")

        p = ap["alpha77"]
        self.add_feature(
            "alpha77",
            f"ts_less(cs_rank(ts_decay_linear((((high + low) / 2 + high) - (vwap + high)), {p['n_decay_a']})), cs_rank(ts_decay_linear(ts_corr((high + low) / 2, ts_mean(volume, {p['n_vol_mean']}), {p['n_corr']}), {p['n_decay_b']})))",
        )

        p = ap["alpha78"]
        self.add_feature(
            "alpha78",
            f"pow2(cs_rank(ts_corr(ts_sum((low * {p['w_low']}) + (vwap * (1 - {p['w_low']})), {p['n_sum_a']}), ts_sum(ts_mean(volume, {p['n_vol_mean']}), {p['n_sum_b']}), {p['n_corr_a']})), cs_rank(ts_corr(cs_rank(vwap), cs_rank(volume), {p['n_corr_b']})))",
        )

        # Alpha79 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha79", "quesval2(cs_rank(ts_delta(close * 0.60733 + open * 0.39267, 1)), cs_rank(ts_corr(ts_rank(vwap, 4), ts_rank(ts_mean(volume, 150), 9), 15)), 1, 0)")

        # Alpha80 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha80", "pow2(cs_rank(sign(ts_delta(open * 0.868128 + high * 0.131872, 4))), ts_rank(ts_corr(high, ts_mean(volume, 10), 5), 6)) * -1")

        p = ap["alpha81"]
        self.add_feature(
            "alpha81",
            f"quesval2(cs_rank(log(ts_product(cs_rank(pow1(cs_rank(ts_corr(vwap, ts_sum(ts_mean(volume, {p['n_vol_mean']}), {p['n_sum_vm']}), {p['n_corr_a']})), {p['pow_rank']})), {p['n_product']}))), cs_rank(ts_corr(cs_rank(vwap), cs_rank(volume), {p['n_corr_b']})), {p['v1']}, {p['v0']}) * -1",
        )

        # Alpha82 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha82", "ts_less(cs_rank(ts_decay_linear(ts_delta(open, 1), 15)), ts_rank(ts_decay_linear(ts_corr(volume, open, 17), 7), 13)) * -1")

        p = ap["alpha83"]
        self.add_feature(
            "alpha83",
            f"(cs_rank(ts_delay((high - low) / (ts_sum(close, {p['n_sum_close']}) / {p['n_sum_close']}), {p['n_delay']})) * cs_rank(cs_rank(volume))) / (((high - low) / (ts_sum(close, {p['n_sum_close']}) / {p['n_sum_close']})) / (vwap - close))",
        )

        p = ap["alpha84"]
        self.add_feature(
            "alpha84",
            f"pow2(ts_rank(vwap - ts_max(vwap, {p['n_max_vwap']}), {p['n_rank']}), ts_delta(close, {p['n_delta_close']}))",
        )

        p = ap["alpha85"]
        self.add_feature(
            "alpha85",
            f"pow2(cs_rank(ts_corr(high * {p['w_high']} + close * {p['w_close']}, ts_mean(volume, {p['n_vol_mean']}), {p['n_corr_a']})), cs_rank(ts_corr(ts_rank((high + low) / 2, {p['n_rank_hl']}), ts_rank(volume, {p['n_rank_vol']}), {p['n_corr_b']})))",
        )

        p = ap["alpha86"]
        self.add_feature(
            "alpha86",
            f"quesval2(ts_rank(ts_corr(close, ts_sum(ts_mean(volume, {p['n_vol_mean']}), {p['n_sum_vm']}), {p['n_corr']}), {p['n_rank']}), cs_rank((open + close) - (vwap + open)), {p['v1']}, {p['v0']}) * -1",
        )

        # Alpha87 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha87", "ts_greater(cs_rank(ts_decay_linear(ts_delta(close * 0.369701 + vwap * 0.630299, 2), 3)), ts_rank(ts_decay_linear(abs(ts_corr(ts_mean(volume, 81), close, 13)), 5), 14)) * -1")

        p = ap["alpha88"]
        self.add_feature(
            "alpha88",
            f"ts_less(cs_rank(ts_decay_linear((cs_rank(open) + cs_rank(low)) - (cs_rank(high) + cs_rank(close)), {p['n_decay_a']})), ts_rank(ts_decay_linear(ts_corr(ts_rank(close, {p['n_rank_close']}), ts_rank(ts_mean(volume, {p['n_vol_mean']}), {p['n_mean_sum']}), {p['n_corr']}), {p['n_decay_b']}), {p['n_rank_b']}))",
        )

        # Alpha89 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha89", "(ts_rank(ts_decay_linear(ts_corr(low, ts_mean(volume, 10), 7), 6), 4) - ts_rank(ts_decay_linear(ts_delta(vwap, 3), 10), 15))")

        # Alpha90 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha90", "pow2(cs_rank(close - ts_max(close, 5)), ts_rank(ts_corr(ts_mean(volume, 40), low, 5), 3)) * -1")

        # Alpha91 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha91", "(ts_rank(ts_decay_linear(ts_decay_linear(ts_corr(close, volume, 10), 16), 4), 5) - cs_rank(ts_decay_linear(ts_corr(vwap, ts_mean(volume, 30), 4), 3))) * -1")

        p = ap["alpha92"]
        self.add_feature(
            "alpha92",
            f"ts_less(ts_rank(ts_decay_linear(quesval2(((high + low) / 2 + close), (low + open), {p['v_a']}, {p['v_b']}), {p['n_decay_a']}), {p['n_rank_a']}), ts_rank(ts_decay_linear(ts_corr(cs_rank(low), cs_rank(ts_mean(volume, {p['n_vol_mean']})), {p['n_corr']}), {p['n_decay_b']}), {p['n_rank_b']}))",
        )

        # Alpha93 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha93", "ts_rank(ts_decay_linear(ts_corr(vwap, ts_mean(volume, 81), 17), 20), 8) / cs_rank(ts_decay_linear(ts_delta(close * 0.524434 + vwap * 0.475566, 3), 16))")

        p = ap["alpha94"]
        self.add_feature(
            "alpha94",
            f"pow2(cs_rank(vwap - ts_min(vwap, {p['n_min_vwap']})), ts_rank(ts_corr(ts_rank(vwap, {p['n_rank_vwap']}), ts_rank(ts_mean(volume, {p['n_vol_mean']}), {p['n_rank_vm']}), {p['n_corr']}), {p['n_rank_last']})) * -1",
        )

        p = ap["alpha95"]
        self.add_feature(
            "alpha95",
            f"quesval2(cs_rank(open - ts_min(open, {p['n_min_open']})), ts_rank(pow1(cs_rank(ts_corr(ts_sum((high + low) / 2, {p['n_sum_hl']}), ts_sum(ts_mean(volume, {p['n_vol_mean']}), {p['n_sum_vm']}), {p['n_corr']})), {p['pow_rank']}), {p['n_rank']}), {p['v1']}, {p['v0']})",
        )

        p = ap["alpha96"]
        self.add_feature(
            "alpha96",
            f"ts_greater(ts_rank(ts_decay_linear(ts_corr(cs_rank(vwap), cs_rank(volume), {p['n_corr_vw']}), {p['n_decay_a']}), {p['n_rank_a']}), ts_rank(ts_decay_linear(ts_argmax(ts_corr(ts_rank(close, {p['n_rank_close']}), ts_rank(ts_mean(volume, {p['n_vol_mean']}), {p['n_rank_vm']}), {p['n_corr_cc']}), {p['n_argmax']}), {p['n_decay_b']}), {p['n_rank_b']})) * -1",
        )

        # Alpha97 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha97", "(cs_rank(ts_decay_linear(ts_delta(low * 0.721001 + vwap * 0.278999, 3), 20)) - ts_rank(ts_decay_linear(ts_rank(ts_corr(ts_rank(low, 8), ts_rank(ts_mean(volume, 60), 17), 5), 19), 16), 7)) * -1")

        p = ap["alpha98"]
        self.add_feature(
            "alpha98",
            f"cs_rank(ts_decay_linear(ts_corr(vwap, ts_sum(ts_mean(volume, {p['n_vol_mean_a']}), {p['n_sum_vm_a']}), {p['n_corr_a']}), {p['n_decay_a']})) - cs_rank(ts_decay_linear(ts_rank(ts_argmin(ts_corr(cs_rank(open), cs_rank(ts_mean(volume, {p['n_vol_mean_b']})), {p['n_corr_open']}), {p['n_argmin_n']}), {p['n_rank_inner']}), {p['n_decay_b']}))",
        )

        p = ap["alpha99"]
        self.add_feature(
            "alpha99",
            f"quesval2(cs_rank(ts_corr(ts_sum((high + low) / 2, {p['n_sum_hl']}), ts_sum(ts_mean(volume, {p['n_vol_mean']}), {p['n_sum_vm']}), {p['n_corr_a']})), cs_rank(ts_corr(low, volume, {p['n_corr_lv']})), {p['v1']}, {p['v0']}) * -1",
        )

        # Alpha100 (contains `IndNeutralize`, currently not implemented)
        # self.add_feature("alpha100", "-1 * ((1.5 * cs_scale(cs_rank(((close - low) - (high - close)) / (high - low) * volume))) - cs_scale(ts_corr(close, cs_rank(ts_mean(volume, 20)), 5) - cs_rank(ts_argmin(close, 30)))) * (volume / ts_mean(volume, 20))")

        p = ap["alpha101"]
        self.add_feature("alpha101", f"((close - open) / ((high - low) + {p['eps_hl']}))")

        # Set label
        self.set_label("ts_delay(close, -3) / ts_delay(close, -1) - 1")
