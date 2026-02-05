import React, { useState, useEffect } from 'react';
import { Upload, Download, X, Loader2 } from 'lucide-react';
import { TestCase, Business } from '../App';
import { apiClient } from '../api/client';

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

  // 弹窗打开时禁用背景滚动
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, []);

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

  const generateYAMLConfig = (): string => {
    const env = business.environments[0];

    let yaml = '';
    yaml += 'target:\n';
    yaml += `  url: ${env?.url || 'https://example.com'}\n\n`;

    yaml += 'llm_config:\n';
    yaml += '  api: openai\n';
    yaml += '  model: gpt-5-mini-2025-08-07\n';
    yaml += '  api_key: your_openai_api_key\n';
    yaml += '  base_url: https://api.openai.com/v1\n';

    yaml += 'browser_config:\n';
    yaml += '  viewport: {"width": 1500, "height": 800}\n';
    yaml += '  headless: False\n';
    yaml += '  language: zh-CN\n';
    yaml += '  # cookies: /path/to/cookie.json\n\n';

    yaml += 'cases:\n';
    testCases.forEach((testCase) => {
      yaml += `  - name: ${testCase.name}\n`;
      yaml += `    login_required: ${testCase.login_required ?? false}\n`;
      if (testCase.snapshot) {
        yaml += `    snapshot: ${testCase.snapshot}\n`;
      }
      if (testCase.use_snapshot) {
        yaml += `    use_snapshot: ${testCase.use_snapshot}\n`;
      }
      yaml += '    steps:\n';

      testCase.steps.forEach((step) => {
        if (step.step_type === 'action' && step.action) {
          yaml += `      - action: ${step.action.description}\n`;
          if (step.action.args && Object.keys(step.action.args).length > 0) {
            yaml += '        args:\n';
            Object.entries(step.action.args).forEach(([key, value]) => {
              if (value !== undefined && value !== null && (typeof value !== 'string' || value !== '')) {
                yaml += `          ${key}: ${value}\n`;
              }
            });
          }
        } else if (step.step_type === 'verify' && step.verify) {
          yaml += `      - verify: ${step.verify.assertion}\n`;
          if (step.verify.args && Object.keys(step.verify.args).length > 0) {
            yaml += '        args:\n';
            Object.entries(step.verify.args).forEach(([key, value]) => {
              if (value !== undefined && value !== null && (typeof value !== 'string' || value !== '')) {
                yaml += `          ${key}: ${value}\n`;
              }
            });
          }
        }
      });
      yaml += '\n';
    });

    return yaml;
  };

  const handleExport = () => {
    const yamlContent = generateYAMLConfig();
    const blob = new Blob([yamlContent], { type: 'text/yaml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${business.name.replace(/\s+/g, '_')}_test_config.yaml`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center p-0 sm:p-4 z-50" style={{ backgroundColor: 'rgba(0, 0, 0, 0.75)' }}>
      <div className="bg-white w-full h-full sm:h-auto sm:rounded-lg sm:max-w-4xl overflow-hidden flex flex-col max-h-screen sm:max-h-[90vh]">
        <div className="p-4 sm:p-6 border-b border-gray-200 flex items-center justify-between sticky top-0 bg-white z-10">
          <h2>配置导入/导出</h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex border-b border-gray-200">
          <button
            onClick={() => setActiveTab('import')}
            className={`flex-1 px-4 sm:px-6 py-3 text-sm sm:text-base ${
              activeTab === 'import'
                ? 'border-b-2 border-blue-600 text-blue-600'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <Upload className="w-4 h-4 sm:w-5 sm:h-5 inline mr-2" />
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
            <Download className="w-4 h-4 sm:w-5 sm:h-5 inline mr-2" />
            导出配置
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 sm:p-6">
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

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 sm:p-4">
                <p className="text-sm text-blue-800 mb-2">配置格式说明：</p>
                <pre className="text-xs text-blue-700 overflow-x-auto">
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
                  预览YAML配置
                </label>
                <textarea
                  value={generateYAMLConfig()}
                  readOnly
                  className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-gray-50 font-mono text-xs sm:text-sm"
                  rows={16}
                />
              </div>
            </div>
          )}
        </div>

        <div className="p-4 sm:p-6 border-t border-gray-200 flex flex-col-reverse sm:flex-row justify-end gap-3 sticky bottom-0 bg-white">
          <button
            onClick={onClose}
            className="w-full sm:w-auto px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            取消
          </button>
          {activeTab === 'import' ? (
            <button
              onClick={handleImport}
              disabled={!importedContent || isLoading}
              className="w-full sm:w-auto px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  导入中...
                </>
              ) : '导入'}
            </button>
          ) : (
            <button
              onClick={handleExport}
              className="w-full sm:w-auto px-4 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
            >
              导出YAML文件
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
