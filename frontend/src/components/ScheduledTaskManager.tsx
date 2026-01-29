import React, { useState, useEffect } from 'react';
import { TestCase, Environment } from '../App';
import { Calendar, Trash2, Edit, Plus, Clock, X, CheckCircle2 } from 'lucide-react';
import { apiClient } from '../api/client';

export type ScheduledTask = {
  id: string;
  businessId: string;
  name: string;
  configs: {
    environmentId: string;
    testCaseIds: string[];
  }[];
  model: string;
  workers: number;
  cronExpression: string;
  enabled: boolean;
  lastRunAt?: string;
  nextRunAt?: string;
};

type Props = {
  businessId: string;
  businessName: string;
  environments: Environment[];
  testCases: TestCase[];
  scheduledTasks: ScheduledTask[];
  setScheduledTasks: (tasks: ScheduledTask[]) => void;
  showHeader?: boolean;
  showCreateButton?: boolean;
  availableModels: { models: string[], default: string };
};

export function ScheduledTaskManager({
  businessId,
  businessName,
  environments,
  testCases,
  scheduledTasks,
  setScheduledTasks,
  showHeader = true,
  showCreateButton = true,
  availableModels
}: Props) {
  const [showModal, setShowModal] = useState(false);
  const [editingTask, setEditingTask] = useState<ScheduledTask | null>(null);

  // Filter tasks for this business
  const businessTasks = scheduledTasks.filter(t => t.businessId === businessId);

  // 弹窗打开时禁用背景滚动
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

  // Form state - use default model from backend
  const [formData, setFormData] = useState<Partial<ScheduledTask>>({
    name: '',
    configs: [],
    model: availableModels.default,
    workers: 1,
    cronExpression: '0 8 * * *',
    enabled: true,
  });

  // Update form model when availableModels changes
  useEffect(() => {
    if (!formData.model || !availableModels.models.includes(formData.model)) {
      setFormData(prev => ({ ...prev, model: availableModels.default }));
    }
  }, [availableModels]);

  // Update form default model when backend config loads
  useEffect(() => {
    if (defaultModel && !formData.model) {
      setFormData(prev => ({ ...prev, model: defaultModel }));
    }
  }, [defaultModel]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingTask) {
      setScheduledTasks(scheduledTasks.map(t => t.id === editingTask.id ? { ...t, ...formData, businessId } as ScheduledTask : t));
    } else {
      const newTask: ScheduledTask = {
        ...formData as ScheduledTask,
        businessId,
        id: crypto.randomUUID(),
      };
      setScheduledTasks([...scheduledTasks, newTask]);
    }
    setShowModal(false);
    resetForm();
  };

  const resetForm = () => {
    setFormData({
      name: '',
      configs: [],
      model: defaultModel || '',
      workers: 1,
      cronExpression: '0 8 * * *',
      enabled: true,
    });
    setEditingTask(null);
  };

  const handleEdit = (task: ScheduledTask) => {
    setEditingTask(task);
    setFormData(task);
    setShowModal(true);
  };

  const handleDelete = (id: string) => {
    if (confirm('确定要删除这个定时任务吗？')) {
      setScheduledTasks(scheduledTasks.filter(t => t.id !== id));
    }
  };

  // Helpers for configs
  const addConfig = () => {
    const newConfigs = [...(formData.configs || [])];
    newConfigs.push({ environmentId: '', testCaseIds: [] });
    setFormData({ ...formData, configs: newConfigs });
  };

  const removeConfig = (index: number) => {
    const newConfigs = [...(formData.configs || [])];
    newConfigs.splice(index, 1);
    setFormData({ ...formData, configs: newConfigs });
  };

  const updateConfigEnv = (index: number, envId: string) => {
    const newConfigs = [...(formData.configs || [])];
    newConfigs[index].environmentId = envId;
    setFormData({ ...formData, configs: newConfigs });
  };

  const toggleConfigCase = (configIndex: number, caseId: string) => {
    const newConfigs = [...(formData.configs || [])];
    const currentIds = newConfigs[configIndex].testCaseIds;
    if (currentIds.includes(caseId)) {
        newConfigs[configIndex].testCaseIds = currentIds.filter(id => id !== caseId);
    } else {
        newConfigs[configIndex].testCaseIds = [...currentIds, caseId];
    }
    setFormData({ ...formData, configs: newConfigs });
  };

  const getEnvName = (envId: string) => {
    const env = environments.find(e => e.id === envId);
    return env?.name || '未选择';
  };

  return (
    <div>
      {showHeader && (
        <div className="mb-6 sm:mb-8 flex justify-between items-center">
          <div>
            <h2 className="text-lg font-semibold mb-1">定时任务</h2>
            <p className="text-sm text-gray-500">管理 {businessName} 的自动执行任务</p>
          </div>
          {showCreateButton && (
            <button
              onClick={() => setShowModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm"
            >
              <Plus className="w-4 h-4" />
              创建任务
            </button>
          )}
        </div>
      )}

      {/* Task List - 和测试用例列表样式一致 */}
      <div className="space-y-4">
        {businessTasks.map(task => (
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
                      <X className="w-5 h-5 text-gray-400 flex-shrink-0" />
                    )}
                    <div className="min-w-0 flex-1">
                      <h3 className="mb-1 truncate font-semibold">{task.name}</h3>
                      <div className="flex flex-wrap items-center gap-3 text-sm text-gray-500">
                        <span className="flex items-center gap-1">
                          <Clock className="w-4 h-4" />
                          {task.cronExpression}
                        </span>
                        <span>模型: {task.model}</span>
                        <span>并发: {task.workers}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      onClick={() => handleEdit(task)}
                      className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
                      title="编辑"
                    >
                      <Edit className="w-4 h-4 text-gray-600" />
                    </button>
                    <button
                      onClick={() => handleDelete(task.id)}
                      className="p-2 hover:bg-red-50 rounded-lg transition-colors"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4 text-red-600" />
                    </button>
                  </div>
                </div>

                {/* 配置信息 - 和测试步骤展示样式一致 */}
                <div className="bg-gray-50 rounded-lg p-3 sm:p-4">
                  <div className="flex items-center gap-2 mb-3 text-sm text-gray-600">
                    <Calendar className="w-4 h-4" />
                    <span>执行配置 ({task.configs.length})</span>
                  </div>
                  <div className="space-y-2">
                    {task.configs.slice(0, 3).map((config, idx) => (
                      <div key={idx} className="flex items-center gap-3 text-sm">
                        <span className="w-6 h-6 bg-white rounded-full border border-gray-200 flex items-center justify-center text-gray-600 flex-shrink-0 text-xs font-medium">
                          {idx + 1}
                        </span>
                        <span className="text-gray-700 flex-shrink-0">{getEnvName(config.environmentId)}</span>
                        <span className="text-gray-400 text-xs">({config.testCaseIds.length} 个用例)</span>
                      </div>
                    ))}
                    {task.configs.length > 3 && (
                      <p className="text-sm text-gray-500 pl-9">
                        还有 {task.configs.length - 3} 个配置...
                      </p>
                    )}
                    {task.configs.length === 0 && (
                      <p className="text-sm text-gray-400">暂无执行配置</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        ))}

        {businessTasks.length === 0 && (
          <div className="text-center py-12 bg-white rounded-lg border border-gray-200 border-dashed">
            <Calendar className="w-12 h-12 text-gray-300 mx-auto mb-4" />
            <p className="text-gray-500 mb-4">还没有定时任务</p>
            <button
              onClick={() => setShowModal(true)}
              className="text-blue-600 hover:text-blue-700 font-medium"
            >
              创建第一个定时任务
            </button>
          </div>
        )}
      </div>

      {/* Modal - 和其他弹窗样式一致 */}
      {showModal && (
        <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ backgroundColor: 'rgba(0, 0, 0, 0.75)' }}>
          <div className="bg-white w-full max-w-3xl rounded-lg flex flex-col shadow-2xl" style={{ maxHeight: 'calc(100vh - 64px)' }}>
            <div className="p-4 sm:p-6 border-b border-gray-200 bg-white rounded-t-lg flex items-center justify-between flex-shrink-0">
              <h2 className="text-xl font-bold text-gray-900">{editingTask ? '编辑任务' : '创建任务'}</h2>
              <button
                onClick={() => { setShowModal(false); resetForm(); }}
                className="p-2 hover:bg-gray-100 rounded-lg transition-colors text-gray-400 hover:text-gray-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-4 sm:p-6 overflow-y-auto flex-1 min-h-0">
              <div className="space-y-6">
                <div>
                  <label className="block text-sm font-medium mb-2 text-gray-700">任务名称 *</label>
                  <input
                    type="text"
                    required
                    value={formData.name}
                    onChange={e => setFormData({...formData, name: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="例如：每日全量回归"
                  />
                </div>

                {/* Configs Section - 和测试步骤样式一致 */}
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <label className="block text-sm font-medium text-gray-700">执行配置 *</label>
                    <button
                      type="button"
                      onClick={addConfig}
                      className="text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1"
                    >
                      <Plus className="w-4 h-4" /> 添加配置
                    </button>
                  </div>

                  {formData.configs?.length === 0 && (
                    <div className="text-center py-8 bg-gray-50 rounded-lg border border-gray-200 border-dashed">
                      <Calendar className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                      <p className="text-sm text-gray-500">点击上方按钮添加执行配置</p>
                    </div>
                  )}

                  <div className="space-y-3">
                    {formData.configs?.map((config, index) => (
                      <div key={index} className="border border-gray-200 rounded-lg p-3 sm:p-4 bg-gray-50/50">
                        <div className="flex items-center gap-2 mb-3">
                          <span className="w-6 h-6 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0">
                            {index + 1}
                          </span>
                          {formData.configs!.length > 0 && (
                            <button
                              type="button"
                              onClick={() => removeConfig(index)}
                              className="ml-auto text-xs text-red-600 hover:text-red-700 font-medium"
                            >
                              删除配置
                            </button>
                          )}
                        </div>

                        <div className="space-y-3">
                          <div>
                            <label className="block text-xs font-medium text-gray-500 mb-1">执行环境 *</label>
                            <select
                              required
                              value={config.environmentId}
                              onChange={e => updateConfigEnv(index, e.target.value)}
                              className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm bg-white"
                            >
                              <option value="">选择环境</option>
                              {environments.map(env => (
                                <option key={env.id} value={env.id}>{env.name} ({env.url})</option>
                              ))}
                            </select>
                          </div>

                          <div>
                            <label className="block text-xs font-medium text-gray-500 mb-1">
                              选择用例 ({config.testCaseIds.length} 已选)
                            </label>
                            <div className="max-h-32 overflow-y-auto border border-gray-200 rounded-lg bg-white p-2 space-y-1">
                              {testCases.map(tc => (
                                <label key={tc.id} className="flex items-center gap-2 text-sm hover:bg-gray-50 p-1.5 rounded cursor-pointer">
                                  <input
                                    type="checkbox"
                                    checked={config.testCaseIds.includes(tc.id)}
                                    onChange={() => toggleConfigCase(index, tc.id)}
                                    className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                  />
                                  <span className="truncate">{tc.name}</span>
                                </label>
                              ))}
                              {testCases.length === 0 && (
                                <p className="text-xs text-gray-400 text-center py-2">该业务下无测试用例</p>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-2 text-gray-700">Cron 表达式</label>
                    <input
                      type="text"
                      required
                      value={formData.cronExpression}
                      onChange={e => setFormData({...formData, cronExpression: e.target.value})}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="0 8 * * *"
                    />
                  </div>
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
                </div>

                <div className="flex items-center">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={formData.enabled}
                      onChange={e => setFormData({...formData, enabled: e.target.checked})}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-700">启用任务</span>
                  </label>
                </div>
              </div>
            </div>

            <div className="p-4 sm:p-6 border-t border-gray-200 bg-gray-50 rounded-b-lg flex justify-end gap-3 flex-shrink-0">
              <button
                type="button"
                onClick={() => { setShowModal(false); resetForm(); }}
                className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-white transition-colors text-sm font-medium"
              >
                取消
              </button>
              <button
                onClick={handleSubmit}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
              >
                {editingTask ? '保存' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
