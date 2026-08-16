# coding:gbk
"""
七星高照ETF轮动超级增强 - QMT 策略
来源: 策略_cleaned.txt (QMT段修复版)

使用说明:
1. 在 QMT 模型研究中新建 Python 策略，引用本文件
2. 回测/实盘建议使用 1 分钟周期 (1m)
3. 修改下方 account / accountType 为实际交易账号
4. 溢价率过滤依赖 QMT 内置 get_etf_iopv()，回测时自动跳过
5. 本策略不依赖 numpy/pandas，适配 QMT 内置 Python 环境
6. LOCAL_DATA_ONLY=True 时仅读本地 datadir，不联网 download/subscribe

日内调度:
- 09:10 持仓检查
- 09:40 行情判断
- 11:00 盈利保护
- 09:46起 分钟回撤(走弱期)
- 13:09 卖出 / 13:10 买入
- 15:05 日报
"""

# 实盘账户配置（回测可保持默认）
account = 'tests'
accountType = 'STOCK'

# True: 仅读本地 datadir，不调用 download_history_data，不 subscribe 联网补数
LOCAL_DATA_ONLY = True


import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Set


# =============================================================================
# 工具函数 - 数据处理
# =============================================================================

def _is_nan(v):
    """
    检查值是否为 NaN（Not a Number）

    输入: 任意类型的值
    输出: bool - 如果是 NaN、None 或无法转换为浮点数则返回 True
    """
    try:
        if v is None:
            return True
        fv = float(v)
        return fv != fv or math.isnan(fv)
    except (TypeError, ValueError):
        return True


def _to_list(data):
    """
    将各种数据格式统一转换为列表

    输入: 支持 numpy array, pandas Series/DataFrame, 普通可迭代对象
    输出: list - 转换后的列表
    """
    if data is None:
        return []
    if hasattr(data, 'tolist'):
        return list(data.tolist())
    if hasattr(data, 'values'):
        vals = data.values
        if hasattr(vals, 'tolist'):
            return list(vals.tolist())
        return list(vals)
    return list(data)


def _is_empty(obj):
    """
    检查数据是否为空

    输入: 任意对象
    输出: bool - 空则返回 True
    """
    if obj is None:
        return True
    if hasattr(obj, 'empty'):
        return bool(obj.empty)
    try:
        return len(obj) == 0
    except TypeError:
        return True


def _has_valid_series(ser) -> bool:
    """检查序列是否有有效数据"""
    return not _is_empty(ser)


def _last_value(series_or_list):
    """
    获取序列/列表的最后一个值

    输入: pandas Series 或普通列表
    输出: 最后一个值，空则返回 None
    """
    if _is_empty(series_or_list):
        return None
    if hasattr(series_or_list, 'iloc'):
        return series_or_list.iloc[-1]
    return series_or_list[-1]


def _sum_values(series_or_list):
    """
    计算序列/列表的有效值之和

    输入: 数据序列
    输出: float - 所有有效值的和
    """
    return sum(float(v) for v in _to_list(series_or_list) if not _is_nan(v))


def _max_values(series_or_list):
    """
    获取序列/列表的最大值

    输入: 数据序列
    输出: float - 最大值，空则返回 None
    """
    vals = [float(v) for v in _to_list(series_or_list) if not _is_nan(v)]
    return max(vals) if vals else None


def _mean_values(series_or_list):
    """
    计算序列/列表的算术平均值

    输入: 数据序列
    输出: float - 平均值，空则返回 0.0
    """
    vals = [float(v) for v in _to_list(series_or_list) if not _is_nan(v)]
    return sum(vals) / len(vals) if vals else 0.0


def _linspace(start, stop, num):
    """
    生成等差数列（类似 numpy.linspace）

    输入: start - 起始值, stop - 结束值, num - 数量
    输出: list - 等差数列
    """
    if num <= 1:
        return [float(start)]
    step = (stop - start) / (num - 1)
    return [start + i * step for i in range(num)]


def _weighted_polyfit(x, y, weights):
    """
    加权线性回归（计算斜率和截距）

    公式: slope = (sw*sxy - sx*sy) / (sw*sxx - sx*sx)
          intercept = (sy - slope*sx) / sw

    输入: x - 自变量列表, y - 因变量列表, weights - 权重列表
    输出: tuple - (slope, intercept)
    """
    sw = sum(weights)
    sx = sum(w * xi for w, xi in zip(weights, x))
    sy = sum(w * yi for w, yi in zip(weights, y))
    sxx = sum(w * xi * xi for w, xi in zip(weights, x))
    sxy = sum(w * xi * yi for w, xi, yi in zip(weights, x, y))
    denom = sw * sxx - sx * sx
    if denom == 0:
        return 0.0, y[0] if y else 0.0
    slope = (sw * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / sw
    return slope, intercept


def _get_field_last(block, field):
    """
    从数据块中获取指定字段的最后一个值

    输入: block - pandas DataFrame 或 dict, field - 字段名
    输出: 最后一个值，字段不存在则返回 None
    """
    if hasattr(block, 'columns') and field in block.columns:
        col = block[field]
        if not _is_empty(col):
            return _last_value(col)
    if isinstance(block, dict) and field in block:
        return _last_value(block[field])
    return None


def _tail_series(ser, count):
    """
    获取序列的末尾 N 个元素

    输入: ser - pandas Series 或列表, count - 元素数量
    输出: 末尾 N 个元素
    """
    if hasattr(ser, 'iloc'):
        return ser.iloc[-count:]
    lst = _to_list(ser)
    return lst[-count:]


def _filter_series_by_end_date(ser, end_str):
    """
    按日期过滤序列（保留 end_str 之前的日期）

    输入: ser - pandas Series 带日期索引, end_str - 截止日期字符串 YYYYMMDD
    输出: 过滤后的序列
    """
    if hasattr(ser, 'index') and hasattr(ser, '__getitem__'):
        try:
            mask = [str(x)[:8] <= end_str for x in ser.index]
            return ser[mask]
        except Exception:
            pass
    return ser


def _valid_closes(closes):
    """
    获取有效的收盘价列表

    输入: 收盘价序列
    输出: list - 有效价格的浮点数列表
    """
    return [float(v) for v in _to_list(closes) if not _is_nan(v)]


def _local_data_only() -> bool:
    """
    获取是否仅使用本地数据的配置

    输出: bool - True 表示仅读本地 datadir，不联网
    """
    try:
        return bool(g.get('local_data_only', LOCAL_DATA_ONLY))
    except NameError:
        return LOCAL_DATA_ONLY


def _normalize_local_block(result: Any, code: str) -> Any:
    """
    规范化本地数据块的格式

    输入: result - 原始数据, code - 证券代码
    输出: 规范化后的数据块
    """
    if result is None:
        return None
    if isinstance(result, dict):
        if code in result:
            return result[code]
        if 'close' in result or 'time' in result:
            return result
        if len(result) == 1:
            return next(iter(result.values()))
    return result


def _has_valid_market_block(block: Any, field: str = 'close') -> bool:
    """
    检查市场数据块是否有效

    输入: block - 数据块, field - 要检查的字段名
    输出: bool - 数据块有效则返回 True
    """
    if block is None:
        return False
    if isinstance(block, dict) and field in block:
        return len(_valid_closes(block[field])) > 0 if field == 'close' else len(_to_list(block[field])) > 0
    if hasattr(block, 'columns') and field in block.columns:
        return not _is_empty(block[field])
    if hasattr(block, '__len__'):
        return len(block) > 0
    return False


def _call_get_local_data(context_info, code: str, period: str, end_time: str = '', count: int = 0) -> Any:
    """
    尝试从本地获取数据（尝试多种数量参数）

    输入: context_info - QMT上下文, code - 证券代码, period - 周期, end_time - 截止时间, count - 数据条数
    输出: 数据块，未找到则返回 None
    """
    end_str = (end_time or '20991231')[:8]
    start_str = '19900101'
    start_t = start_str + '000000'
    end_t = end_str + '235959'
    for cnt in (count, 0, -1, 999999):
        try:
            raw = context_info.get_local_data(code, start_t, end_t, period, 'none', cnt)
            block = _normalize_local_block(raw, code)
            if _has_valid_market_block(block):
                return block
        except Exception:
            continue
    return None


def _market_data_ex_local(
    context_info,
    fields: List[str],
    stock_list: List[str],
    period: str,
    *,
    end_time: str = '',
    start_time: str = '',
    count: int = -1,
    fill_data: bool = True,
) -> Dict[str, Any]:
    """
    仅本地读取行情数据，不触发联网补数

    输入: context_info - QMT上下文, fields - 字段列表, stock_list - 证券列表, period - 周期等
    输出: dict - {证券代码: {字段: 数据}}
    """
    try:
        return context_info.get_market_data_ex(
            fields, stock_list, period=period, end_time=end_time,
            start_time=start_time, count=count, fill_data=fill_data, subscribe=False,
        ) or {}
    except TypeError:
        try:
            return context_info.get_market_data_ex(
                fields, stock_list, period=period, count=count,
                fill_data=fill_data, subscribe=False,
            ) or {}
        except Exception:
            return {}
    except Exception:
        return {}


def _print_missing_local_data(label: str, codes: List[str], period: str) -> None:
    """
    打印缺失的本地数据信息

    输入: label - 标签, codes - 证券代码列表, period - 周期
    """
    if not codes:
        return
    preview = ', '.join(codes[:8])
    suffix = '...' if len(codes) > 8 else ''
    print(f'  [本地数据] 未找到有效 {period} 数据({len(codes)}只) {label}: {preview}{suffix}')


def _debug(msg: str) -> None:
    """
    调试日志输出（受 enable_debug_log 控制）

    输入: msg - 日志消息
    """
    try:
        if g.get('enable_debug_log'):
            print(f'  [DEBUG] {msg}')
    except NameError:
        pass


def _is_valid_backtest_date(date_str: str) -> bool:
    """
    检查是否为有效的回测日期

    输入: date_str - 日期字符串
    输出: bool - 日期有效（大于1990年）则返回 True
    """
    return bool(date_str) and str(date_str)[:8] > '19900101'


def _format_schedule_time(hhmm: str) -> str:
    """
    格式化时间为 HH:MM 格式

    输入: hhmm - 字符串如 "0930"
    输出: 格式化字符串如 "09:30"
    """
    return f'{hhmm[:2]}:{hhmm[2:]}' if len(hhmm) >= 4 else hhmm


def _get_pending_schedule(cur_time: str) -> List[str]:
    """
    获取当前时间点之后待执行的调度任务列表

    输入: cur_time - 当前时间 HHMM 格式
    输出: list - 待执行任务描述列表
    """
    pending: List[str] = []
    if not g.get('check_positions_done') and cur_time < '0910':
        pending.append('09:10 持仓检查')
    if not g.get('regime_check_done') and cur_time < g.get('regime_check_time', '0940'):
        pending.append(f"{_format_schedule_time(g.get('regime_check_time', '0940'))} 行情判断")
    for check_time in g.get('profit_protection_check_times', []):
        check_time_str = check_time.replace(':', '')
        if check_time not in g.get('profit_protection_done_times', set()) and cur_time < check_time_str:
            pending.append(f'{check_time} 盈利保护')
    if not g.get('etf_sell_done') and cur_time < g.get('etf_sell_time', '1309'):
        pending.append(f"{_format_schedule_time(g.get('etf_sell_time', '1309'))} 卖出")
    if not g.get('etf_buy_done') and cur_time < g.get('etf_buy_time', '1310'):
        pending.append(f"{_format_schedule_time(g.get('etf_buy_time', '1310'))} 买入")
    if not g.get('daily_summary_done') and cur_time < '1505':
        pending.append('15:05 日报')
    return pending


def _preload_daily_data(ContextInfo, anchor_date: str, *, label: str = 'preload') -> int:
    """
    预加载日线数据到缓存

    输入: ContextInfo - QMT上下文, anchor_date - 锚定日期, label - 日志标签
    输出: int - 成功加载的证券数量
    """
    if not _is_valid_backtest_date(anchor_date):
        print(f'  [DEBUG][{label}] 跳过日线预加载: anchor_date={anchor_date} 无效')
        return -1
    end_date = trader.get_prev_trade_date(anchor_date)
    if not end_date:
        print(f'  [DEBUG][{label}] 跳过日线预加载: 无法获取 {anchor_date} 的前一交易日')
        return -1
    print(f'  [DEBUG][{label}] 预加载日线: anchor={anchor_date} prev_trade_date={end_date} pool={len(g["all_subscribe_codes"])}只')
    daily_preload = trader.get_daily_data_cached(
        ['close'], g['all_subscribe_codes'], count=60, end_time=end_date
    )
    ok_cnt = sum(
        1 for c in g['all_subscribe_codes']
        if c in daily_preload and _has_valid_series(daily_preload[c].get('close'))
    )
    print(f'  [DEBUG][{label}] 日线预加载结果: 有效{ok_cnt}/{len(g["all_subscribe_codes"])}只')
    if ok_cnt == 0:
        print(f'  [DEBUG][{label}] 日线全部无效！13:09/13:10 排名与交易将无法执行')
    return ok_cnt


def _get_backtest_total_bars(ContextInfo) -> Optional[int]:
    """
    获取回测总K线数

    输入: ContextInfo - QMT上下文
    输出: int 或 None - 总K线数
    """
    for name in ('get_totalbar', 'get_total_bar', 'totalbar'):
        fn = getattr(ContextInfo, name, None)
        if callable(fn):
            try:
                return int(fn())
            except Exception:
                pass
    return None


def _ensure_daily_preload(ContextInfo, cur_date: str) -> None:
    """
    确保日线数据已预加载（每日只加载一次）

    输入: ContextInfo - QMT上下文, cur_date - 当前日期
    """
    if g.get('daily_preload_done') or not _is_valid_backtest_date(cur_date):
        return
    try:
        _preload_daily_data(ContextInfo, cur_date, label='day')
    except Exception as e:
        print(f'  [warning][day] 日线预加载异常: {e}')
    g['daily_preload_done'] = True


def _log_backtest_progress(ContextInfo, cur_date: str, cur_time: str) -> None:
    """
    记录回测进度日志（在关键时间点）

    输入: ContextInfo, cur_date, cur_time
    """
    if not ContextInfo.do_back_test or not g.get('enable_debug_log'):
        return
    barpos = ContextInfo.barpos
    is_last = False
    try:
        is_last = bool(ContextInfo.is_last_bar())
    except Exception:
        pass
    total = _get_backtest_total_bars(ContextInfo)
    total_hint = f' total_bars={total}' if total is not None else ''
    milestone_times = {'1100', '1309', '1310', '1505'}
    if barpos <= 20 or cur_time in milestone_times or is_last:
        print(f'  [DEBUG][heartbeat] bar={barpos}{total_hint} time={cur_time} is_last={is_last}')
    if is_last:
        pending = _get_pending_schedule(cur_time)
        if pending:
            print(f'  [DEBUG][engine] 回测结束 bar={barpos} time={cur_time}，未执行调度: {" -> ".join(pending)}')


_TICK_LOG_TIMES = frozenset({
    '1030', '1045', '1100', '1115', '1130', '1145',
    '1300', '1309', '1310', '1330', '1345', '1500', '1505',
})


def _debug_bar_tick(ContextInfo, cur_time: str) -> None:
    """
    回测时按关键时间点打印推进日志，避免用户误以为引擎卡死

    输入: ContextInfo, cur_time
    """
    if not ContextInfo.do_back_test or not g.get('enable_debug_log'):
        return
    barpos = ContextInfo.barpos
    if barpos <= 3 or cur_time in _TICK_LOG_TIMES:
        print(f'  [DEBUG][tick] bar={barpos} time={cur_time} 引擎推进中...')


class HoldingSnapshot:
    """
    持仓快照类 - 封装持仓信息

    作用: 将QMT柜台返回的持仓数据封装为统一格式

    输入: vol - 总持仓, can_use - 可用数量, cost - 成本价
    输出: 无
    """
    __slots__ = ('m_nVolume', 'm_nCanUseVolume', 'm_dOpenPrice')

    def __init__(self, vol: Any = 0, can_use: Any = 0, cost: Any = 0):
        self.m_nVolume: int = int(vol or 0)
        self.m_nCanUseVolume: int = int(can_use or 0)
        self.m_dOpenPrice: float = float(cost or 0)

    @staticmethod
    def from_counter_row(dt: Any) -> 'HoldingSnapshot':
        """
        从柜台数据行创建持仓快照

        输入: dt - 柜台返回的持仓数据行
        输出: HoldingSnapshot 实例
        """
        return HoldingSnapshot(
            getattr(dt, 'm_nVolume', 0),
            getattr(dt, 'm_nCanUseVolume', 0),
            getattr(dt, 'm_dOpenPrice', 0)
        )


class QMTTrader:
    """
    QMT交易器类 - 封装与QMT交易柜台的交互逻辑

    作用:
    1. 账户资金与持仓管理
    2. 交易执行（买入/卖出）
    3. 行情数据获取
    4. ETF溢价率查询
    5. 日线数据缓存
    """

    def __init__(
        self,
        context_info,
        strategy_name: str = '通用策略',
        *,
        account: str = 'tests',
        accountType: str = 'STOCK',
        daily_fields_preset: Optional[List[str]] = None,
    ):
        """
        初始化QMT交易器

        输入:
            context_info - QMT策略上下文对象
            strategy_name - 策略名称，用于订单标记
            account - 交易账号（实盘必填）
            accountType - 账号类型，STOCK=股票账户
            daily_fields_preset - 日线数据字段预设

        输出: 无
        """
        self.acct_id: str = account
        self.acct_type: str = accountType
        self.is_backtesting: bool = context_info.do_back_test
        self.strategy_name: str = strategy_name
        self.contextInfo = context_info
        self.stock_info_cache = {}
        self._stock_info_cache_date: str = ''
        self.per_amount = 10000
        self.position = 0
        self.positions: Dict[str, int] = {}
        self.waiting_list = []
        self.last_date: str = ''
        self.stock_code: str = context_info.stockcode + '.' + context_info.market

        if self.is_backtesting:
            if not _local_data_only():
                download_history_data(self.stock_code, context_info.period, '', '')
            print(f'[init][回测模式][初始资金:{context_info.capital}][周期:{context_info.period}]')
        else:
            print(f'[init][交易模式][账号:{self.acct_id}][账号类型:{self.acct_type}]')

        self.buy_code = 23 if self.acct_type == 'STOCK' else 33
        self.sell_code = 24 if self.acct_type == 'STOCK' else 34
        self._daily_data_cache: dict = {}
        self._daily_fields_preset: List[str] = list(daily_fields_preset or ['close', 'amount', 'volume'])

    def get_available_cash(self) -> float:
        """
        获取账户可用资金

        输出: float - 可用资金金额
        """
        result = 0.0
        resultlist = get_trade_detail_data(self.acct_id, self.acct_type, 'ACCOUNT')
        for obj in resultlist:
            if obj.m_dAvailable > 0:
                result = float(obj.m_dAvailable)
        return result

    def get_strategy_total_value(self, context_info) -> float:
        """
        获取策略总资产（现金 + 持仓市值）

        输入: context_info - QMT上下文
        输出: float - 总资产
        """
        total_cash = self.get_available_cash()
        holdings = self.get_holdings()
        position_value = 0.0
        for stock_code, snapshot in holdings.items():
            if snapshot.m_nVolume > 0:
                price = self.get_price(context_info, stock_code=stock_code) or 0
                position_value += price * snapshot.m_nVolume
        return total_cash + position_value

    def get_holdings(self, print_holdings=False) -> Dict[str, HoldingSnapshot]:
        """
        获取账户持仓

        输入: print_holdings - 是否打印持仓明细
        输出: dict - {证券代码: HoldingSnapshot}
        """
        holdinglist: Dict[str, HoldingSnapshot] = {}
        holdings = get_trade_detail_data(self.acct_id, self.acct_type, 'POSITION')
        if print_holdings:
            print('柜台持仓明细:')
        for dt in holdings:
            stock_key = dt.m_strInstrumentID + '.' + dt.m_strExchangeID
            holdinglist[stock_key] = HoldingSnapshot.from_counter_row(dt)
            if print_holdings:
                h = holdinglist[stock_key]
                print(stock_key, h.m_nVolume, h.m_nCanUseVolume, h.m_dOpenPrice)
        if self.stock_code in holdinglist:
            self.position = holdinglist[self.stock_code].m_nCanUseVolume
        else:
            self.position = 0
        return holdinglist

    def get_stock_info(self, symbol, field=None):
        """
        获取证券详细信息（带缓存，按日过期）

        输入: symbol - 证券代码, field - 要获取的字段（可选）
        输出: dict 或 指定字段值
        """
        try:
            today = datetime.now().strftime('%Y%m%d')
            if self._stock_info_cache_date != today:
                self.stock_info_cache.clear()
                self._stock_info_cache_date = today
            cache = self.stock_info_cache
            if symbol not in cache:
                info = self.contextInfo.get_instrument_detail(symbol)
                if info:
                    cache[symbol] = info
            info = cache[symbol]
            if info:
                if field:
                    return info.get(field)
                return info
            return None
        except Exception:
            return None

    def is_valid_stock_in_date(self, code: str, date='') -> bool:
        """
        检查证券在指定日期是否有效（在交易日内且未到期）

        输入: code - 证券代码, date - 日期（可选，默认今天）
        输出: bool - 有效则返回 True
        """
        info = self.get_stock_info(code)
        if not info:
            return False
        open_date = info.get('OpenDate')
        if (not open_date and info.get('PreClose') == 1.0) or open_date == 19700101:
            return False
        if date == '':
            date = int(datetime.now().strftime("%Y%m%d"))
        else:
            date = int(date)
        if date < open_date:
            return False
        expire_date = info.get('ExpireDate', 0)
        if expire_date and date >= expire_date:
            return False
        return True

    def get_valid_stock_list(self, sectors: List[str] = None, date='') -> List[str]:
        """
        获取指定板块内的有效证券列表

        输入: sectors - 板块列表（默认['沪深ETF']), date - 日期
        输出: list - 有效证券代码列表
        """
        if sectors is None:
            sectors = ['沪深ETF']
        if date == '':
            date = datetime.now().strftime("%Y%m%d")
        try:
            all_codes = []
            for sector in sectors:
                try:
                    codes = self.contextInfo.get_stock_list_in_sector(sector)
                    all_codes.extend(codes)
                except Exception as e:
                    print(f"【ETF列表】获取板块 '{sector}' 证券列表失败: {e}")
                    continue
            all_codes = list(set(all_codes))
            valid_codes = []
            for code in all_codes:
                try:
                    info = self.get_stock_info(code)
                    if not info:
                        continue
                    if not self.is_backtesting and info.get('InstrumentStatus', 0) >= 1:
                        continue
                    if self.is_valid_stock_in_date(code, date):
                        valid_codes.append(code)
                except:
                    continue
            return valid_codes
        except Exception as e:
            print(f"【板块证券列表】获取有效证券列表异常: {e}")
            return []

    def get_price(self, context_info, stock_code=None, is_bar_price=True):
        """
        获取证券当前价格

        输入:
            context_info - QMT上下文
            stock_code - 证券代码（默认主图标的）
            is_bar_price - 是否使用K线价格

        输出: float 或 None - 当前价格
        """
        if stock_code is None:
            stock_code = self.stock_code
        if self.is_backtesting or not is_bar_price:
            timetag = context_info.get_bar_timetag(context_info.barpos)
            endtime = timetag_to_datetime(timetag, '%Y%m%d%H%M%S')
            df = _market_data_ex_local(
                context_info, ['close', 'lastPrice'], [stock_code],
                context_info.period, end_time=endtime, count=1,
            )
            if not df or stock_code not in df or _is_empty(df[stock_code]):
                return None
            block = df[stock_code]
            current_price = _get_field_last(block, 'lastPrice')
            if current_price is None or _is_nan(current_price):
                current_price = _get_field_last(block, 'close')
            return float(current_price) if current_price is not None and not _is_nan(current_price) else None
        else:
            tick = context_info.get_full_tick([stock_code])
            tick_data = tick.get(stock_code)
            if tick_data:
                return tick_data['lastPrice']
            return None

    def execute_trade(
        self, context_info, signal: str, amount: int = None, price: float = -1, stock_code: str = None,
    ) -> bool:
        """
        执行交易指令

        输入:
            context_info - QMT上下文
            signal - 信号 'buy' 或 'sell'
            amount - 数量
            price - 价格（-1表示市价）
            stock_code - 证券代码

        输出: bool - 成功返回 True
        """
        if signal not in ['buy', 'sell']:
            return False
        if amount is None:
            amount = self.per_amount
        if amount <= 0:
            return False
        if not self.is_backtesting:
            if not context_info.is_last_bar():
                return False
            if self.waiting_list:
                orders = get_trade_detail_data(self.acct_id, self.acct_type, 'order', self.strategy_name)
                found_list = [o.m_strRemark for o in orders if o.m_strRemark in self.waiting_list]
                self.waiting_list = [i for i in self.waiting_list if i not in found_list]
                if len(self.waiting_list) > 0:
                    return False
        if signal == 'buy':
            return self._execute_buy(context_info, amount, price, stock_code=stock_code)
        return self._execute_sell(context_info, amount, price, stock_code=stock_code)

    def _execute_buy(self, context_info, amount: int, price: float = -1, *, stock_code: Optional[str] = None) -> bool:
        """内部方法：执行买入"""
        code = stock_code or self.stock_code
        cur_price = price if price != -1 else self.get_price(context_info, stock_code=code)
        est_cost = (cur_price * amount) if cur_price else 0.0
        if cur_price:
            avail = self.get_available_cash() if self.is_backtesting else self.available_cash
            if avail < est_cost:
                return False
        if self.is_backtesting and not cur_price:
            return False
        self.available_cash = self.get_available_cash()
        curdatetime = self.get_current_time(context_info, '%Y-%m-%d %H:%M:%S')
        msg = f'[{curdatetime}][{self.strategy_name}][{code}][buy] {amount}'
        passorder(self.buy_code, 1101, self.acct_id, code, 14, price, amount, self.strategy_name, 1, msg, context_info)
        self.waiting_list.append(msg)
        self.positions[code] = self.positions.get(code, 0) + amount
        if code == self.stock_code:
            self.position += amount
        return True

    def _execute_sell(self, context_info, amount, price=-1, *, stock_code: Optional[str] = None):
        """内部方法：执行卖出"""
        code = stock_code or self.stock_code
        if self.is_backtesting:
            strat_vol = int(self.positions.get(code, 0))
            if strat_vol <= 0:
                holdings = self.get_holdings()
                if code in holdings:
                    strat_vol = int(holdings[code].m_nCanUseVolume or holdings[code].m_nVolume or 0)
            if amount > strat_vol:
                return False
        else:
            holdings = self.get_holdings()
            can = holdings[code].m_nCanUseVolume if code in holdings else 0
            if amount > can:
                return False
        curdatetime = self.get_current_time(context_info, '%Y-%m-%d %H:%M:%S')
        msg = f'[{curdatetime}][{self.strategy_name}][{code}][sell] {amount}'
        passorder(self.sell_code, 1101, self.acct_id, code, 14, price, amount, self.strategy_name, 1, msg, context_info)
        self.waiting_list.append(msg)
        nv = self.positions.get(code, 0) - amount
        if nv <= 0:
            self.positions.pop(code, None)
        else:
            self.positions[code] = nv
        if code == self.stock_code:
            self.position -= amount
        return True

    def get_current_time(self, context_info: Any, fmt='%H%M%S') -> str:
        """
        获取当前K线时间

        输入: context_info - QMT上下文, fmt - 时间格式
        输出: str - 格式化的时间字符串
        """
        return timetag_to_datetime(context_info.get_bar_timetag(context_info.barpos), fmt)

    def get_recent_trading_days(self, *, start_date='', end_date='', count=8000, end_date_inclusive=False) -> List[str]:
        """
        获取最近的交易日列表

        输入: start_date - 起始日期, end_date - 截止日期, count - 数量, end_date_inclusive - 截止日是否包含
        输出: list - 交易日列表 ['YYYYMMDD', ...]
        """
        if not end_date_inclusive:
            count += 1
        raw_dates = self.contextInfo.get_trading_dates('SH', start_date, end_date, count, '1d')
        if raw_dates:
            trading_days: List[str] = []
            for d in raw_dates:
                if end_date_inclusive or d != end_date:
                    trading_days.append(d)
            return trading_days
        return []

    def get_prev_trade_date(self, date='') -> str:
        """
        获取指定日期的前一个交易日

        输入: date - 日期（默认今天）
        输出: str - 前一交易日
        """
        trading_days = self.get_recent_trading_days(end_date=date, count=2, end_date_inclusive=False)
        return trading_days[-1] if trading_days else ''

    @staticmethod
    def is_etf(stock_code: str, market: str) -> bool:
        """判断是否为ETF"""
        return is_typed_stock(100013, stock_code, market)

    def is_trading_time(self, context_info, curtime='') -> bool:
        """
        判断是否在交易时间内

        输入: context_info - QMT上下文, curtime - 时间（默认当前）
        输出: bool - 在交易时间内返回 True
        """
        if not curtime:
            curtime = self.get_current_time(context_info)
        return '093000' <= curtime <= '145700'

    def is_new_calendar_day(self, context_info, curdate='') -> bool:
        """
        判断是否是新日历日

        输入: context_info - QMT上下文, curdate - 日期
        输出: bool - 新的一天返回 True
        """
        if curdate == '':
            curdate = self.get_current_time(context_info, '%Y%m%d')
        changed = curdate != self.last_date
        if changed:
            self.last_date = curdate
        return changed

    def estimate_today_volume(self, context_info: Any, today_vol: float, cur_dt: str = '') -> float:
        """
        估算今日全天成交量

        输入: context_info - QMT上下文, today_vol - 当前成交量, cur_dt - 当前时间
        输出: float - 估算的全天成交量
        """
        if not cur_dt:
            cur_dt = self.get_current_time(context_info, '%Y%m%d%H%M%S')
        hour = int(cur_dt[8:10])
        minute = int(cur_dt[10:12])
        elapsed_minutes = (hour - 9) * 60 + minute - 30
        if hour >= 13:
            elapsed_minutes -= 90
        elapsed_minutes = max(1, min(elapsed_minutes, 240))
        return today_vol * (240.0 / elapsed_minutes)

    def get_volume_ratio(self, ContextInfo: Any, hist_volumes, today_vol: float, lookback_days=5):
        """
        计算成交量比（预估今日量/历史均量）

        输入: ContextInfo - QMT上下文, hist_volumes - 历史成交量, today_vol - 今日成交量, lookback_days - 回看天数
        输出: float 或 None - 成交量比
        """
        if hist_volumes is None or len(hist_volumes) < lookback_days:
            return None
        past_n_days_vol = _to_list(hist_volumes)[-lookback_days:]
        if any(_is_nan(v) or float(v) == 0 for v in past_n_days_vol):
            return None
        avg_volume = _mean_values(past_n_days_vol)
        if avg_volume == 0:
            return None
        projected_today_vol = self.estimate_today_volume(ContextInfo, today_vol)
        return projected_today_vol / avg_volume if projected_today_vol > 0 else 0

    def get_premium_rate(self, etf: str, current_price: Optional[float]) -> Optional[float]:
        """
        获取ETF溢价率（实盘可用）

        输入: etf - ETF代码, current_price - 当前价格
        输出: float 或 None - 溢价率（小数形式，如0.05表示5%）
        """
        if self.is_backtesting:
            return 0.0
        if current_price is None or (isinstance(current_price, (int, float)) and (current_price <= 0 or current_price != current_price)):
            return None
        try:
            iopv: float = get_etf_iopv(etf)
            if iopv <= 0 or _is_nan(iopv):
                return None
            return (float(current_price) - iopv) / iopv
        except Exception as e:
            return None

    def has_local_data(self, context_info, code: str, period: str, end_time: str = '') -> bool:
        """
        检查本地是否有指定数据

        输入: context_info - QMT上下文, code - 证券代码, period - 周期, end_time - 截止时间
        输出: bool - 有数据返回 True
        """
        block = _call_get_local_data(context_info, code, period, end_time=end_time)
        if _has_valid_market_block(block):
            return True
        data = _market_data_ex_local(context_info, ['close'], [code], period, end_time=end_time, count=5)
        if data and code in data:
            return _has_valid_market_block(data[code])
        return False

    def try_get_local_block(self, context_info, code: str, period: str, end_time: str = '', count: int = 500) -> Any:
        """
        尝试获取本地数据块

        输入: context_info - QMT上下文, code - 证券代码, period - 周期, end_time - 截止时间, count - 数量
        输出: 数据块或 None
        """
        block = _call_get_local_data(context_info, code, period, end_time=end_time, count=count)
        if _has_valid_market_block(block):
            return block
        data = _market_data_ex_local(
            context_info, ['close', 'open', 'high', 'low', 'volume', 'amount'],
            [code], period, end_time=end_time, count=count,
        )
        if data and code in data and _has_valid_market_block(data[code]):
            return data[code]
        return None

    def get_daily_data_cached(
        self, fields: List[str], codes: List[str], count: int,
        end_time: Optional[str] = '', start_time: Optional[str] = '',
        subscribe: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """
        获取日线数据（带缓存）

        输入:
            fields - 字段列表
            codes - 证券代码列表
            count - 数据条数
            end_time - 截止时间
            start_time - 起始时间
            subscribe - 是否订阅

        输出: dict - {证券代码: {字段: 数据}}
        """
        cache = self._daily_data_cache
        if _local_data_only():
            subscribe = False
        if not end_time:
            end_time = self.get_current_time(self.contextInfo, '%Y%m%d')
        fetch_fields = list(set(fields) | set(self._daily_fields_preset))
        self._daily_fields_preset = fetch_fields
        codes_needed: List[str] = []
        today = datetime.now()
        end_time_dt = datetime.strptime(str(end_time)[:8], '%Y%m%d')
        fetch_count = max(count + (today - end_time_dt).days, 500)

        for code in codes:
            entry = cache.get(code)
            if entry is None:
                codes_needed.append(code)
                continue
            cached_data = entry.get('data', {})
            cached_count = entry.get('count', 0)
            if cached_count >= fetch_count and all(f in cached_data for f in fields):
                continue
            codes_needed.append(code)

        if codes_needed:
            fetch_codes = list(set(codes_needed))
            missing_codes: List[str] = []

            def _cache_raw_data(raw_dict, field_list):
                ok = 0
                for code, raw in raw_dict.items():
                    entry = {'data': {}, 'count': 0}
                    for f in field_list:
                        if f in raw and raw[f] is not None and len(raw[f]) > 0:
                            entry['data'][f] = raw[f]
                    if entry['data']:
                        first_ser = next(iter(entry['data'].values()))
                        entry['count'] = len(first_ser)
                        cache[code] = entry
                        ok += 1
                return ok

            for code in fetch_codes:
                loaded = False
                local_block = self.try_get_local_block(self.contextInfo, code, '1d', end_time=end_time, count=fetch_count)
                if local_block is not None:
                    wrapped = {code: local_block}
                    if _cache_raw_data(wrapped, fetch_fields) > 0:
                        loaded = True
                if not loaded:
                    single_data = _market_data_ex_local(
                        self.contextInfo, fetch_fields, [code], '1d',
                        end_time=str(end_time)[:8], count=fetch_count,
                    )
                    if single_data and code in single_data and _cache_raw_data(single_data, fetch_fields) > 0:
                        loaded = True
                if not loaded:
                    missing_codes.append(code)

            if missing_codes:
                _print_missing_local_data('日线', missing_codes, '1d')

        result: Dict[str, Dict[str, Any]] = {}
        if not fields:
            fields = self._daily_fields_preset
        for code in codes:
            entry = cache.get(code)
            if entry is None:
                continue
            cached_data = entry.get('data', {})
            result[code] = {}
            for f in fields:
                ser = cached_data.get(f)
                if ser is not None and len(ser) > 0:
                    if end_time:
                        end_str = str(end_time)[:8]
                        ser = _filter_series_by_end_date(ser, end_str)
                    sliced = _tail_series(ser, count) if len(ser) > 0 else ser
                    result[code][f] = sliced
        return result


trader: QMTTrader  # 全局交易器实例


# =============================================================================
# 全局变量初始化
# =============================================================================

def init_global_vars(ContextInfo):
    """
    初始化全局策略变量

    作用: 集中配置所有策略参数、ETF池、状态标记

    输入: ContextInfo - QMT上下文
    输出: 无（仅设置全局变量 g）
    """
    global g
    g = {}

    g['etf_sell_time'] = '1309'
    g['etf_buy_time'] = '1310'
    g['regime_check_time'] = '0940'

    g['dl_history_data_date'] = ''
    g['local_history_check_date'] = ''
    g['local_data_only'] = LOCAL_DATA_ONLY
    g['enable_detailed_log'] = False
    g['enable_debug_log'] = False
    g['rankings_cache'] = {'date': None, 'data': None}
    g['target_etfs_cache'] = {'date': None, 'data': None}

    g['check_positions_done'] = False
    g['regime_check_done'] = False
    g['profit_protection_done_times'] = set()
    g['etf_sell_done'] = False
    g['etf_buy_done'] = False
    g['daily_summary_done'] = False
    g['daily_preload_done'] = False
    g['debug_schedule_hint_date'] = ''

    g['lookback_days'] = 25
    g['holdings_num'] = 1
    g['defensive_etf'] = '511010.SH'
    g['min_money'] = 5000

    g['enable_profit_protection'] = True
    g['profit_protection_lookback'] = 1
    g['profit_protection_threshold'] = 0.05
    g['profit_protection_check_times'] = ['11:00']

    g['drawdown_selled_today'] = set()
    g['buy_date'] = {}
    g['trade_log'] = {'sell_records': []}

    g['loss'] = 0.97

    g['min_score_threshold'] = 0
    g['max_score_threshold'] = 100.0

    g['enable_volume_check'] = True
    g['volume_lookback'] = 5
    g['volume_threshold'] = 3.6
    g['volume_return_limit'] = 1

    g['use_short_momentum_filter'] = True
    g['short_lookback_days'] = 10
    g['short_momentum_threshold'] = 0.0

    g['enable_premium_filter'] = True
    g['premium_threshold'] = 0.20

    g['intraday_drawdown_threshold'] = 0.02

    g['enable_regime_switch'] = True
    g['weak_period_ma_lookback'] = 10
    g['weak_period_max_days'] = 20
    g['is_a_share_weak'] = False
    g['weak_period_counter'] = 0

    g['enable_avoid_a_share'] = True
    g['enable_intraday_drawdown'] = True

    g['regime_indexes'] = {
        '沪深300': '000300.SH',
        '深证综指': '399101.SZ',
        '创业板指': '399006.SZ',
        '中证A500': '000510.SH',
    }


    g['overseas_etf_pool'] = [
        "513100.SH",
        "513290.SH",
        "513500.SH",
        "159529.SZ",
        "513400.SH",
        "513520.SH",
        "513030.SH",
        "513080.SH",
        "513310.SH",
        "513730.SH",
        "159792.SZ",
        "513130.SH",
        "513050.SH",
        "159920.SZ",
        "513690.SH",
        "511380.SH",
        "511010.SH",
        "511220.SH",
    ]

    g['commodity_etf_pool'] = [
        "518880.SH",
        "159980.SZ",
        "159985.SZ",
        "501018.SH",
        '161226.SZ',
        "159981.SZ",
        "512400.SH",
    ]

    g['domestic_etf_pool'] = [
        "510300.SH",
        "510500.SH",
        "510050.SH",
        "510210.SH",
        "159915.SZ",
        "588080.SH",
        "512100.SH",
        "563360.SH",
        "563300.SH",
        "512890.SH",
        "159967.SZ",
        "588020.SH",
        "512040.SH",
        "159201.SZ",
        "515790.SH",
        "563230.SH",
        "515880.SH",
        "512660.SH",
        "561380.SH",
        "159667.SZ",
        "159559.SZ",
        "159819.SZ",
        "159381.SZ",
        "159732.SZ",
        "159995.SZ",
        "512220.SH",
    ]

    g['etf_pool'] = g['overseas_etf_pool'] + g['commodity_etf_pool'] + g['domestic_etf_pool']

    g['all_subscribe_codes'] = list(set(g['etf_pool'] + list(g['regime_indexes'].values())))


def init(ContextInfo):
    """
    策略初始化入口函数 - QMT策略启动时调用一次

    作用: 初始化交易器、配置参数、检查数据

    调度时间表:
    - 09:10 持仓检查
    - 09:40 行情判断
    - 11:00 盈利保护
    - 09:46起 分钟回撤(走弱期)
    - 13:09 卖出 / 13:10 买入
    - 15:05 日报

    输入: ContextInfo - QMT策略上下文对象
    输出: 无
    """
    global trader

    trader = QMTTrader(
        ContextInfo,
        strategy_name='七星高照ETF轮动超级增强',
        account=account if 'account' in globals() else 'tests',
        accountType=accountType if 'accountType' in globals() else 'STOCK',
    )

    init_global_vars(ContextInfo)

    if trader.is_backtesting:
        g['enable_debug_log'] = True
        g['enable_detailed_log'] = True
        print('  [DEBUG] 回测模式已开启详细日志 (enable_debug_log=True)')
        try:
            ContextInfo.set_universe(g['all_subscribe_codes'])
            print(f'  [DEBUG][init] set_universe({len(g["all_subscribe_codes"])}只)')
        except Exception as e:
            print(f'  [DEBUG][init] set_universe 跳过: {e}')

    print_init_params()

    check_local_history_data(ContextInfo, 'init')

    if not _local_data_only():
        for code in g['all_subscribe_codes']:
            ContextInfo.subscribe_quote(code, period='1m')

    # init 阶段 barpos 尚未推进，cur_date 常为 19700101，此处预加载会误报失败，改到首个有效交易日再加载
    cur_init_date = trader.get_current_time(ContextInfo, '%Y%m%d')[:8]
    bt_start = str(getattr(ContextInfo, 'start', ''))
    bt_end = str(getattr(ContextInfo, 'end', ''))
    print(f'  [DEBUG][init] 回测配置: start={bt_start} end={bt_end} period={ContextInfo.period}')
    if _is_valid_backtest_date(cur_init_date):
        _preload_daily_data(ContextInfo, cur_init_date, label='init')
    else:
        print(f'  [DEBUG][init] 回测尚未开始(cur_date={cur_init_date})，日线预加载推迟到首个有效交易日')
        if bt_start in ('', '-1', 'None') or bt_end in ('', '-1', 'None'):
            print('  [DEBUG][init] ?? 回测起止日期未设置(start/end=-1)，请在QMT回测界面指定有效日期区间')


def print_init_params():
    print(f"""【七星高照ETF轮动超级增强】启动！(QMT版本 - 单文件)
 === 策略参数初始化完成 ===
 === ETF池配置 ===
 - 海外ETF: {len(g['overseas_etf_pool'])}只
 - 商品ETF: {len(g['commodity_etf_pool'])}只
 - A股ETF: {len(g['domestic_etf_pool'])}只
 - 完整池: {len(g['etf_pool'])}只
 - 动量周期: {g['lookback_days']}天
 - 持仓数量: {g['holdings_num']}只
 - 防御ETF: {g['defensive_etf']}
 === 盈利保护 ===
 - 开关: {'开启' if g['enable_profit_protection'] else '关闭'}
 - 回看周期: {g['profit_protection_lookback']}天
 - 回撤阈值: {g['profit_protection_threshold']*100:.0f}%
 - 检查时间点: {g['profit_protection_check_times']}
 === 过滤条件 ===
 - 成交量过滤: {'启用' if g['enable_volume_check'] else '禁用'} (近{g['volume_lookback']}日均量比 < {g['volume_threshold']})
 - 年化收益放量阈值: {g['volume_return_limit']*100:.0f}%
 - 短期动量过滤: {'启用' if g['use_short_momentum_filter'] else '禁用'} ({g['short_lookback_days']}天)
 - 近3日单日跌幅: < {(1-g['loss'])*100:.0f}%
 - 溢价率过滤: {'启用' if g['enable_premium_filter'] else '禁用'} (阈值<={g['premium_threshold']*100:.0f}%)
 === 行情判断 ===
 - 开关: {'启用' if g['enable_regime_switch'] else '关闭'}
 - 走弱期最长: {g['weak_period_max_days']}日
 - 回避A股开关: {'ON' if g['enable_avoid_a_share'] else 'OFF'}
 - 分钟回撤开关: {'ON' if g['enable_intraday_drawdown'] else 'OFF'}
 - 回撤阈值: {g['intraday_drawdown_threshold']*100:.0f}%
 === 日内调度 ===
 - 09:10 持仓检查
 - 09:40 行情判断
 - 盈利保护检查: {g['profit_protection_check_times']}
 - 09:46起 分钟级回撤检查（仅走弱期）
 - 13:09 卖出操作
 - 13:10 买入操作
 - 15:05 盘后总结报告
""")


def handlebar(ContextInfo):
    """
    K线回调函数 - 策略主入口，每根K线触发一次

    作用: 根据时间触发调度任务

    输入: ContextInfo - QMT策略上下文对象
    输出: 无
    """
    if not ContextInfo.do_back_test and not ContextInfo.is_last_bar():
        return
    global trader
    try:
        _handlebar_body(ContextInfo)
    except Exception as e:
        barpos = getattr(ContextInfo, 'barpos', '?')
        print(f'  [FATAL][handlebar] bar={barpos} 异常中断: {e}')
        import traceback
        traceback.print_exc()
        raise


def _handlebar_body(ContextInfo):
    """
    handlebar处理主体 - 包含所有定时调度逻辑

    作用: 按时间顺序执行持仓检查、行情判断、盈利保护、卖出/买入等任务

    输入: ContextInfo - QMT策略上下文对象
    输出: 无
    """
    global trader
    cur_dt = trader.get_current_time(ContextInfo, '%Y%m%d%H%M')
    cur_date = cur_dt[:8]
    cur_time = cur_dt[8:]

    if trader.is_new_calendar_day(ContextInfo, cur_date):
        g['check_positions_done'] = False
        g['regime_check_done'] = False
        g['profit_protection_done_times'] = set()
        g['etf_sell_done'] = False
        g['etf_buy_done'] = False
        g['daily_summary_done'] = False
        g['rankings_cache'] = {'date': None, 'data': None}
        g['target_etfs_cache'] = {'date': None, 'data': None}
        g['drawdown_selled_today'] = set()
        g['trade_log'] = {'sell_records': []}
        g['daily_preload_done'] = False
        g['debug_schedule_hint_date'] = ''
        print(f'{"★" * 10} [{cur_date}] {cur_time} 新交易日日开始 {"★" * 10}')
        if g.get('enable_debug_log'):
            bt_start = str(getattr(ContextInfo, 'start', ''))
            bt_end = str(getattr(ContextInfo, 'end', ''))
            print(f'  [DEBUG][engine] 回测区间={bt_start}~{bt_end} barpos={ContextInfo.barpos} 首根K线时间={cur_time}')
            pending = _get_pending_schedule(cur_time)
            if pending:
                print(f'  [DEBUG][engine] 今日待执行调度: {" -> ".join(pending)}')
            print('  [DEBUG][engine] 10:27~11:00 之间无定时任务，引擎仍在逐分钟推进，日志会暂时静默')

    if not g['check_positions_done'] and cur_time >= '0910':
        _debug(f'[调度] 触发持仓检查 bar={ContextInfo.barpos} time={cur_time}')
        check_positions(ContextInfo)
        g['check_positions_done'] = True

    if not g['regime_check_done'] and cur_time >= g['regime_check_time']:
        _debug(f'[调度] 触发行情判断 bar={ContextInfo.barpos} time={cur_time} threshold={g["regime_check_time"]}')
        regime_check(ContextInfo, cur_date)
        g['regime_check_done'] = True
    elif not g['regime_check_done'] and g.get('enable_debug_log') and cur_time in ('0930', '0935', '0940'):
        _debug(f'[调度] 等待行情判断 time={cur_time} < {g["regime_check_time"]}')

    for check_time in g['profit_protection_check_times']:
        check_time_str = check_time.replace(':', '')
        if check_time not in g['profit_protection_done_times'] and cur_time >= check_time_str:
            _debug(f'[调度] 触发盈利保护 bar={ContextInfo.barpos} time={cur_time}')
            profit_protection_check(ContextInfo)
            g['profit_protection_done_times'].add(check_time)

    if is_intraday_drawdown_enabled() and cur_time >= '0946' and cur_time < '1500':
        intraday_drawdown_check(ContextInfo, cur_date, cur_time)

    if not g['etf_sell_done'] and cur_time >= g['etf_sell_time']:
        _debug(f'[调度] 触发卖出 bar={ContextInfo.barpos} time={cur_time} threshold={g["etf_sell_time"]}')
        check_local_history_data(ContextInfo, cur_date)
        etf_sell_trade(ContextInfo, cur_date, cur_time)
        g['etf_sell_done'] = True
    elif not g['etf_sell_done'] and g.get('enable_debug_log') and cur_time in ('1300', '1305', '1309'):
        _debug(f'[调度] 等待卖出 time={cur_time} < {g["etf_sell_time"]}')

    if not g['etf_buy_done'] and cur_time >= g['etf_buy_time']:
        _debug(f'[调度] 触发买入 bar={ContextInfo.barpos} time={cur_time} threshold={g["etf_buy_time"]}')
        etf_buy_trade(ContextInfo, cur_date, cur_time)
        g['etf_buy_done'] = True
    elif not g['etf_buy_done'] and g.get('enable_debug_log') and cur_time in ('1309', '1310'):
        _debug(f'[调度] 等待买入 time={cur_time} < {g["etf_buy_time"]}')

    if not g['daily_summary_done'] and cur_time >= '1505':
        _debug(f'[调度] 触发日报 bar={ContextInfo.barpos} time={cur_time}')
        daily_summary_report(ContextInfo, cur_date)
        g['daily_summary_done'] = True

    if (
        g.get('enable_debug_log')
        and g.get('debug_schedule_hint_date') != cur_date
        and g.get('regime_check_done')
        and not g.get('etf_sell_done')
        and cur_time >= g.get('regime_check_time', '0940')
        and cur_time < g.get('etf_sell_time', '1309')
    ):
        pending = _get_pending_schedule(cur_time)
        if pending:
            print(f'  [DEBUG][engine] bar={ContextInfo.barpos} time={cur_time} 引擎正常推进，下一任务: {pending[0]}')
            g['debug_schedule_hint_date'] = cur_date

    _debug_bar_tick(ContextInfo, cur_time)
    _log_backtest_progress(ContextInfo, cur_date, cur_time)


def check_positions(ContextInfo):
    """
    持仓检查函数 - 每日09:10执行

    作用: 打印当前所有持仓的详细信息

    输入: ContextInfo - QMT上下文
    输出: 无
    """
    try:
        holdings = trader.get_holdings()
        for sec, pos in holdings.items():
            if pos.m_nVolume > 0:
                name = get_stock_name(sec)
                cost = pos.m_dOpenPrice
                cur_price = trader.get_price(ContextInfo, sec) or 0
                print(f"  持仓：{sec} {name} 数量{pos.m_nVolume} 成本{cost:.3f} 现价{cur_price:.3f}")
    except Exception as e:
        print(f"【持仓检查】获取持仓失败: {e}")


def regime_check(ContextInfo, cur_date: str):
    """
    行情判断函数 - 每日09:40执行

    作用: 根据指数均线判断A股市场状态（走弱期/正常期）

    判断逻辑:
    - 获取沪深300、深证综指、创业板指、中证A500四个指数
    - 比较当前价格与MA10均线的位置
    - >=3个指数跌破 -> 进入"走弱期"
    - >=3个指数站上 -> 恢复正常期

    输入: ContextInfo - QMT上下文, cur_date - 当前日期
    输出: 无
    """
    print("========== 行情判断开始 ==========")

    if not g['enable_regime_switch']:
        g['is_a_share_weak'] = False
        print("  行情判断未启用，始终全市场交易")
        print("========== 行情判断完成 ==========")
        return

    end_date = trader.get_prev_trade_date(cur_date)
    _debug(f'[行情判断] cur_date={cur_date} prev_trade_date(end_date)={end_date} MA周期={g["weak_period_ma_lookback"]} 进入阈值=跌破>=3 恢复阈值=站上>=3')
    if not end_date:
        print("  [warning] 无法获取前一交易日，跳过行情判断")
        print("========== 行情判断完成 ==========")
        return

    index_codes = list(g['regime_indexes'].values())
    index_data = trader.get_daily_data_cached(
        ['close'], index_codes,
        count=g['weak_period_ma_lookback'] + 2, end_time=end_date
    )
    _debug(f'[行情判断] 指数日线请求{len(index_codes)}只 返回{len(index_data or {})}只有效')

    below_count, above_count = 0, 0
    detail = []
    skipped_indexes = []

    for name, code in g['regime_indexes'].items():
        try:
            if not index_data or code not in index_data:
                skipped_indexes.append(f'{name}({code}):无数据')
                print(f"  [warning][行情判断] {name}({code}) 日线未返回")
                continue
            data = index_data[code]
            if 'close' not in data or len(data['close']) < g['weak_period_ma_lookback']:
                bar_n = len(data.get('close', []) or [])
                skipped_indexes.append(f'{name}({code}):bars={bar_n}')
                print(f"  [warning][行情判断] {name}({code}) 日线不足: 需要{g['weak_period_ma_lookback']}根 实际{bar_n}根")
                continue
            closes = _to_list(data['close'])[-g['weak_period_ma_lookback']:]
            current_price = closes[-1]
            ma_val = _mean_values(closes)
            is_below = current_price < ma_val
            if is_below:
                below_count += 1
                detail.append(f"{name}↓")
            else:
                above_count += 1
                detail.append(f"{name}↑")
            print(f"  [行情判断] {name}({code}): 收盘={current_price:.3f} MA{g['weak_period_ma_lookback']}={ma_val:.3f} {'跌破↓' if is_below else '站上↑'} bars={len(closes)}")
        except Exception as e:
            skipped_indexes.append(f'{name}({code}):异常')
            print(f"  [warning] 指数{name}获取失败: {e}")

    if skipped_indexes:
        print(f"  [DEBUG][行情判断] 跳过指数: {', '.join(skipped_indexes)}")
    print(f"  [DEBUG][行情判断] 统计: 跌破={below_count} 站上={above_count} (有效指数={below_count + above_count}/{len(g['regime_indexes'])})")

    old_state = g['is_a_share_weak']

    if not g['is_a_share_weak']:
        if below_count >= 3:
            g['is_a_share_weak'] = True
            g['weak_period_counter'] = 0
            print(f"  ?? 进入走弱期 (跌破:{below_count} {detail})")
            if g['enable_avoid_a_share']:
                print(f"     → 将回避A股ETF，仅交易海外+商品ETF")
            else:
                print(f"     → ?? 回避A股开关已关闭，仍交易全市场ETF")
            if g['enable_intraday_drawdown']:
                print(f"     → ??? 分钟级回撤保护已启用（阈值{g['intraday_drawdown_threshold']*100:.0f}%）")
            else:
                print(f"     → ? 分钟级回撤保护已被独立开关关闭，不触发")
    else:
        g['weak_period_counter'] += 1
        if above_count >= 3:
            g['is_a_share_weak'] = False
            g['weak_period_counter'] = 0
            print(f"  ?? 恢复正常期 (站上:{above_count} {detail})")
            if g['enable_avoid_a_share']:
                print(f"     → 恢复交易A股ETF")
            else:
                print(f"     → 回避A股开关关闭，始终交易全市场")
            if g['enable_intraday_drawdown']:
                print(f"     → 关闭分钟级回撤保护")
            else:
                print(f"     → 分钟级回撤保护独立开关已关闭，无变化")
        elif g['weak_period_counter'] >= g['weak_period_max_days']:
            g['is_a_share_weak'] = False
            g['weak_period_counter'] = 0
            print(f"  ? 走弱期满{g['weak_period_max_days']}日强制退出，恢复正常期")
            if g['enable_avoid_a_share']:
                print(f"     → 恢复交易A股ETF")
            else:
                print(f"     → 回避A股开关关闭，始终交易全市场")
            if g['enable_intraday_drawdown']:
                print(f"     → 关闭分钟级回撤保护")
            else:
                print(f"     → 分钟级回撤保护独立开关已关闭，无变化")

    if old_state != g['is_a_share_weak']:
        g['rankings_cache'] = {'date': None, 'data': None}

    if g['enable_regime_switch']:
        current_status = '走弱期' if g['is_a_share_weak'] else '正常期'
        avoid_status = '(回避A股)' if (g['is_a_share_weak'] and g['enable_avoid_a_share']) else ('(不回避A股)' if g['is_a_share_weak'] else '')
        drawdown_status = '启用' if (g['is_a_share_weak'] and g['enable_intraday_drawdown']) else '关闭'
        state_changed = '是' if old_state != g['is_a_share_weak'] else '否'
        if g['is_a_share_weak'] and g['enable_avoid_a_share']:
            active_pool_n = len(g['overseas_etf_pool']) + len(g['commodity_etf_pool'])
        else:
            active_pool_n = len(g['etf_pool'])
        print(f"  当前状态：{current_status}{avoid_status} 计数:{g['weak_period_counter']}/{g['weak_period_max_days']}")
        print(f"  分钟级回撤保护：{drawdown_status}（阈值{g['intraday_drawdown_threshold']*100:.0f}%）")
        print(f"  [DEBUG][行情判断] 状态变更={state_changed} 旧={'走弱' if old_state else '正常'} -> 新={'走弱' if g['is_a_share_weak'] else '正常'} 当前可用ETF池={active_pool_n}只")
    print("========== 行情判断完成 ==========")


def is_intraday_drawdown_enabled() -> bool:
    """
    判断是否启用日内回撤保护

    作用: 走弱期才启用分钟级回撤检查

    输出: bool - True表示启用
    """
    if not g['enable_intraday_drawdown']:
        return False
    if not g['enable_regime_switch']:
        return False
    return g['is_a_share_weak']


def get_active_etf_pool() -> List[str]:
    """
    根据市场状态返回当前可交易的ETF池

    作用: 走弱期回避A股，正常期使用完整池

    输出: list - 当前可交易的ETF代码列表
    """
    if not g['enable_avoid_a_share']:
        return g['etf_pool']
    if g['is_a_share_weak']:
        return g['overseas_etf_pool'] + g['commodity_etf_pool']
    else:
        return g['etf_pool']


def intraday_drawdown_check(ContextInfo, cur_date: str, cur_time: str):
    """
    分钟级回撤检查 - 仅在走弱期执行，09:46起每分钟检查

    作用: 监控持仓ETF日内回撤，超过阈值时触发止损卖出

    输入: ContextInfo - QMT上下文, cur_date - 日期, cur_time - 时间
    输出: 无
    """
    holdings = trader.get_holdings()
    for sec, pos in holdings.items():
        if pos.m_nVolume <= 0:
            continue
        if sec not in g['etf_pool'] and sec != g['defensive_etf']:
            continue
        if g['buy_date'].get(sec) == cur_date:
            continue

        try:
            minute_data = _market_data_ex_local(
                ContextInfo,
                ['high', 'close'],
                [sec],
                period='1m',
                start_time=cur_date + '093000',
                end_time=cur_date + cur_time + '00',
                count=240,
            )

            if not minute_data or sec not in minute_data:
                continue

            data = minute_data[sec]
            if 'high' not in data or data['high'] is None or len(data['high']) == 0:
                continue

            day_high = _max_values(data['high'])
            current_price = trader.get_price(ContextInfo, sec)
            if current_price is None or day_high <= 0:
                continue

            drawdown = (day_high - current_price) / day_high
            if drawdown >= g['intraday_drawdown_threshold']:
                name = get_stock_name(sec)
                print(f"  ?? 分钟级回撤触发：{sec} {name} 回撤{drawdown*100:.2f}% > {g['intraday_drawdown_threshold']*100:.0f}%")
                if smart_order_target_value(sec, 0, ContextInfo):
                    print(f"  ?? 分钟级回撤卖出：{sec} {name}")
                    g['drawdown_selled_today'].add(sec)
        except Exception as e:
            pass


def profit_protection_check(ContextInfo):
    """
    盈利保护检查 - 在指定时间点执行

    作用: 检查持仓是否从近期高点回撤过大，是则触发卖出

    输入: ContextInfo - QMT上下文
    输出: 无
    """
    if not g['enable_profit_protection']:
        return

    print("========== 盈利保护检查开始 ==========")
    holdings = trader.get_holdings()
    for sec, pos in holdings.items():
        if pos.m_nVolume <= 0:
            continue
        if sec not in g['etf_pool'] and sec != g['defensive_etf']:
            continue
        if check_profit_protection(sec, ContextInfo):
            if smart_order_target_value(sec, 0, ContextInfo):
                name = get_stock_name(sec)
                print(f"  ??? 盈利保护卖出：{sec} {name}")
                g['drawdown_selled_today'].add(sec)
    print("========== 盈利保护检查完成 ==========")


def check_profit_protection(security: str, ContextInfo, lookback=None, threshold=None) -> bool:
    """
    检查盈利保护条件

    作用: 判断持仓是否从近期最高点回撤超过阈值

    输入:
        security - 证券代码
        ContextInfo - QMT上下文
        lookback - 回看天数（默认全局配置）
        threshold - 回撤阈值（默认全局配置）

    输出: bool - 触发则返回 True
    """
    if not g['enable_profit_protection']:
        return False

    lookback = lookback or g['profit_protection_lookback']
    threshold = threshold or g['profit_protection_threshold']

    cur_dt = timetag_to_datetime(ContextInfo.get_bar_timetag(ContextInfo.barpos), '%Y%m%d%H%M%S')
    cur_date = cur_dt[:8]
    end_date = trader.get_prev_trade_date(cur_date)

    hist = trader.get_daily_data_cached(['high'], [security], count=lookback, end_time=end_date)
    if not hist or security not in hist:
        return False

    data = hist[security]
    if 'high' not in data or len(data['high']) < lookback:
        return False

    max_high = _max_values(data['high'])
    current_price = trader.get_price(ContextInfo, security)
    if current_price is None:
        return False

    if current_price <= max_high * (1 - threshold):
        name = get_stock_name(security)
        print(f"  ?? {security} {name} 触发盈利保护：当前价{current_price:.3f}，"
              f"最近{lookback}日最高{max_high:.3f}，回撤{(1 - current_price/max_high)*100:.2f}% > {threshold*100:.0f}%")
        return True
    return False


def get_premium_rate(etf: str, current_price: float, ContextInfo):
    """
    获取ETF溢价率

    作用: 计算 (市价 - IOPV) / IOPV，回测时返回None

    输入: etf - ETF代码, current_price - 当前价格, ContextInfo - QMT上下文
    输出: tuple - (溢价率, 是否通过)
    """
    if ContextInfo.do_back_test:
        return None, True
    premium_rate = trader.get_premium_rate(etf, current_price)
    if premium_rate is None:
        return None, False
    passed = isinstance(premium_rate, (int, float)) and premium_rate <= g['premium_threshold']
    return premium_rate, passed


def get_cached_rankings(ContextInfo, cur_date: str, cur_time: str) -> List[Dict]:
    """
    获取ETF排名（带缓存）

    作用: 同一交易日内复用排名结果，避免重复计算

    输入: ContextInfo - QMT上下文, cur_date - 日期, cur_time - 时间
    输出: list - 排名后的ETF指标列表
    """
    today = cur_date
    if g['rankings_cache']['date'] != today:
        ranked = get_ranked_etfs(ContextInfo, cur_date, cur_time)
        g['rankings_cache'] = {'date': today, 'data': ranked}
    return g['rankings_cache']['data']


def select_target_etfs_from_rankings(ranked: List[Dict], ContextInfo, cur_date: str, cur_time: str) -> List[str]:
    """
    从排名中选择目标ETF

    作用: 根据评分和过滤条件筛选出最终目标ETF

    过滤条件:
    - 盈利保护触发
    - 今日已卖出
    - 日内回撤过大
    - 溢价率过高

    输入:
        ranked - 排名列表
        ContextInfo - QMT上下文
        cur_date - 日期
        cur_time - 时间

    输出: list - 目标ETF代码列表
    """
    target_etfs = []
    skip_reasons = {'score_low': 0, 'profit_prot': 0, 'drawdown_sold': 0, 'intraday_dd': 0, 'premium': 0}
    for m in ranked:
        if len(target_etfs) >= g['holdings_num']:
            break

        if m['score'] < g['min_score_threshold']:
            skip_reasons['score_low'] += 1
            continue

        etf = m['etf']

        if g['enable_profit_protection'] and check_profit_protection(etf, ContextInfo):
            name = get_stock_name(etf)
            print(f"  ?? {etf} {name} 触发盈利保护，从候选列表中排除")
            skip_reasons['profit_prot'] += 1
            continue

        if etf in g['drawdown_selled_today']:
            name = get_stock_name(etf)
            print(f"  ?? {etf} {name} 今日因回撤/盈利保护卖出，禁止日内买回")
            skip_reasons['drawdown_sold'] += 1
            continue

        if check_intraday_drawdown_for_buy(etf, ContextInfo, cur_date, cur_time):
            name = get_stock_name(etf)
            print(f"  ?? {etf} {name} 当前处于日内回撤状态(>{g['intraday_drawdown_threshold']*100:.0f}%)，暂不买入")
            skip_reasons['intraday_dd'] += 1
            continue

        if g['enable_premium_filter']:
            current_price = m['current_price']
            premium, passed = get_premium_rate(etf, current_price, ContextInfo)
            name = get_stock_name(etf)
            if premium is None and not passed:
                if not ContextInfo.do_back_test:
                    print(f"  ?? {etf} {name} 无法获取溢价率，视为不合格，跳过")
                    skip_reasons['premium'] += 1
                    continue
            elif premium is not None and not passed:
                print(f"  ?? {etf} {name} 溢价率{premium*100:.2f}% > {g['premium_threshold']*100:.0f}%，跳过")
                skip_reasons['premium'] += 1
                continue

        target_etfs.append(etf)

    if not target_etfs and ranked:
        print(f"  [DEBUG][选标] 排名{len(ranked)}只但无目标: 跳过统计={skip_reasons}")
    elif target_etfs:
        _debug(f'[选标] 从排名{len(ranked)}只选出{len(target_etfs)}只: {target_etfs}')
    return target_etfs


def get_ranked_etfs(ContextInfo, cur_date: str, cur_time: str) -> List[Dict]:
    """
    计算ETF动量排名

    作用: 根据动量指标对ETF进行排序

    排名指标:
    - score = annualized_returns * r_squared

    输入: ContextInfo - QMT上下文, cur_date - 日期, cur_time - 时间
    输出: list - 排序后的ETF指标列表
    """
    active_pool = get_active_etf_pool()
    end_date = trader.get_prev_trade_date(cur_date)

    if not end_date:
        print(f"  [排名计算] 无法获取前一交易日，跳过本次计算: cur_date={cur_date}")
        return []

    lookback = max(g['lookback_days'], g['short_lookback_days'], g['volume_lookback']) + 20
    print(f"  [排名计算] 使用ETF池，合计{len(active_pool)}只ETF end_date={end_date} lookback={lookback}")

    market_data = trader.get_daily_data_cached(
        ['close', 'volume'], active_pool,
        count=lookback + 20, end_time=end_date
    )

    if not market_data:
        print("  [排名计算] 未找到有效本地日线数据，请先补全 datadir")
        return []

    daily_ok = [
        e for e in active_pool
        if e in market_data
        and _has_valid_series(market_data[e].get('close'))
        and len(_to_list(market_data[e]['close'])) >= g['lookback_days']
    ]
    _debug(f'[排名计算] 日线有效(>={g["lookback_days"]}根)={len(daily_ok)}/{len(active_pool)}只')

    today_vols: Dict[str, float] = {}
    today_prices: Dict[str, float] = {}
    today_suspended: Set[str] = set()

    try:
        minute_data = _market_data_ex_local(
            ContextInfo,
            ['volume', 'close', 'suspendFlag'],
            active_pool,
            period='1m',
            start_time=cur_date + '093000',
            end_time=cur_date + cur_time + '00',
            count=240,
        )
        if minute_data:
            for code, data in minute_data.items():
                if 'suspendFlag' in data and data['suspendFlag'] is not None and len(data['suspendFlag']) > 0:
                    if _last_value(data['suspendFlag']) == 1:
                        today_suspended.add(code)
                        continue
                if 'volume' in data and data['volume'] is not None and len(data['volume']) > 0:
                    today_vols[code] = _sum_values(data['volume'])
                if 'close' in data and data['close'] is not None and len(data['close']) > 0:
                    valid_closes = _valid_closes(data['close'])
                    if len(valid_closes) > 0:
                        today_prices[code] = valid_closes[-1]

        if today_suspended:
            print(f"  ?? 当日停牌ETF({len(today_suspended)}只): {', '.join(sorted(today_suspended))}")

    except Exception as e:
        print(f"  [排名计算] 本地 1m 数据读取异常: {e}")
        if _local_data_only():
            print("  [排名计算] 未找到有效本地 1m 数据，当日分钟量/价可能为空")

    etf_metrics = []
    suspended_count = 0
    filter_stats = {
        'no_daily': 0, 'bars_short': 0, 'vol_zero': 0, 'metrics_none': 0,
        'score_oob': 0, 'passed': 0,
    }

    for etf in active_pool:
        if etf in today_suspended:
            suspended_count += 1
            continue

        if etf not in market_data:
            filter_stats['no_daily'] += 1
            continue

        data = market_data[etf]
        if 'close' not in data or data['close'] is None or len(data['close']) == 0:
            filter_stats['no_daily'] += 1
            continue
        if len(data['close']) < g['lookback_days']:
            filter_stats['bars_short'] += 1
            continue

        raw_closes = _to_list(data['close'])
        raw_volumes = _to_list(data['volume']) if 'volume' in data else [0.0] * len(raw_closes)

        pairs = [
            (float(c), float(v))
            for c, v in zip(raw_closes, raw_volumes)
            if not _is_nan(v) and float(v) > 0
        ]
        hist_closes = [p[0] for p in pairs][-lookback:]
        hist_volumes = [p[1] for p in pairs][-lookback:]

        if len(hist_closes) < g['lookback_days']:
            filter_stats['vol_zero'] += 1
            continue

        current_price = today_prices.get(etf)
        if current_price is None or _is_nan(current_price):
            current_price = trader.get_price(ContextInfo, etf)
        today_vol = today_vols.get(etf, 0)

        metrics = calculate_momentum_metrics(
            etf, hist_closes, hist_volumes, current_price, today_vol, ContextInfo
        )

        if metrics is not None:
            if g['min_score_threshold'] < metrics['score'] < g['max_score_threshold']:
                etf_metrics.append(metrics)
                filter_stats['passed'] += 1
            else:
                filter_stats['score_oob'] += 1
                name = metrics.get('etf_name', '')
                if g['enable_detailed_log']:
                    print(f"  [DEBUG] {etf} {name} 得分{metrics['score']:.2f}超出阈值，过滤")
        else:
            filter_stats['metrics_none'] += 1

    missing_daily = len(active_pool) - suspended_count - len(
        [1 for e in active_pool if e not in today_suspended and e in market_data]
    )
    data_issues = []
    if suspended_count:
        data_issues.append(f"停牌{suspended_count}只")
    if missing_daily:
        data_issues.append(f"日线缺失{missing_daily}只")
    if data_issues:
        print(f"  [排名·数据质量] {', '.join(data_issues)} | 成功计算{len(etf_metrics)}只")
    print(f"  [DEBUG][排名过滤] {filter_stats} | 1m有价格={len(today_prices)}只 1m有量={len(today_vols)}只")

    etf_metrics.sort(key=lambda x: x['score'], reverse=True)
    return etf_metrics


def calculate_momentum_metrics(etf: str, hist_closes, hist_volumes, current_price, today_vol, ContextInfo):
    """
    计算ETF动量评分指标

    作用: 根据历史价格和成交量计算动量指标

    评分公式: score = annualized_returns * r_squared

    过滤条件:
    - 盈利保护触发
    - 溢价率过高
    - 成交量异常放量
    - 短期动量不足
    - 近3日单日跌幅过大

    输入:
        etf - ETF代码
        hist_closes - 历史收盘价
        hist_volumes - 历史成交量
        current_price - 当前价格
        today_vol - 今日成交量
        ContextInfo - QMT上下文

    输出: dict - 包含评分指标，被过滤则返回 None
    """
    try:
        name = get_stock_name(etf)

        price_series = list(hist_closes) + [float(current_price)]

        if check_profit_protection(etf, ContextInfo):
            print(f"  ?? {etf} {name} 触发盈利保护，从排名中排除")
            return None

        if g['enable_premium_filter']:
            premium, passed = get_premium_rate(etf, current_price, ContextInfo)
            if premium is not None:
                if not passed:
                    print(f"  ?? {etf} {name} 溢价率{premium*100:.2f}% > 阈值{g['premium_threshold']*100:.0f}%，排除")
                    return None
            else:
                if not ContextInfo.do_back_test:
                    print(f"  ?? {etf} {name} 无法获取溢价率，排除")
                    return None

        if g['enable_volume_check']:
            vol_ratio = trader.get_volume_ratio(ContextInfo, hist_volumes, today_vol, g['volume_lookback'])
            if vol_ratio is not None and vol_ratio > g['volume_threshold']:
                annualized = get_annualized_returns(price_series, g['lookback_days'])
                if annualized > g['volume_return_limit']:
                    print(f"  ?? {etf} {name} 成交量放量{vol_ratio:.1f}倍，且年化{annualized*100:.1f}% > 阈值{g['volume_return_limit']*100:.1f}%，过滤")
                    return None

        if len(price_series) >= g['short_lookback_days'] + 1:
            short_return = price_series[-1] / price_series[-(g['short_lookback_days'] + 1)] - 1
            short_annualized = (1 + short_return) ** (250 / g['short_lookback_days']) - 1
        else:
            short_annualized = 0

        if g['use_short_momentum_filter'] and short_annualized < g['short_momentum_threshold']:
            if g['enable_detailed_log']:
                print(f"  [DEBUG] {etf} {name} 短期动量{short_annualized*100:.1f}% < 阈值{g['short_momentum_threshold']*100:.1f}%，过滤")
            return None

        recent = price_series[-(g['lookback_days'] + 1):]
        y = [math.log(p) for p in recent]
        x = list(range(len(y)))
        weights = _linspace(1, 2, len(y))
        slope, intercept = _weighted_polyfit(x, y, weights)
        annualized_returns = math.exp(slope * 250) - 1

        y_mean = sum(w * yi for w, yi in zip(weights, y)) / sum(weights)
        ss_res = sum(w * (yi - (slope * xi + intercept)) ** 2 for w, xi, yi in zip(weights, x, y))
        ss_tot = sum(w * (yi - y_mean) ** 2 for w, yi in zip(weights, y))
        r_squared = 1 - ss_res / ss_tot if ss_tot != 0 else 0

        score = annualized_returns * r_squared

        if len(price_series) >= 4:
            day1 = price_series[-1] / price_series[-2]
            day2 = price_series[-2] / price_series[-3]
            day3 = price_series[-3] / price_series[-4]
            if min(day1, day2, day3) < g['loss']:
                print(f"  ?? {etf} {name} 近3日有单日跌幅超{(1-g['loss'])*100:.1f}%，直接排除")
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
        name = get_stock_name(etf)
        print(f"  [warning] 计算{etf} {name}时出错: {e}")
        return None


def get_annualized_returns(price_series, lookback_days):
    """
    计算年化收益率

    作用: 使用加权线性回归计算年化收益率

    输入: price_series - 价格序列, lookback_days - 回看天数
    输出: float - 年化收益率
    """
    recent = list(price_series)[-(lookback_days + 1):]
    y = [math.log(p) for p in recent]
    x = list(range(len(y)))
    weights = _linspace(1, 2, len(y))
    slope, _ = _weighted_polyfit(x, y, weights)
    return math.exp(slope * 250) - 1


def etf_sell_trade(ContextInfo, cur_date: str, cur_time: str):
    """
    ETF卖出操作 - 每日13:09执行

    作用: 卖出不在目标池中的持仓

    输入: ContextInfo - QMT上下文, cur_date - 日期, cur_time - 时间
    输出: 无
    """
    print("========== 卖出操作开始 ==========")
    _ensure_daily_preload(ContextInfo, cur_date)
    cash = trader.get_available_cash()
    total_val = trader.get_strategy_total_value(ContextInfo)
    holdings = trader.get_holdings()
    pos_etfs = [s for s, p in holdings.items() if p.m_nVolume > 0 and (s in g['etf_pool'] or s == g['defensive_etf'])]
    print(f"  [DEBUG][卖出] 账户: 现金={cash:.2f} 总资产={total_val:.2f} 策略持仓={pos_etfs or '空仓'}")

    ranked = get_cached_rankings(ContextInfo, cur_date, cur_time)
    print(f"  [DEBUG][卖出] 排名结果: {len(ranked)}只有效ETF")

    target_etfs = select_target_etfs_from_rankings(ranked, ContextInfo, cur_date, cur_time)

    defensive_available = check_defensive_etf_available(ContextInfo)
    print(f"  [DEBUG][卖出] 目标ETF={target_etfs or '无'} 防御ETF可用={defensive_available}")
    if not target_etfs and defensive_available:
        target_etfs = [g['defensive_etf']]
        name = get_stock_name(g['defensive_etf'])
        print(f"  ??? 无目标ETF，防御模式：{g['defensive_etf']} {name}")

    g['target_etfs_cache'] = {'date': cur_date, 'data': list(target_etfs)}

    target_set = set(target_etfs)

    holdings = trader.get_holdings()
    for sec, pos in holdings.items():
        if pos.m_nVolume <= 0:
            continue
        if sec not in g['etf_pool'] and sec != g['defensive_etf']:
            continue
        if sec not in target_set:
            cost = pos.m_dOpenPrice
            buy_date = g['buy_date'].get(sec)
            hold_days = 0
            if buy_date:
                try:
                    hold_days = (datetime.strptime(cur_date, '%Y%m%d').date()
                                 - datetime.strptime(buy_date, '%Y%m%d').date()).days
                except:
                    pass

            if smart_order_target_value(sec, 0, ContextInfo):
                name = get_stock_name(sec)
                sell_price = trader.get_price(ContextInfo, sec) or 0
                print(f"  ?? 卖出持仓：{sec} {name}")
                g['trade_log']['sell_records'].append({
                    'code': sec,
                    'name': name,
                    'cost': cost,
                    'price': sell_price,
                    'hold_days': hold_days
                })
                if sec in g['buy_date']:
                    del g['buy_date'][sec]

    if g['enable_premium_filter']:
        holdings = trader.get_holdings()
        for sec, pos in holdings.items():
            if pos.m_nVolume <= 0:
                continue
            if sec not in g['etf_pool'] and sec != g['defensive_etf']:
                continue
            current_price = trader.get_price(ContextInfo, sec)
            if current_price:
                premium, passed = get_premium_rate(sec, current_price, ContextInfo)
                if premium is not None and not passed:
                    if smart_order_target_value(sec, 0, ContextInfo):
                        name = get_stock_name(sec)
                        print(f"  ?? 溢价率过高 {sec} {name} 溢价率{premium*100:.2f}% > {g['premium_threshold']*100:.0f}%，卖出")

    print("========== 卖出操作完成 ==========")


def check_intraday_drawdown_for_buy(security: str, ContextInfo, cur_date: str, cur_time: str) -> bool:
    """
    检查日内回撤（买入前判断）

    作用: 判断ETF当前是否处于日内回撤状态

    输入: security - 证券代码, ContextInfo - QMT上下文, cur_date - 日期, cur_time - 时间
    输出: bool - 回撤超过阈值则返回 True
    """
    try:
        minute_data = _market_data_ex_local(
            ContextInfo,
            ['high', 'close'],
            [security],
            period='1m',
            start_time=cur_date + '093000',
            end_time=cur_date + cur_time + '00',
            count=240,
        )
        if not minute_data or security not in minute_data:
            return False

        data = minute_data[security]
        if 'high' not in data or data['high'] is None or len(data['high']) == 0:
            return False

        day_high = data['high'].max()
        close_arr = _valid_closes(data['close'])
        if len(close_arr) == 0:
            return False
        current = close_arr[-1]

        if day_high <= 0:
            return False

        drawdown = (day_high - current) / day_high
        return drawdown >= g['intraday_drawdown_threshold']
    except:
        return False


def etf_buy_trade(ContextInfo, cur_date: str, cur_time: str):
    """
    ETF买入操作 - 每日13:10执行

    作用: 买入评分最高的ETF

    输入: ContextInfo - QMT上下文, cur_date - 日期, cur_time - 时间
    输出: 无
    """
    print("========== 买入操作开始 ==========")
    cash = trader.get_available_cash()
    total_val = trader.get_strategy_total_value(ContextInfo)
    holdings = trader.get_holdings()
    pos_etfs = [s for s, p in holdings.items() if p.m_nVolume > 0 and (s in g['etf_pool'] or s == g['defensive_etf'])]
    print(f"  [DEBUG][买入] 账户: 现金={cash:.2f} 总资产={total_val:.2f} 策略持仓={pos_etfs or '空仓'}")

    ranked = get_cached_rankings(ContextInfo, cur_date, cur_time)

    print("  === ETF排名前5 ===")
    if not ranked:
        print("    (无排名数据 — 请检查日线/1m本地数据是否齐全)")
    for i, m in enumerate(ranked[:5]):
        print(f"    排名{i+1}: {m['etf']} {m['etf_name']} 得分{m['score']:.4f} 年化{m['annualized_returns']*100:.2f}% R2={m['r_squared']:.4f}")

    if g['target_etfs_cache']['date'] == cur_date and g['target_etfs_cache']['data'] is not None:
        target_etfs = list(g['target_etfs_cache']['data'])
        print(f"  ?? 复用13:09目标ETF缓存：{target_etfs}")
    else:
        target_etfs = select_target_etfs_from_rankings(ranked, ContextInfo, cur_date, cur_time)
        if not target_etfs:
            if check_defensive_etf_available(ContextInfo) and g['defensive_etf'] not in g['drawdown_selled_today']:
                target_etfs = [g['defensive_etf']]
                name = get_stock_name(g['defensive_etf'])
                print(f"  ??? 进入防御模式，选择防御ETF：{g['defensive_etf']} {name}")
            else:
                print("  ?? 无目标ETF且防御不可用，保持空仓")
                return

    if target_etfs:
        for i, etf in enumerate(target_etfs):
            m = next((x for x in ranked if x['etf'] == etf), None)
            if m:
                name = get_stock_name(etf)
                print(f"  ?? 目标ETF {i+1}: {etf} {name} 得分{m['score']:.4f}")
    else:
        print("  ?? 无目标ETF，保持空仓")
        return

    holdings = trader.get_holdings()
    current_positions = []
    for s, pos in holdings.items():
        if pos.m_nVolume > 0 and (s in g['etf_pool'] or s == g['defensive_etf']):
            current_positions.append(s)
    current_pos_set = set(current_positions)
    target_set = set(target_etfs)
    to_sell = [s for s in current_pos_set if s not in target_set]

    if to_sell:
        to_sell_names = [get_stock_name(s) for s in to_sell]
        print(f"  尚有持仓需要卖出：{list(zip(to_sell, to_sell_names))}，等待卖出完成再买入")
        return

    total_val = trader.get_strategy_total_value(ContextInfo)
    target_per_etf = total_val / len(target_etfs)

    for etf in target_etfs:
        current_val = 0
        if etf in holdings:
            pos = holdings[etf]
            if pos.m_nVolume > 0:
                current_price = trader.get_price(ContextInfo, etf)
                current_val = pos.m_nVolume * current_price if current_price else 0

        if abs(current_val - target_per_etf) > target_per_etf * 0.05 or current_val == 0:
            _debug(f'[买入] 调仓 {etf}: 当前市值={current_val:.2f} 目标={target_per_etf:.2f} 价差比={abs(current_val-target_per_etf)/target_per_etf*100 if target_per_etf else 0:.1f}%')
            if smart_order_target_value(etf, target_per_etf, ContextInfo):
                action = "买入" if current_val < target_per_etf else "调仓"
                name = get_stock_name(etf)
                print(f"  ?? {action}：{etf} {name} 目标金额{target_per_etf:.2f}")
            else:
                print(f"  [DEBUG][买入] {etf} smart_order_target_value 返回False，未成交")
        else:
            _debug(f'[买入] 跳过 {etf}: 当前市值={current_val:.2f} 已在目标±5%内')

    print("========== 买入操作完成 ==========")


def get_stock_name(symbol: str) -> str:
    """
    获取证券名称

    输入: symbol - 证券代码
    输出: str - 证券名称
    """
    try:
        return trader.get_stock_info(symbol, 'InstrumentName') or '未知'
    except:
        return '未知'


def check_defensive_etf_available(ContextInfo) -> bool:
    """
    检查防御ETF是否可用

    作用: 判断防御ETF是否可以交易（排除停牌、涨跌停）

    输入: ContextInfo - QMT上下文
    输出: bool - 可用则返回 True
    """
    etf = g['defensive_etf']
    try:
        if ContextInfo.do_back_test:
            current_price = trader.get_price(ContextInfo, etf)
            if not current_price:
                return False
            return True
        else:
            tick_data = ContextInfo.get_full_tick([etf])
            if etf not in tick_data:
                return False
            tick = tick_data[etf]
            if tick.get('openInt', 0) in [1, 17]:
                name = get_stock_name(etf)
                print(f"  [DEBUG] 防御ETF {etf} {name} 停牌")
                return False
            last_price = tick.get('lastPrice', 0)
            stock_info = trader.get_stock_info(etf)
            if stock_info:
                high_limit = stock_info.get('UpStopPrice', 0)
                low_limit = stock_info.get('DownStopPrice', 0)
                if high_limit and high_limit > 0 and last_price >= high_limit:
                    name = get_stock_name(etf)
                    print(f"  [DEBUG] 防御ETF {etf} {name} 涨停")
                    return False
                if low_limit and low_limit > 0 and last_price <= low_limit:
                    name = get_stock_name(etf)
                    print(f"  [DEBUG] 防御ETF {etf} {name} 跌停")
                    return False
            return True
    except Exception as e:
        print(f"  检查防御ETF异常: {e}")
        return False


def _submit_passorder(
    context_info, op_code: int, security: str, volume: int, price: float = -1,
) -> bool:
    """
    提交交易委托

    作用: 调用QMT的passorder接口执行交易

    输入:
        context_info - QMT上下文
        op_code - 操作代码（23=买入，24=卖出）
        security - 证券代码
        volume - 数量
        price - 价格

    输出: bool - 成功返回 True
    """
    if volume <= 0:
        return False
    curdatetime = trader.get_current_time(context_info, '%Y-%m-%d %H:%M:%S')
    side = 'buy' if op_code == trader.buy_code else 'sell'
    msg = f'[{curdatetime}][{trader.strategy_name}][{security}][{side}] {volume}'
    passorder(op_code, 1101, trader.acct_id, security, 14, price, volume, trader.strategy_name, 1, msg, context_info)
    if trader.is_backtesting:
        if side == 'buy':
            trader.positions[security] = trader.positions.get(security, 0) + volume
        else:
            nv = trader.positions.get(security, 0) - volume
            if nv <= 0:
                trader.positions.pop(security, None)
            else:
                trader.positions[security] = nv
    return True


def smart_order_target_value(security: str, target_value: float, ContextInfo) -> bool:
    """
    智能目标市值下单

    作用: 根据目标市值自动计算并执行买卖

    输入:
        security - 证券代码
        target_value - 目标市值金额
        ContextInfo - QMT上下文

    输出: bool - 成功返回 True
    """
    try:
        account_id = getattr(trader, 'acct_id', 'tests')
        stock_name = get_stock_name(security)

        current_price = trader.get_price(ContextInfo, security)
        if not current_price:
            print(f"  {security} {stock_name}: 获取价格失败，跳过交易")
            return False

        if not ContextInfo.do_back_test:
            stock_info = trader.get_stock_info(security)
            if stock_info:
                high_limit = stock_info.get('UpStopPrice', 0)
                low_limit = stock_info.get('DownStopPrice', 0)
                if high_limit and high_limit > 0 and current_price >= high_limit:
                    print(f"  {security} {stock_name}: 当前涨停，跳过交易")
                    return False
                if low_limit and low_limit > 0 and current_price <= low_limit:
                    print(f"  {security} {stock_name}: 当前跌停，跳过交易")
                    return False

        target_amount = int(target_value / current_price)
        target_amount = (target_amount // 100) * 100
        if target_amount <= 0 and target_value > 0:
            target_amount = 100

        current_amount = 0
        closeable_amount = 0
        try:
            holdings = trader.get_holdings()
            if security in holdings:
                pos = holdings[security]
                current_amount = pos.m_nVolume
                closeable_amount = pos.m_nCanUseVolume
        except:
            pass

        amount_diff = target_amount - current_amount

        trade_val = abs(amount_diff) * current_price
        _debug(f'[下单] {security} {stock_name}: 现价={current_price:.3f} 目标额={target_value:.2f} 目标量={target_amount} 当前量={current_amount} 差额={amount_diff} 交易额={trade_val:.2f}')
        if 0 < trade_val < g['min_money']:
            print(f"  {security} {stock_name}: 交易金额{trade_val:.2f} < {g['min_money']}，跳过")
            return False

        if amount_diff < 0:
            if closeable_amount == 0:
                print(f"  {security} {stock_name}: 当天买入不可卖出(T+1)")
                return False
            amount_diff = -min(abs(amount_diff), closeable_amount)

        if amount_diff != 0:
            if amount_diff > 0:
                if not _submit_passorder(ContextInfo, trader.buy_code, security, amount_diff):
                    print(f"  [DEBUG][下单] {security} 买入委托提交失败")
                    return False
                print(f"  ?? 买入 {security} {stock_name} 数量{amount_diff} 价格{current_price:.3f}")
                g['buy_date'][security] = timetag_to_datetime(
                    ContextInfo.get_bar_timetag(ContextInfo.barpos), '%Y%m%d'
                )
            else:
                if not _submit_passorder(ContextInfo, trader.sell_code, security, abs(amount_diff)):
                    print(f"  [DEBUG][下单] {security} 卖出委托提交失败")
                    return False
                print(f"  ?? 卖出 {security} {stock_name} 数量{abs(amount_diff)} 价格{current_price:.3f}")
            return True
        _debug(f'[下单] {security} {stock_name}: 无需调仓 (目标量={target_amount} 当前量={current_amount})')
        return False
    except Exception as e:
        print(f"  下单异常: {security} - {e}")
        return False


def daily_summary_report(ContextInfo, cur_date: str):
    """
    盘后日报 - 每日15:05执行

    作用: 打印今日交易摘要和持仓报告

    输入: ContextInfo - QMT上下文, cur_date - 当前日期
    输出: 无
    """
    print("========== 策略运行日报 ==========")
    print(f"  日期: {cur_date[:4]}-{cur_date[4:6]}-{cur_date[6:]}")

    if g['enable_regime_switch']:
        status = "??走弱期" if g['is_a_share_weak'] else "??正常期"
        avoid_status = "回避A股" if (g['is_a_share_weak'] and g['enable_avoid_a_share']) else \
                       ("不回避A股" if g['is_a_share_weak'] else "正常交易")
        drawdown_status = "???启用" if (g['is_a_share_weak'] and g['enable_intraday_drawdown']) else \
                          ("?关闭" if (g['is_a_share_weak'] and not g['enable_intraday_drawdown']) else "?关闭")
        print(f"  市场状态：{status} | {avoid_status} 计数:{g['weak_period_counter']}/{g['weak_period_max_days']}")
        print(f"  分钟级回撤：{drawdown_status}（阈值{g['intraday_drawdown_threshold']*100:.0f}%）")
    else:
        print("  行情判断未启用，始终全市场交易")

    avoid_switch_status = "ON（走弱期回避A股）" if g['enable_avoid_a_share'] else "OFF（走弱期不回避A股）"
    drawdown_switch_status = "ON（走弱期自动启用）" if g['enable_intraday_drawdown'] else "OFF（不触发）"
    print(f"  独立开关：A股回避={avoid_switch_status} | 分钟回撤={drawdown_switch_status}")

    sell_records = g['trade_log'].get('sell_records', [])
    print(f"  今日卖出：{len(sell_records)}只")
    for r in sell_records:
        cost = r.get('cost', 0)
        sell_price = r.get('price', 0)
        profit_pct = (sell_price / cost - 1) * 100 if cost > 0 else 0
        hold_days = r.get('hold_days', 0)
        print(f"    {r['code']} {r['name']} | 成本:{cost:.3f} | 卖出:{sell_price:.3f} | 收益:{profit_pct:+.2f}% | 持有{hold_days}天")

    holdings = trader.get_holdings()
    pos_list = []
    for sec, pos in holdings.items():
        if pos.m_nVolume <= 0:
            continue
        if sec not in g['etf_pool'] and sec != g['defensive_etf']:
            continue
        pos_list.append(sec)
    print(f"  最终持仓：{len(pos_list)}只")
    for sec, pos in holdings.items():
        if pos.m_nVolume <= 0:
            continue
        if sec not in g['etf_pool'] and sec != g['defensive_etf']:
            continue
        current_price = trader.get_price(ContextInfo, sec) or 0
        cost = pos.m_dOpenPrice
        profit_pct = (current_price / cost - 1) * 100 if cost > 0 else 0
        buy_date = g['buy_date'].get(sec)
        hold_days = 0
        if buy_date:
            try:
                hold_days = (datetime.strptime(cur_date, '%Y%m%d').date()
                             - datetime.strptime(buy_date, '%Y%m%d').date()).days
            except:
                pass
        print(f"    {sec} {get_stock_name(sec)} | 成本:{cost:.3f} | 当前:{current_price:.3f} | 收益:{profit_pct:+.2f}% | 持有{hold_days}天")

    total_val = trader.get_strategy_total_value(ContextInfo)
    positions_value = total_val - trader.get_available_cash()
    cash = trader.get_available_cash()
    print(f"  总资产：{total_val:.2f} | 可用：{cash:.2f} | 市值：{positions_value:.2f}")
    print("==========" + "报告结束" + "==========")
    print("")


def check_local_history_data(ContextInfo, cur_date: str):
    """
    检查本地历史数据完整性

    作用: 检查ETF池的1m/1d数据是否存在于本地datadir

    输入: ContextInfo - QMT上下文, cur_date - 当前日期
    输出: 无
    """
    if g.get('local_history_check_date') == cur_date:
        return

    if not _local_data_only():
        dl_history_data(ContextInfo, cur_date)
        g['local_history_check_date'] = cur_date
        return

    print(f'  [本地数据] 检查 ETF 池[{len(g["all_subscribe_codes"])}] 1m/1d（不联网下载）...')
    missing_1m: List[str] = []
    missing_1d: List[str] = []
    for code in g['all_subscribe_codes']:
        if not trader.has_local_data(ContextInfo, code, '1m'):
            missing_1m.append(code)
        if not trader.has_local_data(ContextInfo, code, '1d'):
            missing_1d.append(code)

    if missing_1m:
        _print_missing_local_data('ETF池', missing_1m, '1m')
    if missing_1d:
        _print_missing_local_data('ETF池', missing_1d, '1d')
    if not missing_1m and not missing_1d:
        print('  [本地数据] 检查通过：1m/1d 均已在本地 datadir')
    else:
        print('  [本地数据] 请先用 download_etf_pool.py 或 QMT 数据管理补全本地数据')

    g['local_history_check_date'] = cur_date


def dl_history_data(ContextInfo, cur_date: str):
    """
    下载历史数据

    作用: 联网下载ETF池的历史行情数据

    输入: ContextInfo - QMT上下文, cur_date - 当前日期
    输出: 无
    """
    if ContextInfo.do_back_test and g['dl_history_data_date']:
        return
    pool_n = len(g['all_subscribe_codes'])
    print('  下载ETF池[%d]历史行情...' % pool_n)
    for code in g['all_subscribe_codes']:
        download_history_data(code, '1m', '', '')
        download_history_data(code, '1d', '', '')
    g['dl_history_data_date'] = cur_date

