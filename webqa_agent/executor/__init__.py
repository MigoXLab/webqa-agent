"""Executor package for WebQA Agent test modes."""

# Core executors (Gen/Run modes)
from webqa_agent.executor.gen_executor import GenExecutor
from webqa_agent.executor.result_aggregator import ResultAggregator
from webqa_agent.executor.run_executor import RunExecutor

__all__ = [
    'GenExecutor',
    'RunExecutor',
    'ResultAggregator',
]
