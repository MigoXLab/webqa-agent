import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Sparkles,
  AlertCircle,
  Loader2,
  Globe,
  Target,
  Zap,
  Link,
  Search,
  ChevronDown,
  ChevronRight,
  Shield,
  Settings2,
  Cpu,
} from 'lucide-react';
import { apiClient } from '../api/client';

const TEST_ITEMS = [
  { key: 'functional' as const, label: '功能测试', icon: Target },
  { key: 'performance' as const, label: '网站性能', icon: Zap },
  { key: 'traverse' as const, label: '暴力点击', icon: Search },
  { key: 'links' as const, label: '网站内容', icon: Link },
  { key: 'security' as const, label: '安全扫描', icon: Shield },
];

export function GenPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);

  // Form State
  const [targetUrl, setTargetUrl] = useState('');
  const [businessObjectives, setBusinessObjectives] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [availableModels, setAvailableModels] = useState<string[]>([]);

  // Test Items (Custom Tools)
  const [testItems, setTestItems] = useState({
    functional: true,
    performance: true,
    traverse: true,
    links: true,
    security: true,
  });

  // Execution Config (default expanded)
  const [showExecutionConfig, setShowExecutionConfig] = useState(true);
  const [workers, setWorkers] = useState(4);

  // Advanced Options
  const [showAdvanced, setShowAdvanced] = useState(true);
  const [enableReflection, setEnableReflection] = useState(false);
  const [dynamicStepGeneration, setDynamicStepGeneration] = useState(false);
  const [cookies, setCookies] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const init = async () => {
      try {
        const models = await apiClient.getAvailableModels('gen');
        setAvailableModels(models.models);
        setSelectedModel(models.default);
      } catch (err) {
        console.error('Failed to load init data:', err);
        setError('加载初始化数据失败');
      }
    };
    init();
  }, []);

  const handleSubmit = async () => {
    if (!targetUrl) {
      setError('请输入目标 URL');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const enabledTools: string[] = [];
      if (testItems.performance) enabledTools.push('lighthouse');
      if (testItems.traverse) enabledTools.push('traverse_clickable_elements');
      if (testItems.links) enabledTools.push('detect_dynamic_links');
      if (testItems.security) enabledTools.push('nuclei');

      let finalBusinessObjectives = businessObjectives;
      if (testItems.functional) {
        const functionalInstruction = `
测试要求：以真实用户视角对每个功能模块进行完整的端到端测试，必须执行完整的交互流程（如：表单需填写并提交、对话功能需发送消息并验证回复、搜索功能需输入关键词并验证结果），禁止仅点击入口而不完成完整操作流程。
`;
        finalBusinessObjectives = finalBusinessObjectives
          ? `${finalBusinessObjectives}\n${functionalInstruction}`
          : functionalInstruction;
      } else {
        const enabledToolNames = enabledTools.length > 0
          ? enabledTools.join(', ')
          : 'none';
        const noFunctionalInstruction = `
重要提示：用户已明确禁用功能测试。
1. 请勿生成任何功能测试用例或执行手动探索步骤。
2. 你的唯一任务是执行已启用的工具（${enabledToolNames}）并报告其发现。
3. 严禁使用未启用的工具。
4. 如果未启用任何工具，请直接报告未请求任何操作。
`;
        finalBusinessObjectives = finalBusinessObjectives
          ? `${finalBusinessObjectives}\n${noFunctionalInstruction}`
          : noFunctionalInstruction;
      }

      let parsedCookies = undefined;
      if (cookies.trim()) {
        try {
          parsedCookies = JSON.parse(cookies);
          if (!Array.isArray(parsedCookies)) {
            throw new Error('Cookies must be a JSON array');
          }
        } catch (e) {
          setError('Cookies 必须是有效的 JSON 数组格式 (例如: [{"name": "session", "value": "123", "domain": "example.com", "path": "/"}])');
          setLoading(false);
          return;
        }
      }

      const execution = await apiClient.createExecution({
        trigger_type: 'gen',
        model: selectedModel,
        workers: workers,
        gen_config: {
          target_url: targetUrl,
          llm_config: { model: selectedModel },
          business_objectives: finalBusinessObjectives,
          _display_objectives: businessObjectives || undefined,
          custom_tools: { enabled: enabledTools },
          browser_config: { cookies: parsedCookies },
          report_config: { language: 'zh-CN', save_screenshots: true },
          skip_reflection: !enableReflection,
          dynamic_step_generation: { enabled: dynamicStepGeneration },
          max_concurrent_tests: workers,
        }
      });

      navigate(`/execution/${execution.id}`);
    } catch (err: any) {
      console.error('Failed to start exploration:', err);
      setError(err.message || '启动探索失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 sm:py-6">
        {/* Page Header */}
        <div className="mb-6 sm:mb-8">
          <h1 className="text-xl font-semibold text-purple-700 flex items-center gap-2">
            <Sparkles className="w-5 h-5" />
            AI 探索
          </h1>
          <p className="text-gray-600 mt-1">输入目标网址，AI 将自主探索网站，自动发现功能缺陷、性能瓶颈和安全隐患</p>
        </div>

        <div className="space-y-4">

          {/* Target URL */}
          <div>
            <label className="block text-sm font-medium mb-1.5 text-gray-700">
              目标网址 <span className="text-red-500">*</span>
            </label>
            <div className="relative">
              <input
                type="url"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm placeholder-gray-400 resize-none"
                placeholder="https://example.com"
                value={targetUrl}
                onChange={(e) => setTargetUrl(e.target.value)}
              />
            </div>
          </div>

          {/* Test Items — 5 items in a row */}
          <div>
            <label className="block text-sm font-medium mb-1.5 text-gray-700">
              测试项目 <span className="text-red-500">*</span>
            </label>
            <div className="flex gap-2">
              {TEST_ITEMS.map((item) => {
                const active = testItems[item.key];
                const Icon = item.icon;
                return (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => setTestItems(prev => ({ ...prev, [item.key]: !prev[item.key] }))}
                    className={`flex items-center justify-center gap-2 px-4 py-2 rounded-lg border transition-colors ${
                      active
                        ? 'border-purple-300 bg-purple-50 ring-1 ring-purple-200'
                        : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    <Icon className={`w-4 h-4 flex-shrink-0 ${active ? 'text-purple-600' : 'text-gray-400'}`} />
                    <span className={`text-sm font-medium whitespace-nowrap ${active ? 'text-purple-700' : 'text-gray-700'}`}>
                      {item.label}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Business Objectives */}
          <div>
            <label className="block text-sm font-medium mb-1.5 text-gray-700">
              测试目标
              <span className="ml-1.5 text-xs text-gray-400 font-normal">【可选】留空则由 AI 自主探索</span>
            </label>
            <textarea
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm placeholder-gray-400 resize-none"
              placeholder="例如：测试用户登录、搜索商品、加入购物车并结算的核心流程"
              value={businessObjectives}
              onChange={(e) => setBusinessObjectives(e.target.value)}
            />
          </div>

          {/* Execution Config — collapsible, default expanded */}
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <button
              type="button"
              onClick={() => setShowExecutionConfig(!showExecutionConfig)}
              className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
            >
              {showExecutionConfig
                ? <ChevronDown className="w-3 h-3 text-gray-400 flex-shrink-0" />
                : <ChevronRight className="w-3 h-3 text-gray-400 flex-shrink-0" />
              }
              <Cpu className="w-3 h-3 text-gray-400 flex-shrink-0" />
              <span className="text-xs font-medium text-gray-500">执行配置</span>

              {!showExecutionConfig && (
                <div className="flex items-center gap-2 ml-2 flex-wrap">
                  <span className="px-2 py-0.5 bg-white border border-gray-200 rounded text-xs text-gray-500">
                    {selectedModel || '默认模型'}
                  </span>
                  <span className="px-2 py-0.5 bg-white border border-gray-200 rounded text-xs text-gray-500">
                    并发 {workers}
                  </span>
                  {cookies.trim() && (
                    <span className="px-2 py-0.5 bg-purple-50 border border-purple-200 rounded text-xs text-purple-600">
                      Cookies
                    </span>
                  )}
                </div>
              )}
            </button>

            {showExecutionConfig && (
              <div className="px-4 py-4 border-t border-gray-200 space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  {/* Model Selection */}
                  <div>
                    <label className="block text-sm font-medium mb-1.5 text-gray-700">模型</label>
                    <select
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm bg-white"
                      value={selectedModel}
                      onChange={(e) => setSelectedModel(e.target.value)}
                    >
                      {availableModels.map((model) => (
                        <option key={model} value={model}>{model}</option>
                      ))}
                    </select>
                  </div>
                  {/* Workers */}
                  <div>
                    <label className="block text-sm font-medium mb-1.5 text-gray-700">并发数</label>
                    <select
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm bg-white"
                      value={workers}
                      onChange={(e) => setWorkers(parseInt(e.target.value))}
                    >
                      {[1, 2, 3, 4, 5].map((n) => (
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </select>
                  </div>
                </div>
                {/* Cookies */}
                <div>
                  <label className="block text-sm font-medium mb-1.5 text-gray-700">
                    <div className="flex items-center gap-1.5">
                      Cookies
                      <span className="text-xs text-gray-400 font-normal">【可选】用于需要登录态的网站</span>
                    </div>
                  </label>
                  <textarea
                    rows={2}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 text-xs font-mono placeholder-gray-400 resize-none"
                    placeholder='[{"name": "session_id", "value": "abc123", "domain": ".example.com", "path": "/"}]'
                    value={cookies}
                    onChange={(e) => setCookies(e.target.value)}
                  />
                  <p className="mt-1 text-xs text-gray-400">
                    JSON 数组格式，每个对象需包含 name、value、domain、path 字段。可从浏览器 DevTools &gt; Application &gt; Cookies 中导出。
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Advanced Options — collapsible */}
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
            >
              {showAdvanced
                ? <ChevronDown className="w-3 h-3 text-gray-400 flex-shrink-0" />
                : <ChevronRight className="w-3 h-3 text-gray-400 flex-shrink-0" />
              }
              <Settings2 className="w-3 h-3 text-gray-400 flex-shrink-0" />
              <span className="text-xs font-medium text-gray-500">高级选项</span>

              {!showAdvanced && (
                <div className="flex items-center gap-2 ml-2 flex-wrap">
                  {dynamicStepGeneration && (
                    <span className="px-2 py-0.5 bg-purple-50 border border-purple-200 rounded text-xs text-purple-600">
                      智能规划
                    </span>
                  )}
                  {enableReflection && (
                    <span className="px-2 py-0.5 bg-purple-50 border border-purple-200 rounded text-xs text-purple-600">
                      智能修正
                    </span>
                  )}
                </div>
              )}
            </button>

            {showAdvanced && (
              <div className="px-4 py-4 border-t border-gray-200 space-y-4">
                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={dynamicStepGeneration}
                    onChange={(e) => setDynamicStepGeneration(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500 flex-shrink-0"
                  />
                  <div>
                    <span className="text-sm text-gray-700 font-medium">智能规划</span>
                    <p className="text-xs text-gray-500 mt-0.5">
                      遇到弹窗、遮挡等障碍时，Agent 自动插入临时步骤来恢复执行，会增加执行时间和 token 消耗
                    </p>
                  </div>
                </label>

                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enableReflection}
                    onChange={(e) => setEnableReflection(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500 flex-shrink-0"
                  />
                  <div>
                    <span className="text-sm text-gray-700 font-medium">智能修正</span>
                    <p className="text-xs text-gray-500 mt-0.5">
                      失败时触发 LLM 分析并重新规划，会增加执行时间和 token 消耗
                    </p>
                  </div>
                </label>
              </div>
            )}
          </div>

          {/* Error Message */}
          {error && (
            <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2.5">
              <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          {/* Submit Button */}
          <button
            type="button"
            onClick={handleSubmit}
            disabled={loading}
            className={`w-full flex justify-center items-center py-2.5 px-4 rounded-lg text-sm font-medium border border-purple-300 text-purple-700 bg-purple-50 ring-1 ring-purple-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-purple-500 transition-colors ${
              loading ? 'cursor-not-allowed opacity-60' : 'hover:bg-purple-100'
            }`}
          >
            {loading ? (
              <><Loader2 className="animate-spin mr-2 h-4 w-4" />正在启动...</>
            ) : (
              <><Sparkles className="mr-2 h-4 w-4" />开始探索</>
            )}
          </button>

        </div>
      </div>
    </div>
  );
}
