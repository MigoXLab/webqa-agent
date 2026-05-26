import type { Execution, RunnerSource } from '../api/client';

export function getRunnerSource(exec: Execution): RunnerSource {
  const source = String(exec.config?.runner_source || '').toLowerCase();
  if (source === 'cc-mini' || source === 'cc_mini' || source === 'mini') {
    return 'mini';
  }
  return 'standard';
}

export function isMiniExecution(exec: Execution): boolean {
  return getRunnerSource(exec) === 'mini';
}
