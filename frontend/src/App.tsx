import React, { useState, useEffect, useCallback } from 'react';
import { Routes, Route, Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { BusinessManager } from './components/BusinessManager';
import { TestCaseManager } from './components/TestCaseManager';
import { ScheduledTaskManager } from './components/ScheduledTaskManager';
import { ExecutionHistory } from './components/ExecutionHistory';
import { ExecutionDetail } from './components/ExecutionDetail';
import { CaseEditorPage } from './components/CaseEditorPage';
import { GenPage } from './components/GenPage';
import { LayoutDashboard, History, Box, Loader2, Github, Sparkles } from 'lucide-react';
import { apiClient, Business as APIBusiness, TestCase as APITestCase, Execution as APIExecution } from './api/client';

// Re-export types for backward compatibility
export type Environment = {
  id: string;
  name: string;
  url: string;
  auth_type?: 'none' | 'sso' | 'cookies';
  sso_username?: string;
  sso_password?: string;
  sso_env?: 'prod' | 'staging' | 'dev';
  cookies?: any[];
  ignore_rules?: {
    network?: Array<{ pattern: string; type: string }>;
    console?: Array<{ pattern: string; match_type: string }>;
  };
  browser_config?: {
    viewport?: { width: number; height: number };
    headless?: boolean;
    language?: string;
  };
};

export type BusinessFile = {
  id: string;
  name: string;
  size: number;
  type: string;
  uploadedAt: string;
  url: string;
};

export type Business = {
  id: string;
  name: string;
  description: string;
  environments: Environment[];
  files: BusinessFile[];
  createdAt: string;
};

export type TestCase = {
  id: string;
  businessId: string;
  name: string;
  description: string;
  login_required: boolean;
  steps: TestStep[];
  version?: string;
  snapshot?: string;
  use_snapshot?: string;
  createdAt: string;
  status: 'draft' | 'active' | 'disabled'; // Keep for API compatibility
};

export type ActionArgs = {
  file_path?: string | string[];
};

export type VerifyArgs = {
  use_context?: boolean;
  context?: boolean;
};

export type TestStep = {
  id: string;
  order: number;
  step_type: 'action' | 'verify';
  action?: {
    description: string;
    args?: ActionArgs;
  };
  verify?: {
    assertion: string;
    args?: VerifyArgs;
  };
};

export type ExecutionResult = {
  id: string;
  testCaseId: string;
  testCaseName: string;
  businessId: string;
  environmentId: string;
  status: 'running' | 'passed' | 'failed' | 'skipped';
  startTime: string;
  endTime?: string;
  duration?: number;
  steps: StepResult[];
};

export type StepResult = {
  stepId: string;
  order: number;
  description: string;
  status: 'pending' | 'running' | 'passed' | 'failed';
  screenshot?: string;
  logs: string[];
  error?: string;
  timestamp: string;
};

export type BatchExecution = {
  id: string;
  businessId: string;
  environmentId: string;
  testCases: string[];
  status: 'pending' | 'running' | 'completed' | 'failed';
  startTime: string;
  endTime?: string;
  results: ExecutionResult[];
};

type BusinessTab = 'cases' | 'schedules' | 'settings';

// Convert API types to frontend types
function toFrontendBusiness(apiBusiness: APIBusiness): Business {
  if (!apiBusiness) {
    console.error('Invalid business data:', apiBusiness);
    return {} as Business;
  }
  return {
    id: apiBusiness.id,
    name: apiBusiness.name,
    description: apiBusiness.description || '',
    environments: (apiBusiness.environments || []).map(env => ({
      id: env.id || crypto.randomUUID(),
      name: env.name || 'Unknown Environment',
      url: env.url || '',
      auth_type: env.auth_type || 'none',
      sso_username: env.sso_username,
      sso_password: env.sso_password,
      sso_env: env.sso_env || 'prod',
      cookies: env.cookies || [],
      ignore_rules: env.ignore_rules || {},
      browser_config: env.browser_config || {},
    })),
    files: [], // Files are managed separately via OSS
    createdAt: (apiBusiness.created_at || new Date().toISOString()).split('T')[0],
  };
}

function toFrontendTestCase(apiCase: APITestCase): TestCase {
  if (!apiCase) {
     console.error('Invalid test case data:', apiCase);
     return {} as TestCase;
  }
  return {
    id: apiCase.id,
    businessId: apiCase.business_id,
    name: apiCase.name,
    description: apiCase.description || '',
    login_required: apiCase.login_required ?? false,
    steps: (apiCase.steps || []).map((step, idx) => {
      // Handle malformed data where description/assertion might be objects
      let description = '';
      let assertion = '';
      let args = step.args || {};

      if (step.step_type === 'action') {
        // If description is an object with nested structure, extract it
        if (typeof step.description === 'object' && step.description !== null) {
          const descObj = step.description as any;
          description = descObj.description || JSON.stringify(step.description);
          // Merge args if present in the nested object
          if (descObj.args) {
            args = { ...args, ...descObj.args };
          }
        } else {
          description = step.description || '';
        }
      } else {
        assertion = step.assertion || '';
      }

      return {
        id: crypto.randomUUID(),
        order: idx + 1,
        step_type: step.step_type,
        action: step.step_type === 'action' ? {
          description,
          args,
        } : undefined,
        verify: step.step_type === 'verify' ? {
          assertion,
          args,
        } : undefined,
      };
    }),
    version: apiCase.version,
    snapshot: apiCase.snapshot,
    use_snapshot: apiCase.use_snapshot,
    createdAt: (apiCase.created_at || new Date().toISOString()).split('T')[0],
    status: (apiCase.status || 'active') as 'draft' | 'active' | 'disabled',
  };
}

function toAPIExecution(exec: APIExecution): BatchExecution {
  return {
    id: exec.id,
    businessId: exec.business_id,
    environmentId: exec.environment_id || '',
    testCases: exec.test_case_ids,
    status: exec.status === 'passed' ? 'completed' :
            exec.status === 'running' ? 'running' :
            exec.status === 'pending' ? 'pending' : 'failed',
    startTime: exec.started_at || exec.created_at,
    endTime: exec.completed_at,
    results: [],
  };
}

// Business Detail Wrapper Component
function BusinessDetailWrapper({
  businesses,
  testCases,
  setTestCases,
  setBusinesses,
  onBatchExecute,
  availableModels,
}: {
  businesses: Business[];
  testCases: TestCase[];
  setTestCases: (cases: TestCase[] | ((prev: TestCase[]) => TestCase[])) => void;
  setBusinesses: (businesses: Business[]) => void;
  onBatchExecute: (execution: BatchExecution) => void;
  availableModels: { models: string[], default: string };
}) {
  const { businessId } = useParams<{ businessId: string }>();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<BusinessTab>('cases');
  const business = businesses.find(b => b.id === businessId);

  useEffect(() => {
    // If business not found in memory, redirect to home
    if (!business && businesses.length > 0) {
      navigate('/');
    }
  }, [business, businesses, navigate]);

  if (!business) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 text-blue-600 animate-spin" />
          <p className="text-gray-600">加载业务信息...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto">
      <div className="py-4">
        <TestCaseManager
          business={business}
          testCases={testCases.filter(tc => tc.businessId === business.id)}
          setTestCases={setTestCases}
          onBack={() => navigate('/')}
          onDebug={() => {}}
          onBatchExecute={onBatchExecute}
          onBusinessUpdate={(updated) => {
            setBusinesses(businesses.map(b => b.id === updated.id ? updated : b));
          }}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          availableModels={availableModels}
        />
      </div>
    </div>
  );
}

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [executions, setExecutions] = useState<BatchExecution[]>([]);
  const [availableModels, setAvailableModels] = useState<{ models: string[], default: string }>({
    models: ['gpt-4o-mini'],
    default: 'gpt-4o-mini'
  });

  // Determine current view from route
  const isCaseEditor = /^\/business\/[^/]+\/case\//.test(location.pathname);
  const view = location.pathname === '/history' ? 'history' :
               location.pathname === '/gen' ? 'gen' :
               isCaseEditor ? 'case_editor' :
               location.pathname.startsWith('/business/') ? 'business_detail' :
               location.pathname.startsWith('/execution/') ? 'execution_detail' : 'businesses';

  // Load businesses and models on mount
  useEffect(() => {
    loadBusinesses();
    loadModels();
  }, []);

  const loadModels = async () => {
    try {
      const config = await apiClient.getAvailableModels();
      setAvailableModels(config);
    } catch (err) {
      console.error('Failed to load models:', err);
    }
  };

  // Load test cases when viewing a business detail page
  useEffect(() => {
    const businessIdMatch = location.pathname.match(/^\/business\/([^/]+)/);
    if (businessIdMatch) {
      const businessId = businessIdMatch[1];
      loadTestCases(businessId);
    }
  }, [location.pathname]);

  const loadBusinesses = async () => {
    try {
      setLoading(true);
      const response = await apiClient.getBusinesses();
      setBusinesses(response.items.map(toFrontendBusiness));
      setError(null);
    } catch (err) {
      console.error('Failed to load businesses:', err);
      setError('服务暂不可用');
      // Use mock data in development
      setBusinesses([]);
    } finally {
      setLoading(false);
    }
  };

  const loadTestCases = async (businessId: string) => {
    try {
      const response = await apiClient.getTestCases(businessId);
      const frontendCases = response.items.map(toFrontendTestCase);
      setTestCases(prev => {
        // Replace cases for this business, keep others
        const otherCases = prev.filter(tc => tc.businessId !== businessId);
        return [...otherCases, ...frontendCases];
      });
    } catch (err) {
      console.error('Failed to load test cases:', err);
    }
  };

  const handleSelectBusiness = (business: Business) => {
    navigate(`/business/${business.id}`);
  };

  const handleBatchExecute = (execution: BatchExecution) => {
    setExecutions([execution, ...executions]);
    // Navigate to execution detail page directly
    navigate(`/execution/${execution.id}`);
  };

  // Custom setter that syncs with API
  const handleSetBusinesses = useCallback((newBusinesses: Business[] | ((prev: Business[]) => Business[])) => {
    setBusinesses(newBusinesses);
    // Reload from API to ensure consistency
    loadBusinesses();
  }, []);

  const handleSetTestCases = useCallback((newCases: TestCase[] | ((prev: TestCase[]) => TestCase[])) => {
    setTestCases(newCases);
    // Note: Don't automatically reload from API here - the caller is responsible for providing correct data
    // This prevents race conditions where a reload might return stale data before the save is fully committed
  }, []);

  if (loading && businesses.length === 0) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 text-blue-600 animate-spin" />
          <p className="text-gray-600">加载中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-50 flex flex-col" style={{ height: '100vh', overflow: 'hidden' }}>
      {/* Header Navigation */}
      <header className="bg-white border-b border-gray-200" style={{ flexShrink: 0, zIndex: 40, position: 'relative' }}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-16">
            <Link to="/" className="flex items-center gap-3 flex-shrink-0 hover:opacity-80 transition-opacity" style={{ marginRight: '32px' }}>
              <div className="flex items-center gap-2">
                <img
                  src="https://static.openxlab.org.cn/platform-config-upload/biz-images/extends/logo.svg"
                  alt="logo"
                  className="h-auto flex-shrink-0"
                  style={{ width: '58px' }}
                />
                <h1 className="text-gray-900 text-lg md:text-xl font-bold mr-6">WebQA Agent</h1>
              </div>
            </Link>

            <nav className="flex items-center gap-2">
              <Link
                to="/gen"
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  view === 'gen'
                    ? 'bg-gray-100 text-gray-900'
                    : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-purple-600" />
                  AI 探索
                </div>
              </Link>
              <Link
                to="/"
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  view === 'businesses' || view === 'business_detail' || view === 'case_editor'
                    ? 'bg-gray-100 text-gray-900'
                    : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <LayoutDashboard className="w-4 h-4" />
                  业务管理
                </div>
              </Link>
              <Link
                to="/history"
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  view === 'history' || view === 'execution_detail'
                    ? 'bg-gray-100 text-gray-900'
                    : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <History className="w-4 h-4" />
                  执行记录
                </div>
              </Link>
            </nav>
          </div>

          <a
            href="https://github.com/MigoXLab/webqa-agent"
            target="_blank"
            rel="noopener noreferrer"
            className="text-gray-500 hover:text-gray-900 transition-colors flex items-center gap-2"
            title="View on GitHub"
          >
            <Github className="w-5 h-5" />
            <span className="text-sm font-medium hidden sm:inline">GitHub Star ⭐</span>
          </a>
        </div>
      </header>

      {/* Error Banner */}
      {error && (
        <div className="bg-amber-50 border-b border-amber-200 px-4 py-3">
          <div className="max-w-7xl mx-auto flex items-center gap-2 text-amber-800">
            <span className="text-sm">⚠️ {error}</span>
            <button
              onClick={loadBusinesses}
              className="ml-auto text-sm text-amber-700 hover:text-amber-900 underline"
            >
              重试
            </button>
          </div>
        </div>
      )}

      {/* Main Content */}
      <main
        className="flex-1"
        style={{ position: 'relative', overflow: 'auto' }}
      >
        <Routes>
          <Route path="/" element={
            <BusinessManager
              businesses={businesses}
              setBusinesses={handleSetBusinesses}
              onSelectBusiness={handleSelectBusiness}
            />
          } />
          <Route path="/gen" element={<GenPage />} />
          <Route path="/business/:businessId" element={
            <BusinessDetailWrapper
              businesses={businesses}
              testCases={testCases}
              setTestCases={handleSetTestCases}
              setBusinesses={(newBusinesses) => {
                setBusinesses(newBusinesses);
                loadBusinesses();
              }}
              onBatchExecute={handleBatchExecute}
              availableModels={availableModels}
            />
          } />
          <Route path="/business/:businessId/case/new" element={<CaseEditorPage />} />
          <Route path="/business/:businessId/case/:caseId" element={<CaseEditorPage />} />
          <Route path="/history" element={
            <ExecutionHistory businesses={businesses} />
          } />
          <Route path="/execution/:executionId" element={
            <ExecutionDetail />
          } />
        </Routes>
      </main>
    </div>
  );
}
