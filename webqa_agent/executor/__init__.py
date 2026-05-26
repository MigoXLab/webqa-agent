"""Executor package for WebQA Agent test modes."""

from webqa_agent.executor.flash_executor import FlashBatchResult, FlashExecutor
from webqa_agent.executor.result_aggregator import ResultAggregator

try:
    from webqa_agent.executor.gen_executor import GenExecutor
    from webqa_agent.executor.run_executor import RunExecutor
except ModuleNotFoundError:
    GenExecutor = None
    RunExecutor = None

__all__ = [
    'FlashBatchResult',
    'FlashExecutor',
    'GenExecutor',
    'RunExecutor',
    'ResultAggregator',
]
