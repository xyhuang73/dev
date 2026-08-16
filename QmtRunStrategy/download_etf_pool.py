# coding:gbk
"""
七星高照 ETF 池 — QMT 本地 1m 数据检测与下载

用法:
1. 在 QMT「模型研究」中新建 Python 策略，引用本文件
2. 修改下方「下载配置」中的起止日期
3. 点击「运行」或「回测」（周期任意，逻辑仅在 init 执行一次）
4. 查看输出窗口：先显示本地数据状态，再显示下载/更新进度

并行:
- PARALLEL_WORKERS 控制并行线程数（默认 6，建议 4~8）
- SHOW_PROGRESS_BAR 显示文本进度条（含百分比、ETA、当前标的）
- 设为 1 则恢复串行；若 QMT 报错可降为 2 或 1

说明:
- 股票池与 Qixingaozhao_qmt.py 中 init_global_vars 保持一致
- 模型研究 download_history_data 写入: {QMT安装目录}/datadir （非 userdata_mini）
- userdata_mini/datadir 为 miniQMT/xtdata 常用路径，两者可能不一致
- 本地检测优先读磁盘 .DAT，避免 get_local_data API 误报「缺失」
"""

from datetime import datetime
import os
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    _HAS_FUTURES = True
except ImportError:
    _HAS_FUTURES = False


# ==================== 下载配置（可按需修改） ====================
DOWNLOAD_PERIOD = '1m'
DOWNLOAD_START = '20220101'       # 期望本地覆盖的起始日期 YYYYMMDD
DOWNLOAD_END = ''                 # 结束日期，空字符串表示至最新
FORCE_REDOWNLOAD = False          # True: 忽略本地是否完整，全部重新下载
ALSO_DOWNLOAD_1D = False          # True: 额外下载日线（策略 ranking 也会用到 1d）
DOWNLOAD_1D_START = ''            # 空则与 DOWNLOAD_START 相同
DOWNLOAD_1D_END = ''              # 空则与 DOWNLOAD_END 相同
PARALLEL_WORKERS = 6              # 并行线程数，建议 4~8；设为 1 则串行
VERIFY_AFTER_DOWNLOAD = True      # 下载完成后是否复检本地数据状态
SHOW_PROGRESS_BAR = True          # 显示文本进度条
PROGRESS_BAR_WIDTH = 36           # 进度条宽度（字符数）
SHOW_DOWNLOAD_ITEM_LOG = False    # 是否逐条打印 [OK]/[FAIL]（开进度条建议 False）

# ==================== 本地数据目录（国金 QMT 实测） ====================
# 模型研究 / download_history_data 实际写入安装目录下 datadir，不是 userdata_mini
QMT_INSTALL_ROOT = r'D:\MiniQmt\国金证券QMT交易端'
DOWNLOAD_DATADIR = ''             # 空 = QMT_INSTALL_ROOT + '/datadir'
MINIQMT_DATADIR = ''              # 空 = QMT_INSTALL_ROOT + '/userdata_mini/datadir'
USE_FILESYSTEM_PROBE = True       # True: 优先用磁盘 .DAT 检测（推荐）
MIN_DAT_FILE_BYTES = 1024         # 小于此字节数视为空文件
MIN_1M_OK_BYTES = 50 * 1024       # 1m 文件大于此值通常认为已有可用数据
MIN_1D_OK_BYTES = 5 * 1024        # 1d 文件阈值


# ==================== ETF 池（与策略文件同步） ====================
REGIME_INDEXES = {
    '沪深300': '000300.SH',
    '深证综指': '399101.SZ',
    '创业板指': '399006.SZ',
    '中证A500': '000510.SH',
}

OVERSEAS_ETF_POOL = [
    '513100.SH', '513290.SH', '513500.SH', '159529.SZ', '513400.SH',
    '513520.SH', '513030.SH', '513080.SH', '513310.SH', '513730.SH',
    '159792.SZ', '513130.SH', '513050.SH', '159920.SZ', '513690.SH',
    '511380.SH', '511010.SH', '511220.SH',
]

COMMODITY_ETF_POOL = [
    '518880.SH', '159980.SZ', '159985.SZ', '501018.SH', '161226.SZ',
    '159981.SZ', '512400.SH',
]

DOMESTIC_ETF_POOL = [
    '510300.SH', '510500.SH', '510050.SH', '510210.SH', '159915.SZ',
    '588080.SH', '512100.SH', '563360.SH', '563300.SH', '512890.SH',
    '159967.SZ', '588020.SH', '512040.SH', '159201.SZ', '515790.SH',
    '563230.SH', '515880.SH', '512660.SH', '561380.SH', '159667.SZ',
    '159559.SZ', '159819.SZ', '159381.SZ', '159732.SZ', '159995.SZ',
    '512220.SH',
]

ETF_POOL = OVERSEAS_ETF_POOL + COMMODITY_ETF_POOL + DOMESTIC_ETF_POOL
ALL_SUBSCRIBE_CODES = sorted(set(ETF_POOL + list(REGIME_INDEXES.values())))

# QMT datadir 下周期目录名因版本可能不同，按常见候选依次匹配
_PERIOD_DIR_CANDIDATES: Dict[str, List[str]] = {
    '1m': ['60', '1m', '60000', '60001'],
    '1d': ['86400', '1d', '86401'],
    '5m': ['300', '5m'],
    '15m': ['900', '15m'],
    '30m': ['1800', '30m'],
    '60m': ['3600', '60m'],
}

_CODE_GROUP: Dict[str, str] = {}
for _c in OVERSEAS_ETF_POOL:
    _CODE_GROUP[_c] = '海外'
for _c in COMMODITY_ETF_POOL:
    _CODE_GROUP[_c] = '商品'
for _c in DOMESTIC_ETF_POOL:
    _CODE_GROUP[_c] = 'A股'
for _name, _c in REGIME_INDEXES.items():
    _CODE_GROUP[_c] = '指数:' + _name

_print_lock = threading.Lock()
_PRIMARY_DATADIR = ''
_MINIQMT_DATADIR = ''


def _log(msg: str) -> None:
    with _print_lock:
        print(msg)


class TextProgressBar:
    """QMT 控制台可用的 ASCII 进度条（不依赖 tqdm）。"""

    def __init__(self, total: int, label: str = '') -> None:
        self.total = max(int(total), 0)
        self.label = label or '进度'
        self.done = 0
        self.ok_count = 0
        self.fail_count = 0
        self.last_item = ''
        self._t0 = datetime.now()
        self._last_print_ts = 0.0

    def _should_print(self) -> bool:
        if self.total <= 0:
            return False
        if self.done <= 1:
            return True
        if self.done >= self.total:
            return True
        if self.total <= 20:
            return True
        now = datetime.now().timestamp()
        if now - self._last_print_ts >= 0.5:
            return True
        if self.done % max(1, self.total // 20) == 0:
            return True
        return False

    def update(self, item: str = '', ok: bool = True) -> None:
        if self.total <= 0:
            return
        self.done = min(self.done + 1, self.total)
        if ok:
            self.ok_count += 1
        else:
            self.fail_count += 1
        if item:
            self.last_item = item
        if SHOW_PROGRESS_BAR and self._should_print():
            self._render()

    def finish(self) -> None:
        if self.total <= 0:
            return
        self.done = self.total
        if SHOW_PROGRESS_BAR:
            self._render(final=True)

    def _render(self, final: bool = False) -> None:
        width = max(10, int(PROGRESS_BAR_WIDTH))
        ratio = float(self.done) / float(self.total) if self.total else 1.0
        ratio = max(0.0, min(1.0, ratio))
        filled = int(width * ratio)
        bar = '#' * filled + '-' * (width - filled)
        elapsed = (datetime.now() - self._t0).total_seconds()
        eta = (elapsed / self.done * (self.total - self.done)) if self.done > 0 else 0.0
        pct = int(ratio * 100)
        tail = self.last_item
        if tail and len(tail) > 18:
            tail = tail[:18]
        msg = (
            '  [%s] |%s| %3d%% %d/%d  ok:%d fail:%d  %.0fs'
            % (self.label, bar, pct, self.done, self.total, self.ok_count, self.fail_count, elapsed)
        )
        if eta > 0 and not final:
            msg += ' ETA:%.0fs' % eta
        if tail:
            msg += '  %s' % tail
        self._last_print_ts = datetime.now().timestamp()
        _log(msg)


def _effective_workers() -> int:
    try:
        n = int(PARALLEL_WORKERS)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(n, 16))


def _run_parallel(
    items: List[Any],
    worker: Callable[[Any], Any],
    workers: int,
    label: str = '',
    progress: Optional[TextProgressBar] = None,
    on_result: Optional[Callable[[Any], Tuple[bool, str]]] = None,
) -> List[Any]:
    if not items:
        return []

    total = len(items)

    def _handle_done(result: Any) -> None:
        if progress is None:
            return
        ok, item_name = True, ''
        if on_result is not None:
            try:
                ok, item_name = on_result(result)
            except Exception:
                ok, item_name = False, ''
        elif isinstance(result, Exception):
            ok, item_name = False, ''
        elif isinstance(result, tuple) and len(result) >= 1:
            item_name = str(result[0])
            if len(result) >= 2 and isinstance(result[1], bool):
                ok = result[1]
        progress.update(item_name, ok=ok)

    if workers <= 1 or not _HAS_FUTURES or total == 1:
        results: List[Any] = []
        for item in items:
            try:
                result = worker(item)
            except Exception as exc:
                result = exc
            results.append(result)
            _handle_done(result)
        if progress is not None:
            progress.finish()
        return results

    results = [None] * total
    indexed = list(enumerate(items))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(worker, item): idx for idx, item in indexed}
        for fut in as_completed(future_map):
            idx = future_map[fut]
            try:
                result = fut.result()
            except Exception as exc:
                result = exc
            results[idx] = result
            _handle_done(result)

    if progress is not None:
        progress.finish()
    return results


# ==================== 本地数据路径探测 ====================
def _split_vt_symbol(vt: str) -> Tuple[str, str]:
    text = (vt or '').strip()
    if '.' in text:
        code, mkt = text.rsplit('.', 1)
        return code.strip(), mkt.strip().upper()
    return text, ''


def _norm_path(path: str) -> str:
    try:
        return os.path.normpath(os.path.abspath(path))
    except Exception:
        return path


def _configured_download_datadir() -> str:
    custom = (DOWNLOAD_DATADIR or '').strip()
    if custom:
        return _norm_path(custom)
    root = (QMT_INSTALL_ROOT or '').strip()
    if root:
        return _norm_path(os.path.join(root, 'datadir'))
    return ''


def _configured_miniqmt_datadir() -> str:
    custom = (MINIQMT_DATADIR or '').strip()
    if custom:
        return _norm_path(custom)
    root = (QMT_INSTALL_ROOT or '').strip()
    if root:
        return _norm_path(os.path.join(root, 'userdata_mini', 'datadir'))
    return ''


def init_storage_paths(ContextInfo) -> None:
    """解析并缓存下载目录 / miniQMT 目录。"""
    global _PRIMARY_DATADIR, _MINIQMT_DATADIR

    _PRIMARY_DATADIR = _configured_download_datadir()
    _MINIQMT_DATADIR = _configured_miniqmt_datadir()

    if _PRIMARY_DATADIR and _is_existing_dir(_PRIMARY_DATADIR):
        return

    for item in _resolve_datadir_candidates(ContextInfo):
        path = item.get('path', '')
        if not path or not _is_existing_dir(path):
            continue
        src = item.get('source', '')
        if 'userdata_mini' in src or 'userdata_mini' in path:
            if not _MINIQMT_DATADIR:
                _MINIQMT_DATADIR = path
            continue
        if path.endswith('datadir') or os.path.basename(path) == 'datadir':
            _PRIMARY_DATADIR = path
            break

    if not _PRIMARY_DATADIR:
        _PRIMARY_DATADIR = _configured_download_datadir()
    if not _MINIQMT_DATADIR:
        _MINIQMT_DATADIR = _configured_miniqmt_datadir()


def get_download_datadir() -> str:
    return _PRIMARY_DATADIR or _configured_download_datadir()


def get_miniqmt_datadir() -> str:
    return _MINIQMT_DATADIR or _configured_miniqmt_datadir()


def _min_ok_bytes(period: str) -> int:
    return MIN_1D_OK_BYTES if period == '1d' else MIN_1M_OK_BYTES


def _count_period_dat_files(datadir: str, period: str) -> int:
    if not datadir or not _is_existing_dir(datadir):
        return 0
    period_dirs = _PERIOD_DIR_CANDIDATES.get(period, [period])
    total = 0
    try:
        for mkt in ('SH', 'SZ', 'sh', 'sz'):
            mkt_dir = os.path.join(datadir, mkt)
            if not _is_existing_dir(mkt_dir):
                continue
            for pd in period_dirs:
                pd_dir = os.path.join(mkt_dir, pd)
                if _is_existing_dir(pd_dir):
                    total += len([f for f in os.listdir(pd_dir) if f.upper().endswith('.DAT')])
    except Exception:
        pass
    return total


def _file_mtime_yyyymmdd(path: str) -> str:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y%m%d')
    except Exception:
        return ''


def _probe_via_api(
    ContextInfo,
    code: str,
    period: str,
    req_start: str,
    req_end: str,
) -> Optional[Dict[str, Any]]:
    block = _get_local_block(ContextInfo, code, period, req_start, req_end)
    if block is None:
        return None

    closes = None
    times: List[str] = []

    if isinstance(block, dict):
        if 'close' in block:
            closes = _to_list(block['close'])
        for key in ('time', 'stime', 'datetime', 'date'):
            if key in block:
                times = [_norm_date_str(x) for x in _to_list(block[key])]
                break
    elif hasattr(block, 'columns'):
        if 'close' in block.columns:
            closes = _to_list(block['close'])
        times = _extract_time_index(block)
    elif hasattr(block, '__len__'):
        closes = _to_list(block)

    if not times:
        times = _extract_time_index(block)
    valid_times = [t for t in times if t and _valid_yyyymmdd(t)]
    bar_count = len(closes) if closes else len(valid_times)
    if bar_count <= 0:
        return None

    first_date = min(valid_times) if valid_times else ''
    last_date = max(valid_times) if valid_times else ''
    return {
        'bar_count': bar_count,
        'first_date': first_date,
        'last_date': last_date,
        'source': 'API',
    }


def _classify_coverage(
    req_start: str,
    req_end: str,
    first_date: str,
    last_date: str,
    file_size: int,
    period: str,
    from_disk: bool,
) -> Tuple[str, str]:
    min_ok = _min_ok_bytes(period)
    if file_size < MIN_DAT_FILE_BYTES:
        return '缺失', '磁盘文件过小或为空'

    if first_date and last_date:
        if first_date <= req_start and last_date >= req_end:
            return '完整', '已覆盖目标区间'
        if last_date < req_end:
            return '待更新', '末条日期早于目标结束日'
        if first_date > req_start:
            return '部分', '缺少区间前段数据'
        return '已有', '本地有数据'

    if from_disk and file_size >= min_ok:
        if last_date and last_date >= req_end:
            return '完整', '磁盘文件已存在(按修改时间判断)'
        return '已有', '磁盘文件已存在 %.1fKB' % (file_size / 1024.0)

    if file_size >= min_ok:
        return '已有', '本地文件已存在'
    return '已有', '磁盘有文件但体积偏小'


def _probe_via_filesystem(
    code: str,
    period: str,
    req_start: str,
    req_end: str,
) -> Dict[str, Any]:
    datadir = get_download_datadir()
    period_dir, dat_path = _find_symbol_dat_file(datadir, code, period)

    if not dat_path or not os.path.isfile(dat_path):
        return {
            'code': code,
            'status': '缺失',
            'bar_count': 0,
            'first_date': '',
            'last_date': '',
            'detail': '磁盘无DAT: %s' % dat_path,
            'dat_path': dat_path or '',
            'period_dir': period_dir,
        }

    try:
        file_size = int(os.path.getsize(dat_path))
    except Exception:
        file_size = 0

    last_date = _file_mtime_yyyymmdd(dat_path)
    first_date = ''
    bar_count = 0
    status, detail = _classify_coverage(
        req_start, req_end, first_date, last_date, file_size, period, from_disk=True,
    )
    return {
        'code': code,
        'status': status,
        'bar_count': bar_count,
        'first_date': first_date or '-',
        'last_date': last_date or '-',
        'detail': detail,
        'dat_path': dat_path,
        'period_dir': period_dir,
        'file_size': file_size,
    }


def _merge_api_into_fs(fs_info: Dict[str, Any], api_info: Dict[str, Any], req_start: str, req_end: str, period: str) -> Dict[str, Any]:
    file_size = int(fs_info.get('file_size') or 0)
    first_date = api_info.get('first_date') or ''
    last_date = api_info.get('last_date') or fs_info.get('last_date') or ''
    bar_count = int(api_info.get('bar_count') or 0)
    status, detail = _classify_coverage(
        req_start, req_end, first_date, last_date, file_size, period, from_disk=True,
    )
    fs_info['status'] = status
    fs_info['detail'] = detail + ' +API'
    fs_info['bar_count'] = bar_count
    fs_info['first_date'] = first_date or '-'
    fs_info['last_date'] = last_date or '-'
    return fs_info


def _is_existing_dir(path: str) -> bool:
    try:
        return bool(path) and os.path.isdir(path)
    except Exception:
        return False


def _call_global_path_fn(fn_name: str) -> Optional[str]:
    fn = globals().get(fn_name)
    if fn is None:
        return None
    try:
        result = fn()
        if result:
            return _norm_path(str(result))
    except Exception:
        pass
    return None


def _resolve_datadir_candidates(ContextInfo) -> List[Dict[str, str]]:
    found: List[Dict[str, str]] = []
    seen = set()

    def _add(path: Optional[str], source: str) -> None:
        if not path:
            return
        norm = _norm_path(path)
        if norm in seen:
            return
        seen.add(norm)
        found.append({
            'path': norm,
            'source': source,
            'exists': '是' if _is_existing_dir(norm) else '否',
        })

    _add(_configured_download_datadir(), '配置: DOWNLOAD_DATADIR [模型研究下载]')
    _add(_configured_miniqmt_datadir(), '配置: MINIQMT_DATADIR [miniQMT/xtdata]')

    try:
        from xtquant import xtdata  # type: ignore
        data_dir = getattr(xtdata, 'get_data_dir', None)
        if callable(data_dir):
            _add(str(data_dir()), 'xtdata.get_data_dir()')
    except Exception:
        pass

    install_roots: List[str] = []
    for fn_name in ('get_main_path', 'get_qmt_path', 'get_app_path'):
        root = _call_global_path_fn(fn_name)
        if root and root not in install_roots:
            install_roots.append(root)

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir and script_dir not in install_roots:
            install_roots.append(script_dir)
    except Exception:
        pass

    for root in install_roots:
        _add(os.path.join(root, 'datadir'), '推断: {安装目录}/datadir [模型研究下载]')
        _add(os.path.join(root, 'userdata_mini', 'datadir'), '推断: userdata_mini/datadir [miniQMT]')
        _add(os.path.join(root, 'userdata', 'datadir'), '推断: userdata/datadir')

    for attr in ('datadir', 'data_dir', 'user_data_dir'):
        try:
            val = getattr(ContextInfo, attr, None)
            if val:
                text = str(val)
                if text.endswith('datadir'):
                    _add(text, 'ContextInfo.' + attr)
                else:
                    _add(os.path.join(text, 'datadir'), 'ContextInfo.' + attr + '/datadir')
        except Exception:
            pass

    return found


def _find_symbol_dat_file(datadir: str, vt: str, period: str) -> Tuple[str, str]:
    code, mkt = _split_vt_symbol(vt)
    if not code or not mkt:
        return '', ''

    period_dirs = _PERIOD_DIR_CANDIDATES.get(period, [period])
    for period_dir in period_dirs:
        for folder in (mkt, mkt.lower()):
            fp = os.path.join(datadir, folder, period_dir, code + '.DAT')
            if os.path.isfile(fp):
                return period_dir, _norm_path(fp)

    try:
        import glob
        pattern = os.path.join(datadir, '**', code + '.DAT')
        for fp in glob.glob(pattern, recursive=True):
            parent = os.path.basename(os.path.dirname(fp))
            grand = os.path.basename(os.path.dirname(os.path.dirname(fp)))
            if grand.upper() == mkt and parent in period_dirs:
                return parent, _norm_path(fp)
    except Exception:
        pass

    expected_period = period_dirs[0] if period_dirs else period
    expected = os.path.join(datadir, mkt, expected_period, code + '.DAT')
    return expected_period, _norm_path(expected)


def _print_data_storage_info(ContextInfo, period: str, title: str = '本地数据存储位置') -> None:
    init_storage_paths(ContextInfo)
    download_dir = get_download_datadir()
    mini_dir = get_miniqmt_datadir()

    print('=' * 72)
    print('【%s】' % title)
    print('  数据格式: QMT 二进制 *.DAT（与「数据管理-补充数据」相同）')
    print('')
    print('  [1] 模型研究 download_history_data 写入目录（本脚本检测/下载用这个）:')
    print('      %s' % (download_dir or '(未配置)'))
    if download_dir:
        print('      目录存在: %s' % ('是' if _is_existing_dir(download_dir) else '否'))
        cnt = _count_period_dat_files(download_dir, period)
        pd_name = _PERIOD_DIR_CANDIDATES.get(period, [period])[0]
        print('      %s 文件数(SH+SZ): %d  (子目录示例: %s)' % (period, cnt, pd_name))
        print('      路径规则: {datadir}/{SH|SZ}/{%s}/{代码}.DAT' % pd_name)
    print('')
    print('  [2] miniQMT / userdata_mini 目录（xtdata 常用，与本脚本下载位置可能不同）:')
    print('      %s' % (mini_dir or '(未配置)'))
    if mini_dir:
        print('      目录存在: %s' % ('是' if _is_existing_dir(mini_dir) else '否'))
        cnt_mini = _count_period_dat_files(mini_dir, period)
        print('      %s 文件数(SH+SZ): %d' % (period, cnt_mini))
        if cnt_mini == 0 and download_dir and _count_period_dat_files(download_dir, period) > 0:
            print('      提示: miniQMT 下无 %s 数据，但 [1] 已有文件 — 请勿只看 userdata_mini' % period)

    sample_code = ALL_SUBSCRIBE_CODES[0] if ALL_SUBSCRIBE_CODES else '513100.SH'
    period_dir, sample_file = _find_symbol_dat_file(download_dir, sample_code, period)
    print('')
    print('  示例文件(%s):' % sample_code)
    if sample_file and os.path.isfile(sample_file):
        print('    %s' % sample_file)
        try:
            print('    大小: %.1f KB  修改: %s' % (
                os.path.getsize(sample_file) / 1024.0,
                _file_mtime_yyyymmdd(sample_file),
            ))
        except Exception:
            pass
    else:
        print('    %s  (尚未生成)' % (sample_file or '-'))

    if ALSO_DOWNLOAD_1D:
        d1_dir, d1_file = _find_symbol_dat_file(download_dir, sample_code, '1d')
        print('  附加 1d 示例: %s' % (d1_file or d1_dir))
    print('-' * 72)


def _to_list(data: Any) -> List[Any]:
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


def _norm_date_str(value: Any) -> str:
    if value is None:
        return ''
    text = str(value).strip()
    if len(text) >= 8 and text[:8].isdigit():
        return text[:8]
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(text[:19], fmt).strftime('%Y%m%d')
        except ValueError:
            continue
    digits = ''.join(ch for ch in text if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ''


def _today_yyyymmdd() -> str:
    """下载工具在 init 阶段运行，bar 时间戳常为 19700101，直接用系统日期。"""
    return datetime.now().strftime('%Y%m%d')


def _valid_yyyymmdd(text: str) -> bool:
    text = (text or '').strip()
    if len(text) != 8 or not text.isdigit():
        return False
    if text < '19900101':
        return False
    return text <= _today_yyyymmdd()


def _resolve_end_date(end_cfg: str) -> str:
    end_cfg = (end_cfg or '').strip()
    if end_cfg:
        if not _valid_yyyymmdd(end_cfg):
            print('[警告] DOWNLOAD_END=%s 无效，改用今日 %s' % (end_cfg, _today_yyyymmdd()))
            return _today_yyyymmdd()
        return end_cfg
    return _today_yyyymmdd()


def _time_range(start: str, end: str) -> Tuple[str, str]:
    """QMT 本地数据接口常用 YYYYMMDD 或 YYYYMMDDHHMMSS。"""
    start_s = (start or '').strip()
    end_s = (end or '').strip()
    if len(start_s) == 8:
        start_s = start_s + '000000'
    if len(end_s) == 8:
        end_s = end_s + '235959'
    return start_s, end_s


def _extract_time_index(block: Any) -> List[str]:
    if block is None:
        return []
    if hasattr(block, 'index'):
        return [_norm_date_str(x) for x in _to_list(block.index)]
    if isinstance(block, dict):
        for key in ('time', 'datetime', 'date'):
            if key in block:
                return [_norm_date_str(x) for x in _to_list(block[key])]
    return []


def _normalize_market_block(result: Any, code: str) -> Any:
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


def _call_get_local_data(ContextInfo, code: str, period: str, start: str, end: str) -> Any:
    """
    国金/QMT 常见签名:
        get_local_data(stock_code, start_time, end_time, period, divid_type, count)
    不同版本 count=0/-1 含义略有差异，依次尝试。
    """
    start_t, end_t = _time_range(start, end)
    last_exc = None
    for count in (0, -1, 999999):
        try:
            result = ContextInfo.get_local_data(code, start_t, end_t, period, 'none', count)
            block = _normalize_market_block(result, code)
            if block is not None:
                return block
        except Exception as exc:
            last_exc = exc
    if last_exc is not None:
        return None
    return None


def _call_market_data_ex(ContextInfo, code: str, period: str, start: str, end: str) -> Any:
    start_t, end_t = _time_range(start, end)
    try:
        data = ContextInfo.get_market_data_ex(
            ['close', 'time'],
            [code],
            period=period,
            start_time=start_t,
            end_time=end_t,
            count=-1,
            fill_data=True,
            subscribe=False,
        )
    except TypeError:
        try:
            data = ContextInfo.get_market_data_ex(
                ['close'],
                [code],
                period=period,
                start_time=start_t,
                end_time=end_t,
                count=-1,
                fill_data=True,
                subscribe=False,
            )
        except Exception:
            return None
    except Exception:
        return None
    return _normalize_market_block(data, code)


def _get_local_block(ContextInfo, code: str, period: str, start: str, end: str) -> Any:
    block = _call_get_local_data(ContextInfo, code, period, start, end)
    if block is not None:
        return block
    return _call_market_data_ex(ContextInfo, code, period, start, end)


def probe_local_data(
    ContextInfo,
    code: str,
    period: str,
    req_start: str,
    req_end: str,
) -> Dict[str, Any]:
    init_storage_paths(ContextInfo)

    if USE_FILESYSTEM_PROBE:
        fs_info = _probe_via_filesystem(code, period, req_start, req_end)
        if fs_info.get('status') != '缺失':
            api_info = _probe_via_api(ContextInfo, code, period, req_start, req_end)
            if api_info:
                return _merge_api_into_fs(fs_info, api_info, req_start, req_end, period)
            return fs_info
        if not get_download_datadir():
            return fs_info

    api_info = _probe_via_api(ContextInfo, code, period, req_start, req_end)
    if api_info:
        datadir = get_download_datadir()
        period_dir, dat_path = _find_symbol_dat_file(datadir, code, period)
        file_size = 0
        if dat_path and os.path.isfile(dat_path):
            try:
                file_size = int(os.path.getsize(dat_path))
            except Exception:
                pass
        status, detail = _classify_coverage(
            req_start,
            req_end,
            api_info.get('first_date') or '',
            api_info.get('last_date') or '',
            file_size,
            period,
            bool(file_size),
        )
        return {
            'code': code,
            'status': status,
            'bar_count': int(api_info.get('bar_count') or 0),
            'first_date': api_info.get('first_date') or '-',
            'last_date': api_info.get('last_date') or '-',
            'detail': detail + ' (API)',
            'dat_path': dat_path or '',
            'period_dir': period_dir,
        }

    if USE_FILESYSTEM_PROBE:
        return _probe_via_filesystem(code, period, req_start, req_end)

    return {
        'code': code,
        'status': '缺失',
        'bar_count': 0,
        'first_date': '',
        'last_date': '',
        'detail': '本地无数据(API+磁盘均未命中)',
        'dat_path': '',
    }


def _print_scan_header(period: str, req_start: str, req_end: str, total: int, workers: int) -> None:
    end_show = req_end if req_end else '最新'
    mode = '并行x%d' % workers if workers > 1 and _HAS_FUTURES else '串行'
    print('=' * 72)
    print('【七星高照 ETF 池】本地数据检测')
    print('  周期: %s  目标区间: %s ~ %s  标的数: %d' % (period, req_start, end_show, total))
    print(
        '  强制重下: %s  附加1d: %s  下载模式: %s'
        % ('是' if FORCE_REDOWNLOAD else '否', '是' if ALSO_DOWNLOAD_1D else '否', mode)
    )
    print('-' * 72)
    print('序号  代码          分组        状态      条数      首条        末条        说明')
    print('-' * 72)


def _print_scan_row(index: int, info: Dict[str, Any]) -> None:
    code = info['code']
    group = _CODE_GROUP.get(code, '其他')
    print(
        '%3d  %-12s  %-10s  %-6s  %8d  %-10s  %-10s  %s'
        % (
            index,
            code,
            group[:10],
            info['status'],
            info['bar_count'],
            info['first_date'] or '-',
            info['last_date'] or '-',
            info['detail'],
        )
    )


def _need_download(info: Dict[str, Any]) -> bool:
    if FORCE_REDOWNLOAD:
        return True
    return info['status'] in ('缺失', '待更新', '部分')


def _download_one(code: str, period: str, start: str, end: str) -> None:
    download_history_data(code, period, start, end)


def _download_worker(task: Tuple[str, str, str, str]) -> Tuple[str, bool, str]:
    code, period, start, end = task
    try:
        _download_one(code, period, start, end)
        _, dat_path = _find_symbol_dat_file(get_download_datadir(), code, period)
        if dat_path and os.path.isfile(dat_path):
            size = int(os.path.getsize(dat_path))
            if size >= MIN_DAT_FILE_BYTES:
                return code, True, ''
            return code, False, 'DAT过小(%dB): %s' % (size, dat_path)
        return code, False, 'download已调用但磁盘未找到: %s' % (dat_path or '-')
    except Exception as exc:
        return code, False, str(exc)


def _run_download_phase(
    ContextInfo,
    codes: List[str],
    period: str,
    req_start: str,
    req_end: str,
    phase_title: str,
    pre_scan: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[int, int, int]:
    workers = _effective_workers()
    print('')
    print('=' * 72)
    print(phase_title)
    print('-' * 72)

    skipped = 0
    ok_count = 0
    fail_count = 0
    todo: List[str] = []
    status_map: Dict[str, Dict[str, Any]] = dict(pre_scan or {})

    for code in codes:
        info = status_map.get(code)
        if info is None:
            info = probe_local_data(ContextInfo, code, period, req_start, req_end)
            status_map[code] = info
        if _need_download(info):
            todo.append(code)
        else:
            skipped += 1

    if not todo:
        print('  全部标的本地数据已满足目标区间，无需下载。')
        return skipped, ok_count, fail_count

    print('  待处理 %d 只，跳过 %d 只，并行线程 %d' % (len(todo), skipped, workers))
    print('-' * 72)

    tasks = [(code, period, req_start, req_end) for code in todo]
    t0 = datetime.now()

    def _download_on_result(result: Any) -> Tuple[bool, str]:
        if isinstance(result, Exception):
            return False, '异常'
        code, ok, _err = result
        return bool(ok), str(code)

    dl_progress = TextProgressBar(len(tasks), label='下载' + period) if SHOW_PROGRESS_BAR else None
    results = _run_parallel(
        tasks,
        _download_worker,
        workers,
        label='下载',
        progress=dl_progress,
        on_result=_download_on_result,
    )
    elapsed = (datetime.now() - t0).total_seconds()

    download_ok: List[str] = []
    for item in results:
        if isinstance(item, Exception):
            fail_count += 1
            if SHOW_DOWNLOAD_ITEM_LOG:
                _log('  [FAIL] 下载线程异常: %s' % item)
            continue
        code, ok, err = item
        before = status_map.get(code, {})
        group = _CODE_GROUP.get(code, '其他')
        if ok:
            download_ok.append(code)
            ok_count += 1
            if SHOW_DOWNLOAD_ITEM_LOG:
                _log('  [OK] %s (%s)  原状态:%s  下载完成' % (code, group, before.get('status', '-')))
        else:
            fail_count += 1
            if SHOW_DOWNLOAD_ITEM_LOG:
                _log('  [FAIL] %s (%s)  下载失败: %s' % (code, group, err))
            else:
                _log('  [FAIL] %s  下载失败: %s' % (code, err))

    print('-' * 72)
    print('  下载阶段耗时 %.1f 秒，成功 %d，失败 %d' % (elapsed, ok_count, fail_count))

    if VERIFY_AFTER_DOWNLOAD and download_ok:
        print('  开始并行复检本地数据...')
        verify_tasks = download_ok

        def _verify_one(c: str) -> Tuple[str, Dict[str, Any]]:
            return c, probe_local_data(ContextInfo, c, period, req_start, req_end)

        def _verify_on_result(result: Any) -> Tuple[bool, str]:
            if isinstance(result, Exception):
                return False, '异常'
            code, after = result
            ok = after.get('status') not in ('缺失',)
            return ok, str(code)

        verify_progress = TextProgressBar(len(verify_tasks), label='复检' + period) if SHOW_PROGRESS_BAR else None
        verify_results = _run_parallel(
            verify_tasks,
            _verify_one,
            workers,
            label='复检',
            progress=verify_progress,
            on_result=_verify_on_result,
        )
        if SHOW_DOWNLOAD_ITEM_LOG:
            for item in verify_results:
                if isinstance(item, Exception):
                    continue
                code, after = item
                status_map[code] = after
                _log(
                    '  [复检] %s  状态:%s  条数:%d  区间:%s~%s  (%s)'
                    % (
                        code,
                        after['status'],
                        after['bar_count'],
                        after['first_date'] or '-',
                        after['last_date'] or '-',
                        after['detail'],
                    )
                )
        else:
            for item in verify_results:
                if isinstance(item, Exception):
                    continue
                code, after = item
                status_map[code] = after

    return skipped, ok_count, fail_count


def run_pool_download(ContextInfo) -> None:
    init_storage_paths(ContextInfo)
    req_start = (DOWNLOAD_START or '').strip()
    req_end = _resolve_end_date(DOWNLOAD_END)
    if not req_start:
        print('[错误] DOWNLOAD_START 不能为空，请配置起始日期 YYYYMMDD')
        return
    if not _valid_yyyymmdd(req_start):
        print('[错误] DOWNLOAD_START=%s 无效，请使用 YYYYMMDD 且 >= 19900101' % req_start)
        return
    if req_start > req_end:
        print('[错误] 起始日 %s 晚于结束日 %s' % (req_start, req_end))
        return

    codes = ALL_SUBSCRIBE_CODES
    workers = _effective_workers()
    _print_data_storage_info(ContextInfo, DOWNLOAD_PERIOD, title='下载前-本地数据存储位置')
    _print_scan_header(DOWNLOAD_PERIOD, req_start, req_end, len(codes), workers)

    scan_t0 = datetime.now()
    if workers > 1 and _HAS_FUTURES:
        scan_jobs = [(code, DOWNLOAD_PERIOD, req_start, req_end) for code in codes]

        def _scan_one(job: Tuple[str, str, str, str]) -> Dict[str, Any]:
            code, period, s, e = job
            return probe_local_data(ContextInfo, code, period, s, e)

        def _scan_on_result(result: Any) -> Tuple[bool, str]:
            if isinstance(result, Exception):
                return False, '异常'
            if isinstance(result, dict):
                return True, str(result.get('code', ''))
            return False, ''

        scan_progress = TextProgressBar(len(scan_jobs), label='检测') if SHOW_PROGRESS_BAR else None
        scan_results = _run_parallel(
            scan_jobs,
            _scan_one,
            workers,
            label='检测',
            progress=scan_progress,
            on_result=_scan_on_result,
        )
    else:
        scan_progress = TextProgressBar(len(codes), label='检测') if SHOW_PROGRESS_BAR else None
        scan_results = []
        for code in codes:
            info = probe_local_data(ContextInfo, code, DOWNLOAD_PERIOD, req_start, req_end)
            scan_results.append(info)
            if scan_progress is not None:
                scan_progress.update(code, ok=True)
        if scan_progress is not None:
            scan_progress.finish()
    scan_elapsed = (datetime.now() - scan_t0).total_seconds()
    print('  本地检测耗时 %.1f 秒' % scan_elapsed)

    scan_by_code = {info['code']: info for info in scan_results if isinstance(info, dict)}
    for i, code in enumerate(codes, 1):
        info = scan_by_code.get(code)
        if info is None:
            info = {'code': code, 'status': '缺失', 'bar_count': 0, 'first_date': '', 'last_date': '', 'detail': '检测异常'}
        _print_scan_row(i, info)

    complete = sum(1 for x in scan_by_code.values() if x.get('status') == '完整')
    partial = sum(1 for x in scan_by_code.values() if x.get('status') in ('部分', '待更新', '已有'))
    missing = sum(1 for x in scan_by_code.values() if x.get('status') == '缺失')
    print('-' * 72)
    print(
        '检测汇总: 完整 %d | 部分/待更新/已有 %d | 缺失 %d | 合计 %d'
        % (complete, partial, missing, len(codes))
    )

    skip1, ok1, fail1 = _run_download_phase(
        ContextInfo,
        codes,
        DOWNLOAD_PERIOD,
        req_start,
        req_end,
        '【阶段1】下载 / 更新 %s 数据' % DOWNLOAD_PERIOD,
        pre_scan=scan_by_code,
    )

    skip2 = ok2 = fail2 = 0
    if ALSO_DOWNLOAD_1D:
        d1_start = (DOWNLOAD_1D_START or req_start).strip()
        d1_end = _resolve_end_date(DOWNLOAD_1D_END or req_end)
        skip2, ok2, fail2 = _run_download_phase(
            ContextInfo,
            codes,
            '1d',
            d1_start,
            d1_end,
            '【阶段2】下载 / 更新 1d 数据',
            pre_scan=None,
        )

    print('')
    print('=' * 72)
    print('【任务结束】')
    print(
        '  %s: 跳过 %d  成功 %d  失败 %d'
        % (DOWNLOAD_PERIOD, skip1, ok1, fail1)
    )
    if ALSO_DOWNLOAD_1D:
        print('  1d: 跳过 %d  成功 %d  失败 %d' % (skip2, ok2, fail2))
    _print_data_storage_info(ContextInfo, DOWNLOAD_PERIOD, title='下载后-本地数据存储位置')
    print('=' * 72)


def init(ContextInfo):
    print('')
    print('>>> download_etf_pool.py 启动 (%s)' % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    run_pool_download(ContextInfo)
    print('>>> download_etf_pool.py 完成，handlebar 不再执行下载逻辑')
    print('')


def handlebar(ContextInfo):
    return
