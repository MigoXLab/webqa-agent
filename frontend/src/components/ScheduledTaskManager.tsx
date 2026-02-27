import React, { useState, useEffect, useRef } from 'react';
import { Calendar, Trash2, Edit, Plus, Clock, CheckCircle2, XCircle, AlertCircle, Loader2, ChevronDown, ChevronUp, Play, RefreshCw } from 'lucide-react';
import { apiClient } from '../api/client';

export type ScheduledTask = {
  id: string;
  business_id: string;
  business_name?: string;
  name: string;
  description?: string;
  environment_id: string;
  environment_name?: string;
  test_case_ids: string[];
  model: string;
  workers: number;
  cron_expression: string;
  enabled: boolean;
  webhook_url?: string;
  feishu_notify_user_id?: string;
  last_run_at?: string;
  next_run_at?: string;
  created_at: string;
  updated_at: string;
};

type Environment = {
  id: string;
  name: string;
  url: string;
};

type TestCase = {
  id: string;
  name: string;
  login_required?: boolean;
  snapshot?: string;
  use_snapshot?: string;
};

type Props = {
  businessId: string;
  businessName: string;
  environments: Environment[];
  testCases: TestCase[];
  showHeader?: boolean;
  showCreateButton?: boolean;
  availableModels: { models: string[], default: string };
  onRefresh?: () => void;
  openCreateModal?: boolean;
  onCreateModalClose?: () => void;
};

export function ScheduledTaskManager({
  businessId,
  businessName,
  environments,
  testCases,
  showHeader = true,
  showCreateButton = true,
  availableModels,
  onRefresh,
  openCreateModal,
  onCreateModalClose,
}: Props) {
  const [showModal, setShowModal] = useState(false);
  const [editingTask, setEditingTask] = useState<ScheduledTask | null>(null);
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [triggeringTaskId, setTriggeringTaskId] = useState<string | null>(null);
  const [triggerResult, setTriggerResult] = useState<{ taskId: string; success: boolean } | null>(null);

  // Local environments & test cases state (synced from API when modal opens)
  const [localEnvironments, setLocalEnvironments] = useState<Environment[]>(environments);
  const [localTestCases, setLocalTestCases] = useState<TestCase[]>(testCases);
  const [refreshingData, setRefreshingData] = useState(false);

  // Cron validation state
  const [cronValidation, setCronValidation] = useState<{
    is_valid: boolean;
    error?: string;
    next_run_times?: string[];
  } | null>(null);
  const [validatingCron, setValidatingCron] = useState(false);
  const [testCasesExpanded, setTestCasesExpanded] = useState(false);
  const [feishuConfigExpanded, setFeishuConfigExpanded] = useState(false);

  // Form state
  const [formData, setFormData] = useState<Partial<ScheduledTask>>({
    name: '',
    description: '',
    environment_id: '',
    test_case_ids: [],
    model: availableModels.default,
    workers: 2,
    cron_expression: '0 8 * * *',
    enabled: true,
    webhook_url: '',
    feishu_notify_user_id: '',
  });

  // Keep local state in sync when props change
  useEffect(() => {
    setLocalEnvironments(environments);
  }, [environments]);

  useEffect(() => {
    setLocalTestCases(testCases);
  }, [testCases]);

  // Refresh environments and test cases from API
  const refreshModalData = async () => {
    setRefreshingData(true);
    try {
      const [business, casesResponse] = await Promise.all([
        apiClient.getBusiness(businessId),
        apiClient.getTestCases(businessId),
      ]);
      setLocalEnvironments(
        (business.environments || []).map(env => ({
          id: env.id || crypto.randomUUID(),
          name: env.name || 'Unknown Environment',
          url: env.url || '',
        }))
      );
      setLocalTestCases(
        (casesResponse.items || []).map(tc => ({
          id: tc.id,
          name: tc.name,
          login_required: tc.login_required,
          snapshot: tc.snapshot,
          use_snapshot: tc.use_snapshot,
        }))
      );
    } catch (err) {
      console.error('Failed to refresh modal data:', err);
    } finally {
      setRefreshingData(false);
    }
  };

  // Open create modal with data refresh
  const openCreateModalWithRefresh = () => {
    resetForm();
    setShowModal(true);
    refreshModalData();
  };

  // React to external create modal trigger
  useEffect(() => {
    if (openCreateModal) {
      resetForm();
      setShowModal(true);
      refreshModalData();
    }
  }, [openCreateModal]);

  // Load tasks
  useEffect(() => {
    loadTasks();
  }, [businessId]);

  const loadTasks = async () => {
    try {
      setLoading(true);
      const response = await apiClient.getScheduledTasks({ business_id: businessId });
      setTasks(response.items || []);
    } catch (err: any) {
      console.error('Failed to load scheduled tasks:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Validate cron expression (only when modal is open)
  useEffect(() => {
    if (!showModal) return;

    const validateCron = async () => {
      if (!formData.cron_expression) {
        setCronValidation(null);
        return;
      }

      setValidatingCron(true);
      try {
        const result = await apiClient.validateCron(formData.cron_expression);
        setCronValidation(result);
      } catch (err) {
        setCronValidation({ is_valid: false, error: '验证失败' });
      } finally {
        setValidatingCron(false);
      }
    };

    const timer = setTimeout(validateCron, 500); // Debounce
    return () => clearTimeout(timer);
  }, [formData.cron_expression, showModal]);

  // Lock body scroll when modal is open
  useEffect(() => {
    if (showModal) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [showModal]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validation
    if (!formData.name) {
      setError('请输入任务名称');
      return;
    }
    if (!formData.environment_id) {
      setError('请选择执行环境');
      return;
    }
    if (!formData.test_case_ids || formData.test_case_ids.length === 0) {
      setError('请至少选择一个测试用例');
      return;
    }
    if (!cronValidation?.is_valid) {
      setError('Cron 表达式无效');
      return;
    }

    setError(null);
    setSaving(true);

    try {
      if (editingTask) {
        // Update
        await apiClient.updateScheduledTask(editingTask.id, {
          name: formData.name,
          description: formData.description,
          environment_id: formData.environment_id,
          test_case_ids: formData.test_case_ids,
          model: formData.model,
          workers: formData.workers,
          cron_expression: formData.cron_expression,
          enabled: formData.enabled,
          webhook_url: formData.webhook_url || null,
          feishu_notify_user_id: formData.feishu_notify_user_id || null,
        });
      } else {
        // Create
        await apiClient.createScheduledTask({
          business_id: businessId,
          name: formData.name!,
          description: formData.description,
          environment_id: formData.environment_id!,
          test_case_ids: formData.test_case_ids!,
          model: formData.model!,
          workers: formData.workers!,
          cron_expression: formData.cron_expression!,
          enabled: formData.enabled!,
          webhook_url: formData.webhook_url || undefined,
          feishu_notify_user_id: formData.feishu_notify_user_id || undefined,
        });
      }

      await loadTasks();
      handleCloseModal();
      onRefresh?.();
    } catch (err: any) {
      console.error('Failed to save task:', err);
      setError(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const resetForm = () => {
    setFormData({
      name: '',
      description: '',
      environment_id: '',
      test_case_ids: [],
      model: availableModels.default,
      workers: 2,
      cron_expression: '0 8 * * *',
      enabled: true,
      webhook_url: '',
      feishu_notify_user_id: '',
    });
    setEditingTask(null);
    setError(null);
    setCronValidation(null);
    setTestCasesExpanded(false);
    setFeishuConfigExpanded(false);
  };

  const handleCloseModal = () => {
    setShowModal(false);
    resetForm();
    onCreateModalClose?.();
  };

  const handleEdit = (task: ScheduledTask) => {
    setEditingTask(task);
    setFormData({
      name: task.name,
      description: task.description,
      environment_id: task.environment_id,
      test_case_ids: task.test_case_ids,
      model: task.model,
      workers: task.workers,
      cron_expression: task.cron_expression,
      enabled: task.enabled,
      webhook_url: task.webhook_url || '',
      feishu_notify_user_id: task.feishu_notify_user_id || '',
    });
    // Auto-expand feishu config if task already has notification settings
    setFeishuConfigExpanded(!!(task.webhook_url || task.feishu_notify_user_id));
    setError(null);
    setShowModal(true);
    refreshModalData();
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`确定要删除定时任务"${name}"吗？`)) {
      return;
    }

    try {
      await apiClient.deleteScheduledTask(id);
      await loadTasks();
      onRefresh?.();
    } catch (err: any) {
      console.error('Failed to delete task:', err);
      alert('删除失败: ' + err.message);
    }
  };

  const handleToggle = async (task: ScheduledTask) => {
    try {
      await apiClient.toggleScheduledTask(task.id, !task.enabled);
      await loadTasks();
      onRefresh?.();
    } catch (err: any) {
      console.error('Failed to toggle task:', err);
      alert('切换失败: ' + err.message);
    }
  };

  const handleTrigger = async (task: ScheduledTask) => {
    setTriggeringTaskId(task.id);
    setTriggerResult(null);
    try {
      await apiClient.triggerScheduledTask(task.id);
      setTriggerResult({ taskId: task.id, success: true });
      onRefresh?.();
    } catch (err: any) {
      console.error('Failed to trigger task:', err);
      setTriggerResult({ taskId: task.id, success: false });
    } finally {
      setTriggeringTaskId(null);
      // 2 秒后清除结果提示
      setTimeout(() => setTriggerResult(null), 2000);
    }
  };

  const toggleTestCase = (caseId: string) => {
    const currentIds = formData.test_case_ids || [];
    let newIds: string[];
    if (currentIds.includes(caseId)) {
      newIds = currentIds.filter(id => id !== caseId);
    } else {
      newIds = [...currentIds, caseId];
    }
    const orderMap = new Map<string, number>(localTestCases.map((tc, idx) => [tc.id, idx]));
    newIds.sort((a, b) => (orderMap.get(a) ?? Infinity) - (orderMap.get(b) ?? Infinity));
    setFormData({ ...formData, test_case_ids: newIds });
  };

  const getEnvName = (envId: string) => {
    const env = localEnvironments.find(e => e.id === envId) || environments.find(e => e.id === envId);
    return env?.name || '未知环境';
  };

  const formatDateTime = (dateStr?: string) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mb-2"></div>
          <p className="text-gray-500 text-sm">加载定时任务...</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      {showHeader && (
        <div className="mb-6 sm:mb-8 flex justify-between items-center">
          <div>
            <h2 className="text-lg font-semibold mb-1">管理 {businessName} 的自动执行任务</h2>
          </div>
          {showCreateButton && (
            <button
              onClick={openCreateModalWithRefresh}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm"
            >
              <Plus className="w-4 h-4" />
              创建任务
            </button>
          )}
        </div>
      )}

      {/* Task List */}
      <div className="space-y-4">
        {tasks.map(task => (
          <div
            key={task.id}
            className="bg-white rounded-lg border border-gray-200 p-4 sm:p-6 hover:shadow-md transition-shadow"
          >
            <div className="flex items-start gap-3 sm:gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-3">
                  <div className="flex items-center gap-3 min-w-0">
                    {task.enabled ? (
                      <CheckCircle2 className="w-5 h-5 text-green-500 flex-shrink-0" />
                    ) : (
                      <XCircle className="w-5 h-5 text-gray-400 flex-shrink-0" />
                    )}
                    <div className="min-w-0 flex-1">
                      <h3 className="mb-1 truncate font-semibold">{task.name}</h3>
                      {task.description && (
                        <p className="text-sm text-gray-500 mb-2">{task.description}</p>
                      )}
                      <div className="flex flex-wrap items-center gap-3 text-sm text-gray-500">
                        <span className="flex items-center gap-1">
                          <Clock className="w-4 h-4" />
                          {task.cron_expression}
                        </span>
                        <span>模型: {task.model}</span>
                        <span>并发: {task.workers}</span>
                        <span className="text-blue-600">📢 飞书通知{task.webhook_url ? '（默认+自定义群）' : '（默认群）'}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      onClick={() => handleTrigger(task)}
                      disabled={triggeringTaskId === task.id}
                      className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:cursor-not-allowed border ${
                        triggerResult?.taskId === task.id
                          ? triggerResult.success
                            ? 'bg-green-50 text-green-700 border-green-200'
                            : 'bg-red-50 text-red-700 border-red-200'
                          : 'bg-blue-50 hover:bg-blue-100 text-blue-700 border-blue-200 disabled:opacity-50'
                      }`}
                      title={`立即执行${task.webhook_url ? '，完成后将通知到默认群和自定义飞书群' : '，完成后将通知到默认飞书群'}`}
                    >
                      {triggeringTaskId === task.id ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : triggerResult?.taskId === task.id ? (
                        triggerResult.success ? (
                          <CheckCircle2 className="w-3 h-3" />
                        ) : (
                          <XCircle className="w-3 h-3" />
                        )
                      ) : (
                        <Play className="w-3 h-3" />
                      )}
                      {triggerResult?.taskId === task.id
                        ? triggerResult.success ? '已触发' : '失败'
                        : '执行'}
                    </button>
                    <label
                      className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium flex-shrink-0 cursor-pointer transition-colors border ${
                        task.enabled
                          ? 'bg-green-50 hover:bg-green-100 text-green-700 border-green-200'
                          : 'bg-gray-50 hover:bg-gray-100 text-gray-600 border-gray-200'
                      }`}
                      title={task.enabled ? '点击禁用' : '点击启用'}
                    >
                      <input
                        type="checkbox"
                        checked={task.enabled}
                        onChange={() => handleToggle(task)}
                        className={`w-4 h-3.5 rounded cursor-pointer ${
                          task.enabled
                            ? 'border-green-300 text-green-600 focus:ring-green-500'
                            : 'border-gray-300 text-gray-400 focus:ring-gray-400'
                        }`}
                      />
                      {task.enabled ? '启用定时任务' : '禁用定时任务'}
                    </label>
                    <button
                      onClick={() => handleEdit(task)}
                      className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
                      title="编辑"
                    >
                      <Edit className="w-4 h-4 text-gray-600" />
                    </button>
                    <button
                      onClick={() => handleDelete(task.id, task.name)}
                      className="p-2 hover:bg-red-50 rounded-lg transition-colors"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4 text-red-600" />
                    </button>
                  </div>
                </div>

                {/* Task Info */}
                <div className="bg-gray-50 rounded-lg p-3 sm:p-4">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                    <div>
                      <span className="text-gray-600">执行环境：</span>
                      <span className="font-medium">{task.environment_name || getEnvName(task.environment_id)}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">测试用例：</span>
                      <span className="font-medium">{task.test_case_ids.length} 个</span>
                    </div>
                    <div>
                      <span className="text-gray-600">上次执行：</span>
                      <span className="font-medium">{formatDateTime(task.last_run_at)}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">下次执行：</span>
                      <span className="font-medium text-blue-600">{formatDateTime(task.next_run_at)}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ))}

        {tasks.length === 0 && (
          <div className="text-center py-12 bg-white rounded-lg border border-gray-200 border-dashed">
            <Calendar className="w-12 h-12 text-gray-300 mx-auto mb-4" />
            <p className="text-gray-500 mb-4">还没有定时任务</p>
            <button
              onClick={openCreateModalWithRefresh}
              className="text-blue-600 hover:text-blue-700 font-medium"
            >
              创建第一个定时任务
            </button>
          </div>
        )}
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ backgroundColor: 'rgba(0, 0, 0, 0.75)' }}>
          <form onSubmit={handleSubmit} className="bg-white rounded-lg flex flex-col shadow-2xl" style={{ width: '960px', maxWidth: '90vw', maxHeight: 'calc(100vh - 64px)' }}>
            <div className="border border-gray-200 rounded-lg flex flex-col flex-1 min-h-0 overflow-hidden">
              {/* Header */}
              <div className="border-b border-gray-200 flex-shrink-0" style={{ padding: '16px 28px' }}>
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-gray-900">{editingTask ? '编辑任务' : '创建任务'}</h2>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleCloseModal}
                      className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium"
                      disabled={saving}
                    >
                      关闭
                    </button>
                    <button
                      type="submit"
                      disabled={saving || !cronValidation?.is_valid}
                      className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                      {saving && <Loader2 className="w-4 h-4 animate-spin" />}
                      {editingTask ? '保存' : '创建'}
                    </button>
                  </div>
                </div>
                {error && (
                  <div className="mt-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    <span>{error}</span>
                  </div>
                )}
              </div>

              {/* Content */}
              <div className="flex-1 overflow-y-auto" style={{ padding: '24px 28px' }}>
                <div className="space-y-6">
                <div>
                  <label className="block text-sm font-medium mb-2 text-gray-700">任务名称 *</label>
                  <input
                    type="text"
                    required
                    value={formData.name}
                    onChange={e => setFormData({...formData, name: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="例如：每日生产环境测试"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2 text-gray-700">执行环境 *</label>
                  <select
                    required
                    value={formData.environment_id}
                    onChange={e => setFormData({...formData, environment_id: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="">选择环境</option>
                    {localEnvironments.map(env => (
                      <option key={env.id} value={env.id}>{env.name} ({env.url})</option>
                    ))}
                  </select>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="block text-sm font-medium text-gray-700">
                      选择测试用例 * ({formData.test_case_ids?.length || 0}/{localTestCases.length} 已选)
                    </label>
                    {localTestCases.length > 5 && (
                      <button
                        type="button"
                        onClick={() => setTestCasesExpanded(!testCasesExpanded)}
                        className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 font-medium"
                      >
                        {testCasesExpanded ? (
                          <>收起 <ChevronUp className="w-3.5 h-3.5" /></>
                        ) : (
                          <>展开全部 <ChevronDown className="w-3.5 h-3.5" /></>
                        )}
                      </button>
                    )}
                  </div>
                  <div className={`${testCasesExpanded ? 'max-h-[400px]' : 'max-h-48'} overflow-y-auto border border-gray-200 rounded-lg bg-white p-3 space-y-1 transition-[max-height] duration-300`}>
                    {localTestCases.length > 0 && (
                      <label className="flex items-center gap-2 text-sm hover:bg-gray-50 px-2 py-1.5 rounded cursor-pointer border-b border-gray-100 pb-2 mb-1">
                        <input
                          type="checkbox"
                          checked={formData.test_case_ids?.length === localTestCases.length}
                          onChange={() => {
                            const allSelected = formData.test_case_ids?.length === localTestCases.length;
                            setFormData({
                              ...formData,
                              test_case_ids: allSelected ? [] : localTestCases.map(tc => tc.id),
                            });
                          }}
                          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 flex-shrink-0"
                        />
                        <span className="font-medium text-gray-700">全选</span>
                      </label>
                    )}
                    {localTestCases.map(tc => (
                      <label key={tc.id} className="flex items-center gap-2 text-sm hover:bg-gray-50 px-2 py-1.5 rounded cursor-pointer">
                        <input
                          type="checkbox"
                          checked={formData.test_case_ids?.includes(tc.id) || false}
                          onChange={() => toggleTestCase(tc.id)}
                          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 flex-shrink-0"
                        />
                        <span className="truncate flex-1">{tc.name}</span>
                        <span className="flex items-center gap-2 flex-shrink-0">
                          {tc.login_required && (
                            <span className="px-3 py-1.5 bg-blue-50 text-blue-700 rounded-lg text-xs font-medium border border-blue-200">
                              需登录
                            </span>
                          )}
                          {tc.snapshot && (
                            <span className="px-3 py-1.5 bg-gray-50 text-gray-500 rounded-lg text-xs font-medium border border-gray-200">
                              📸 快照: {tc.snapshot}
                            </span>
                          )}
                          {tc.use_snapshot && (
                            <span className="px-3 py-1.5 bg-gray-50 text-gray-500 rounded-lg text-xs font-medium border border-gray-200">
                              🔄 使用: {tc.use_snapshot}
                            </span>
                          )}
                        </span>
                      </label>
                    ))}
                    {localTestCases.length === 0 && (
                      <p className="text-sm text-gray-400 text-center py-4">该业务下无测试用例</p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={refreshModalData}
                    disabled={refreshingData}
                    className="mt-2 flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-700 font-medium cursor-pointer transition-colors disabled:opacity-50"
                  >
                    <RefreshCw className={`w-3 h-3 ${refreshingData ? 'animate-spin' : ''}`} />
                    {refreshingData ? '同步中...' : '点击同步最新环境和用例'}
                  </button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-2 text-gray-700">模型</label>
                    <select
                      value={formData.model}
                      onChange={e => setFormData({...formData, model: e.target.value})}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {availableModels.models.map(model => (
                        <option key={model} value={model}>{model}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-2 text-gray-700">并发数</label>
                    <select
                      value={formData.workers}
                      onChange={e => setFormData({...formData, workers: parseInt(e.target.value)})}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {[1, 2, 3, 4, 5].map(n => (
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2 text-gray-700">Cron 表达式 *</label>
                  <input
                    type="text"
                    required
                    value={formData.cron_expression}
                    onChange={e => setFormData({...formData, cron_expression: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="0 8 * * *"
                  />

                  {/* Cron Validation Status */}
                  <div className="mt-2 flex items-center gap-2">
                    {validatingCron && (
                      <span className="text-sm text-gray-500">验证中...</span>
                    )}
                    {!validatingCron && cronValidation && (
                      cronValidation.is_valid ? (
                        <div className="flex items-center gap-2 text-green-600 text-sm">
                          <CheckCircle2 className="w-4 h-4" />
                          <span>有效的 Cron 表达式</span>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2 text-red-600 text-sm">
                          <XCircle className="w-4 h-4" />
                          <span>{cronValidation.error || '无效的 Cron 表达式'}</span>
                        </div>
                      )
                    )}
                  </div>

                  {/* Cron Examples */}
                  <div className="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-2">
                    <p className="text-xs font-medium text-gray-500 mb-2">常用示例（格式：分 时 日 月 周）</p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-1">
                      {[
                        { expr: '0 8 * * *', desc: ' 每天 8:00' },
                        { expr: '0 8-20/2 * * *', desc: ' 每天 8:00-20:00 每隔 2 小时' },
                        { expr: '0 9 * * 1-5', desc: ' 工作日每天 9:00' },
                        { expr: '*/30 9-17 * * 1-5', desc: ' 工作日 9:00-17:00 每 30 分钟' },
                      ].map(item => (
                        <button
                          key={item.expr}
                          type="button"
                          onClick={() => setFormData({ ...formData, cron_expression: item.expr })}
                          className="text-left text-xs px-2 py-1.5 rounded hover:bg-blue-50 hover:text-blue-600 transition-colors group"
                        >
                          <code className="text-blue-600 group-hover:text-blue-700 font-mono">{item.expr}</code>
                          <span className="text-gray-500 ml-2">{item.desc}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                <div>
                  <button
                    type="button"
                    onClick={() => setFeishuConfigExpanded(!feishuConfigExpanded)}
                    className="flex items-center gap-2 text-sm font-medium text-gray-700 hover:text-blue-600 transition-colors"
                  >
                    飞书通知配置
                    {feishuConfigExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    {(formData.webhook_url || formData.feishu_notify_user_id) && (
                      <span className="text-xs text-blue-600 font-normal">（已配置）</span>
                    )}
                  </button>
                  {feishuConfigExpanded && (
                    <div className="mt-2 space-y-3 border border-gray-200 rounded-lg p-4 bg-gray-50">
                      <div>
                        <label className="block text-xs font-medium mb-1 text-gray-600">失败时通知的飞书群: 填写飞书机器人 Webhook 地址</label>
                        <input
                          type="url"
                          value={formData.webhook_url}
                          onChange={e => setFormData({...formData, webhook_url: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white text-sm"
                          placeholder="留空则仅发送到系统默认群"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium mb-1 text-gray-600">失败时 @通知人: 填写飞书 open_id，多人用逗号分隔</label>
                        <input
                          type="text"
                          value={formData.feishu_notify_user_id}
                          onChange={e => setFormData({...formData, feishu_notify_user_id: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white text-sm"
                          placeholder="例如: ou_xxxx, ou_yyyy"
                        />
                      </div>
                      <p className="text-xs text-gray-400">注: 手动执行任务不管成功或失败都会发送通知到自定义飞书群</p>
                    </div>
                  )}
                </div>

                <div className="flex items-center">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={formData.enabled}
                      onChange={e => setFormData({...formData, enabled: e.target.checked})}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-700">创建后立即启用</span>
                  </label>
                </div>
              </div>
              </div>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
