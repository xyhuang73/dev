"""旧 BackTest 接口到新量化核心合同的兼容适配器。"""

from .job_config_adapter import job_to_run_config

__all__ = ["job_to_run_config"]

