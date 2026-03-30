import React, { useState, useEffect } from 'react';
import { Upload, Download, Loader2 } from 'lucide-react';
import { TestCase, Business } from '../App';
import { apiClient } from '../api/client';
import yaml from 'js-yaml';

type Props = {
  business: Business;
  testCases: TestCase[];
  onImport: (cases: TestCase[]) => void;
  onClose: () => void;
};

export function ConfigImportExport({ business, testCases, onImport, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<'import' | 'export'>('import');
  const [importedContent, setImportedContent] = useState('');
  const [parseError, setParseError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState('');
  const [generateCookiesOnExport, setGenerateCookiesOnExport] = useState(false);
  const [selectedExportEnvId, setSelectedExportEnvId] = useState<string>(business.environments[0]?.id || '');

  // 弹窗打开时禁用背景滚动
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, []);

  useEffect(() => {
    if (!business.environments.length) {
      setSelectedExportEnvId('');
      return;
    }
    const hasSelected = business.environments.some((env) => env.id === selectedExportEnvId);
    if (!hasSelected) {
      setSelectedExportEnvId(business.environments[0].id);
    }
  }, [business.environments, selectedExportEnvId]);

  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (e) => {
        const content = e.target?.result as string;
        setImportedContent(content);
        setParseError('');
      };
      reader.readAsText(file);
    }
  };

  const parseYAMLConfig = (yamlText: string): TestCase[] => {
    try {
      const lines = yamlText.split('\n');
      const cases: TestCase[] = [];
      let currentCase: Partial<TestCase> | null = null;
      let inCases = false;
      let inSteps = false;
      let currentStep: any = null;
      let inArgs = false;

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trim();

        if (trimmed.startsWith('cases:')) {
          inCases = true;
          continue;
        }

        if (inCases) {
          // 检测新的case
          if (trimmed.startsWith('- name:')) {
            // 保存之前的step和case
            if (currentStep && currentCase) {
              currentCase.steps!.push(currentStep);
              currentStep = null;
            }
            if (currentCase && currentCase.name) {
              cases.push(currentCase as TestCase);
            }

            currentCase = {
              id: crypto.randomUUID(),
              businessId: business.id,
              name: trimmed.replace('- name:', '').trim(),
              description: '',
              login_required: false,
              status: 'active',
              steps: [],
              createdAt: new Date().toISOString().split('T')[0],
            };
            inSteps = false;
            inArgs = false;
          } else if (trimmed.startsWith('login_required:') && currentCase && !inSteps) {
            const value = trimmed.replace('login_required:', '').trim().toLowerCase();
            currentCase.login_required = value === 'true';
          } else if (trimmed.startsWith('snapshot:') && currentCase && !inSteps) {
            currentCase.snapshot = trimmed.replace('snapshot:', '').trim();
          } else if (trimmed.startsWith('use_snapshot:') && currentCase && !inSteps) {
            currentCase.use_snapshot = trimmed.replace('use_snapshot:', '').trim();
          } else if (trimmed.startsWith('steps:') && currentCase) {
            inSteps = true;
            inArgs = false;
          } else if (inSteps && currentCase) {
            // 处理 args:
            if (trimmed === 'args:') {
              inArgs = true;
              if (!currentStep) {
                currentStep = {};
              }
              continue;
            }

            // 处理args内的字段
            if (inArgs && trimmed.includes(':') && line.match(/^\s{8,}/)) {
              const [key, ...valueParts] = trimmed.split(':');
              const value = valueParts.join(':').trim();

              if (!currentStep.args) {
                currentStep.args = {};
              }

              // 解析值
              let parsedValue: any = value;
              if (value === 'true') parsedValue = true;
              else if (value === 'false') parsedValue = false;
              else if (!isNaN(Number(value)) && value !== '') parsedValue = Number(value);

              currentStep.args[key.trim()] = parsedValue;
              continue;
            }

            // 处理 action 或 verify
            if (trimmed.startsWith('- action:')) {
              // 保存之前的step
              if (currentStep && currentStep.step_type) {
                currentCase.steps!.push(currentStep);
              }

              const description = trimmed.replace('- action:', '').trim();
              currentStep = {
                id: crypto.randomUUID(),
                order: currentCase.steps!.length + 1,
                step_type: 'action',
                action: {
                  description: description,
                },
              };
              inArgs = false;
            } else if (trimmed.startsWith('- verify:')) {
              // 保存之前的step
              if (currentStep && currentStep.step_type) {
                currentCase.steps!.push(currentStep);
              }

              const assertion = trimmed.replace('- verify:', '').trim();
              currentStep = {
                id: crypto.randomUUID(),
                order: currentCase.steps!.length + 1,
                step_type: 'verify',
                verify: {
                  assertion: assertion,
                },
              };
              inArgs = false;
            }
          }
        }
      }

      // 添加最后一个step和case
      if (currentStep && currentStep.step_type && currentCase) {
        // 将args合并到action或verify中
        if (currentStep.args) {
          if (currentStep.step_type === 'action' && currentStep.action) {
            currentStep.action.args = currentStep.args;
          } else if (currentStep.step_type === 'verify' && currentStep.verify) {
            currentStep.verify.args = currentStep.args;
          }
          delete currentStep.args;
        }
        currentCase.steps!.push(currentStep);
      }
      if (currentCase && currentCase.name) {
        cases.push(currentCase as TestCase);
      }

      return cases;
    } catch (error) {
      throw new Error('YAML 解析失败：' + (error as Error).message);
    }
  };

  const handleImport = async () => {
    if (!importedContent.trim()) {
      setParseError('请输入或上传 YAML 内容');
      return;
    }

    setIsLoading(true);
    setParseError('');

    try {
      // Call backend API to import
      const result = await apiClient.importTestCases(business.id, importedContent);

      // Convert backend TestCase format to frontend format
      const importedCases = result.cases.map(c => {
        console.log('Importing case:', c.name, 'with snapshot:', c.snapshot, 'use_snapshot:', c.use_snapshot);

        // Ensure steps is valid
        const steps = Array.isArray(c.steps) ? c.steps : [];

        return {
          id: c.id,
          businessId: c.business_id,
          name: c.name,
          description: c.description || '',
          login_required: c.login_required ?? false,
          snapshot: c.snapshot,
          use_snapshot: c.use_snapshot,
          status: (c.status || 'active') as 'active' | 'draft' | 'disabled',
          steps: steps.map((s, idx) => {
            // Handle malformed data where description/assertion might be objects
            let description = '';
            let assertion = '';
            let args = s.args || {};

            if (s.step_type === 'action') {
              // If description is an object with nested structure, extract it
              if (typeof s.description === 'object' && s.description !== null) {
                const descObj = s.description as any;
                description = descObj.description || JSON.stringify(s.description);
                // Merge args if present in the nested object
                if (descObj.args) {
                  args = { ...args, ...descObj.args };
                }
              } else {
                description = s.description || '';
              }
            } else if (s.step_type === 'verify') {
              // If assertion is an object, extract it
              if (typeof s.assertion === 'object' && s.assertion !== null) {
                const assertObj = s.assertion as any;
                assertion = assertObj.assertion || JSON.stringify(s.assertion);
                if (assertObj.args) {
                  args = { ...args, ...assertObj.args };
                }
              } else {
                assertion = s.assertion || '';
              }
            }

            return {
              id: crypto.randomUUID(),
              order: idx + 1,
              step_type: s.step_type,
              action: s.step_type === 'action'
                ? { description, args }
                : undefined,
              verify: s.step_type === 'verify'
                ? { assertion, args }
                : undefined,
            };
          }),
          createdAt: c.created_at?.split('T')[0] || new Date().toISOString().split('T')[0],
        };
      }) as TestCase[];

      onImport(importedCases);
      alert(`成功导入 ${result.imported_count} 个测试用例`);
      onClose();
    } catch (error: any) {
      const errorMsg = error?.message || '导入失败，请检查 YAML 格式';
      setParseError(errorMsg);
    } finally {
      setIsLoading(false);
    }
  };

  const getSelectedExportEnvironment = () => {
    if (!business.environments.length) return undefined;
    return business.environments.find((env) => env.id === selectedExportEnvId) || business.environments[0];
  };

  const generateYAMLConfig = (
    casesToExport: TestCase[] = testCases,
    overrideCookies?: Record<string, any>[],
    includeCookies: boolean = true,
  ): string => {
    const selectedEnv = getSelectedExportEnvironment();
    const resolvedCookies = overrideCookies ?? (selectedEnv?.cookies || []);
    const cookiesPlaceholder = '__WEBQA_COOKIES_PLACEHOLDER__';

    const config: Record<string, any> = {
      target: { url: selectedEnv?.url || 'https://example.com' },
      llm_config: {
        api: 'openai',
        model: 'gpt-5-mini-2025-08-07',
        api_key: 'your_openai_api_key',
        base_url: 'https://api.openai.com/v1',
      },
      browser_config: {
        viewport: selectedEnv?.browser_config?.viewport || { width: 1500, height: 800 },
        headless: selectedEnv?.browser_config?.headless ?? false,
        language: selectedEnv?.browser_config?.language || 'zh-CN',
      },
      cases: casesToExport.map((testCase) => ({
        name: testCase.name,
        login_required: testCase.login_required ?? false,
        ...(testCase.snapshot ? { snapshot: testCase.snapshot } : {}),
        ...(testCase.use_snapshot ? { use_snapshot: testCase.use_snapshot } : {}),
        steps: testCase.steps
          .map((step) => {
            if (step.step_type === 'action' && step.action) {
              const actionArgs = step.action.args
                ? Object.fromEntries(
                    Object.entries(step.action.args).filter(
                      ([, value]) => value !== undefined && value !== null && (typeof value !== 'string' || value !== ''),
                    ),
                  )
                : undefined;
              return {
                action: step.action.description,
                ...(actionArgs && Object.keys(actionArgs).length ? { args: actionArgs } : {}),
              };
            }
            if (step.step_type === 'verify' && step.verify) {
              const verifyArgs = step.verify.args
                ? Object.fromEntries(
                    Object.entries(step.verify.args).filter(
                      ([, value]) => value !== undefined && value !== null && (typeof value !== 'string' || value !== ''),
                    ),
                  )
                : undefined;
              return {
                verify: step.verify.assertion,
                ...(verifyArgs && Object.keys(verifyArgs).length ? { args: verifyArgs } : {}),
              };
            }
            return null;
          })
          .filter(Boolean),
      })),
    };

    const hasIgnoreRules =
      !!selectedEnv?.ignore_rules &&
      ((selectedEnv.ignore_rules.network?.length ?? 0) > 0 || (selectedEnv.ignore_rules.console?.length ?? 0) > 0);
    if (hasIgnoreRules) config.ignore_rules = selectedEnv?.ignore_rules;

    config.report = { language: 'zh-CN' };

    if (includeCookies) {
      config.browser_config.cookies = cookiesPlaceholder;
    }

    const yamlText = yaml.dump(config, { lineWidth: -1, noRefs: true });
    const withInlineViewport = yamlText.replace(
      /(^\s*viewport:\s*\n)(\s*)width:\s*(\d+)\s*\n\2height:\s*(\d+)/m,
      (_match, viewportLine: string, _childIndent: string, width: string, height: string) => {
        const indentMatch = viewportLine.match(/^(\s*)viewport:/);
        const indent = indentMatch?.[1] ?? '  ';
        return `${indent}viewport: {"width": ${width}, "height": ${height}}`;
      },
    );
    const withPythonBooleans = withInlineViewport.replace(
      /:\s*(true|false)(\s*$)/gm,
      (_match, boolValue: string, lineEnd: string) => `: ${boolValue === 'true' ? 'True' : 'False'}${lineEnd}`,
    );

    if (!includeCookies) return withPythonBooleans;

    const cookiesInline = JSON.stringify(resolvedCookies);
    return withPythonBooleans.replace(
      new RegExp(`(^\\s*cookies:\\s*)${cookiesPlaceholder}\\s*$`, 'm'),
      `$1${cookiesInline}`,
    );
  };

  const handleExport = async () => {
    setExportError('');
    setIsExporting(true);
    const selectedEnv = getSelectedExportEnvironment();
    if (!selectedEnv) {
      setExportError('请先选择导出环境');
      setIsExporting(false);
      return;
    }

    let cookiesForExport: Record<string, any>[] | undefined;
    if (generateCookiesOnExport) {
      try {
        const cookieResult = await apiClient.generateEnvironmentCookies(selectedEnv.id);
        cookiesForExport = cookieResult.cookies || [];
      } catch (error: any) {
        setExportError(`生成 cookies 失败：${error?.message || '未知错误'}`);
        setIsExporting(false);
        return;
      }
    }

    const envName = selectedEnv.name?.trim() || 'default_env';
    const businessName = business.name.replace(/\s+/g, '_');
    const safeEnvName = envName.replace(/\s+/g, '_');
    const loginRequiredCases = testCases.filter((testCase) => !!testCase.login_required);
    const noLoginCases = testCases.filter((testCase) => !testCase.login_required);

    const downloadYaml = (yamlContent: string, fileName: string) => {
      const blob = new Blob([yamlContent], { type: 'text/yaml' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = fileName;
      a.click();
      URL.revokeObjectURL(url);
    };

    if (loginRequiredCases.length > 0) {
      downloadYaml(
        generateYAMLConfig(loginRequiredCases, cookiesForExport, true),
        `${businessName}_${safeEnvName}_login_required_test_config.yaml`,
      );
    }
    if (noLoginCases.length > 0) {
      downloadYaml(
        generateYAMLConfig(noLoginCases, undefined, false),
        `${businessName}_${safeEnvName}_no_login_test_config.yaml`,
      );
    }
    if (loginRequiredCases.length === 0 && noLoginCases.length === 0) {
      alert('没有可导出的测试用例');
    }
    setIsExporting(false);
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ backgroundColor: 'rgba(0, 0, 0, 0.75)' }}>
      <div className="bg-white rounded-lg flex flex-col shadow-2xl" style={{ width: '960px', maxWidth: '90vw', maxHeight: 'calc(100vh - 64px)' }}>
        <div className="border border-gray-200 rounded-lg flex flex-col flex-1 min-h-0 overflow-hidden">
          {/* Header */}
          <div className="border-b border-gray-200 flex-shrink-0" style={{ padding: '16px 28px' }}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">配置导入/导出</h2>
              <div className="flex items-center gap-2">
                <button
                  onClick={onClose}
                  className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium"
                >
                  关闭
                </button>
                {activeTab === 'import' ? (
                  <button
                    onClick={handleImport}
                    disabled={!importedContent || isLoading}
                    className="flex items-center justify-center gap-2 px-4 py-2 bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 border border-blue-200 disabled:bg-gray-100 disabled:text-gray-400 disabled:border-gray-200 disabled:cursor-not-allowed transition-colors text-sm font-medium"
                  >
                    {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
                    {isLoading ? '导入中...' : '导入'}
                  </button>
                ) : (
                  <button
                    onClick={handleExport}
                    disabled={isExporting}
                    className="flex items-center justify-center gap-2 px-4 py-2 bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 border border-blue-200 disabled:bg-gray-100 disabled:text-gray-400 disabled:border-gray-200 disabled:cursor-not-allowed transition-colors text-sm font-medium"
                  >
                    {isExporting && <Loader2 className="w-4 h-4 animate-spin" />}
                    {isExporting ? '导出中...' : '导出YAML文件'}
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex border-b border-gray-200">
            <button
              onClick={() => setActiveTab('import')}
              className={`flex-1 px-4 sm:px-6 py-3 text-sm sm:text-base ${
                activeTab === 'import'
                  ? 'border-b-2 border-blue-600 text-blue-600'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <Upload className="w-4 h-4 sm:w-5 sm:h-5 inline mr-2 text-blue-600" />
              导入配置
            </button>
            <button
              onClick={() => setActiveTab('export')}
              className={`flex-1 px-4 sm:px-6 py-3 text-sm sm:text-base ${
                activeTab === 'export'
                  ? 'border-b-2 border-blue-600 text-blue-600'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <Download className="w-4 h-4 sm:w-5 sm:h-5 inline mr-2 text-blue-600" />
              导出配置
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto" style={{ padding: '24px 28px' }}>
          {activeTab === 'import' ? (
            <div className="space-y-4">
              <div>
                <label className="block text-sm mb-2 text-gray-700">
                  选择YAML配置文件
                </label>
                <input
                  type="file"
                  accept=".yaml,.yml"
                  onChange={handleFileUpload}
                  className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                />
              </div>

              <div>
                <label className="block text-sm mb-2 text-gray-700">
                  或粘贴YAML内容
                </label>
                <textarea
                  value={importedContent}
                  onChange={(e) => {
                    setImportedContent(e.target.value);
                    setParseError('');
                  }}
                  className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-xs sm:text-sm"
                  rows={12}
                  placeholder="粘贴YAML配置内容..."
                />
              </div>

              {parseError && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm">
                  {parseError}
                </div>
              )}

              <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 sm:p-4">
                <p className="text-sm text-purple-800 mb-2">配置格式说明：</p>
                <pre className="text-xs text-purple-700 overflow-x-auto">
{`cases:
  - name: Baidu Image Upload
    login_required: true
    steps:
      - verify: Verify the page displays correctly
      - action: Click the upload button and upload files
        args:
          file_path: [./tests/img/test.jpeg, ./tests/file/bench.pdf]
      - verify: Verify upload success
        args:
          use_context: true`}
                </pre>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 sm:p-4">
                <p className="text-sm text-gray-600">
                  当前有 {testCases.length} 个测试用例将被导出
                </p>
              </div>

              <div>
                <label className="block text-sm mb-2 text-gray-700">
                  选择导出环境
                </label>
                <select
                  value={selectedExportEnvId}
                  onChange={(e) => setSelectedExportEnvId(e.target.value)}
                  className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm bg-white"
                  disabled={business.environments.length === 0}
                >
                  {business.environments.length === 0 ? (
                    <option value="">暂无可用环境</option>
                  ) : (
                    business.environments.map((env) => (
                      <option key={env.id} value={env.id}>
                        {env.name} ({env.url || '未设置URL'})
                      </option>
                    ))
                  )}
                </select>
              </div>

              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={generateCookiesOnExport}
                  onChange={(e) => setGenerateCookiesOnExport(e.target.checked)}
                  className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-700">勾选后自动生成浏览器 cookies</span>
              </label>

              {exportError && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm">
                  {exportError}
                </div>
              )}

              <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 sm:p-4">
                <label className="block text-sm mb-2 text-purple-800">
                  预览YAML配置
                </label>
                <textarea
                  value={generateYAMLConfig()}
                  readOnly
                  className="w-full px-3 py-2.5 border border-purple-200 rounded-lg bg-purple-50 font-mono text-xs sm:text-sm text-purple-700"
                  rows={16}
                />
              </div>
            </div>
          )}
          </div>
        </div>
      </div>
    </div>
  );
}
