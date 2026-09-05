# coding: utf-8
"""
S000001 - 七星高照 A股动量轮动（MiniQMT 单文件版）

将本文件全部复制到 MiniQMT 策略编辑器即可编译。运行前请确认：
1. 右侧“默认周期”设为 1分钟（不能使用日线）。
2. 回测可保留 ACCOUNT_ID='tests'；模拟/实盘必须填写真实股票账号。
3. LIVE_DRY_RUN 默认 True：回测会正常报单，模拟/实盘只打印计划、不报单。

交易时序：
- 13:09：仅使用前一交易日及更早的完整日线生成目标股票，卖出非目标持仓。
- 13:10：复用 13:09 的同一目标结果，买入/调仓。

策略核心沿用 S000001：加权对数价格回归，score = 年化收益率 * R²，
并增加适用于 A 股的 ST/退市、流动性、短期动量、单日大跌、涨跌停、
T+1 可卖数量和 100 股整手约束。
"""

import math
from datetime import datetime, timedelta


# =============================================================================
# 可调参数（复制到 MiniQMT 后主要修改这里）
# =============================================================================

STRATEGY_ID = 'S000001'
STRATEGY_NAME = 'S000001_QiXingGaoZhao_Ashare'

ACCOUNT_ID = 'tests'          # 模拟/实盘请改为真实股票账号
ACCOUNT_TYPE = 'STOCK'
LIVE_DRY_RUN = True           # True=模拟/实盘只打印；回测不受此开关影响

A_SHARE_SECTOR = '沪深A股'
INCLUDE_CHINEXT = True        # 创业板 300/301；无交易权限时改为 False
INCLUDE_STAR = True           # 科创板 688/689；无交易权限时改为 False
EXCLUDE_ST = True

SELL_TIME = '1309'
BUY_TIME = '1310'
HOLDINGS_NUM = 3
TARGET_POSITION_RATIO = 0.95
LOOKBACK_DAYS = 25
SHORT_LOOKBACK_DAYS = 10
MIN_SCORE = 0.0
MAX_SCORE = 100.0
MAX_SINGLE_DAY_DROP = 0.03

ENABLE_LIQUIDITY_FILTER = True
LIQUIDITY_LOOKBACK = 5
MIN_AVG_DAILY_AMOUNT = 20000000.0

ENABLE_VOLUME_FILTER = True
VOLUME_LOOKBACK = 5
MAX_VOLUME_RATIO = 3.6
VOLUME_FILTER_MIN_ANNUALIZED = 1.0

MIN_ORDER_VALUE = 5000.0
LOT_SIZE = 100
BUY_CASH_BUFFER = 0.998
HISTORY_BATCH_SIZE = 400
RANK_LOG_COUNT = 10

# 安全边界：默认只管理本策略下单过的证券，不接管账户内全部 A 股。
# 如果使用完全独立的策略专用账户，可显式改成 True。
MANAGE_ALL_A_SHARE_POSITIONS = False
INITIAL_MANAGED_SYMBOLS = []

# 当 MiniQMT 无法读取“沪深A股”板块时使用。指数 000001.SH 已明确排除。
FALLBACK_A_SHARE_POOL = [
    '600000.SH', '600004.SH', '600006.SH', '600007.SH', '600008.SH',
    '600009.SH', '600010.SH', '600011.SH', '600012.SH', '600015.SH',
    '600016.SH', '600017.SH', '600018.SH', '600019.SH', '600020.SH',
    '600021.SH', '600022.SH', '600023.SH', '600025.SH', '600026.SH',
    '600027.SH', '600028.SH', '600029.SH', '600030.SH', '600031.SH',
    '600032.SH', '600033.SH', '600035.SH', '600036.SH', '600037.SH',
    '600038.SH', '600039.SH', '600048.SH', '600050.SH', '600051.SH',
    '600052.SH', '600053.SH', '600054.SH',
]


STATE = {
    'universe': [],
    'universe_set': set(),
    'managed_symbols': set(INITIAL_MANAGED_SYMBOLS),
    'event_keys': set(),
    'target_date': '',
    'targets': [],
    'ranking': [],
    'target_ready': False,
    'period_ok': True,
    # 仅用于 MiniQMT 回测中的轻量持仓/资金镜像。
    'shadow_positions': {},
    'shadow_buy_dates': {},
    'shadow_cash': None,
}


# =============================================================================
# MiniQMT 入口
# =============================================================================

def init(ContextInfo):
    """MiniQMT 初始化入口。"""
    STATE['event_keys'] = set()
    STATE['target_ready'] = False
    STATE['target_date'] = ''
    STATE['targets'] = []
    STATE['ranking'] = []
    STATE['managed_symbols'] = set(INITIAL_MANAGED_SYMBOLS)

    period = str(getattr(ContextInfo, 'period', '') or '').lower()
    if period and ('m' not in period and 'min' not in period):
        STATE['period_ok'] = False
        print('[%s][错误] 当前周期=%s。时间事件策略必须把“默认周期”设为1分钟；本次拒绝交易。'
              % (STRATEGY_ID, period))
    else:
        STATE['period_ok'] = True

    STATE['universe'] = _load_a_share_universe(ContextInfo)
    STATE['universe_set'] = set(STATE['universe'])
    if hasattr(ContextInfo, 'set_universe'):
        ContextInfo.set_universe(STATE['universe'])

    if _is_backtest(ContextInfo):
        capital = _safe_float(getattr(ContextInfo, 'capital', 0), 0.0)
        STATE['shadow_cash'] = capital
        STATE['shadow_positions'] = {}
        STATE['shadow_buy_dates'] = {}
    else:
        _recover_managed_symbols_from_orders()

    print('========== %s 七星高照A股版启动 ==========' % STRATEGY_ID)
    print('策略名=%s  股票池=%d只  动量=%d日  目标持仓=%d只'
          % (STRATEGY_NAME, len(STATE['universe']), LOOKBACK_DAYS, HOLDINGS_NUM))
    print('事件：%s卖出，%s买入；信号只使用前一交易日及更早的完整日线。'
          % (SELL_TIME, BUY_TIME))
    print('实盘保护：LIVE_DRY_RUN=%s；管理账户全部A股=%s'
          % (LIVE_DRY_RUN, MANAGE_ALL_A_SHARE_POSITIONS))
    if not STATE['universe']:
        print('[错误] A股股票池为空，请检查板块数据。')


def handlebar(ContextInfo):
    """MiniQMT Bar 驱动入口；同一天的每个事件最多执行一次。"""
    if not STATE['period_ok'] or not STATE['universe']:
        return
    if not _is_backtest(ContextInfo):
        try:
            if not ContextInfo.is_last_bar():
                return
        except Exception:
            pass

    cur_date, cur_time = _bar_date_time(ContextInfo)
    if not cur_date or not cur_time:
        return

    # 卖出先于买入。5分钟周期若在13:10首次回调，也会按顺序补做两个事件；
    # 日线周期已在 init 中拦截。
    sell_key = cur_date + ':SELL'
    if cur_time >= SELL_TIME and sell_key not in STATE['event_keys']:
        STATE['event_keys'].add(sell_key)
        _on_sell_event(ContextInfo, cur_date)

    buy_key = cur_date + ':BUY'
    if cur_time >= BUY_TIME and cur_time < '1500' and buy_key not in STATE['event_keys']:
        STATE['event_keys'].add(buy_key)
        _on_buy_event(ContextInfo, cur_date)


# =============================================================================
# 股票池与信号
# =============================================================================

def _load_a_share_universe(ContextInfo):
    raw = []
    try:
        raw = ContextInfo.get_stock_list_in_sector(A_SHARE_SECTOR) or []
        print('[股票池] 从板块“%s”读取到%d只证券。' % (A_SHARE_SECTOR, len(raw)))
    except Exception as exc:
        print('[股票池][警告] 读取板块失败：%s' % exc)

    if not raw:
        raw = list(FALLBACK_A_SHARE_POOL)
        print('[股票池] 使用内置回退A股池，共%d只。' % len(raw))

    result = []
    seen = set()
    for value in raw:
        code = str(value).strip().upper()
        if code not in seen and _is_a_share_code(code):
            seen.add(code)
            result.append(code)
    result.sort()
    return result


def _is_a_share_code(code):
    """仅接受沪深 A 股代码；显式排除指数、ETF、B股和其他品种。"""
    if len(code) != 9 or code[6:] not in ('.SH', '.SZ'):
        return False
    digits = code[:6]
    if not digits.isdigit():
        return False
    if code.endswith('.SH'):
        if digits.startswith(('600', '601', '603', '605')):
            return True
        if INCLUDE_STAR and digits.startswith(('688', '689')):
            return True
        return False
    if digits.startswith(('000', '001', '002', '003')):
        return True
    if INCLUDE_CHINEXT and digits.startswith(('300', '301')):
        return True
    return False


def _previous_trading_date(ContextInfo, cur_date):
    try:
        values = ContextInfo.get_trading_dates('SH', '', cur_date, 5, '1d') or []
        dates = sorted(set(str(v)[:8] for v in values if str(v)[:8] < cur_date))
        if dates:
            return dates[-1]
    except Exception as exc:
        print('[交易日][警告] get_trading_dates失败：%s' % exc)

    # 只作为接口失败时的兜底；节假日由行情接口返回的最近有效日线自然修正。
    value = datetime.strptime(cur_date, '%Y%m%d') - timedelta(days=1)
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value.strftime('%Y%m%d')


def _build_targets(ContextInfo, cur_date):
    end_date = _previous_trading_date(ContextInfo, cur_date)
    fields = ['close', 'volume', 'amount']
    fetch_count = max(LOOKBACK_DAYS + 3, SHORT_LOOKBACK_DAYS + 3,
                      VOLUME_LOOKBACK + 3, LIQUIDITY_LOOKBACK + 3)
    ranking = []
    usable_history_count = 0

    print('[信号] 开始计算：信号日=%s，历史截止=%s，股票池=%d只。'
          % (cur_date, end_date, len(STATE['universe'])))
    for start in range(0, len(STATE['universe']), HISTORY_BATCH_SIZE):
        codes = STATE['universe'][start:start + HISTORY_BATCH_SIZE]
        try:
            data = ContextInfo.get_market_data_ex(
                fields, codes, period='1d', count=fetch_count,
                end_time=end_date, dividend_type=getattr(ContextInfo, 'dividend_type', 'front'),
                fill_data=True, subscribe=False)
        except Exception as exc:
            print('[行情][警告] 第%d-%d只批量读取失败：%s'
                  % (start + 1, start + len(codes), exc))
            continue
        if not data:
            continue

        for code in codes:
            block = data.get(code) if hasattr(data, 'get') else None
            closes = _field_values(block, 'close')
            if len(closes) < LOOKBACK_DAYS + 1:
                continue
            usable_history_count += 1
            volumes = _field_values(block, 'volume')
            amounts = _field_values(block, 'amount')
            metrics = _score_stock(code, closes, volumes, amounts)
            if metrics is not None:
                ranking.append(metrics)

    if usable_history_count == 0:
        print('[信号][失败] 没有任何股票取得足够日线；为避免误清仓，本日不交易。')
        STATE['target_ready'] = False
        STATE['target_date'] = cur_date
        STATE['targets'] = []
        STATE['ranking'] = []
        return False

    ranking.sort(key=lambda item: (-item['score'], item['code']))
    targets = []
    for item in ranking:
        if _instrument_is_selectable(ContextInfo, item['code'], cur_date):
            targets.append(item['code'])
            if len(targets) >= HOLDINGS_NUM:
                break

    STATE['target_ready'] = True
    STATE['target_date'] = cur_date
    STATE['targets'] = targets
    STATE['ranking'] = ranking

    print('[信号] 可用历史=%d只，通过量价过滤=%d只，目标=%s'
          % (usable_history_count, len(ranking), targets))
    for index, item in enumerate(ranking[:RANK_LOG_COUNT]):
        print('  排名%02d %s score=%.4f 年化=%.2f%% R2=%.4f 短期=%.2f%%'
              % (index + 1, item['code'], item['score'],
                 item['annualized'] * 100.0, item['r_squared'],
                 item['short_annualized'] * 100.0))
    if not targets:
        print('[信号] 没有符合条件的目标，目标仓位为空仓。')
    return True


def _score_stock(code, closes, volumes, amounts):
    prices = [_safe_float(v, 0.0) for v in closes]
    prices = [v for v in prices if v > 0]
    if len(prices) < LOOKBACK_DAYS + 1:
        return None

    if ENABLE_LIQUIDITY_FILTER and len(amounts) >= LIQUIDITY_LOOKBACK:
        recent_amounts = [_safe_float(v, 0.0) for v in amounts[-LIQUIDITY_LOOKBACK:]]
        if min(recent_amounts) <= 0:
            return None
        if sum(recent_amounts) / len(recent_amounts) < MIN_AVG_DAILY_AMOUNT:
            return None

    short_ann = 0.0
    if len(prices) >= SHORT_LOOKBACK_DAYS + 1:
        short_return = prices[-1] / prices[-(SHORT_LOOKBACK_DAYS + 1)] - 1.0
        try:
            short_ann = (1.0 + short_return) ** (250.0 / SHORT_LOOKBACK_DAYS) - 1.0
        except Exception:
            return None
        if short_ann < 0.0:
            return None

    if len(prices) >= 4:
        ratios = [prices[-1] / prices[-2], prices[-2] / prices[-3], prices[-3] / prices[-4]]
        if min(ratios) < 1.0 - MAX_SINGLE_DAY_DROP:
            return None

    annualized, r_squared, score = _momentum_score(prices, LOOKBACK_DAYS)
    if annualized is None or score <= MIN_SCORE or score >= MAX_SCORE:
        return None

    if ENABLE_VOLUME_FILTER and len(volumes) >= VOLUME_LOOKBACK + 1:
        vols = [_safe_float(v, 0.0) for v in volumes[-(VOLUME_LOOKBACK + 1):]]
        base = vols[:-1]
        if min(base) > 0:
            ratio = vols[-1] / (sum(base) / len(base))
            if ratio > MAX_VOLUME_RATIO and annualized > VOLUME_FILTER_MIN_ANNUALIZED:
                return None

    return {
        'code': code,
        'annualized': annualized,
        'r_squared': r_squared,
        'score': score,
        'short_annualized': short_ann,
    }


def _momentum_score(price_series, lookback_days):
    recent = list(price_series[-(lookback_days + 1):])
    if len(recent) < 3 or min(recent) <= 0:
        return None, None, None
    y = [math.log(v) for v in recent]
    x = list(range(len(y)))
    weights = _linspace(1.0, 2.0, len(y))
    slope, intercept = _weighted_polyfit(x, y, weights)
    try:
        annualized = math.exp(slope * 250.0) - 1.0
    except OverflowError:
        return None, None, None
    y_mean = sum(w * value for w, value in zip(weights, y)) / sum(weights)
    ss_res = sum(w * (value - (slope * pos + intercept)) ** 2
                 for w, pos, value in zip(weights, x, y))
    ss_tot = sum(w * (value - y_mean) ** 2 for w, value in zip(weights, y))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    r_squared = max(0.0, min(1.0, r_squared))
    return annualized, r_squared, annualized * r_squared


def _linspace(start, stop, count):
    if count <= 1:
        return [float(start)]
    step = (stop - start) / float(count - 1)
    return [start + step * index for index in range(count)]


def _weighted_polyfit(x, y, weights):
    sw = sum(weights)
    sx = sum(w * value for w, value in zip(weights, x))
    sy = sum(w * value for w, value in zip(weights, y))
    sxx = sum(w * value * value for w, value in zip(weights, x))
    sxy = sum(w * xv * yv for w, xv, yv in zip(weights, x, y))
    denominator = sw * sxx - sx * sx
    if denominator == 0:
        return 0.0, y[0] if y else 0.0
    slope = (sw * sxy - sx * sy) / denominator
    return slope, (sy - slope * sx) / sw


def _instrument_is_selectable(ContextInfo, code, cur_date):
    try:
        info = ContextInfo.get_instrument_detail(code) or {}
    except Exception:
        info = {}
    if not info:
        return True

    name = str(info.get('InstrumentName', '') or '').upper()
    if EXCLUDE_ST and ('ST' in name or '退' in name):
        return False
    open_date = str(info.get('OpenDate', '') or '')[:8]
    expire_date = str(info.get('ExpireDate', '') or '')[:8]
    if open_date and open_date.isdigit() and cur_date < open_date:
        return False
    if expire_date and expire_date.isdigit() and expire_date != '0' and cur_date >= expire_date:
        return False
    if not _is_backtest(ContextInfo):
        status = _safe_float(info.get('InstrumentStatus', 0), 0.0)
        if status >= 1:
            return False
    return True


# =============================================================================
# 交易事件与风控
# =============================================================================

def _on_sell_event(ContextInfo, cur_date):
    print('========== [%s %s] 卖出事件 ==========' % (cur_date, SELL_TIME))
    if STATE['target_date'] != cur_date or not STATE['target_ready']:
        if not _build_targets(ContextInfo, cur_date):
            return

    targets = set(STATE['targets'])
    positions = _get_positions(ContextInfo, cur_date)
    managed = _managed_position_symbols(positions)
    for code in sorted(managed - targets):
        position = positions.get(code, {})
        volume = int(position.get('volume', 0) or 0)
        can_use = int(position.get('can_use', 0) or 0)
        if volume <= 0:
            continue
        if can_use <= 0:
            print('[卖出][跳过] %s 持仓=%d，可卖=0（A股T+1或冻结）。' % (code, volume))
            continue
        price = _current_price(ContextInfo, code)
        if not _tradeable_at_price(ContextInfo, code, price, 'SELL'):
            continue
        _submit_order(ContextInfo, 'SELL', code, can_use, price, cur_date)


def _on_buy_event(ContextInfo, cur_date):
    print('========== [%s %s] 买入事件 ==========' % (cur_date, BUY_TIME))
    if STATE['target_date'] != cur_date or not STATE['target_ready']:
        print('[买入][跳过] 当日13:09目标未成功生成，禁止临时重算后买入。')
        return
    targets = list(STATE['targets'])
    if not targets:
        print('[买入] 目标为空，保持现金。')
        return

    positions = _get_positions(ContextInfo, cur_date)
    remaining_old = _managed_position_symbols(positions) - set(targets)
    if remaining_old and not (LIVE_DRY_RUN and not _is_backtest(ContextInfo)):
        print('[买入][跳过] 非目标持仓尚未卖完：%s' % sorted(remaining_old))
        return

    prices = {}
    for code in targets:
        price = _current_price(ContextInfo, code)
        if _tradeable_at_price(ContextInfo, code, price, 'BUY'):
            prices[code] = price
    if not prices:
        print('[买入][跳过] 所有目标均无有效价格、停牌或涨停。')
        return

    cash = _available_cash(ContextInfo)
    equity = cash
    for code, position in positions.items():
        if code in _managed_position_symbols(positions):
            price = prices.get(code) or _current_price(ContextInfo, code)
            if price:
                equity += int(position.get('volume', 0) or 0) * price
    target_value = equity * TARGET_POSITION_RATIO / float(len(targets))

    for code in targets:
        price = prices.get(code)
        if not price:
            continue
        current_volume = int(positions.get(code, {}).get('volume', 0) or 0)
        target_volume = int(target_value / price / LOT_SIZE) * LOT_SIZE
        buy_volume = max(0, target_volume - current_volume)
        affordable = int(cash * BUY_CASH_BUFFER / price / LOT_SIZE) * LOT_SIZE
        buy_volume = min(buy_volume, affordable)
        if buy_volume <= 0:
            print('[买入][跳过] %s 无需增仓或可用资金不足。' % code)
            continue
        if buy_volume * price < MIN_ORDER_VALUE:
            print('[买入][跳过] %s 委托金额%.2f低于最小金额%.2f。'
                  % (code, buy_volume * price, MIN_ORDER_VALUE))
            continue
        if _submit_order(ContextInfo, 'BUY', code, buy_volume, price, cur_date):
            cash -= buy_volume * price


def _submit_order(ContextInfo, side, code, volume, price, cur_date):
    volume = int(volume // LOT_SIZE) * LOT_SIZE
    if volume <= 0 or not price or price <= 0:
        return False
    is_backtest = _is_backtest(ContextInfo)
    remark = '[%s][%s][%s][%s] %d@%.3f' % (
        cur_date, STRATEGY_ID, code, side, volume, price)

    if LIVE_DRY_RUN and not is_backtest:
        print('[DRY_RUN][计划%s] %s 数量=%d 参考价=%.3f 备注=%s'
              % ('买入' if side == 'BUY' else '卖出', code, volume, price, remark))
        return True

    operation = 23 if side == 'BUY' else 24
    try:
        # 1101=股票；14=指定价；quickTrade=1；策略名和备注用于持仓归属恢复。
        passorder(operation, 1101, ACCOUNT_ID, code, 14, price, volume,
                  STRATEGY_NAME, 1, remark, ContextInfo)
    except Exception as exc:
        print('[委托][失败] %s %s 数量=%d：%s' % (side, code, volume, exc))
        return False

    STATE['managed_symbols'].add(code)
    if is_backtest:
        _update_shadow_after_order(side, code, volume, price, cur_date)
    print('[委托][%s] %s 数量=%d 参考价=%.3f' % (side, code, volume, price))
    return True


def _tradeable_at_price(ContextInfo, code, price, side):
    if not price or price <= 0:
        print('[%s][跳过] %s 无有效现价。' % (side, code))
        return False
    if _is_backtest(ContextInfo):
        return True
    try:
        tick_map = ContextInfo.get_full_tick([code]) or {}
        tick = tick_map.get(code, {}) or {}
        if tick.get('openInt', 0) in (1, 17):
            print('[%s][跳过] %s 当前停牌。' % (side, code))
            return False
    except Exception:
        pass
    try:
        info = ContextInfo.get_instrument_detail(code) or {}
        up_limit = _safe_float(info.get('UpStopPrice', 0), 0.0)
        down_limit = _safe_float(info.get('DownStopPrice', 0), 0.0)
        if side == 'BUY' and up_limit > 0 and price >= up_limit:
            print('[买入][跳过] %s 当前涨停。' % code)
            return False
        if side == 'SELL' and down_limit > 0 and price <= down_limit:
            print('[卖出][跳过] %s 当前跌停。' % code)
            return False
    except Exception:
        pass
    return True


# =============================================================================
# 账户、持仓、价格与兼容辅助
# =============================================================================

def _get_positions(ContextInfo, cur_date):
    if _is_backtest(ContextInfo):
        result = {}
        for code, volume in STATE['shadow_positions'].items():
            if volume <= 0:
                continue
            buy_date = STATE['shadow_buy_dates'].get(code, '')
            can_use = volume if not buy_date or buy_date < cur_date else 0
            result[code] = {'volume': volume, 'can_use': can_use, 'cost': 0.0}
        return result

    result = {}
    try:
        rows = get_trade_detail_data(ACCOUNT_ID, ACCOUNT_TYPE, 'POSITION') or []
        for row in rows:
            code = _row_symbol(row)
            if not code:
                continue
            result[code] = {
                'volume': int(getattr(row, 'm_nVolume', 0) or 0),
                'can_use': int(getattr(row, 'm_nCanUseVolume', 0) or 0),
                'cost': _safe_float(getattr(row, 'm_dOpenPrice', 0), 0.0),
            }
    except Exception as exc:
        print('[账户][警告] 获取持仓失败：%s' % exc)
    return result


def _available_cash(ContextInfo):
    if _is_backtest(ContextInfo):
        return max(0.0, _safe_float(STATE['shadow_cash'], 0.0))
    try:
        rows = get_trade_detail_data(ACCOUNT_ID, ACCOUNT_TYPE, 'ACCOUNT') or []
        values = [_safe_float(getattr(row, 'm_dAvailable', 0), 0.0) for row in rows]
        if values:
            return max(0.0, max(values))
    except Exception as exc:
        print('[账户][警告] 获取可用资金失败：%s' % exc)
    return 0.0


def _managed_position_symbols(positions):
    held_a_shares = set(code for code, pos in positions.items()
                        if _is_a_share_code(code) and int(pos.get('volume', 0) or 0) > 0)
    if MANAGE_ALL_A_SHARE_POSITIONS:
        return held_a_shares
    return held_a_shares & STATE['managed_symbols']


def _recover_managed_symbols_from_orders():
    """尽力从带策略名的历史委托恢复归属；失败时保持安全的空集合。"""
    try:
        rows = get_trade_detail_data(ACCOUNT_ID, ACCOUNT_TYPE, 'ORDER', STRATEGY_NAME) or []
        for row in rows:
            code = _row_symbol(row)
            if code and _is_a_share_code(code):
                STATE['managed_symbols'].add(code)
        if STATE['managed_symbols']:
            print('[持仓归属] 从策略委托恢复：%s' % sorted(STATE['managed_symbols']))
    except Exception as exc:
        print('[持仓归属][提示] 未能读取策略历史委托：%s' % exc)


def _row_symbol(row):
    instrument = str(getattr(row, 'm_strInstrumentID', '') or
                     getattr(row, 'm_strStockCode', '') or '').upper()
    if '.' in instrument:
        return instrument
    exchange = str(getattr(row, 'm_strExchangeID', '') or '').upper()
    if exchange in ('SH', 'SZ') and instrument:
        return instrument + '.' + exchange
    return ''


def _current_price(ContextInfo, code):
    if not _is_backtest(ContextInfo):
        try:
            tick = (ContextInfo.get_full_tick([code]) or {}).get(code, {}) or {}
            value = _safe_float(tick.get('lastPrice', 0), 0.0)
            if value > 0:
                return value
        except Exception:
            pass
    try:
        end_time = _bar_date_time(ContextInfo)[0] + _bar_date_time(ContextInfo)[1] + '00'
        data = ContextInfo.get_market_data_ex(
            ['close', 'lastPrice'], [code], period=getattr(ContextInfo, 'period', '1m'),
            count=1, end_time=end_time,
            dividend_type=getattr(ContextInfo, 'dividend_type', 'front'),
            fill_data=True, subscribe=True)
        block = data.get(code) if data and hasattr(data, 'get') else None
        last_values = _field_values(block, 'lastPrice')
        close_values = _field_values(block, 'close')
        if last_values and last_values[-1] > 0:
            return last_values[-1]
        if close_values and close_values[-1] > 0:
            return close_values[-1]
    except Exception as exc:
        print('[行情][警告] %s 获取现价失败：%s' % (code, exc))
    return None


def _field_values(block, field):
    if block is None:
        return []
    try:
        if hasattr(block, 'columns') and field in block.columns:
            source = block[field]
        elif isinstance(block, dict) and field in block:
            source = block[field]
        else:
            return []
        if hasattr(source, 'tolist'):
            raw = source.tolist()
        elif hasattr(source, 'values') and hasattr(source.values, 'tolist'):
            raw = source.values.tolist()
        else:
            raw = list(source)
        result = []
        for value in raw:
            number = _safe_float(value, None)
            if number is not None and number == number:
                result.append(number)
        return result
    except Exception:
        return []


def _update_shadow_after_order(side, code, volume, price, cur_date):
    old = int(STATE['shadow_positions'].get(code, 0) or 0)
    cash = _safe_float(STATE['shadow_cash'], 0.0)
    if side == 'BUY':
        STATE['shadow_positions'][code] = old + volume
        STATE['shadow_buy_dates'][code] = cur_date
        STATE['shadow_cash'] = max(0.0, cash - volume * price)
    else:
        new_volume = max(0, old - volume)
        STATE['shadow_positions'][code] = new_volume
        STATE['shadow_cash'] = cash + volume * price
        if new_volume == 0:
            STATE['shadow_buy_dates'].pop(code, None)


def _bar_date_time(ContextInfo):
    try:
        timetag = ContextInfo.get_bar_timetag(ContextInfo.barpos)
        value = timetag_to_datetime(timetag, '%Y%m%d%H%M%S')
        return value[:8], value[8:12]
    except Exception:
        return '', ''


def _is_backtest(ContextInfo):
    return bool(getattr(ContextInfo, 'do_back_test', False))


def _safe_float(value, default=0.0):
    try:
        number = float(value)
        if number != number or math.isinf(number):
            return default
        return number
    except (TypeError, ValueError):
        return default
