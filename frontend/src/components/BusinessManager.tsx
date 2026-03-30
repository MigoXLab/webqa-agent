import { Plus, FolderOpen, Settings, Loader2, ChevronDown, ChevronUp, Trash2 } from 'lucide-react';
import { Business, Environment } from '../App';
import React, { useState, useEffect } from 'react';
import { apiClient } from '../api/client';

type Props = {
  businesses: Business[];
  setBusinesses: (businesses: Business[]) => void;
  onSelectBusiness: (business: Business) => void;
  initialEditId?: string;
  onClose?: () => void;
  inline?: boolean;
};

export function BusinessManager({ businesses, setBusinesses, onSelectBusiness, initialEditId, onClose, inline = false }: Props) {
  const [showModal, setShowModal] = useState(!!initialEditId);
  const [editingBusiness, setEditingBusiness] = useState<Business | null>(
    initialEditId ? businesses.find(b => b.id === initialEditId) || null : null
  );
  // Track which env sections are collapsed (default: all expanded)
  const [collapsedEnvSections, setCollapsedEnvSections] = useState<Record<string, Record<string, boolean>>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (inline) return;
    if (showModal) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [showModal, inline]);

  const [formData, setFormData] = useState<{
    name: string;
    environments: Environment[];
  }>(editingBusiness ? {
    name: editingBusiness.name,
    environments: editingBusiness.environments,
  } : {
    name: '',
    environments: [{ id: crypto.randomUUID(), name: '开发环境', url: '', auth_type: 'none' }],
  });

  // Helper to toggle section collapse
  const toggleSection = (envId: string, section: string) => {
    setCollapsedEnvSections(prev => {
      const currentValue = prev[envId]?.[section] ?? true; // Get current value with default
      return {
        ...prev,
        [envId]: {
          ...prev[envId],
          [section]: !currentValue // Toggle from current value
        }
      };
    });
  };

  const isSectionCollapsed = (envId: string, section: string) => {
    return collapsedEnvSections[envId]?.[section] ?? true; // Default: collapsed
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);

    try {
      if (editingBusiness) {
        // Update existing business
        await apiClient.updateBusiness(editingBusiness.id, {
          name: formData.name,
          environments: formData.environments.map(env => ({
            id: env.id,
            name: env.name,
            url: env.url,
            auth_type: env.auth_type || 'none',
            sso_username: env.sso_username,
            sso_password: env.sso_password,
            sso_env: env.sso_env || 'prod',
            cookies: env.cookies,
            browser_config: env.browser_config,
            ignore_rules: env.ignore_rules,
          })),
        });
      } else {
        // Create new business
        await apiClient.createBusiness({
          name: formData.name,
          environments: formData.environments.map(env => ({
            name: env.name,
            url: env.url,
            auth_type: env.auth_type || 'none',
            sso_username: env.sso_username,
            sso_password: env.sso_password,
            sso_env: env.sso_env || 'prod',
            cookies: env.cookies,
            browser_config: env.browser_config,
            ignore_rules: env.ignore_rules,
          })),
        });
      }

      // Trigger parent to reload
      setBusinesses([...businesses]);

      if (inline) {
        // Inline mode: keep form populated, no modal to close
      } else {
        setShowModal(false);
        resetForm();
        if (onClose) onClose();
      }
    } catch (err: any) {
      setError(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const resetForm = () => {
    setFormData({
      name: '',
      environments: [{ id: crypto.randomUUID(), name: '开发环境', url: '', auth_type: 'none' }],
    });
    setEditingBusiness(null);
    setCollapsedEnvSections({});
    setError(null);
  };

  const handleCancel = () => {
    setShowModal(false);
    resetForm();
    if (onClose) onClose();
  };

  const handleEdit = (business: Business) => {
    setEditingBusiness(business);
    setFormData({
      name: business.name,
      environments: business.environments,
    });
    setShowModal(true);
  };

  const addEnvironment = () => {
    setFormData({
      ...formData,
      environments: [
        ...formData.environments,
        { id: crypto.randomUUID(), name: '', url: '', auth_type: 'none' },
      ],
    });
  };

  const updateEnvironment = (index: number, updates: Partial<Environment>) => {
    const newEnvs = [...formData.environments];
    newEnvs[index] = { ...newEnvs[index], ...updates };
    setFormData({ ...formData, environments: newEnvs });
  };

  const removeEnvironment = async (index: number) => {
    const envToRemove = formData.environments[index];
    if (!envToRemove) return;

    // Prevent deleting the last environment
    if (formData.environments.length <= 1) {
      setError('至少需要保留一个环境');
      return;
    }

    // Confirm before deletion
    const confirmed = window.confirm(
      `确认删除环境「${envToRemove.name || '未命名'}」？\n\n` +
      '注意：关联的定时任务也会一并删除，此操作不可撤销。'
    );
    if (!confirmed) return;

    // If editing an existing business, call API to delete immediately
    if (editingBusiness) {
      try {
        await apiClient.deleteEnvironment(envToRemove.id);
      } catch (err: any) {
        setError(`删除环境失败: ${err.message || '未知错误'}`);
        return;
      }
    }

    // Remove from form state
    setFormData({
      ...formData,
      environments: formData.environments.filter((_, i) => i !== index),
    });
    // Clean up collapsed sections for removed env
    setCollapsedEnvSections(prev => {
      const newState = { ...prev };
      delete newState[envToRemove.id];
      return newState;
    });
  };

  const renderFormContent = () => (
    <>
      {/* Header */}
      {!inline && (
        <div className="border-b border-gray-200 flex items-center justify-between flex-shrink-0" style={{ padding: '16px 28px' }}>
          <h2 className="text-lg font-semibold text-gray-900">{editingBusiness ? '编辑业务' : '创建新业务'}</h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCancel}
              disabled={saving}
              className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium disabled:opacity-50"
            >
              关闭
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium flex items-center gap-2 disabled:opacity-50"
            >
              {saving && <Loader2 className="w-4 h-4 animate-spin" />}
              {editingBusiness ? '保存' : '创建'}
            </button>
          </div>
        </div>
      )}

      {/* Content */}
      <div className={`flex-1 overflow-y-auto ${inline ? 'p-0' : ''}`} style={inline ? undefined : { padding: '24px 28px' }}>
            {error && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                {error}
              </div>
            )}
            <div className="space-y-4 mb-6">
              <div>
                <label className="block text-sm mb-2 text-gray-700">
                  业务名称 *
                </label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="例如：百度"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-3">
                  <label className="block text-sm text-gray-700">
                    环境设置 *
                  </label>
                  <button
                    type="button"
                    onClick={addEnvironment}
                    className="text-sm text-blue-600 hover:text-blue-700"
                  >
                    + 添加环境
                  </button>
                </div>

                <div className="space-y-4">
                  {formData.environments.map((env, index) => (
                    <div key={env.id} className="border border-gray-200 rounded-lg p-4 bg-gray-50/50">
                      {/* Environment basic info */}
                      <div className="flex flex-col sm:flex-row gap-2 mb-4">
                        <input
                          type="text"
                          required
                          value={env.name}
                          onChange={(e) => updateEnvironment(index, { name: e.target.value })}
                          className="w-full sm:w-1/3 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                          placeholder="环境名称"
                        />
                        <input
                          type="url"
                          required
                          value={env.url}
                          onChange={(e) => updateEnvironment(index, { url: e.target.value })}
                          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                          placeholder="https://..."
                        />
                        <button
                          type="button"
                          onClick={() => removeEnvironment(index)}
                          className="p-1.5 hover:bg-red-50 rounded-lg transition-colors"
                          title="删除环境"
                        >
                          <Trash2 className="w-4 h-4 text-red-600" />
                        </button>
                      </div>

                      {/* Auth Section - Always visible, collapsible */}
                      <div className="border border-gray-200 rounded-lg bg-white mb-3">
                        <button
                          type="button"
                          onClick={() => toggleSection(env.id, 'auth')}
                          className="w-full flex items-center justify-between p-3 text-left hover:bg-gray-50 transition-colors"
                        >
                          <span className="text-sm font-medium text-gray-700">登录配置</span>
                          {isSectionCollapsed(env.id, 'auth') ? (
                            <ChevronDown className="w-4 h-4 text-gray-500" />
                          ) : (
                            <ChevronUp className="w-4 h-4 text-gray-500" />
                          )}
                        </button>
                        {!isSectionCollapsed(env.id, 'auth') && (
                          <div className="p-3 pt-0 space-y-3">
                            <div className="flex gap-4">
                              <label className="flex items-center gap-2 text-sm">
                                <input
                                  type="radio"
                                  name={`auth-${env.id}`}
                                  checked={env.auth_type === 'none' || !env.auth_type}
                                  onChange={() => updateEnvironment(index, { auth_type: 'none' })}
                                />
                                无
                              </label>
                              <label className="flex items-center gap-2 text-sm">
                                <input
                                  type="radio"
                                  name={`auth-${env.id}`}
                                  checked={env.auth_type === 'sso'}
                                  onChange={() => updateEnvironment(index, { auth_type: 'sso' })}
                                />
                                SSO
                              </label>
                              <label className="flex items-center gap-2 text-sm">
                                <input
                                  type="radio"
                                  name={`auth-${env.id}`}
                                  checked={env.auth_type === 'cookies'}
                                  onChange={() => updateEnvironment(index, { auth_type: 'cookies' })}
                                />
                                Cookies
                              </label>
                            </div>

                            {env.auth_type === 'sso' && (
                              <div className="bg-blue-50 p-3 rounded-lg space-y-3">
                                <div className="grid grid-cols-2 gap-3">
                                  <div>
                                    <label className="block text-xs text-gray-500 mb-1">SSO 用户名</label>
                                    <input
                                      type="text"
                                      value={env.sso_username || ''}
                                      onChange={(e) => updateEnvironment(index, { sso_username: e.target.value })}
                                      className="w-full px-2 py-1.5 border rounded text-sm bg-white"
                                    />
                                  </div>
                                  <div>
                                    <label className="block text-xs text-gray-500 mb-1">SSO 密码</label>
                                    <input
                                      type="password"
                                      value={env.sso_password || ''}
                                      onChange={(e) => updateEnvironment(index, { sso_password: e.target.value })}
                                      className="w-full px-2 py-1.5 border rounded text-sm bg-white"
                                    />
                                  </div>
                                </div>
                                <div>
                                  <label className="block text-xs text-gray-500 mb-1">SSO 环境</label>
                                  <div className="flex gap-4">
                                    <label className="flex items-center gap-2 cursor-pointer">
                                      <input
                                        type="radio"
                                        name={`sso_env_${index}`}
                                        value="prod"
                                        checked={(env.sso_env || 'prod') === 'prod'}
                                        onChange={(e) => updateEnvironment(index, { sso_env: e.target.value as 'prod' | 'staging' | 'dev' })}
                                        className="text-blue-600"
                                      />
                                      <span className="text-sm text-gray-700">生产环境 (prod)</span>
                                    </label>
                                    <label className="flex items-center gap-2 cursor-pointer">
                                      <input
                                        type="radio"
                                        name={`sso_env_${index}`}
                                        value="staging"
                                        checked={env.sso_env === 'staging'}
                                        onChange={(e) => updateEnvironment(index, { sso_env: e.target.value as 'prod' | 'staging' | 'dev' })}
                                        className="text-blue-600"
                                      />
                                      <span className="text-sm text-gray-700">测试环境 (staging)</span>
                                    </label>
                                    <label className="flex items-center gap-2 cursor-pointer">
                                      <input
                                        type="radio"
                                        name={`sso_env_${index}`}
                                        value="dev"
                                        checked={env.sso_env === 'dev'}
                                        onChange={(e) => updateEnvironment(index, { sso_env: e.target.value as 'prod' | 'staging' | 'dev' })}
                                        className="text-blue-600"
                                      />
                                      <span className="text-sm text-gray-700">开发环境 (dev)</span>
                                    </label>
                                  </div>
                                </div>
                              </div>
                            )}

                            {env.auth_type === 'cookies' && (
                              <div className="bg-blue-50 p-3 rounded-lg">
                                <label className="block text-xs text-gray-500 mb-1">Cookies (JSON 格式)</label>
                                <textarea
                                  value={JSON.stringify(env.cookies || [], null, 2)}
                                  onChange={(e) => {
                                    try {
                                      const cookies = JSON.parse(e.target.value);
                                      updateEnvironment(index, { cookies });
                                    } catch (err) {
                                      // ignore invalid json while typing
                                    }
                                  }}
                                  className="w-full px-2 py-1.5 border rounded text-sm font-mono bg-white"
                                  rows={3}
                                  placeholder='[{"name": "session", "value": "..."}]'
                                />
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Ignore Rules Section - Always visible, collapsible */}
                      <div className="border border-gray-200 rounded-lg bg-white">
                        <button
                          type="button"
                          onClick={() => toggleSection(env.id, 'ignore')}
                          className="w-full flex items-center justify-between p-3 text-left hover:bg-gray-50 transition-colors"
                        >
                          <div className="flex flex-col">
                            <span className="text-sm font-medium text-gray-700">浏览器报错规则</span>
                            <span className="text-xs text-gray-500 mt-0.5">过滤测试中不需要关注的网络请求和控制台错误</span>
                          </div>
                          {isSectionCollapsed(env.id, 'ignore') ? (
                            <ChevronDown className="w-4 h-4 text-gray-500 flex-shrink-0" />
                          ) : (
                            <ChevronUp className="w-4 h-4 text-gray-500 flex-shrink-0" />
                          )}
                        </button>
                        {!isSectionCollapsed(env.id, 'ignore') && (
                          <div className="p-4 pt-0 space-y-5">
                            {/* 网络忽略规则 */}
                            <div className="bg-gradient-to-br from-orange-50 to-amber-50 p-4 rounded-xl border border-orange-100 shadow-sm">
                              <div className="flex items-center justify-between mb-3">
                                <div className="flex items-center gap-2">
                                  <div className="w-1.5 h-1.5 rounded-full bg-orange-500"></div>
                                  <label className="text-sm font-semibold text-gray-800">
                                    网络域名过滤
                                  </label>
                                </div>
                                <button
                                  type="button"
                                  onClick={() => {
                                    const network = [...(env.ignore_rules?.network || []), { pattern: '', type: 'domain' }];
                                    updateEnvironment(index, { ignore_rules: { ...env.ignore_rules, network } });
                                  }}
                                  className="text-xs text-blue-600 hover:text-blue-700 hover:bg-blue-100 px-2 py-1 rounded-md flex items-center gap-1 font-medium transition-colors"
                                >
                                  + 添加规则
                                </button>
                              </div>
                              {(env.ignore_rules?.network || []).length === 0 ? (
                                <div className="text-center py-6">
                                </div>
                              ) : (
                                <div className="space-y-2">
                                  {(env.ignore_rules?.network || []).map((rule: any, ruleIdx: number) => (
                                    <div key={ruleIdx} className="group flex items-center gap-2 bg-white p-2.5 rounded-lg border border-orange-100 hover:border-orange-300 hover:shadow-sm transition-all">
                                      <div className="flex-1 relative">
                                        <input
                                          type="text"
                                          value={rule.pattern || ''}
                                          onChange={(e) => {
                                            const network = [...(env.ignore_rules?.network || [])];
                                            network[ruleIdx] = { ...network[ruleIdx], pattern: e.target.value, type: 'domain' };
                                            updateEnvironment(index, { ignore_rules: { ...env.ignore_rules, network } });
                                          }}
                                          placeholder="例如: .*\.google-analytics\.com.* 或 .*\.doubleclick\.net.*"
                                          className="w-full px-3 py-2 text-xs border-0 bg-gray-50 rounded-md focus:outline-none focus:ring-2 focus:ring-orange-400 focus:bg-white transition-all font-mono"
                                        />
                                      </div>
                                      <button
                                        type="button"
                                        onClick={() => {
                                          const network = (env.ignore_rules?.network || []).filter((_: any, i: number) => i !== ruleIdx);
                                          updateEnvironment(index, { ignore_rules: { ...env.ignore_rules, network } });
                                        }}
                                        className="p-2 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-md opacity-0 group-hover:opacity-100 transition-all"
                                        title="删除规则"
                                      >
                                        <Trash2 className="w-4 h-4" />
                                      </button>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>

                            {/* 控制台忽略规则 */}
                            <div className="bg-gradient-to-br from-blue-50 to-indigo-50 p-4 rounded-xl border border-blue-100 shadow-sm">
                              <div className="flex items-center justify-between mb-3">
                                <div className="flex items-center gap-2">
                                  <div className="w-1.5 h-1.5 rounded-full bg-blue-500"></div>
                                  <label className="text-sm font-semibold text-gray-800">
                                    控制台日志过滤
                                  </label>
                                </div>
                                <button
                                  type="button"
                                  onClick={() => {
                                    const console = [...(env.ignore_rules?.console || []), { pattern: '', match_type: 'contains' }];
                                    updateEnvironment(index, { ignore_rules: { ...env.ignore_rules, console } });
                                  }}
                                  className="text-xs text-blue-600 hover:text-blue-700 hover:bg-blue-100 px-2 py-1 rounded-md flex items-center gap-1 font-medium transition-colors"
                                >
                                  + 添加规则
                                </button>
                              </div>
                              {(env.ignore_rules?.console || []).length === 0 ? (
                                <div className="text-center py-6">
                                </div>
                              ) : (
                                <div className="space-y-2">
                                  {(env.ignore_rules?.console || []).map((rule: any, ruleIdx: number) => (
                                    <div key={ruleIdx} className="group flex items-center gap-2 bg-white p-2.5 rounded-lg border border-blue-100 hover:border-blue-300 hover:shadow-sm transition-all">
                                      <div className="flex-1 flex gap-2">
                                        <input
                                          type="text"
                                          value={rule.pattern || ''}
                                          onChange={(e) => {
                                            const console = [...(env.ignore_rules?.console || [])];
                                            console[ruleIdx] = { ...console[ruleIdx], pattern: e.target.value };
                                            updateEnvironment(index, { ignore_rules: { ...env.ignore_rules, console } });
                                          }}
                                          placeholder="例如: Failed to load resource 或正则: .*favicon.*"
                                          className="flex-1 px-3 py-2 text-xs border-0 bg-gray-50 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-400 focus:bg-white transition-all font-mono"
                                        />
                                        <select
                                          value={rule.match_type || 'contains'}
                                          onChange={(e) => {
                                            const console = [...(env.ignore_rules?.console || [])];
                                            console[ruleIdx] = { ...console[ruleIdx], match_type: e.target.value };
                                            updateEnvironment(index, { ignore_rules: { ...env.ignore_rules, console } });
                                          }}
                                          className="px-3 py-2 text-xs border-0 bg-blue-50 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-400 font-medium text-blue-700 cursor-pointer"
                                        >
                                          <option value="contains">包含</option>
                                          <option value="regex">正则</option>
                                        </select>
                                      </div>
                                      <button
                                        type="button"
                                        onClick={() => {
                                          const console = (env.ignore_rules?.console || []).filter((_: any, i: number) => i !== ruleIdx);
                                          updateEnvironment(index, { ignore_rules: { ...env.ignore_rules, console } });
                                        }}
                                        className="p-2 text-red-400 hover:text-red-600 hover:bg-red-50 rounded-md opacity-0 group-hover:opacity-100 transition-all"
                                        title="删除规则"
                                      >
                                        <Trash2 className="w-4 h-4" />
                                      </button>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
    </>
  );

  const renderModal = () => (
    <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ backgroundColor: 'rgba(0, 0, 0, 0.75)' }}>
      <form onSubmit={handleSubmit} className="bg-white rounded-lg flex flex-col shadow-2xl" style={{ width: '960px', maxWidth: '90vw', height: '600px', maxHeight: 'calc(100vh - 64px)' }}>
        <div className="border border-gray-200 rounded-lg flex flex-col flex-1 min-h-0 overflow-hidden">
          {renderFormContent()}
        </div>
      </form>
    </div>
  );

  if (inline && initialEditId) {
    return (
      <form onSubmit={handleSubmit}>
        {renderFormContent()}
        {/* Inline save button */}
        <div className="flex justify-end mt-4">
          <button
            type="submit"
            disabled={saving}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium flex items-center gap-2 disabled:opacity-50"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            保存
          </button>
        </div>
      </form>
    );
  }

  if (initialEditId) {
    return <>{showModal && renderModal()}</>;
  }

  return (
    <div className="min-h-screen px-4 sm:px-6 py-4 sm:py-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-6 sm:mb-8 flex items-center">
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors whitespace-nowrap"
        >
          <Plus className="w-5 h-5" />
          创建业务
        </button>
      </div>

      {/* Business Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
        {businesses.map((business) => (
          <div
            key={business.id}
            className="bg-white rounded-lg border border-gray-200 p-4 sm:p-6 hover:shadow-lg transition-shadow cursor-pointer h-full flex flex-col"
            onClick={() => onSelectBusiness(business)}
          >
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3 flex-1 min-w-0">
                <div className="w-10 h-10 sm:w-12 sm:h-12 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0">
                  <FolderOpen className="w-5 h-5 sm:w-6 sm:h-6 text-blue-600" />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="mb-1 truncate">{business.name}</h3>
                  <p className="text-sm text-gray-500">{business.createdAt}</p>
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleEdit(business);
                }}
                className="p-2 hover:bg-gray-100 rounded-lg transition-colors flex-shrink-0"
              >
                <Settings className="w-5 h-5 text-gray-600" />
              </button>
            </div>

            <div className="space-y-2 mt-4 flex-1">
              <p className="text-sm text-gray-500">环境配置：</p>
              {business.environments.map((env) => (
                <div key={env.id} className="flex items-center gap-2 text-sm min-w-0">
                  <div className="w-2 h-2 bg-green-500 rounded-full flex-shrink-0"></div>
                  <span className="text-gray-700 flex-shrink-0">{env.name}</span>
                  <span className="text-gray-400 truncate">{env.url}</span>
                  {env.auth_type && env.auth_type !== 'none' && (
                    <span className="text-xs bg-gray-100 px-1.5 py-0.5 rounded text-gray-500">{env.auth_type}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {businesses.length === 0 && (
        <div className="text-center py-12">
          <FolderOpen className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <p className="text-gray-500">还没有业务，点击"创建业务"开始</p>
        </div>
      )}

      {showModal && renderModal()}
    </div>
  );
}
