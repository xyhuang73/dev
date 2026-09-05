"""旧策略到统一 SignalFrame/TargetPosition 合同的迁移适配器。"""

from .s000001 import S000001OutputCollector
from .s000002 import build_s000002_outputs

__all__ = ["S000001OutputCollector", "build_s000002_outputs"]

