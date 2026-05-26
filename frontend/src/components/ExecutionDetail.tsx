import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  CheckCircle,
  XCircle,
  Loader2,
  Clock,
  AlertTriangle,
  ExternalLink,
  RefreshCw,
  Maximize2,
  Minimize2,
  StopCircle,
  Sparkles
} from 'lucide-react';
import { apiClient, ExecutionProgress, Execution } from '../api/client';

export function ExecutionDetail() {
  const { executionId } = useParams<{ executionId: string }>();
  const navigate = useNavigate();

  const [execution, setExecution] = useState<Execution | null>(null);
  const [progress, setProgress] = useState<ExecutionProgress | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);

  // Calculate running time
  const [runningTime, setRunningTime] = useState<string>('');
  // Fullscreen log toggle
  const [isLogFullscreen, setIsLogFullscreen] = useState(false);

  // Escape key to exit fullscreen
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isLogFullscreen) {
        setIsLogFullscreen(false);
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isLogFullscreen]);

  // Load execution details and progress
  const loadData = useCallback(async (showLoading = false) => {
    if (!executionId) return;

    try {
      if (showLoading) setLoading(true);

      // Load execution details
      const exec = await apiClient.getExecution(executionId);
      setExecution(exec);

      // Always try to load progress (Redis cache retains history)
      try {
        const prog = await apiClient.getExecutionProgress(executionId);
        setProgress(prog);
      } catch (e) {
        // Progress might not be available for old executions
        console.log('Progress not available:', e);
      }

      setError(null);
    } catch (err) {
      console.error('Failed to load execution:', err);
      setError('加载执行详情失败');
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [executionId]);

  // Initial load
  useEffect(() => {
    loadData(true);
  }, [loadData]);

  // Polling for progress (only when running)
  useEffect(() => {
    if (!execution) return;

    // Stop polling if execution is complete
    if (!['pending', 'running'].includes(execution.status)) {
      return;
    }

    // Poll every 2 seconds for running, 5 seconds for pending
    const interval = execution.status === 'running' ? 2000 : 5000;
    const timer = setInterval(() => loadData(false), interval);

    return () => clearInterval(timer);
  }, [execution?.status, loadData]);

  // Running time counter
  useEffect(() => {
    if (!execution?.started_at) return;

    const updateTime = () => {
      const start = new Date(execution.started_at!).getTime();
      const end = execution.completed_at
        ? new Date(execution.completed_at).getTime()
        : Date.now();
      const diff = Math.floor((end - start) / 1000);

      const minutes = Math.floor(diff / 60);
      const seconds = diff % 60;
      setRunningTime(`${minutes}m ${seconds}s`);
    };

    updateTime();

    // Only continue updating if still running
    if (['running'].includes(execution.status)) {
      const timer = setInterval(updateTime, 1000);
      return () => clearInterval(timer);
    }
  }, [execution?.started_at, execution?.completed_at, execution?.status]);

  // Format time
  const formatTime = (dateStr?: string) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  // Render status badge
  const renderStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
      case 'passed':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 bg-green-100 text-green-700 rounded-full text-sm font-medium">
            <CheckCircle className="w-4 h-4" />
            已完成
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-2 bg-red-100 text-red-700 rounded-full text-sm font-medium">
            <XCircle className="w-4 h-4" />
            执行失败
          </span>
        );
      case 'timeout':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-2 bg-orange-100 text-orange-700 rounded-full text-sm font-medium">
            <Clock className="w-4 h-4" />
            执行超时
          </span>
        );
      case 'running':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-2 bg-blue-100 text-blue-700 rounded-full text-sm font-medium">
            <Loader2 className="w-4 h-4 animate-spin" />
            正在执行
          </span>
        );
      case 'pending':
        return (
          <span className="inline-flex items-center gap-1.5 px-2 py-2 bg-gray-100 text-gray-700 rounded-full text-sm font-medium">
            <Clock className="w-4 h-4" />
            排队中
          </span>
        );
      default:
        return null;
    }
  };

  // Stop execution
  const handleStop = async () => {
    if (!executionId) return;
    if (!confirm('确定要停止当前任务吗？')) return;

    try {
      setStopping(true);
      await apiClient.stopExecution(executionId);
      // Refresh data to show updated status
      await loadData(false);
    } catch (err) {
      console.error('Failed to stop execution:', err);
      alert('停止任务失败');
    } finally {
      setStopping(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 text-blue-600 animate-spin" />
          <p className="text-gray-600">加载执行详情...</p>
        </div>
      </div>
    );
  }

  if (error || !execution) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <XCircle className="w-16 h-16 text-red-400 mx-auto mb-4" />
          <p className="text-gray-600 text-lg">{error || '执行记录不存在'}</p>
          <button
            onClick={() => navigate('/history')}
            className="mt-4 text-blue-600 hover:text-blue-700"
          >
            返回执行历史
          </button>
        </div>
      </div>
    );
  }

  const isRunning = ['pending', 'running'].includes(execution.status);
  const isCompleted = ['completed', 'passed', 'failed', 'timeout'].includes(execution.status);
  return (
    <div className="min-h-screen bg-gray-50 px-4 sm:px-6 py-4 sm:py-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/history')}
              className="flex items-center gap-1.5 text-gray-500 hover:text-gray-900 transition-colors text-sm"
            >
              <ArrowLeft className="w-4 h-4" />
              <span>返回执行列表</span>
            </button>
            <div className="h-6 w-px bg-gray-300" />
            <h1 className="text-xl font-semibold text-gray-900">
              任务 ID: <span className="font-mono text-gray-600">{executionId?.slice(0, 8)}...</span>
            </h1>
          </div>

          <div className="flex items-center gap-3">
            {/* Stop button */}
            {isRunning && (
              <button
                onClick={handleStop}
                disabled={stopping}
                className="flex items-center gap-2 px-3 py-1.5 text-red-600 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors border border-red-200"
              >
                {stopping ? <Loader2 className="w-4 h-4 animate-spin" /> : <StopCircle className="w-4 h-4" />}
                停止执行
              </button>
            )}

            {/* Refresh button */}
            <button
              onClick={() => loadData(false)}
              className="flex items-center gap-2 px-3 py-1.5 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              刷新
            </button>
          </div>
        </div>

        {/* Execution Overview Card */}
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden mb-6">
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between bg-gray-50/50">
            <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2">
              📊 执行概览
            </h2>
            <div className="flex items-center gap-3">
              {renderStatusBadge(execution.status)}
              {execution.data_flow_report_url && (
                <button
                  onClick={() => window.open(execution.data_flow_report_url, '_blank')}
                  className="inline-flex items-center gap-2 px-4 py-1.5 bg-indigo-50 text-indigo-600 border border-indigo-200 rounded-lg hover:bg-indigo-100 transition-colors text-sm font-medium"
                >
                  Agent Trace
                  <ExternalLink className="w-4 h-4" />
                </button>
              )}
              {execution.report_url && (
                <button
                  onClick={() => window.open(execution.report_url, '_blank')}
                  className="inline-flex items-center gap-2 px-4 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
                >
                  查看报告
                  <ExternalLink className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>

          <div className="px-10 py-8 flex gap-x-12 gap-y-6 flex-wrap">
              {execution.trigger_type === 'gen' ? (
                <>
                  <div className="px-4 py-4">
                    <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">类型</span>
                    <p className="mt-1 font-medium text-purple-600 flex items-center gap-1.5">
                      <Sparkles className="w-4 h-4" />
                      AI 探索
                    </p>
                  </div>
                  <div className="px-4 py-4">
                    <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">目标网址</span>
                    <p className="mt-1 font-medium text-gray-900" title={execution.config?.target_url}>
                      {execution.config?.target_url || '-'}
                    </p>
                  </div>
                </>
              ) : (
                <>
                  <div className="px-4 py-4">
                    <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">业务</span>
                    <p className="mt-1 font-medium text-gray-900">{execution.business_name || '-'}</p>
                  </div>
                  <div className="px-4 py-4">
                    <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">环境</span>
                    <p className="mt-1 font-medium text-gray-900">{execution.environment_name || '-'}</p>
                  </div>
                </>
              )}
              <div className="px-4 py-4">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">模型</span>
                <p className="mt-1 font-medium text-gray-900">{execution.model}</p>
              </div>
              <div className="px-4 py-4">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">用例数</span>
                <p className="mt-1 font-medium text-gray-900">{execution.test_case_ids?.length || '-'}</p>
              </div>
              <div className="px-4 py-4">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">开始时间</span>
                <p className="mt-1 font-medium text-gray-900">{formatTime(execution.started_at)}</p>
              </div>
              <div className="px-4 py-4">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">运行时长</span>
                <p className="mt-1 font-medium text-gray-900 flex items-center gap-2">
                  {runningTime || '-'}
                  {isRunning && <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />}
                </p>
              </div>
          </div>
          {execution.trigger_type === 'gen' && execution.config?._display_objectives && (
            <div className="px-10 py-8 flex gap-x-12 gap-y-6 flex-wrap">
              <div className="px-4 py-4">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">测试目标</span>
                <p className="mt-1 text-sm pb-6 text-gray-900 whitespace-pre-line break-words">
                  {execution.config._display_objectives}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Real-time Progress Section */}
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden mb-6">
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between bg-gray-50/50">
            <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2">
              📜 {isRunning ? '实时日志' : '执行日志'}
            </h2>
            {progress?.updated_at && (
              <span className="text-xs text-gray-400">
                更新于 {new Date(progress.updated_at).toLocaleTimeString('zh-CN')}
              </span>
            )}
          </div>

          <div className="divide-y divide-gray-100">
            {/* Completed Tasks Table */}
            {progress?.completed && progress.completed.length > 0 && (
              <div className="p-6">
                <div className="overflow-hidden rounded-lg border border-gray-200">
                  <table className="w-full">
                    <thead>
                      <tr className="bg-gray-50">
                        <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">执行状态</th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">用例名称</th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">测试结果</th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">耗时</th>
                        <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">错误信息</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {progress.completed.map((task, idx) => (
                        <tr key={idx} className="hover:bg-gray-50/50 transition-colors">
                          <td className="px-4 py-3">
                            {task.status === 'failed' ? (
                              <span className="inline-flex items-center gap-1.5 text-red-600">
                                <XCircle className="w-4 h-4" />
                                <span className="text-sm font-medium">异常中断</span>
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1.5 text-green-600">
                                <CheckCircle className="w-4 h-4" />
                                <span className="text-sm font-medium">执行完成</span>
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-900 font-medium">
                            {task.name}
                          </td>
                          <td className="px-4 py-3">
                            {task.status === 'failed' ? (
                              <span className="text-sm text-gray-400">-</span>
                            ) : task.result === 'passed' ? (
                              <span className="inline-flex items-center gap-1.5 text-green-600">
                                <CheckCircle className="w-4 h-4" />
                                <span className="text-sm font-medium">Pass</span>
                              </span>
                            ) : task.result === 'warning' ? (
                              <span className="inline-flex items-center gap-1.5 text-orange-500">
                                <AlertTriangle className="w-4 h-4" />
                                <span className="text-sm font-medium">Warning</span>
                              </span>
                            ) : task.result === 'failed' ? (
                              <span className="inline-flex items-center gap-1.5 text-red-600">
                                <XCircle className="w-4 h-4" />
                                <span className="text-sm font-medium">Fail</span>
                              </span>
                            ) : (
                              <span className="text-sm text-gray-400">-</span>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <span className="text-sm text-gray-600 font-mono">
                              {task.duration?.toFixed(2)}s
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            {task.error ? (
                              <span className="text-sm text-red-600 max-w-xs truncate block" title={task.error}>
                                {task.error}
                              </span>
                            ) : (
                              <span className="text-gray-400">-</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Running Tasks */}
            {progress?.running && progress.running.length > 0 && (
              <div className="p-6">
                <div className="space-y-2">
                  {progress.running.map((task, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between py-3 px-4 bg-blue-50 rounded-lg border border-blue-100"
                    >
                      <div className="flex items-center gap-3">
                        <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
                        <span className="text-sm font-medium text-gray-900">{task.name}</span>
                      </div>
                      <span className="text-sm text-blue-600 font-mono font-medium">
                        [{task.elapsed?.toFixed(2)}s]
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Logs */}
            {progress?.logs && progress.logs.length > 0 && (
              <div className={
                isLogFullscreen
                  ? "fixed inset-0 z-50 bg-gray-900 flex flex-col"
                  : "p-6"
              }>
                <div className={
                  isLogFullscreen
                    ? "flex-1 flex flex-col overflow-hidden"
                    : "bg-gray-900 rounded-lg overflow-hidden"
                }>
                  {/* Log toolbar */}
                  <div className={`flex items-center justify-between px-4 py-2 ${isLogFullscreen ? 'bg-gray-800 border-b border-gray-700' : ''}`}>
                    <span className="text-xs text-gray-400 font-medium">
                      日志
                    </span>
                    <button
                      onClick={() => setIsLogFullscreen(!isLogFullscreen)}
                      className="p-1.5 rounded hover:bg-gray-700 text-gray-400 hover:text-gray-200 transition-colors"
                      title={isLogFullscreen ? '退出全屏' : '全屏显示'}
                    >
                      {isLogFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                    </button>
                  </div>
                  <div
                    className="overflow-y-auto p-4"
                    style={isLogFullscreen ? { flex: 1 } : { height: '500px', maxHeight: '500px' }}
                  >
                    <pre className="text-xs text-green-400 font-mono whitespace-pre-wrap leading-relaxed break-all">
                      {progress.logs.join('\n')}
                    </pre>
                  </div>
                </div>
              </div>
            )}

            {/* Empty state */}
            {(!progress || (progress.completed.length === 0 && progress.running.length === 0 && progress.logs.length === 0)) && (
              <div className="p-2 text-center text-gray-500">
                {isRunning ? (
                  <>
                    <Loader2 className="w-8 h-8 text-gray-300 mx-auto mb-3 animate-spin" />
                    <p>等待任务开始执行...</p>
                  </>
                ) : (
                  <>
                    <span className="p-2 text-gray-500">日志缓存已过期或不可用</span>
                  </>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Error message */}
        {execution.error_message && (
          <div className="mt-6 bg-red-50 border border-red-200 rounded-lg p-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
              <div>
                <h3 className="font-medium text-red-700">错误信息</h3>
                <p className="text-sm text-red-600 mt-1">{execution.error_message}</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
