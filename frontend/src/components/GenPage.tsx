import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Sparkles,
  AlertCircle,
  Loader2,
  Target,
  Zap,
  Link,
  Search,
  ChevronDown,
  ChevronRight,
  Shield,
  Settings2,
  Cpu,
  Trash2,
  Plus,
} from 'lucide-react';
import { apiClient, GenAccountPayload, MINI_RUNNER_SOURCE_API } from '../api/client';
import { FileManager } from './FileManager';
import { BusinessFile } from '../App';

const TEST_ITEMS = [
  { key: 'functional' as const, label: '功能测试', icon: Target },
  { key: 'performance' as const, label: '网站性能', icon: Zap },
  { key: 'traverse' as const, label: '暴力点击', icon: Search },
  { key: 'links' as const, label: '网站内容', icon: Link },
  { key: 'security' as const, label: '安全扫描', icon: Shield },
];

// Maps TEST_ITEMS keys to Flash runner task texts sent to the backend.
const MINI_TASK_MAP: Record<string, string> = {
  functional: '进行页面完整的功能测试',
  performance: '网页性能测试，输出页面性能指标（如加载时间、资源大小等）',
  traverse: '调用 button-check skill，遍历页面所有交互元素，验证点击/输入是否报错',
  links: '调用 ui-audit skill，对页面做 UX/可访问性审计，输出审计报告',
  security: '执行nuclei扫描，扫描目标URL的基础安全漏洞',
};

/** Gen 页「并发数」下拉默认值（仅前端；不传 workers 时仍由后端 DEFAULT_WORKERS 兜底）。 */
const DEFAULT_GEN_WORKERS = 2;

type AuthType = 'none' | 'sso' | 'cookies';

type GenAuthAccount = {
  id: string;
  name: string;
  is_default: boolean;
  sso_username?: string;
  sso_password?: string;
  sso_env?: 'prod' | 'staging' | 'dev';
  cookies_text?: string;
  cookies?: Array<Record<string, any>>;
};

function normalizeAccounts(accounts: GenAuthAccount[]): GenAuthAccount[] {
  if (!accounts.length) return [];
  const defaultIndex = accounts.findIndex((acc) => acc.is_default);
  const keepIndex = defaultIndex >= 0 ? defaultIndex : 0;
  return accounts.map((acc, idx) => ({ ...acc, is_default: idx === keepIndex }));
}

function buildAccountsPayload(authType: AuthType, accounts: GenAuthAccount[]): GenAccountPayload[] {
  const normalized = normalizeAccounts(accounts);
  if (authType === 'sso') {
    return normalized.map((acc) => ({
      name: acc.name.trim(),
      is_default: acc.is_default,
      default: acc.is_default,
      sso_username: (acc.sso_username || '').trim(),
      sso_password: acc.sso_password || '',
      sso_env: acc.sso_env || 'prod',
    }));
  }
  if (authType === 'cookies') {
    return normalized.map((acc) => ({
      name: acc.name.trim(),
      is_default: acc.is_default,
      default: acc.is_default,
      cookies: acc.cookies || [],
    }));
  }
  return [];
}

function getDefaultAccount(accounts: GenAccountPayload[]): GenAccountPayload | undefined {
  if (!accounts.length) return undefined;
  return accounts.find((acc) => acc.default || acc.is_default) || accounts[0];
}

export function GenPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [loading, setLoading] = useState(false);

  // Form State
  const [targetUrl, setTargetUrl] = useState('');
  const [businessObjectives, setBusinessObjectives] = useState('');
  const [miniObjectives, setMiniObjectives] = useState<string[]>(['']);
  const [selectedModel, setSelectedModel] = useState('');
  const [availableModels, setAvailableModels] = useState<string[]>([]);

  // Test Items (Custom Tools)
  const [testItems, setTestItems] = useState({
    functional: true,
    performance: false,
    traverse: false,
    links: false,
    security: false,
  });

  // Runner selection: 'standard' | 'mini' | 'both'
  const [runnerMode, setRunnerMode] = useState<'standard' | 'mini' | 'both'>('mini');

  // Execution Config (default expanded)
  const [showExecutionConfig, setShowExecutionConfig] = useState(true);
  const [workers, setWorkers] = useState(DEFAULT_GEN_WORKERS);

  // Advanced Options
  const [showAdvanced, setShowAdvanced] = useState(true);
  const [enableReflection, setEnableReflection] = useState(false);
  const [dynamicStepGeneration, setDynamicStepGeneration] = useState(false);
  const [authType, setAuthType] = useState<AuthType>('none');
  const [accounts, setAccounts] = useState<GenAuthAccount[]>([]);
  const [error, setError] = useState<string | null>(null);

  // File upload
  const [businesses, setBusinesses] = useState<{ id: string; name: string }[]>([]);
  const [selectedBusinessId, setSelectedBusinessId] = useState<string>('');
  const [files, setFiles] = useState<BusinessFile[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);

  useEffect(() => {
    const init = async () => {
      try {
        const [models, bizResp] = await Promise.all([
          apiClient.getAvailableModels('gen'),
          apiClient.getBusinesses(),
        ]);
        setAvailableModels(models.models);
        setBusinesses(bizResp.items.map((b) => ({ id: b.id, name: b.name })));

        const fromExecution = (location.state as any)?.fromExecution;
        if (fromExecution?.config) {
          const cfg = fromExecution.config;
          if (cfg.target_url) setTargetUrl(cfg.target_url);
          if (Array.isArray(cfg.business_objectives) && cfg.business_objectives.length > 0) {
            const savedTasks = cfg.business_objectives as string[];
            const presetValues = new Set(Object.values(MINI_TASK_MAP));
            const customObjs = savedTasks.filter(t => !presetValues.has(t));
            if (customObjs.length > 0) setMiniObjectives(customObjs);
            const restored = { functional: false, performance: false, traverse: false, links: false, security: false };
            for (const [key, task] of Object.entries(MINI_TASK_MAP)) {
              if (savedTasks.includes(task)) (restored as any)[key] = true;
            }
            setTestItems(restored);
          } else if (cfg._display_objectives) {
            setBusinessObjectives(cfg._display_objectives);
            setMiniObjectives([cfg._display_objectives]);
          } else if (cfg.business_objectives && typeof cfg.business_objectives === 'string') {
            setBusinessObjectives(cfg.business_objectives);
            if (cfg.business_objectives.trim()) setMiniObjectives([cfg.business_objectives.trim()]);
          }
          const model = cfg.llm_config?.model;
          if (model && models.models.includes(model)) setSelectedModel(model);
          else setSelectedModel(models.default);
          if (typeof fromExecution.workers === 'number') setWorkers(fromExecution.workers);
          const enabled: string[] = cfg.custom_tools?.enabled ?? [];
          setTestItems({
            functional: true,
            performance: enabled.includes('lighthouse'),
            traverse: enabled.includes('traverse_clickable_elements'),
            links: enabled.includes('detect_dynamic_links'),
            security: enabled.includes('nuclei'),
          });
          const rs = cfg.runner_source as string | undefined;
          if (rs === 'standard' || rs === 'mini' || rs === 'both') setRunnerMode(rs as 'standard' | 'mini' | 'both');
          else if (rs === 'cc-mini' || rs === 'cc_mini') setRunnerMode('mini');
          if (fromExecution.business_id) setSelectedBusinessId(fromExecution.business_id);
          // auth
          const authTypeVal = cfg.auth_type as AuthType;
          if (authTypeVal === 'sso' || authTypeVal === 'cookies') {
            setAuthType(authTypeVal);
            const rawAccounts: GenAuthAccount[] = (cfg.accounts || []).map((acc: any, idx: number) => ({
              id: acc.id || String(idx),
              name: acc.name || `账号${idx + 1}`,
              is_default: Boolean(acc.default || acc.is_default),
              sso_username: acc.sso_username,
              sso_password: acc.sso_password,
              sso_env: acc.sso_env,
              cookies_text: acc.cookies ? JSON.stringify(acc.cookies, null, 2) : undefined,
              cookies: acc.cookies,
            }));
            if (rawAccounts.length) setAccounts(rawAccounts);
          }
          // files
          if (Array.isArray(cfg.test_files) && cfg.test_files.length) {
            setSelectedFiles(cfg.test_files);
          }
        } else {
          setSelectedModel(models.default);
        }
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

    const customMiniObjectives = runnerMode !== 'standard'
      ? miniObjectives.filter(o => o.trim())
      : [];
    const hasCustomObjectives = customMiniObjectives.length > 0;

    const fromCheckboxes = TEST_ITEMS.filter((item) => {
      if (!testItems[item.key]) return false;
      // Custom 测试目标 replaces the preset functional line for Flash (not Standard).
      if (runnerMode !== 'standard' && item.key === 'functional' && hasCustomObjectives) {
        return false;
      }
      return true;
    }).map((item) => MINI_TASK_MAP[item.key]);
    const miniTasks =
      runnerMode !== 'standard' && hasCustomObjectives
        ? [...customMiniObjectives, ...fromCheckboxes]
        : fromCheckboxes;
    if (runnerMode !== 'standard' && miniTasks.length === 0) {
      setError('请至少选择一个测试项目');
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

      let finalBusinessObjectives = runnerMode === 'standard'
        ? businessObjectives
        : (hasCustomObjectives ? customMiniObjectives.join('\n') : businessObjectives);
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

      let normalizedAccounts: GenAuthAccount[] = [];
      if (authType !== 'none') {
        if (!accounts.length) {
          setError('请至少配置一个账号');
          setLoading(false);
          return;
        }
        normalizedAccounts = normalizeAccounts(accounts).map((acc) => ({
          ...acc,
          name: acc.name.trim(),
        }));
        const duplicateName = normalizedAccounts.find(
          (acc, idx) =>
            normalizedAccounts.findIndex((other) => other.name === acc.name) !== idx
        );
        if (duplicateName?.name) {
          setError(`存在重复账号名称：${duplicateName.name}`);
          setLoading(false);
          return;
        }
        if (normalizedAccounts.some((acc) => !acc.name)) {
          setError('账号名称不能为空');
          setLoading(false);
          return;
        }
        if (authType === 'sso') {
          const invalidAccount = normalizedAccounts.find(
            (acc) => !(acc.sso_username || '').trim() || !(acc.sso_password || '').trim()
          );
          if (invalidAccount) {
            setError(`SSO 账号「${invalidAccount.name || '未命名'}」缺少用户名或密码`);
            setLoading(false);
            return;
          }
        }
        if (authType === 'cookies') {
          for (const account of normalizedAccounts) {
            const rawCookies = (account.cookies_text || '').trim();
            if (!rawCookies) {
              setError(`Cookies 账号「${account.name || '未命名'}」缺少 cookies`);
              setLoading(false);
              return;
            }
            try {
              const parsed = JSON.parse(rawCookies);
              if (!Array.isArray(parsed) || parsed.length === 0) {
                throw new Error('cookies must be non-empty array');
              }
              account.cookies = parsed;
            } catch {
              setError(`Cookies 账号「${account.name || '未命名'}」JSON 格式无效`);
              setLoading(false);
              return;
            }
          }
        }
        if (runnerMode === 'standard' && normalizedAccounts.length > 1) {
          setError('Standard 模式仅支持单账号，请切换到 Flash 或全选');
          setLoading(false);
          return;
        }
      }

      const allAccountsPayload = buildAccountsPayload(authType, normalizedAccounts);
      const defaultAccount = getDefaultAccount(allAccountsPayload);
      const defaultCookies = defaultAccount?.cookies;

      const baseGenConfig = {
        target_url: targetUrl,
        llm_config: { model: selectedModel },
        business_objectives: finalBusinessObjectives,
        _display_objectives: (runnerMode !== 'standard' && hasCustomObjectives
          ? customMiniObjectives.join('\n')
          : businessObjectives) || undefined,
        custom_tools: { enabled: enabledTools },
        browser_config: { cookies: defaultCookies },
        auth_type: authType,
        ...(allAccountsPayload.length > 0 ? { accounts: allAccountsPayload } : {}),
        report_config: { language: 'zh-CN', save_screenshots: true },
        skip_reflection: !enableReflection,
        dynamic_step_generation: { enabled: dynamicStepGeneration },
        max_concurrent_tests: workers,
        ...(selectedFiles.length > 0 ? { test_files: selectedFiles } : {}),
      };

      if (runnerMode === 'both') {
        const standardGenConfig = {
          ...baseGenConfig,
          runner_source: 'standard' as const,
          // Override: standard runner's planning_mode should be based on its own objectives,
          // not Flash's custom objectives which may have been set in baseGenConfig.
          _display_objectives: businessObjectives.trim() || undefined,
          browser_config: { cookies: defaultCookies },
          ...(authType === 'sso'
            ? {
                auth_type: 'sso' as const,
                accounts: defaultAccount ? [defaultAccount] : [],
              }
            : { auth_type: undefined, accounts: undefined }),
        };
        const miniGenConfig = {
          ...baseGenConfig,
          runner_source: MINI_RUNNER_SOURCE_API,
          business_objectives: miniTasks,
          max_concurrent_tests: workers,
          _display_objectives: (hasCustomObjectives ? customMiniObjectives.join('\n') : businessObjectives.trim()) || undefined,
        };
        const dualResult = await apiClient.createDualGenExecutions({
          business_id: selectedBusinessId || undefined,
          model: selectedModel,
          workers: workers,
          base_gen_config: baseGenConfig,
          standard_gen_config: standardGenConfig,
          mini_gen_config: miniGenConfig,
        });
        const startedCount = Number(Boolean(dualResult.executions.standard)) + Number(Boolean(dualResult.executions.mini));
        if (startedCount === 0) {
          throw new Error(dualResult.errors.join('；') || '启动探索失败');
        }
        if (dualResult.errors.length > 0) {
          setError(`已启动 ${startedCount}/2 个任务，失败：${dualResult.errors.join('；')}`);
        }
      } else {
        const isMiniRunner = runnerMode === 'mini';
        const genConfigBase = isMiniRunner
          ? (() => {
              const { business_objectives: _, ...rest } = baseGenConfig;
              return rest;
            })()
          : baseGenConfig;
        await apiClient.createExecution({
          business_id: selectedBusinessId || undefined,
          trigger_type: 'gen',
          model: selectedModel,
          workers: workers,
          gen_config: {
            ...genConfigBase,
            ...(runnerMode === 'standard'
              ? {
                  browser_config: { cookies: defaultCookies },
                  ...(authType === 'sso'
                    ? { auth_type: 'sso' as const, accounts: defaultAccount ? [defaultAccount] : [] }
                    : { auth_type: undefined, accounts: undefined }),
                }
              : {
                  business_objectives: miniTasks,
                  max_concurrent_tests: workers,
                  _display_objectives: (hasCustomObjectives ? customMiniObjectives.join('\n') : businessObjectives.trim()) || undefined,
                }),
            runner_source: runnerMode === 'standard' ? 'standard' : MINI_RUNNER_SOURCE_API,
          },
        });
      }

      navigate('/history');
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

          {/* Test Items — unified for both runners */}
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
              <span className="ml-1.5 text-xs text-gray-400 font-normal">
                {runnerMode === 'standard'
                  ? '【可选】留空则由 AI 自主探索'
                  : '【可选】每条目标作为 Flash 的独立任务；填写后不再执行预设「功能测试」'}
              </span>
            </label>
            {runnerMode === 'standard' ? (
              <textarea
                rows={3}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm placeholder-gray-400 resize-none"
                placeholder="例如：测试用户登录、搜索商品、加入购物车并结算的核心流程"
                value={businessObjectives}
                onChange={(e) => setBusinessObjectives(e.target.value)}
              />
            ) : (
              <div className="space-y-2">
                {miniObjectives.map((obj, idx) => (
                  <div key={idx} className="flex gap-2 items-start">
                    <textarea
                      rows={2}
                      className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm placeholder-gray-400 resize-none"
                      placeholder="例如：测试用户登录、搜索商品、加入购物车并结算的核心流程"
                      value={obj}
                      onChange={(e) => {
                        const updated = [...miniObjectives];
                        updated[idx] = e.target.value;
                        setMiniObjectives(updated);
                      }}
                    />
                    {miniObjectives.length > 1 && (
                      <button
                        type="button"
                        onClick={() => setMiniObjectives(miniObjectives.filter((_, i) => i !== idx))}
                        className="mt-1 p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
                        title="删除此目标"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => setMiniObjectives([...miniObjectives, ''])}
                  className="flex items-center gap-1.5 text-sm text-purple-600 hover:text-purple-700 hover:bg-purple-50 px-2 py-1 rounded transition-colors"
                >
                  + 新增测试目标
                </button>
              </div>
            )}
          </div>

          {/* Test Files — optional business association for file upload testing */}
          <div>
            <label className="block text-sm font-medium mb-1.5 text-gray-700">
              测试文件
              <span className="ml-1.5 text-xs text-gray-400 font-normal">【可选】关联业务后，可选择文件用于上传测试</span>
            </label>
            <select
              className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm bg-white"
              value={selectedBusinessId}
              onChange={(e) => {
                setSelectedBusinessId(e.target.value);
                setFiles([]);
                setSelectedFiles([]);
              }}
            >
              <option value="">不关联</option>
              {businesses.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>

            {selectedBusinessId && (
              <div className="mt-3 border border-gray-200 rounded-lg p-3">
                <FileManager
                  businessId={selectedBusinessId}
                  files={files}
                  onFilesChange={setFiles}
                  inline
                  selectable
                  selectedFiles={selectedFiles}
                  onSelectionChange={setSelectedFiles}
                  hideDelete
                />
              </div>
            )}
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
                    {runnerMode === 'both' ? '全选' : runnerMode === 'mini' ? 'Flash' : 'Standard'}
                  </span>
                  <span className="px-2 py-0.5 bg-white border border-gray-200 rounded text-xs text-gray-500">
                    {selectedModel || '默认模型'}
                  </span>
                  <span className="px-2 py-0.5 bg-white border border-gray-200 rounded text-xs text-gray-500">
                    并发 {workers}
                  </span>
                  {runnerMode !== 'standard' && (() => {
                    const count = TEST_ITEMS.filter((item) => testItems[item.key]).length;
                    return count > 0 ? (
                      <span className="px-2 py-0.5 bg-white border border-gray-200 rounded text-xs text-gray-500">
                        Flash × {count}
                      </span>
                    ) : null;
                  })()}
                  {authType !== 'none' && accounts.length > 0 && (
                    <span className="px-2 py-0.5 bg-purple-50 border border-purple-200 rounded text-xs text-purple-600">
                      {authType.toUpperCase()} 账号 {accounts.length}
                    </span>
                  )}
                </div>
              )}
            </button>

            {showExecutionConfig && (
              <div className="px-4 py-4 border-t border-gray-200 space-y-4">
                {/* Runner Selection */}
                <div>
                  <label className="block text-sm font-medium mb-1.5 text-gray-700">执行方式</label>
                  <div className="flex gap-2">
                    {([
                      { value: 'both', label: '全选' },
                      { value: 'standard', label: 'Standard' },
                      { value: 'mini', label: 'Flash' },
                    ] as const).map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setRunnerMode(opt.value)}
                        className={`px-4 py-1.5 rounded-lg border text-sm font-medium transition-colors ${
                          runnerMode === opt.value
                            ? 'border-purple-300 bg-purple-50 text-purple-700 ring-1 ring-purple-200'
                            : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>

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
                {/* Auth Accounts */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <label className="block text-sm font-medium text-gray-700">登录配置</label>
                    {runnerMode === 'standard' && authType !== 'none' && (
                      <span className="text-xs text-amber-600">Standard 仅支持单账号</span>
                    )}
                  </div>
                  <div className="flex gap-4">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="radio"
                        name="gen-auth-type"
                        checked={authType === 'none'}
                        onChange={() => {
                          setAuthType('none');
                          setAccounts([]);
                        }}
                      />
                      无
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="radio"
                        name="gen-auth-type"
                        checked={authType === 'sso'}
                        onChange={() => {
                          setAuthType('sso');
                          setAccounts([
                            {
                              id: crypto.randomUUID(),
                              name: '',
                              is_default: true,
                              sso_username: '',
                              sso_password: '',
                              sso_env: 'prod',
                            },
                          ]);
                        }}
                      />
                      SSO
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="radio"
                        name="gen-auth-type"
                        checked={authType === 'cookies'}
                        onChange={() => {
                          setAuthType('cookies');
                          setAccounts([
                            {
                              id: crypto.randomUUID(),
                              name: '',
                              is_default: true,
                              cookies_text: '[]',
                            },
                          ]);
                        }}
                      />
                      Cookies
                    </label>
                  </div>

                  {authType === 'sso' && (
                    <div className="space-y-2">
                      {accounts.map((account, accountIdx) => (
                        <div key={account.id} className="bg-blue-50 border border-blue-100 rounded-lg p-3 space-y-2">
                          <div className="flex items-center gap-2 text-xs text-gray-500">
                            <div className="w-8 text-center flex-shrink-0">默认</div>
                            <div className="flex-1 min-w-0">账户名称</div>
                            <div className="flex-1 min-w-0">SSO 用户名</div>
                            <div className="flex-1 min-w-0">SSO 密码</div>
                            <div className="w-7 flex-shrink-0" />
                          </div>
                          <div className="flex items-start gap-2">
                            <div className="w-8 flex justify-center pt-2 flex-shrink-0">
                              <input
                                type="radio"
                                name="gen-default-account"
                                checked={account.is_default}
                                onChange={() => {
                                  setAccounts((prev) => prev.map((acc, idx) => ({ ...acc, is_default: idx === accountIdx })));
                                }}
                              />
                            </div>
                            <div className="flex-1 min-w-0">
                              <input
                                type="text"
                                value={account.name}
                                onChange={(e) => {
                                  const value = e.target.value;
                                  setAccounts((prev) => prev.map((acc, idx) => idx === accountIdx ? { ...acc, name: value } : acc));
                                }}
                                className="w-full px-2 py-1.5 border rounded text-sm bg-white"
                                placeholder="账号名称"
                              />
                            </div>
                            <div className="flex-1 min-w-0">
                              <input
                                type="text"
                                value={account.sso_username || ''}
                                onChange={(e) => {
                                  const value = e.target.value;
                                  setAccounts((prev) => prev.map((acc, idx) => idx === accountIdx ? { ...acc, sso_username: value } : acc));
                                }}
                                className="w-full px-2 py-1.5 border rounded text-sm bg-white"
                                placeholder="SSO 用户名"
                              />
                            </div>
                            <div className="flex-1 min-w-0">
                              <input
                                type="password"
                                value={account.sso_password || ''}
                                onChange={(e) => {
                                  const value = e.target.value;
                                  setAccounts((prev) => prev.map((acc, idx) => idx === accountIdx ? { ...acc, sso_password: value } : acc));
                                }}
                                className="w-full px-2 py-1.5 border rounded text-sm bg-white"
                                placeholder="SSO 密码"
                              />
                            </div>
                            {(accounts.length > 1) && (
                              <button
                                type="button"
                                onClick={() => {
                                  setAccounts((prev) => normalizeAccounts(prev.filter((_, idx) => idx !== accountIdx)));
                                }}
                                className="p-1.5 mb-0.5 text-red-600 hover:bg-red-50 rounded-lg transition-colors flex-shrink-0 mt-[2px]"
                                title="删除账户"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            )}
                          </div>
                          <div className="flex gap-4 text-sm">
                            {(['prod', 'staging', 'dev'] as const).map((envVal) => (
                              <label key={envVal} className="flex items-center gap-2">
                                <input
                                  type="radio"
                                  name={`gen-sso-env-${account.id}`}
                                  checked={(account.sso_env || 'prod') === envVal}
                                  onChange={() => {
                                    setAccounts((prev) => prev.map((acc, idx) => idx === accountIdx ? { ...acc, sso_env: envVal } : acc));
                                  }}
                                />
                                {envVal}
                              </label>
                            ))}
                          </div>
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={() => {
                          setAccounts((prev) => normalizeAccounts([
                            ...prev,
                            {
                              id: crypto.randomUUID(),
                              name: '',
                              is_default: prev.length === 0,
                              sso_username: '',
                              sso_password: '',
                              sso_env: 'prod',
                            },
                          ]));
                        }}
                        className="text-xs text-blue-600 hover:text-blue-700"
                      >
                        + 添加 SSO 账号
                      </button>
                    </div>
                  )}

                  {authType === 'cookies' && (
                    <div className="space-y-2">
                      {accounts.map((account, accountIdx) => (
                        <div key={account.id} className="bg-blue-50 border border-blue-100 rounded-lg p-3 space-y-2">
                          <div className="flex items-center gap-2 text-xs text-gray-500">
                            <div className="w-8 text-center flex-shrink-0">默认</div>
                            <div className="flex-1 min-w-0">账户名称</div>
                            <div className="flex-1 min-w-0">Cookies (JSON 格式)</div>
                            <div className="w-7 flex-shrink-0" />
                          </div>
                          <div className="flex items-start gap-2">
                            <div className="w-8 flex justify-center pt-2 flex-shrink-0">
                              <input
                                type="radio"
                                name="gen-default-account"
                                checked={account.is_default}
                                onChange={() => {
                                  setAccounts((prev) => prev.map((acc, idx) => ({ ...acc, is_default: idx === accountIdx })));
                                }}
                              />
                            </div>
                            <div className="flex-1 min-w-0">
                              <input
                                type="text"
                                value={account.name}
                                onChange={(e) => {
                                  const value = e.target.value;
                                  setAccounts((prev) => prev.map((acc, idx) => idx === accountIdx ? { ...acc, name: value } : acc));
                                }}
                                className="w-full px-2 py-1.5 border rounded text-sm bg-white"
                                placeholder="账号名称"
                              />
                            </div>
                            <div className="flex-1 min-w-0">
                              <textarea
                                rows={1}
                                value={account.cookies_text || ''}
                                onChange={(e) => {
                                  const value = e.target.value;
                                  setAccounts((prev) => prev.map((acc, idx) => idx === accountIdx ? { ...acc, cookies_text: value } : acc));
                                }}
                                className="w-full px-2 py-1.5 border rounded text-xs font-mono bg-white resize-none"
                                placeholder='[{"name":"session","value":"...","domain":".example.com","path":"/"}]'
                              />
                            </div>
                            {(accounts.length > 1) && (
                              <button
                                type="button"
                                onClick={() => {
                                  setAccounts((prev) => normalizeAccounts(prev.filter((_, idx) => idx !== accountIdx)));
                                }}
                                className="p-1.5 mb-0.5 text-red-600 hover:bg-red-50 rounded-lg transition-colors flex-shrink-0 mt-[2px]"
                                title="删除账户"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={() => {
                          setAccounts((prev) => normalizeAccounts([
                            ...prev,
                            {
                              id: crypto.randomUUID(),
                              name: '',
                              is_default: prev.length === 0,
                              cookies_text: '[]',
                            },
                          ]));
                        }}
                        className="text-xs text-blue-600 hover:text-blue-700"
                      >
                        + 添加 Cookies 账号
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Advanced Options — collapsible, hidden for Flash mode */}
          {runnerMode !== 'mini' && <div className="border border-gray-200 rounded-lg overflow-hidden">
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
          </div>}

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
