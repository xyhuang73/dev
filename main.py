"""
TigerTrade：程序入口，负责创建 QApplication 并加载 Designer 生成的 UI。
"""
import faulthandler

import sys
from pathlib import Path

# 原生扩展（polars/Qt 等）若段错误，将 Python 栈写入 stderr，便于排查「无 Python 报错却闪退」
faulthandler.enable(all_threads=True)

# 项目根加入模块搜索路径，便于任意 cwd 下运行
_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from PySide6.QtCore import QFile, QIODevice
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication

from gui_tiger import attach_tiger_trade_handlers
from BackTest import attach_backtest_handlers
from Prepare import attach_prepare_handlers
from qmt_service import load_config


def main() -> int:
    # Qt 应用单例
    app = QApplication(sys.argv)
    # 启动时补全 Config/qmt.json（与 qmt_service 共用一套逻辑）
    load_config()

    ui_path = _APP_DIR / "GUI" / "TigerTrade.ui"
    ui_file = QFile(str(ui_path))
    if not ui_file.open(QIODevice.ReadOnly):
        raise RuntimeError(f"无法打开 UI 文件: {ui_path}")

    loader = QUiLoader()
    window = loader.load(ui_file)
    ui_file.close()

    if window is None:
        raise RuntimeError("加载 TigerTrade.ui 失败，请确认文件为有效的 Qt Designer 导出格式。")

    window.setWindowTitle("TigerTrade")
    attach_tiger_trade_handlers(window)
    # 「回测」按钮 → 打开 GUI/BackTest.ui（逻辑在 BackTest 包内）
    attach_backtest_handlers(window)
    # 「更新」按钮 → 打开 GUI/UpdateStock.ui（逻辑在 Prepare 包内）
    attach_prepare_handlers(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
