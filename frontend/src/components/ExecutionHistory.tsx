import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Business } from '../App';
import { apiClient, Execution } from '../api/client';
import { FileText, ExternalLink, Loader2, Filter, CheckCircle, XCircle, Clock, AlertTriangle, Eye, RotateCcw } from 'lucide-react';
import { getRunnerSource } from '../utils/executionUtils';

type Props = {
  businesses: Business[];
};

type SortOrder = 'asc' | 'desc';

export function ExecutionHistory({ businesses }: Props) {
  const navigate = useNavigate();
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selectedBusinessId, setSelectedBusinessId] = useState<string>('');
  const [selectedTriggerType, setSelectedTriggerType] = useState<string>('');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const isGenFilter = selectedBusinessId === '__gen__';

  // Check if there are any active (pending/running) executions
  const hasActiveExecutions = executions.some(e =>
    e.status === 'pending' || e.status === 'running'
  );

  // Load executions with adaptive polling
  useEffect(() => {
    loadExecutions(true); // Initial load with spinner
  }, [selectedBusinessId, selectedTriggerType, currentPage, pageSize]);

  // Adaptive polling: faster when there are active executions
  useEffect(() => {
    // Poll every 3s when active, 20s when idle
    const interval = hasActiveExecutions ? 3000 : 20000;

    const timer = setInterval(() => {
      loadExecutions(false); // Background refresh without spinner
    }, interval);

    return () => clearInterval(timer);
  }, [selectedBusinessId, selectedTriggerType, hasActiveExecutions, currentPage, pageSize]);

  const loadExecutions = async (showLoading = true) => {
    try {
      if (showLoading) setLoading(true);
      const response = await apiClient.getExecutions({
        business_id: (!selectedBusinessId || isGenFilter) ? undefined : selectedBusinessId,
        trigger_type: isGenFilter ? 'gen' : (selectedTriggerType || undefined),
        limit: pageSize,
        offset: (currentPage - 1) * pageSize,
      });
      setExecutions(response.items);
      setTotal(response.total);
    } catch (err) {
      console.error('Failed to load executions:', err);
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  // Sort executions by time (since backend might not return sorted by default or we want to toggle)
  const sortedExecutions = [...executions].sort((a, b) => {
    const timeA = new Date(a.started_at || a.created_at).getTime();
    const timeB = new Date(b.started_at || b.created_at).getTime();
    return sortOrder === 'desc' ? timeB - timeA : timeA - timeB;
  });

  const toggleSortOrder = () => {
    setSortOrder(prev => prev === 'desc' ? 'asc' : 'desc');
  };

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };

  const totalPages = Math.ceil(total / pageSize);
  const startItem = (currentPage - 1) * pageSize + 1;
  const endItem = Math.min(currentPage * pageSize, total);

  const formatTime = (dateStr?: string) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).replace(/\//g, '/');
  };

  const openReport = (url?: string) => {
    if (url) {
      window.open(url, '_blank');
    }
  };

  // Generate a color for business tag based on name
  const getBusinessColor = (name?: string) => {
    if (!name) return 'bg-gray-100 text-gray-600';
    const colors = [
      'bg-purple-100 text-purple-700',
      'bg-green-100 text-green-700',
      'bg-purple-100 text-purple-700',
      'bg-orange-100 text-orange-700',
      'bg-pink-100 text-pink-700',
      'bg-cyan-100 text-cyan-700',
      'bg-yellow-100 text-yellow-700',
    ];
    const hash = name.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
    return colors[hash % colors.length];
  };

  // Render status badge
  const renderStatus = (status: string) => {
    return null; // Status is now integrated into action column
  };

  // Render action column based on status
  const renderAction = (exec: Execution) => {
    const rerun = exec.trigger_type === 'gen' && exec.config?.target_url ? (
      <button
        onClick={() => navigate('/gen', { state: { fromExecution: exec } })}
        className="inline-flex items-center px-3 py-1.5 bg-purple-50 text-purple-600 hover:bg-purple-100 rounded-lg transition-colors text-sm font-medium"
        title="将此次配置填入探索表单"
      >
        回填参数
      </button>
    ) : null;
    switch (exec.status) {
      case 'completed':
      case 'passed':
        return (
          <div className="flex items-center gap-2">
            {exec.report_url && (
              <button
                onClick={() => openReport(exec.report_url!)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-600 hover:bg-blue-100 rounded-lg transition-colors text-sm font-medium"
              >
                查看报告
                <ExternalLink className="w-3 h-3" />
              </button>
            )}
            <button
              onClick={() => navigate(`/execution/${exec.id}`)}
              className="inline-flex items-center px-3 py-1.5 bg-gray-50 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors text-sm font-medium"
            >
              查看执行日志
            </button>
            {rerun}
          </div>
        );
      case 'failed':
        return (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 text-red-500 bg-red-50/50 px-3 py-1.5 rounded-lg w-fit">
              <XCircle className="w-3 h-3" />
              <span className="text-sm font-medium">执行失败</span>
            </div>
            <button
              onClick={() => navigate(`/execution/${exec.id}`)}
              className="inline-flex items-center px-3 py-1.5 bg-gray-50 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors text-sm font-medium"
            >
              查看执行日志
            </button>
            {rerun}
          </div>
        );
      case 'timeout':
        return (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 text-orange-500 bg-orange-50/50 px-3 py-1.5 rounded-lg w-fit">
              <Clock className="w-4 h-4" />
              <span className="text-sm font-medium">执行超时</span>
            </div>
            <button
              onClick={() => navigate(`/execution/${exec.id}`)}
              className="inline-flex items-center px-3 py-1.5 bg-gray-50 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors text-sm font-medium"
            >
              查看执行日志
            </button>
            {rerun}
          </div>
        );
      case 'warning':
        return (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 text-yellow-600 bg-yellow-50/50 px-3 py-1.5 rounded-lg w-fit">
              <AlertTriangle className="w-4 h-4" />
              <span className="text-sm font-medium">执行异常</span>
            </div>
            <button
              onClick={() => navigate(`/execution/${exec.id}`)}
              className="inline-flex items-center px-3 py-1.5 bg-gray-50 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors text-sm font-medium"
            >
              查看执行日志
            </button>
            {rerun}
          </div>
        );
      case 'running':
        return (
          <div className="flex flex-col items-start gap-1">
            <button
              onClick={() => navigate(`/execution/${exec.id}`)}
              className="flex items-center gap-2 text-blue-600 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-lg transition-colors"
            >
              <Loader2 className="w-4 h-4 animate-spin" />
              <span className="text-sm font-medium">查看进度</span>
            </button>
            <span className="text-xs text-gray-400 pl-1">点击查看实时执行日志</span>
          </div>
        );
      case 'pending':
        return (
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate(`/execution/${exec.id}`)}
              className="flex items-center gap-2 text-gray-500 bg-gray-50 hover:bg-gray-100 px-3 py-1.5 rounded-lg transition-colors"
            >
              <Clock className="w-4 h-4" />
              <span className="text-sm font-medium">排队中</span>
            </button>
            {rerun}
          </div>
        );
      default:
        return <span className="text-sm text-gray-400">-</span>;
    }
  };

  return (
    <div className="min-h-screen px-4 sm:px-6 py-4 sm:py-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">执行记录</h1>
          <p className="text-gray-600 mt-1">查看所有测试执行记录</p>
        </div>
      </div>

      {/* Loading State */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 text-blue-600 animate-spin" />
        </div>
      )}

      {/* Executions Table */}
      {!loading && sortedExecutions.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
            <thead>
              <tr className="bg-gray-50/50 border-b border-gray-200">
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider w-32">
                  任务ID
                </th>
                <th
                  className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 transition-colors relative group"
                >
                  <div className="flex items-center gap-2">
                    <select
                      id="business-filter"
                      value={selectedBusinessId}
                      onChange={(e) => {
                        setSelectedBusinessId(e.target.value);
                        if (e.target.value === '__gen__') setSelectedTriggerType('');
                        setCurrentPage(1);
                      }}
                      className="cursor-pointer"
                    >
                      <option value="">全部来源</option>
                      <option value="__gen__">AI 探索</option>
                      {businesses.map(b => (
                        <option key={b.id} value={b.id}>{b.name}</option>
                      ))}
                    </select>
                    <Filter className={`w-3 h-3 ${selectedBusinessId ? 'text-blue-600' : 'text-gray-400'} group-hover:text-gray-600`} />
                  </div>
                </th>
                {selectedBusinessId && (
                  <th
                    className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 transition-colors relative group"
                  >
                    {isGenFilter ? (
                      <span>目标网址</span>
                    ) : (
                      <div className="flex items-center gap-2">
                        <select
                          value={selectedTriggerType}
                          onChange={(e) => {
                            setSelectedTriggerType(e.target.value);
                            setCurrentPage(1);
                          }}
                          className="cursor-pointer"
                        >
                          <option value="">触发方式</option>
                          <option value="manual">手动触发</option>
                          <option value="scheduled">定时触发</option>
                        </select>
                        <Filter className={`w-3 h-3 ${selectedTriggerType ? 'text-blue-600' : 'text-gray-400'}`} />
                      </div>
                    )}
                  </th>
                )}
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  通过数
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  警告数
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  失败数
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider w-48">
                  <button
                    onClick={toggleSortOrder}
                    className="flex items-center gap-1.5 hover:text-gray-900 transition-colors group text-xs font-semibold uppercase tracking-wider"
                  >
                    执行时间
                    <span className="text-gray-400 group-hover:text-gray-600">
                      {sortOrder === 'desc' ? '↓' : '↑'}
                    </span>
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider w-fit whitespace-nowrap">
                  操作 / 状态
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {sortedExecutions.map(exec => (
                <tr key={exec.id} className="hover:bg-gray-50/80 transition-all group">
                  {/* Task ID */}
                  <td className="px-6 py-4">
                    <span className="font-mono text-sm text-gray-500 bg-gray-100 px-2 py-1 rounded group-hover:bg-gray-200 transition-colors" title={exec.id}>
                      {exec.id.slice(0, 8)}
                    </span>
                  </td>

                  {/* Source */}
                  <td className="px-6 py-4">
                    {exec.trigger_type === 'gen' ? (
                      <div className="flex flex-col">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-purple-600">AI 探索</span>
                          {getRunnerSource(exec) === 'mini' ? (
                            <span className="text-[10px] px-1.5 py-0.5">
                              Flash
                            </span>
                          ) : null}
                        </div>
                        {!selectedBusinessId && exec.config?.target_url && (
                          <span className="text-xs text-gray-500 truncate max-w-[200px]" title={exec.config.target_url}>
                            {exec.config.target_url.replace(/^https?:\/\//, '').slice(0, 20)}
                            {exec.config.target_url.replace(/^https?:\/\//, '').length > 20 ? '...' : ''}
                          </span>
                        )}
                      </div>
                    ) : (
                      <div className="flex flex-col">
                        <span className="text-sm font-medium text-gray-900">
                          {exec.business_name || '-'}
                        </span>
                        {exec.environment_name && (
                          <div className="flex items-center gap-1.5 text-xs text-gray-500">
                            <div className="w-1 h-1 rounded-full bg-gray-300" />
                            {exec.environment_name}
                          </div>
                        )}
                      </div>
                    )}
                  </td>

                  {/* Trigger Type / Target URL — only when a source is selected */}
                  {selectedBusinessId && (
                    <td className="px-6 py-4">
                      {exec.trigger_type === 'gen' ? (
                        exec.config?.target_url ? (
                          <div className="relative group/url">
                            <span className="text-sm text-gray-900 cursor-default">
                              {(() => {
                                const short = exec.config.target_url.replace(/^https?:\/\//, '');
                                return short.length > 20 ? short.slice(0, 20) + '...' : short;
                              })()}
                            </span>
                            {exec.config.target_url.replace(/^https?:\/\//, '').length > 20 && (
                              <div className="absolute left-0 bottom-full mb-1 hidden group-hover/url:block z-10 px-2 py-1 text-xs text-white bg-gray-800 rounded shadow-lg whitespace-nowrap">
                                {exec.config.target_url}
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-sm text-gray-400">-</span>
                        )
                      ) : (
                        <span className="text-sm text-gray-600">
                          {exec.trigger_type === 'scheduled' ? '定时触发' : '手动触发'}
                        </span>
                      )}
                    </td>
                  )}

                  {/* Passed Count */}
                  <td className="px-6 py-4">
                    {exec.result_count ? (
                      <span className="text-sm font-semibold text-green-600 bg-green-50 px-2 py-1 rounded">
                        {exec.result_count.passed}
                      </span>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>

                  {/* Warning Count */}
                  <td className="px-6 py-4">
                    {exec.result_count && (exec.result_count.warning || 0) > 0 ? (
                      <span className="text-sm font-semibold text-yellow-500">
                        {exec.result_count.warning}
                      </span>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>

                  {/* Failed Count */}
                  <td className="px-6 py-4">
                    {exec.result_count && exec.result_count.failed > 0 ? (
                      <span className="text-sm font-semibold text-red-600 bg-red-50 px-2 py-1 rounded">
                        {exec.result_count.failed}
                      </span>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>

                  {/* Execution Time */}
                  <td className="px-6 py-4">
                    <div className="flex flex-col">
                      <span className="text-sm font-medium text-gray-900">
                        {formatTime(exec.started_at || exec.created_at).split(' ')[0]}
                      </span>
                      <span className="text-xs text-gray-400">
                        {formatTime(exec.started_at || exec.created_at).split(' ')[1]}
                      </span>
                    </div>
                  </td>

                  {/* Actions / Status */}
                  <td className="px-6 py-4 w-px whitespace-nowrap">
                    {renderAction(exec)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}

      {/* Pagination */}
      {!loading && total > 0 && (
        <div className="mt-4 py-4 flex justify-end px-2">
          <ul className="ant-pagination ant-pagination-small ant-pagination-mini ant-table-pagination ant-table-pagination-end css-p45i5k css-var-root flex items-center">
            {/* Previous Page */}
            <li
              title="Previous Page"
              className={`ant-pagination-prev ${currentPage === 1 ? 'ant-pagination-disabled' : ''}`}
              aria-disabled={currentPage === 1}
            >
              <button
                className="ant-pagination-item-link flex items-center justify-center"
                type="button"
                tabindex="-1"
                disabled={currentPage === 1}
                onClick={() => currentPage > 1 && handlePageChange(currentPage - 1)}
              >
                <span role="img" aria-label="left" className="anticon anticon-left">
                  <svg viewBox="64 64 896 896" focusable="false" data-icon="left" width="1em" height="1em" fill="currentColor" aria-hidden="true">
                    <path d="M724 218.3V141c0-6.7-7.7-10.4-12.9-6.3L260.3 486.8a31.86 31.86 0 000 50.3l450.8 352.1c5.3 4.1 12.9.4 12.9-6.3v-77.3c0-4.9-2.3-9.6-6.1-12.6l-360-281 360-281.1c3.8-3 6.1-7.7 6.1-12.6z"></path>
                  </svg>
                </span>
              </button>
            </li>

            {/* Page Numbers */}
            {Array.from({ length: totalPages }, (_, i) => i + 1)
              .filter(pageNum => {
                if (totalPages <= 5) return true;
                if (pageNum === 1 || pageNum === totalPages) return true;
                return Math.abs(pageNum - currentPage) <= 1;
              })
              .map((pageNum, idx, arr) => {
                const elements: React.ReactNode[] = [];
                // Add ellipsis
                if (idx > 0 && pageNum - arr[idx - 1] > 1) {
                  elements.push(
                    <li key={`sep-${pageNum}`} className="ant-pagination-jump-next ant-pagination-item-link">
                      <span className="ant-pagination-item-ellipsis">•••</span>
                    </li>
                  );
                }
                elements.push(
                  <li
                    key={pageNum}
                    title={String(pageNum)}
                    className={`ant-pagination-item ant-pagination-item-${pageNum} ${currentPage === pageNum ? 'ant-pagination-item-active' : ''}`}
                    tabIndex={0}
                    onClick={() => handlePageChange(pageNum)}
                  >
                    <a rel="nofollow">{pageNum}</a>
                  </li>
                );
                return elements;
              })}

            {/* Next Page */}
            <li
              title="Next Page"
              tabIndex={0}
              className={`ant-pagination-next ${currentPage === totalPages ? 'ant-pagination-disabled' : ''}`}
              aria-disabled={currentPage === totalPages}
            >
              <button
                className="ant-pagination-item-link flex items-center justify-center"
                type="button"
                tabindex="-1"
                disabled={currentPage === totalPages}
                onClick={() => currentPage < totalPages && handlePageChange(currentPage + 1)}
              >
                <span role="img" aria-label="right" className="anticon anticon-right">
                  <svg viewBox="64 64 896 896" focusable="false" data-icon="right" width="1em" height="1em" fill="currentColor" aria-hidden="true">
                    <path d="M765.7 486.8L314.9 134.7A7.97 7.97 0 00302 141v77.3c0 4.9 2.3 9.6 6.1 12.6l360 281.1-360 281.1c-3.9 3-6.1 7.7-6.1 12.6V883c0 6.7 7.7 10.4 12.9 6.3l450.8-352.1a31.96 31.96 0 000-50.4z"></path>
                  </svg>
                </span>
              </button>
            </li>
          </ul>
        </div>
      )}

      {/* Empty State */}
      {!loading && sortedExecutions.length === 0 && (
        <div className="text-center py-16 bg-white rounded-lg border border-gray-200">
          <FileText className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <p className="text-gray-500 text-lg">暂无执行记录</p>
          {(selectedBusinessId || selectedTriggerType) && (
            <button
              onClick={() => {
                setSelectedBusinessId('');
                setSelectedTriggerType('');
                setCurrentPage(1);
              }}
              className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 bg-blue-50 text-blue-600 hover:bg-blue-100 rounded-lg transition-colors text-sm font-medium"
            >
              查看全部记录
            </button>
          )}
        </div>
      )}
    </div>
  );
}
