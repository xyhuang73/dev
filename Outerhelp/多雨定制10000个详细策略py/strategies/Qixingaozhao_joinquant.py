# -*- coding: utf-8 -*-
"""
七星高照 ETF 轮动超级增强 - 聚宽 JoinQuant 版
来源: 策略_cleaned.txt (聚宽段，第 1~884 行)

使用说明:
1. 登录 joinquant.com -> 研究 -> 新建策略 -> 粘贴本文件全部内容
2. 回测设置建议: 起始资金 100 万，基准沪深300，频率按日调度即可
3. 策略使用 run_daily + handle_data(分钟回撤)，聚宽会自动按调度执行
4. 买卖时间: 14:51 卖出 / 14:52 买入

依赖: 聚宽内置 jqdata / numpy / pandas，无需额外安装
"""

import numpy as np
import math
import datetime
import pandas as pd
import time
from functools import wraps
from jqdata import *

def time_monitor(func_name=None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            start_real = datetime.datetime.now()

            log.info(f"⏱️ [{func_name or func.__name__}] 开始执行 - 真实时间: {start_real.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")

            try:
                result = func(*args, **kwargs)
                end_time = time.time()
                end_real = datetime.datetime.now()
                elapsed = end_time - start_time

                log.info(f"✅ [{func_name or func.__name__}] 执行完成 - 耗时: {elapsed*1000:.2f}ms | 真实时间: {end_real.strftime('%H:%M:%S')}")

                if elapsed > 0.95:
                    log.warning(f"⚠️ [{func_name or func.__name__}] 执行耗时过长: {elapsed*1000:.2f}ms")

                return result
            except Exception as e:
                end_time = time.time()
                elapsed = end_time - start_time
                log.error(f"❌ [{func_name or func.__name__}] 执行异常 - 耗时: {elapsed*1000:.2f}ms | 错误: {str(e)[:100]}")
                raise
        return wrapper
    return decorator

def get_real_time():
    return datetime.datetime.now().strftime('%H:%M:%S')

def initialize(context):
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_slippage(PriceRelatedSlippage(0.0001), type="fund")
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0005,
            close_commission=0.0005,
            close_today_commission=0,
            min_commission=5,
        ),
        type="fund",
    )
    set_benchmark("000300.XSHG")

    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'debug')
    log.info("🚀 ========== 策略初始化开始 ==========")

    g.etf_pool_bak = [
        "518880.XSHG",
        "159985.XSHE",
        "501018.XSHG",
        "161226.XSHE",
        "513100.XSHG",
        "159915.XSHE",
        "511220.XSHG",
    ]

    g.overseas_etf_pool = [
        "513100.XSHG",
        "513290.XSHG",
        "513500.XSHG",
        "159529.XSHE",
        "513400.XSHG",
        "513520.XSHG",
        "513030.XSHG",
        "513080.XSHG",
        "513310.XSHG",
        "513730.XSHG",
        "159792.XSHE",
        "513130.XSHG",
        "513050.XSHG",
        "159920.XSHE",
        "513690.XSHG",
        "511380.XSHG",
        "511010.XSHG",
        "511220.XSHG",
    ]

    g.commodity_etf_pool = [
        "518880.XSHG",
        "159980.XSHE",
        "159985.XSHE",
        "501018.XSHG",
        '161226.XSHE',
        "159981.XSHE",
        "512400.XSHG",
    ]

    g.domestic_etf_pool = [
        "510300.XSHG",
        "510500.XSHG",
        "510050.XSHG",
        "510210.XSHG",
        "159915.XSHE",
        "588080.XSHG",
        "512100.XSHG",
        "563360.XSHG",
        "563300.XSHG",
        "512890.XSHG",
        "159967.XSHE",
        "588020.XSHG",
        "512040.XSHG",
        "159201.XSHE",
        "515790.XSHG",
        "563230.XSHG",
        "515880.XSHG",
        "512660.XSHG",
        "561380.XSHG",
        "159667.XSHE",
        "159559.XSHE",
        "159819.XSHE",
        "159381.XSHE",
        "159732.XSHE",
        "159995.XSHE",
        "512220.XSHG",
    ]

    g.etf_pool = g.overseas_etf_pool + g.commodity_etf_pool + g.domestic_etf_pool

    g.lookback_days = 25
    g.holdings_num = 1
    g.defensive_etf = '511010.XSHG'
    g.min_money = 5000

    g.enable_profit_protection = True
    g.profit_protection_lookback = 1
    g.profit_protection_threshold = 0.05

    g.profit_protection_check_times = ['11:00']


    g.loss = 0.97

    g.min_score_threshold = 0
    g.max_score_threshold = 100.0

    g.enable_volume_check = True
    g.volume_lookback = 5
    g.volume_threshold = 3.72
    g.volume_return_limit = 1

    g.use_short_momentum_filter = True
    g.short_lookback_days = 10
    g.short_momentum_threshold = 0.0

    g.enable_premium_filter = True
    g.premium_threshold = 0.20

    g.intraday_drawdown_threshold = 0.02

    g.enable_regime_switch = True
    g.weak_period_ma_lookback = 10
    g.weak_period_max_days = 20
    g.is_a_share_weak = False
    g.weak_period_counter = 0
    g.enable_avoid_a_share = True
    g.enable_intraday_drawdown = True
    g.regime_indexes = {
        '沪深300': '000300.XSHG',
        '深证综指': '399101.XSHE',
        '创业板指': '399006.XSHE',
        '中证A500': '000510.XSHG',
    }

    g.rankings_cache = {'date': None, 'data': None}
    g.target_etfs_cache = {'date': None, 'data': None}
    g.drawdown_selled_today = set()

    g.buy_date = {}
    g.trade_log = {'sell_records': []}

    run_daily(check_positions, time='09:10')
    run_daily(regime_check, time='09:40')
    run_daily(etf_sell_trade, time='14:51')
    run_daily(etf_buy_trade, time='14:52')
    run_daily(daily_summary_report, time='15:05')

    for check_time in g.profit_protection_check_times:
        run_daily(profit_protection_check, time=check_time)
        log.info(f"📅 已注册盈利保护检查时间：{check_time}")

    if g.enable_regime_switch:
        log.info(f"🌍 A股行情判断已启用，走弱期最长{g.weak_period_max_days}日")
        if g.enable_avoid_a_share:
            log.info(f"🔄 走弱期回避A股开关：ON（走弱期自动回避A股ETF）")
        else:
            log.info(f"⚠️ 走弱期回避A股开关：OFF（走弱期仍交易A股ETF）")
        if g.enable_intraday_drawdown:
            log.info(f"🛡️ 分钟级回撤保护开关：ON（走弱期自动启用）")
        else:
            log.info(f"⭕ 分钟级回撤保护开关：OFF（不触发）")
    else:
        log.info("⚠️ A股行情判断未启用")

    log.info(f"📋 策略初始化完成：ETF池{len(g.etf_pool)}只（海外{len(g.overseas_etf_pool)}只+商品{len(g.commodity_etf_pool)}只+A股{len(g.domestic_etf_pool)}只）")
    log.info(f"📈 盈利保护：{'开' if g.enable_profit_protection else '关'}，回撤{g.profit_protection_threshold*100:.0f}%")
    if g.enable_premium_filter:
        log.info(f"💰 溢价率过滤已启用，阈值：{g.premium_threshold*100:.0f}%")
    else:
        log.info("⚠️ 溢价率过滤未启用")

    log.info("🎉 ========== 策略初始化完成 ==========")


def check_positions(context):

    log.info(f"\n{'='*22}🐂🧨🧨🧨🧨🧨{context.current_dt.strftime('%Y-%m-%d')}📌策略运行开始📌一路长红🧨🧨🧨🧨🧨🐂{'='*22}")

    g.drawdown_selled_today = set()
    g.target_etfs_cache = {'date': None, 'data': None}
    g.trade_log['sell_records'] = []
    for sec in context.portfolio.positions:
        pos = context.portfolio.positions[sec]
        if pos.total_amount > 0:
            log.info(f"📊 持仓：{sec} {get_name(sec)} 数量{pos.total_amount} 成本{pos.avg_cost:.3f} 现价{pos.price:.3f}")

def regime_check(context):

    log.info("🌍 ========== 行情判断开始 ==========")

    if not g.enable_regime_switch:
        g.is_a_share_weak = False
        return

    below_count, above_count = 0, 0
    detail = []
    for name, code in g.regime_indexes.items():
        try:
            df = attribute_history(code, g.weak_period_ma_lookback + 1, '1d', ['close'], skip_paused=False)
            if df.empty or len(df) < g.weak_period_ma_lookback:
                continue
            current_price = df['close'].iloc[-1]
            ma_val = df['close'].iloc[-g.weak_period_ma_lookback:].mean()
            if current_price < ma_val:
                below_count += 1
                detail.append(f"{name}↓")
            else:
                above_count += 1
                detail.append(f"{name}↑")
        except Exception as e:
            log.warning(f"⚠️ 指数{name}获取失败: {e}")

    old_state = g.is_a_share_weak

    if not g.is_a_share_weak:
        if below_count >= 3:
            g.is_a_share_weak = True
            g.weak_period_counter = 0
            log.info(f"🔴 进入走弱期 (跌破:{below_count} {detail})")
            if g.enable_avoid_a_share:
                log.info(f"   → 将回避A股ETF，仅交易海外+商品ETF")
            else:
                log.info(f"   → ⚠️ 回避A股开关已关闭，仍交易全市场ETF")
            if g.enable_intraday_drawdown:
                log.info(f"   → 🛡️ 分钟级回撤保护已启用（阈值{g.intraday_drawdown_threshold*100:.0f}%）")
            else:
                log.info(f"   → ⭕ 分钟级回撤保护已被独立开关关闭，不触发")
    else:
        g.weak_period_counter += 1
        if above_count >= 3:
            g.is_a_share_weak = False
            g.weak_period_counter = 0
            log.info(f"🟢 恢复正常期 (站上:{above_count} {detail})")
            if g.enable_avoid_a_share:
                log.info(f"   → 恢复交易A股ETF")
            else:
                log.info(f"   → 回避A股开关关闭，始终交易全市场")
            if g.enable_intraday_drawdown:
                log.info(f"   → 关闭分钟级回撤保护")
            else:
                log.info(f"   → 分钟级回撤保护独立开关已关闭，无变化")
        elif g.weak_period_counter >= g.weak_period_max_days:
            g.is_a_share_weak = False
            g.weak_period_counter = 0
            log.info(f"⏰ 走弱期满{g.weak_period_max_days}日强制退出，恢复正常期")
            if g.enable_avoid_a_share:
                log.info(f"   → 恢复交易A股ETF")
            else:
                log.info(f"   → 回避A股开关关闭，始终交易全市场")
            if g.enable_intraday_drawdown:
                log.info(f"   → 关闭分钟级回撤保护")
            else:
                log.info(f"   → 分钟级回撤保护独立开关已关闭，无变化")

    if old_state != g.is_a_share_weak:
        g.rankings_cache = {'date': None, 'data': None}
        g.target_etfs_cache = {'date': None, 'data': None}

    if g.enable_regime_switch:
        current_status = '🔴走弱期' if g.is_a_share_weak else '🟢正常期'
        avoid_status = '(回避A股)' if (g.is_a_share_weak and g.enable_avoid_a_share) else ('(不回避A股)' if g.is_a_share_weak else '')
        drawdown_status = '🛡️启用' if (g.is_a_share_weak and g.enable_intraday_drawdown) else ('⭕关闭' if (g.is_a_share_weak and not g.enable_intraday_drawdown) else '⭕关闭')
        log.info(f"📊 当前状态：{current_status}{avoid_status} 计数:{g.weak_period_counter}/{g.weak_period_max_days}")
        log.info(f"📊 分钟级回撤保护：{drawdown_status}（阈值{g.intraday_drawdown_threshold*100:.0f}%）")
    log.info("🌍 ========== 行情判断完成 ==========")


def is_intraday_drawdown_enabled():
    if not g.enable_intraday_drawdown:
        return False
    if not g.enable_regime_switch:
        return False
    return g.is_a_share_weak


def get_active_etf_pool():
    if not g.enable_avoid_a_share:
        log.info(f"📊 【强制】A股回避开关已关闭，使用完整池({len(g.etf_pool)}只)")
        return g.etf_pool

    if g.is_a_share_weak:
        active_pool = g.overseas_etf_pool + g.commodity_etf_pool
        log.info(f"📊 【走弱期】使用海外+商品池({len(active_pool)}只)")
        return active_pool
    else:
        log.info(f"📊 【正常期】使用完整池({len(g.etf_pool)}只)")
        return g.etf_pool


def handle_data(context, data):
    if not is_intraday_drawdown_enabled():
        return

    current_time = context.current_dt.strftime('%H:%M')
    if current_time < '09:46':
        return

    intraday_drawdown_check(context)


def intraday_drawdown_check(context):
    for sec in list(context.portfolio.positions.keys()):
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        pos = context.portfolio.positions[sec]
        if pos.total_amount == 0:
            continue
        if g.buy_date.get(sec) == context.current_dt.date():
            continue

        try:
            df = get_price(sec, start_date=context.current_dt.date(), end_date=context.current_dt,
                           frequency='1m', fields=['high', 'close'], skip_paused=True, fq='pre')
            if df is None or df.empty:
                continue
            day_high = df['high'].max()
            current_price = df['close'].iloc[-1]
            if day_high <= 0:
                continue
            drawdown = (day_high - current_price) / day_high
            if drawdown >= g.intraday_drawdown_threshold:
                log.info(f"⚠️ 分钟级回撤触发：{sec} {get_name(sec)} 回撤{drawdown*100:.2f}%")
                if smart_order_target_value(sec, 0, context):
                    log.info(f"🧨 分钟级回撤卖出：{sec} {get_name(sec)}")
                    g.drawdown_selled_today.add(sec)
        except Exception as e:
            log.debug(f"分钟级回撤检查异常 {sec}: {e}")


@time_monitor(func_name="盈利保护检查")
def profit_protection_check(context):
    if not g.enable_profit_protection:
        log.debug("盈利保护模块已关闭，跳过检查")
        return

    log.info("🛡️ ========== 盈利保护检查开始 ==========")
    for sec in list(context.portfolio.positions.keys()):
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        pos = context.portfolio.positions[sec]
        if pos.total_amount > 0:
            if check_profit_protection(sec, context):
                if smart_order_target_value(sec, 0, context):
                    log.info(f"🛡️ 盈利保护卖出：{sec} {get_name(sec)}")
                    g.drawdown_selled_today.add(sec)
    log.info("🛡️ ========== 盈利保护检查完成 ==========")


def check_profit_protection(security, context, lookback=None, threshold=None):
    if not g.enable_profit_protection:
        return False

    lookback = lookback or g.profit_protection_lookback
    threshold = threshold or g.profit_protection_threshold

    hist = attribute_history(security, lookback, '1d', ['high'])
    if hist.empty or len(hist) < lookback:
        return False

    max_high = hist['high'].max()
    current_price = get_current_data()[security].last_price

    if current_price <= max_high * (1 - threshold):
        log.info(f"🔻 盈利保护触发 {security} 回撤{(1-current_price/max_high)*100:.2f}% > {threshold*100:.0f}%")
        return True
    return False


def get_premium_rate(code, date):
    price_data = get_price(code, start_date=date, end_date=date, frequency='daily', fields=['close'])
    if price_data.empty:
        log.debug(f"⚠️ {date} {code} 无交易价格数据")
        return None, None, None
    price = price_data['close'].iloc[0]

    net_value = None
    use_date = date
    max_search_days = 3
    found = False

    for _ in range(max_search_days):
        net_data = get_extras('unit_net_value', code, start_date=use_date, end_date=use_date, df=True)
        if not net_data.empty and not pd.isna(net_data[code].iloc[0]):
            net_value = net_data[code].iloc[0]
            found = True
            break

        try:
            q = query(finance.FUND_NET_VALUE).filter(
                finance.FUND_NET_VALUE.code == code,
                finance.FUND_NET_VALUE.day == use_date
            )
            net_df = finance.run_query(q)
            if not net_df.empty:
                net_value = net_df['net_value'].iloc[0]
                found = True
                break
        except:
            pass

        trade_days = get_trade_days(end_date=use_date, count=2)
        if len(trade_days) < 2:
            break
        use_date = trade_days[0]

    if not found or net_value is None:
        log.debug(f"⚠️ {code} 在{date}无净值数据")
        return None, None, None

    if use_date != date:
        log.debug(f"🔍 {code} 使用最近净值日期 {use_date}")

    premium_rate = (price - net_value) / net_value
    return premium_rate, price, net_value


def get_cached_rankings(context):
    today = context.current_dt.date()
    if g.rankings_cache['date'] != today:
        log.info("📊 重新计算ETF排名...")
        ranked = get_ranked_etfs(context)
        g.rankings_cache = {'date': today, 'data': ranked}
    else:
        log.debug("🔍 使用缓存的ETF排名")
    return g.rankings_cache['data']


def get_ranked_etfs(context):
    active_pool = get_active_etf_pool()

    etf_metrics = []
    for etf in active_pool:
        if get_current_data()[etf].paused:
            log.debug(f"❌ {etf} {get_name(etf)} 停牌，跳过")
            continue

        metrics = calculate_momentum_metrics(context, etf)
        if metrics is not None:
            if g.min_score_threshold < metrics['score'] < g.max_score_threshold:
                etf_metrics.append(metrics)
            else:
                log.debug(f"❌ {etf} {metrics['etf_name']} 得分{metrics['score']:.2f}超出阈值，过滤")

    etf_metrics.sort(key=lambda x: x['score'], reverse=True)
    return etf_metrics


def calculate_momentum_metrics(context, etf):
    try:
        name = get_name(etf)
        lookback = max(g.lookback_days, g.short_lookback_days) + 20
        prices = attribute_history(etf, lookback, '1d', ['close', 'high'])
        if len(prices) < g.lookback_days:
            log.debug(f"🚫 {etf} {name} 历史数据不足{len(prices)}天，跳过")
            return None

        current_price = get_current_data()[etf].last_price
        price_series = np.append(prices["close"].values, current_price)

        if check_profit_protection(etf, context):
            log.info(f"🚫 {etf} {name} 触发盈利保护，从排名中排除")
            return None

        if g.enable_premium_filter:
            prev_date = get_trade_days(end_date=context.current_dt.date(), count=2)[0]
            premium, _, _ = get_premium_rate(etf, prev_date)
            if premium is not None:
                if premium > g.premium_threshold:
                    log.info(f"🚫 {etf} {name} 溢价率{premium*100:.2f}% > 阈值，排除")
                    return None
            else:
                log.debug(f"🚫 {etf} {name} 无法获取{prev_date}的净值，排除")
                return None

        if g.enable_volume_check:
            vol_ratio = get_volume_ratio(context, etf)
            if vol_ratio is not None:
                annualized = get_annualized_returns(price_series, g.lookback_days)
                if annualized > g.volume_return_limit:
                    log.info(f"📉 {etf} {name} 成交量放量，过滤")
                    return None

        if len(price_series) >= g.short_lookback_days + 1:
            short_return = price_series[-1] / price_series[-(g.short_lookback_days + 1)] - 1
            short_annualized = (1 + short_return) ** (250 / g.short_lookback_days) - 1
        else:
            short_annualized = 0

        if g.use_short_momentum_filter and short_annualized < g.short_momentum_threshold:
            log.debug(f"❌ {etf} {name} 短期动量不足，过滤")
            return None

        recent = price_series[-(g.lookback_days + 1):]
        y = np.log(recent)
        x = np.arange(len(y))
        weights = np.linspace(1, 2, len(y))
        slope, intercept = np.polyfit(x, y, 1, w=weights)
        annualized_returns = math.exp(slope * 250) - 1

        ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
        ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0

        score = annualized_returns * r_squared

        if len(price_series) >= 4:
            day1 = price_series[-1] / price_series[-2]
            day2 = price_series[-2] / price_series[-3]
            day3 = price_series[-3] / price_series[-4]
            if min(day1, day2, day3) < g.loss:
                log.info(f"⚠️ {etf} {name} 近3日有单日跌幅超限，排除")
                return None

        return {
            'etf': etf,
            'etf_name': name,
            'annualized_returns': annualized_returns,
            'r_squared': r_squared,
            'score': score,
            'current_price': current_price,
            'short_annualized': short_annualized,
        }

    except Exception as e:
        log.warning(f"计算{etf} {get_name(etf)}时出错: {e}")
        return None


def get_annualized_returns(price_series, lookback_days):
    recent = price_series[-(lookback_days + 1):]
    y = np.log(recent)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    slope, _ = np.polyfit(x, y, 1, w=weights)
    return math.exp(slope * 250) - 1


def get_volume_ratio(context, security, lookback=None, threshold=None):
    lookback = lookback or g.volume_lookback
    threshold = threshold or g.volume_threshold
    try:
        name = get_name(security)
        hist = attribute_history(security, lookback, '1d', ['volume'])
        if hist.empty or len(hist) < lookback:
            return None
        avg_vol = hist['volume'].mean()

        today = context.current_dt.date()
        df_vol = get_price(security, start_date=today, end_date=context.current_dt,
                           frequency='1m', fields=['volume'], skip_paused=False, fq='pre')
        if df_vol is None or df_vol.empty:
            return None
        current_vol = df_vol['volume'].sum()
        now = context.current_dt
        elapsed_minutes = (now.hour - 9) * 60 + now.minute - 30
        if now.hour >= 13: elapsed_minutes -= 90
        elapsed_minutes = max(1, min(elapsed_minutes, 240))
        projected_today_vol = current_vol * (240.0 / elapsed_minutes)
        ratio = projected_today_vol / avg_vol if avg_vol > 0 else 0
        if ratio > threshold:
            log.debug(f"❌ {security} {name} 成交量比{ratio:.2f} > {threshold}")
            return ratio
        return None
    except Exception as e:
        log.warning(f"🚨成交量计算失败 {security}: {e}")
        return None


def check_intraday_drawdown_for_buy(security, context):
    try:
        df = get_price(security, start_date=context.current_dt.date(), end_date=context.current_dt,
                       frequency='1m', fields=['high', 'close'], skip_paused=True, fq='pre')
        if df is None or df.empty:
            return False
        day_high = df['high'].max()
        current = df['close'].iloc[-1]
        if day_high <= 0:
            return False
        drawdown = (day_high - current) / day_high
        return drawdown >= g.intraday_drawdown_threshold
    except:
        return False


def select_target_etfs_from_rankings(context, ranked):
    target_etfs = []
    for m in ranked:
        if len(target_etfs) >= g.holdings_num:
            break

        if m['score'] < g.min_score_threshold:
            continue

        etf = m['etf']

        if g.enable_profit_protection and check_profit_protection(etf, context):
            log.info(f"🚫 {etf} {m['etf_name']} 触发盈利保护，从候选列表中排除")
            continue

        if etf in g.drawdown_selled_today:
            log.info(f"🚫 {etf} {m['etf_name']} 今日因回撤/盈利保护卖出，禁止日内买回")
            continue

        if check_intraday_drawdown_for_buy(etf, context):
            log.info(f"🌊 {etf} {m['etf_name']} 当前处于日内回撤状态(>{g.intraday_drawdown_threshold*100:.0f}%)，暂不买入")
            continue

        target_etfs.append(etf)

    return target_etfs


@time_monitor(func_name="卖出操作")
def etf_sell_trade(context):
    log.info("📤 ========== 卖出操作开始 ==========")

    ranked = get_cached_rankings(context)
    target_etfs = select_target_etfs_from_rankings(context, ranked)

    defensive_available = check_defensive_etf_available(context)
    if not target_etfs and defensive_available:
        target_etfs = [g.defensive_etf]
        log.info(f"🛡️ 无目标ETF，防御模式：{g.defensive_etf} {get_name(g.defensive_etf)}")

    g.target_etfs_cache = {'date': context.current_dt.date(), 'data': list(target_etfs)}

    target_set = set(target_etfs)

    for sec in list(context.portfolio.positions.keys()):
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        if sec not in target_set:
            pos = context.portfolio.positions[sec]
            if pos.total_amount > 0:
                cost = pos.avg_cost
                buy_date = g.buy_date.get(sec)
                hold_days = (context.current_dt.date() - buy_date).days if buy_date else 0
                if smart_order_target_value(sec, 0, context):
                    log.info(f"📤 卖出持仓：{sec} {get_name(sec)}")
                    g.trade_log['sell_records'].append({
                        'time': get_real_time(),
                        'code': sec,
                        'name': get_name(sec),
                        'cost': cost,
                        'price': get_current_data()[sec].last_price,
                        'hold_days': hold_days
                    })
                    if sec in g.buy_date:
                        del g.buy_date[sec]

    log.info("📤 ========== 卖出操作完成 ==========")


@time_monitor(func_name="买入操作")
def etf_buy_trade(context):
    log.info("📥 ========== 买入操作开始 ==========")

    ranked = get_cached_rankings(context)
    log.info("📊 === ETF排名前5 ===")
    for i, m in enumerate(ranked[:5]):
        annual_pct = m['annualized_returns'] * 100
        r_sq = m['r_squared']
        log.info(f"   排名{i+1}: {m['etf']} {m['etf_name']} 得分{m['score']:.4f} 年化{annual_pct:.2f}%")

    today = context.current_dt.date()
    if g.target_etfs_cache['date'] == today and g.target_etfs_cache['data'] is not None:
        target_etfs = list(g.target_etfs_cache['data'])
        log.info(f"📋 复用14:51目标ETF缓存：{target_etfs}")
    else:
        target_etfs = select_target_etfs_from_rankings(context, ranked)
        if not target_etfs:
            if check_defensive_etf_available(context) and g.defensive_etf not in g.drawdown_selled_today:
                target_etfs = [g.defensive_etf]
                log.info(f"🛡️ 进入防御模式：{g.defensive_etf} {get_name(g.defensive_etf)}")
            else:
                log.info("💤 无目标ETF且防御不可用，保持空仓")
                return

    if target_etfs:
        for i, etf in enumerate(target_etfs):
            m = next((x for x in ranked if x['etf'] == etf), None)
            if m:
                log.info(f"🎯 目标ETF {i+1}: {etf} {m['etf_name']} 得分{m['score']:.4f}")
    else:
        log.info("💤 无目标ETF，保持空仓")
        return

    current_etf_pos = [s for s in context.portfolio.positions if s in g.etf_pool or s == g.defensive_etf]
    to_sell = [s for s in current_etf_pos if s not in target_etfs]
    if to_sell:
        log.info(f"⏳ 尚有持仓需要卖出：{[get_name(s) for s in to_sell]}，等待卖出完成")
        return

    total_val = context.portfolio.total_value
    target_per_etf = total_val / len(target_etfs)

    for etf in target_etfs:
        current_val = 0
        if etf in context.portfolio.positions:
            pos = context.portfolio.positions[etf]
            if pos.total_amount > 0:
                current_val = pos.total_amount * pos.price
        if abs(current_val - target_per_etf) > target_per_etf * 0.05 or current_val == 0:
            if smart_order_target_value(etf, target_per_etf, context):
                action = "买入" if current_val < target_per_etf else "调仓"
                log.info(f"📦 {action}：{etf} {get_name(etf)} 目标金额{target_per_etf:.2f}")

    log.info("📥 ========== 买入操作完成 ==========")


def get_name(security):
    try:
        return get_current_data()[security].name
    except:
        return "未知"


def check_defensive_etf_available(context):
    data = get_current_data()
    etf = g.defensive_etf
    if data[etf].paused:
        return False
    if data[etf].last_price >= data[etf].high_limit:
        return False
    if data[etf].last_price <= data[etf].low_limit:
        return False
    return True


def smart_order_target_value(security, target_value, context):
    data = get_current_data()
    name = get_name(security)

    if data[security].paused:
        log.info(f"❌ {security} {name} 停牌，跳过")
        return False

    price = data[security].last_price
    if price == 0:
        return False

    target_amount = int(target_value / price)
    target_amount = (target_amount // 100) * 100
    if target_amount <= 0 and target_value > 0:
        target_amount = 100

    cur_pos = context.portfolio.positions.get(security, None)
    cur_amount = cur_pos.total_amount if cur_pos else 0
    diff = target_amount - cur_amount

    if diff > 0:
        if data[security].last_price >= data[security].high_limit:
            log.info(f"🔒 {security} {name} 涨停，跳过买入")
            return False
    elif diff < 0:
        if data[security].last_price <= data[security].low_limit:
            log.info(f"🔒 {security} {name} 跌停，跳过卖出")
            return False

    trade_val = abs(diff) * price
    if 0 < trade_val < g.min_money:
        log.info(f"💰 {security} {name} 交易金额太小，跳过")
        return False

    if diff < 0:
        closeable = cur_pos.closeable_amount if cur_pos else 0
        if closeable == 0:
            return False
        diff = -min(abs(diff), closeable)

    if diff != 0:
        order_result = order(security, diff)
        if order_result:
            log.info(f"{'📥 买入' if diff>0 else '📤 卖出'} {security} {name} 数量{abs(diff)} 价格{price:.3f}")
            if diff > 0:
                g.buy_date[security] = context.current_dt.date()
            return True
        else:
            log.warning(f"⚠️ 下单失败: {security} {name}")
            return False
    return False


def daily_summary_report(context):
    current_date = context.current_dt.strftime('%Y-%m-%d')
    total_value = context.portfolio.total_value
    cash = context.portfolio.cash
    positions_value = total_value - cash

    log.info("📋 ========== 策略运行日报 ==========")
    log.info(f"📅 日期: {current_date}")

    if g.enable_regime_switch:
        status = "🔴走弱期" if g.is_a_share_weak else "🟢正常期"
        avoid_status = "回避A股" if (g.is_a_share_weak and g.enable_avoid_a_share) else ("不回避A股" if g.is_a_share_weak else "正常交易")
        drawdown_status = "🛡️启用" if (g.is_a_share_weak and g.enable_intraday_drawdown) else ("⭕关闭" if (g.is_a_share_weak and not g.enable_intraday_drawdown) else "⭕关闭")
        log.info(f"🌍 市场状态：{status} | {avoid_status} 计数:{g.weak_period_counter}/{g.weak_period_max_days}")
        log.info(f"🛡️ 分钟级回撤：{drawdown_status}（阈值{g.intraday_drawdown_threshold*100:.0f}%）")
    else:
        log.info("🌍 行情判断未启用，始终全市场交易")

    avoid_switch_status = "ON（走弱期回避A股）" if g.enable_avoid_a_share else "OFF（走弱期不回避A股）"
    drawdown_switch_status = "ON（走弱期自动启用）" if g.enable_intraday_drawdown else "OFF（不触发）"
    log.info(f"⚙️ 独立开关：A股回避={avoid_switch_status} | 分钟回撤={drawdown_switch_status}")

    sell_records = g.trade_log.get('sell_records', [])
    log.info(f"📤 今日卖出：{len(sell_records)}只")
    for r in sell_records:
        cost = r.get('cost', 0)
        sell_price = r.get('price', 0)
        profit_pct = (sell_price / cost - 1) * 100 if cost > 0 else 0
        hold_days = r.get('hold_days', 0)
        log.info(f"   {r['code']} {r['name']} | 成本:{cost:.3f} | 卖出:{sell_price:.3f} | 收益:{profit_pct:+.2f}% | 持有{hold_days}天")

    pos_list = []
    for sec, pos in context.portfolio.positions.items():
        if pos.total_amount == 0:
            continue
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        pos_list.append(sec)
    log.info(f"📊 最终持仓：{len(pos_list)}只")
    for sec, pos in context.portfolio.positions.items():
        if pos.total_amount == 0:
            continue
        if sec not in g.etf_pool and sec != g.defensive_etf:
            continue
        current_price = get_current_data()[sec].last_price
        cost = pos.avg_cost
        profit_pct = (current_price / cost - 1) * 100 if cost > 0 else 0
        buy_date = g.buy_date.get(sec)
        hold_days = (context.current_dt.date() - buy_date).days if buy_date else 0
        log.info(f"   {sec} {get_name(sec)} | 成本:{cost:.3f} | 当前:{current_price:.3f} | 收益:{profit_pct:+.2f}% | 持有{hold_days}天")

    returns = (total_value - context.portfolio.starting_cash) / context.portfolio.starting_cash * 100
    log.info(f"💰 总资产：{total_value:.2f} | 可用：{cash:.2f} | 市值：{positions_value:.2f} | 累计收益：{returns:.2f}%")
    log.info("📋🐂🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩报告结束 🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🚩🐂")
    log.info("")

