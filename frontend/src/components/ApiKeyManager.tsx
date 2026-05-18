import React, { useState, useEffect } from 'react';
import { Key, Copy, Check, Trash2, Plus, X, Loader2 } from 'lucide-react';
import { apiClient, ApiKey, ApiKeyCreated } from '../api/client';

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function ApiKeyManager() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyExpiry, setNewKeyExpiry] = useState('never');
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null);
  const [creating, setCreating] = useState(false);
  const [keyCopied, setKeyCopied] = useState(false);
  const [configCopied, setConfigCopied] = useState(false);

  useEffect(() => {
    loadKeys();
  }, []);

  const loadKeys = async () => {
    try {
      setLoading(true);
      const response = await apiClient.getApiKeys();
      setKeys(response.items);
    } catch (err) {
      console.error('Failed to load API keys:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!newKeyName.trim()) return;
    try {
      setCreating(true);
      const payload: { name: string; expires_in_days?: number } = {
        name: newKeyName.trim(),
      };
      if (newKeyExpiry !== 'never') {
        payload.expires_in_days = parseInt(newKeyExpiry, 10);
      }
      const created = await apiClient.createApiKey(payload);
      setCreatedKey(created);
      setShowCreateModal(false);
      setShowKeyModal(true);
      setNewKeyName('');
      setNewKeyExpiry('never');
      await loadKeys();
    } catch (err) {
      console.error('Failed to create API key:', err);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`确定要撤销 API Key "${name}" 吗？撤销后使用该 Key 的所有应用将立即失去访问权限。`)) {
      return;
    }
    try {
      await apiClient.deleteApiKey(id);
      await loadKeys();
    } catch (err: any) {
      console.error('Failed to delete API key:', err);
      alert('撤销失败: ' + err.message);
    }
  };

  const handleCopyKey = async () => {
    if (!createdKey) return;
    await navigator.clipboard.writeText(createdKey.full_key);
    setKeyCopied(true);
    setTimeout(() => setKeyCopied(false), 2000);
  };

  const handleCopyConfig = async () => {
    if (!createdKey) return;
    await navigator.clipboard.writeText(configText(createdKey.full_key));
    setConfigCopied(true);
    setTimeout(() => setConfigCopied(false), 2000);
  };

  const configText = (fullKey: string) => {
    const config = {
      mcpServers: {
        webqa: {
          command: '/path/to/webqa-mcp-server',
          env: {
            WEBQA_API_URL: window.location.origin,
            WEBQA_API_KEY: fullKey,
          },
        },
      },
    };
    return JSON.stringify(config, null, 2);
  };

  return (
    <div className="min-h-screen px-4 sm:px-6 py-4 sm:py-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">API Keys</h1>
          <p className="text-gray-500 text-sm mt-1">
            通过 MCP 协议或 REST API 访问 WebQA 服务，在 Claude Code、Cursor 等工具中配置后可直接发起测试
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors whitespace-nowrap"
        >
          <Plus className="w-5 h-5" />
          创建 API Key
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 text-blue-600 animate-spin" />
        </div>
      )}

      {/* Empty State */}
      {!loading && keys.length === 0 && (
        <div className="text-center py-12">
          <Key className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <p className="text-gray-500">还没有 API Key，点击"创建 API Key"开始使用</p>
        </div>
      )}

      {/* Keys Table */}
      {!loading && keys.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50/50 border-b border-gray-200">
                  <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">名称</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Key</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">创建时间</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">最后使用</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">过期时间</th>
                  <th className="px-6 py-4 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">操作</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((key) => (
                  <tr key={key.id} className="border-b border-gray-100 last:border-b-0 hover:bg-gray-50/50 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{key.name}</td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <code className="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded font-mono">
                        {key.key_prefix}...
                      </code>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{formatDate(key.created_at)}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{formatDate(key.last_used)}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {key.expires_at ? formatDate(key.expires_at) : (
                        <span className="inline-flex items-center gap-1 text-green-600">
                          <span className="w-1.5 h-1.5 bg-green-500 rounded-full"></span>
                          永不过期
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right">
                      <button
                        onClick={() => handleDelete(key.id, key.name)}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-red-500 bg-red-50/50 hover:bg-red-100 rounded-lg transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        撤销
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ backgroundColor: 'rgba(0, 0, 0, 0.75)' }}>
          <div className="bg-white rounded-lg border border-gray-200" style={{ width: 480, maxWidth: '90vw', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)' }}>
            {/* Header */}
            <div className="border-b border-gray-200" style={{ padding: '16px 24px' }}>
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-gray-900">创建 API Key</h2>
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Body */}
            <div style={{ padding: '20px 24px' }} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">名称</label>
                <input
                  type="text"
                  placeholder="例如：Claude Code 集成"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">过期时间</label>
                <select
                  value={newKeyExpiry}
                  onChange={(e) => setNewKeyExpiry(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white"
                >
                  <option value="never">永不过期</option>
                  <option value="30">30 天</option>
                  <option value="90">90 天</option>
                  <option value="365">365 天</option>
                </select>
              </div>
            </div>

            {/* Footer */}
            <div className="border-t border-gray-200 flex justify-end gap-3" style={{ padding: '16px 24px' }}>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium"
              >
                取消
              </button>
              <button
                onClick={handleCreate}
                disabled={!newKeyName.trim() || creating}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {creating && <Loader2 className="w-4 h-4 animate-spin" />}
                {creating ? '创建中...' : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Created Key Modal */}
      {showKeyModal && createdKey && (
        <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ backgroundColor: 'rgba(0, 0, 0, 0.75)' }}>
          <div className="bg-white rounded-lg border border-gray-200" style={{ width: 600, maxWidth: '90vw', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)' }}>
            {/* Header */}
            <div className="border-b border-gray-200" style={{ padding: '16px 24px' }}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="w-7 h-7 bg-green-100 rounded-full flex items-center justify-center flex-shrink-0">
                    <Check className="w-4 h-4 text-green-600" />
                  </div>
                  <h2 className="text-lg font-semibold text-gray-900">API Key 已创建</h2>
                </div>
                <button
                  type="button"
                  onClick={() => { setShowKeyModal(false); setCreatedKey(null); }}
                  className="text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Body */}
            <div style={{ padding: '20px 24px' }} className="space-y-4">
              {/* Warning */}
              <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5 text-sm text-amber-800 flex items-center gap-2">
                <span className="flex-shrink-0">⚠️</span>
                <span>请立即复制此密钥，关闭后将无法再次查看。</span>
              </div>

              {/* Full key */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">API Key</label>
                <div className="flex items-center gap-2">
                  <div className="flex-1 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2.5 font-mono text-sm text-gray-800 break-all select-all" style={{ lineHeight: '1.5' }}>
                    {createdKey.full_key}
                  </div>
                  <button
                    onClick={handleCopyKey}
                    className="flex-shrink-0 p-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
                    title="复制 Key"
                  >
                    {keyCopied ? (
                      <Check className="w-4 h-4 text-green-600" />
                    ) : (
                      <Copy className="w-4 h-4 text-gray-500" />
                    )}
                  </button>
                </div>
              </div>

              {/* MCP config snippet */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-sm font-medium text-gray-700">
                    Claude Code / Cursor 配置
                  </label>
                  <button
                    onClick={handleCopyConfig}
                    className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded transition-colors"
                  >
                    {configCopied ? (
                      <>
                        <Check className="w-3 h-3 text-green-600" />
                        <span className="text-green-600">已复制</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3 h-3" />
                        复制配置
                      </>
                    )}
                  </button>
                </div>
                <div className="bg-gray-50 border border-gray-200 rounded-lg overflow-hidden">
                  <pre
                    className="text-sm font-mono text-gray-700 overflow-x-auto"
                    style={{ padding: '12px 16px', lineHeight: '1.6', margin: 0 }}
                  >{configText(createdKey.full_key)}</pre>
                </div>
                <p className="text-xs text-gray-400 mt-1.5">
                  * command 请替换为 <code className="text-gray-500">which webqa-mcp-server</code> 输出的实际路径
                </p>
              </div>
            </div>

            {/* Footer */}
            <div className="border-t border-gray-200 flex justify-end" style={{ padding: '16px 24px' }}>
              <button
                onClick={() => { setShowKeyModal(false); setCreatedKey(null); setKeyCopied(false); setConfigCopied(false); }}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
              >
                已复制，关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
