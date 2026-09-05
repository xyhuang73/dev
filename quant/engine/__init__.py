"""回测、事件、模拟与实盘引擎共享合同。"""

from .contracts import RunConfig, RunMode, RunResult, SignalFrame, TargetPosition

__all__ = ["RunConfig", "RunMode", "RunResult", "SignalFrame", "TargetPosition"]

