import type { Execution, RunnerSource } from '../api/client';

export function getRunnerSource(exec: Execution): RunnerSource {
  const source = String(exec.config?.runner_source || '').toLowerCase();
  return source === 'cc-mini' || source === 'cc_mini' ? 'cc-mini' : 'standard';
}

export function isCcMiniExecution(exec: Execution): boolean {
  return getRunnerSource(exec) === 'cc-mini';
}
