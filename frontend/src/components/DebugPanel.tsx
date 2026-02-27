import { useState, useEffect } from 'react';
import { ArrowLeft, Play, Pause, RotateCcw, CheckCircle2, XCircle, Clock, Image as ImageIcon, FileText } from 'lucide-react';
import { TestCase, Environment, Business, ExecutionResult, StepResult } from '../App';

type Props = {
  testCase: TestCase;
  environment: Environment;
  business: Business;
  onBack: () => void;
};

export function DebugPanel({ testCase, environment, business, onBack }: Props) {
  const [isRunning, setIsRunning] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [currentStepIndex, setCurrentStepIndex] = useState(-1);
  const [executionResult, setExecutionResult] = useState<ExecutionResult | null>(null);
  const [showVideo, setShowVideo] = useState(false);

  const startExecution = () => {
    setIsRunning(true);
    setIsPaused(false);
    setCurrentStepIndex(0);

    // 初始化执行结果
    const result: ExecutionResult = {
      id: crypto.randomUUID(),
      testCaseId: testCase.id,
      testCaseName: testCase.name,
      businessId: business.id,
      environmentId: environment.id,
      status: 'running',
      startTime: new Date().toISOString(),
      duration: 0,
      steps: testCase.steps.map(step => ({
        stepId: step.id,
        order: step.order,
        description: step.description,
        status: 'pending',
        screenshot: '',
        logs: [],
        timestamp: '',
      })),
    };

    setExecutionResult(result);
  };

  const pauseExecution = () => {
    setIsPaused(true);
  };

  const resumeExecution = () => {
    setIsPaused(false);
  };

  const resetExecution = () => {
    setIsRunning(false);
    setIsPaused(false);
    setCurrentStepIndex(-1);
    setExecutionResult(null);
  };

  // 模拟步骤执行
  useEffect(() => {
    if (!isRunning || isPaused || currentStepIndex === -1 || !executionResult) return;

    if (currentStepIndex >= testCase.steps.length) {
      // 执行完成
      setIsRunning(false);
      setExecutionResult({
        ...executionResult,
        status: executionResult.steps.every(s => s.status === 'passed') ? 'passed' : 'failed',
        endTime: new Date().toISOString(),
        duration: Date.now() - new Date(executionResult.startTime).getTime(),
      });
      return;
    }

    const timer = setTimeout(() => {
      const step = testCase.steps[currentStepIndex];
      const description = step.step_type === 'action' ? step.action?.description : step.verify?.assertion;
      const shouldFail = Math.random() > 0.85; // 15% 失败率

      const stepResult: StepResult = {
        stepId: step.id,
        order: step.order,
        description: description || '',
        status: shouldFail ? 'failed' : 'passed',
        screenshot: `https://images.unsplash.com/photo-${1550000000000 + Math.floor(Math.random() * 100000000)}?w=800&h=600&fit=crop`,
        logs: [
          `[${new Date().toISOString()}] 开始执行步骤 ${step.order}: ${description}`,
          `[${new Date().toISOString()}] 步骤类型: ${step.step_type}`,
          step.step_type === 'action' && step.action?.args?.file_path ? `[${new Date().toISOString()}] 文件路径: ${step.action.args.file_path}` : '',
          step.step_type === 'verify' && step.verify?.args?.use_context ? `[${new Date().toISOString()}] 使用上下文: true` : '',
          `[${new Date().toISOString()}] 正在执行操作...`,
          shouldFail
            ? `[${new Date().toISOString()}] ❌ 执行失败: 元素未找到或操作超时`
            : `[${new Date().toISOString()}] ✓ 执行成功`,
        ].filter(Boolean),
        error: shouldFail ? '元素未找到或操作超时' : undefined,
        timestamp: new Date().toISOString(),
      };

      setExecutionResult(prev => {
        if (!prev) return prev;
        const newSteps = [...prev.steps];
        newSteps[currentStepIndex] = stepResult;
        return {
          ...prev,
          steps: newSteps,
        };
      });

      if (shouldFail) {
        // 如果失败，停止执行
        setIsRunning(false);
        setExecutionResult(prev => prev ? {
          ...prev,
          status: 'failed',
          endTime: new Date().toISOString(),
          duration: Date.now() - new Date(prev.startTime).getTime(),
        } : prev);
      } else {
        setCurrentStepIndex(prev => prev + 1);
      }
    }, 2000); // 每个步骤执行2秒

    return () => clearTimeout(timer);
  }, [isRunning, isPaused, currentStepIndex, testCase, executionResult]);

  const currentStep = currentStepIndex >= 0 && currentStepIndex < testCase.steps.length
    ? testCase.steps[currentStepIndex]
    : null;

  const selectedStepResult = executionResult?.steps[currentStepIndex];

  const getStepDescription = (step: typeof testCase.steps[0]) => {
    return step.step_type === 'action' ? step.action?.description : step.verify?.assertion;
  };

  return (
    <div className="min-h-screen px-4 sm:px-6 py-4 sm:py-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-4 sm:mb-6">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-gray-500 hover:text-gray-900 transition-colors text-sm mb-4"
        >
          <ArrowLeft className="w-4 h-4" />
          返回用例列表
        </button>
        <div className="flex flex-col gap-4">
          <div>
            <h1 className="text-xl font-semibold text-gray-900 mb-2">{testCase.name}</h1>
            <p className="text-gray-600 text-sm sm:text-base">
              {business.name} · {environment.name} ({environment.url})
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            {!isRunning ? (
              <button
                onClick={startExecution}
                className="flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 border border-blue-200 transition-colors flex-1 sm:flex-initial font-medium"
              >
                <Play className="w-5 h-5" />
                开始调试
              </button>
            ) : (
              <>
                {isPaused ? (
                  <button
                    onClick={resumeExecution}
                    className="flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 border border-blue-200 transition-colors flex-1 sm:flex-initial font-medium"
                  >
                    <Play className="w-5 h-5" />
                    继续
                  </button>
                ) : (
                  <button
                    onClick={pauseExecution}
                    className="flex items-center justify-center gap-2 px-4 py-2.5 bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 transition-colors flex-1 sm:flex-initial"
                  >
                    <Pause className="w-5 h-5" />
                    暂停
                  </button>
                )}
              </>
            )}
            <button
              onClick={resetExecution}
              className="flex items-center justify-center gap-2 px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              <RotateCcw className="w-5 h-5" />
              <span className="hidden sm:inline">重置</span>
            </button>
            <button
              onClick={() => setShowVideo(!showVideo)}
              className="flex items-center justify-center gap-2 px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              <ImageIcon className="w-5 h-5" />
              <span className="hidden sm:inline">{showVideo ? '查看截图' : '查看视频'}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Status Bar */}
      {executionResult && (
        <div className="bg-white rounded-lg border border-gray-200 p-4 mb-4 sm:mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex flex-wrap items-center gap-4 sm:gap-6">
              <div className="flex items-center gap-2">
                {executionResult.status === 'running' && (
                  <>
                    <div className="w-3 h-3 bg-blue-500 rounded-full animate-pulse"></div>
                    <span className="text-blue-600 text-sm sm:text-base">执行中...</span>
                  </>
                )}
                {executionResult.status === 'passed' && (
                  <>
                    <CheckCircle2 className="w-5 h-5 text-green-500" />
                    <span className="text-green-600 text-sm sm:text-base">执行成功</span>
                  </>
                )}
                {executionResult.status === 'failed' && (
                  <>
                    <XCircle className="w-5 h-5 text-red-500" />
                    <span className="text-red-600 text-sm sm:text-base">执行失败</span>
                  </>
                )}
              </div>

              <div className="flex items-center gap-2 text-xs sm:text-sm text-gray-600">
                <Clock className="w-4 h-4" />
                <span>
                  步骤进度: {executionResult.steps.filter(s => s.status === 'passed' || s.status === 'failed').length} / {testCase.steps.length}
                </span>
              </div>

              {executionResult.duration && (
                <div className="text-xs sm:text-sm text-gray-600">
                  耗时: {(executionResult.duration / 1000).toFixed(2)}s
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-6">
        {/* Steps List */}
        <div className="lg:col-span-1 bg-white rounded-lg border border-gray-200 p-4">
          <h3 className="mb-4">测试步骤</h3>
          <div className="space-y-2">
            {testCase.steps.map((step, index) => {
              const stepResult = executionResult?.steps[index];
              const isActive = index === currentStepIndex;

              return (
                <div
                  key={step.id}
                  className={`p-3 rounded-lg border-2 transition-all cursor-pointer ${
                    isActive
                      ? 'border-blue-500 bg-blue-50'
                      : stepResult?.status === 'passed'
                      ? 'border-green-200 bg-green-50'
                      : stepResult?.status === 'failed'
                      ? 'border-red-200 bg-red-50'
                      : 'border-gray-200 bg-white'
                  }`}
                  onClick={() => {
                    if (executionResult) {
                      setCurrentStepIndex(index);
                    }
                  }}
                >
                  <div className="flex items-start gap-2">
                    <span className="w-6 h-6 bg-white rounded-full flex items-center justify-center text-sm flex-shrink-0">
                      {step.order}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm truncate">{getStepDescription(step)}</p>
                      <p className="text-xs text-gray-500">{step.step_type}</p>
                    </div>
                    {stepResult?.status === 'passed' && (
                      <CheckCircle2 className="w-4 h-4 text-green-500 flex-shrink-0" />
                    )}
                    {stepResult?.status === 'failed' && (
                      <XCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
                    )}
                    {stepResult?.status === 'running' && (
                      <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin flex-shrink-0"></div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Main Content */}
        <div className="lg:col-span-2 space-y-4 sm:space-y-6">
          {/* Screenshot/Video */}
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base sm:text-lg">{showVideo ? '执行视频' : '步骤截图'}</h3>
              {selectedStepResult && (
                <span className="text-xs sm:text-sm text-gray-500">
                  {new Date(selectedStepResult.timestamp).toLocaleString()}
                </span>
              )}
            </div>
            <div className="bg-gray-100 rounded-lg aspect-video flex items-center justify-center overflow-hidden">
              {selectedStepResult?.screenshot ? (
                showVideo ? (
                  <div className="relative w-full h-full bg-black flex items-center justify-center">
                    <div className="absolute inset-0 flex items-center justify-center">
                      <Play className="w-12 h-12 sm:w-16 sm:h-16 text-white opacity-50" />
                    </div>
                    <img
                      src={selectedStepResult.screenshot}
                      alt="Video frame"
                      className="max-w-full max-h-full object-contain"
                    />
                    <div className="absolute bottom-2 sm:bottom-4 left-2 sm:left-4 right-2 sm:right-4 bg-black bg-opacity-75 rounded px-2 sm:px-3 py-1.5 sm:py-2 text-white text-xs sm:text-sm">
                      <div className="flex items-center justify-between">
                        <span>00:00:{((currentStepIndex + 1) * 2).toString().padStart(2, '0')}</span>
                        <span>00:00:{(testCase.steps.length * 2).toString().padStart(2, '0')}</span>
                      </div>
                      <div className="w-full bg-gray-600 h-1 rounded-full mt-1.5 sm:mt-2">
                        <div
                          className="bg-blue-500 h-1 rounded-full"
                          style={{ width: `${((currentStepIndex + 1) / testCase.steps.length) * 100}%` }}
                        ></div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <img
                    src={selectedStepResult.screenshot}
                    alt="Screenshot"
                    className="max-w-full max-h-full object-contain"
                  />
                )
              ) : (
                <div className="text-center text-gray-400">
                  <ImageIcon className="w-12 h-12 sm:w-16 sm:h-16 mx-auto mb-2" />
                  <p className="text-sm sm:text-base">
                    {isRunning ? '等待执行...' : '开始调试以查看截图'}
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Logs */}
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center gap-2 mb-4">
              <FileText className="w-5 h-5 text-gray-600" />
              <h3 className="text-base sm:text-lg">执行日志</h3>
            </div>
            <div className="bg-gray-900 text-green-400 rounded-lg p-3 sm:p-4 font-mono text-xs sm:text-sm h-48 sm:h-64 overflow-y-auto">
              {selectedStepResult?.logs.length ? (
                <div className="space-y-1">
                  {selectedStepResult.logs.map((log, index) => (
                    <div key={index} className="whitespace-pre-wrap break-words">
                      {log}
                    </div>
                  ))}
                  {selectedStepResult.error && (
                    <div className="text-red-400 mt-2">
                      错误: {selectedStepResult.error}
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-gray-500">
                  {isRunning ? '等待日志输出...' : '没有日志信息'}
                </div>
              )}
            </div>
          </div>

          {/* Step Details */}
          {currentStep && (
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <h3 className="mb-4 text-base sm:text-lg">步骤详情</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="text-sm text-gray-500">步骤序号</label>
                  <p className="text-sm sm:text-base">{currentStep.order}</p>
                </div>
                <div>
                  <label className="text-sm text-gray-500">步骤类型</label>
                  <p className="text-sm sm:text-base">{currentStep.step_type}</p>
                </div>
                <div className="col-span-1 sm:col-span-2">
                  <label className="text-sm text-gray-500">
                    {currentStep.step_type === 'action' ? 'Description (描述)' : 'Assertion (断言)'}
                  </label>
                  <p className="text-sm sm:text-base break-words">{getStepDescription(currentStep)}</p>
                </div>

                {/* Action Args */}
                {currentStep.step_type === 'action' && currentStep.action?.args && (
                  <>
                    {currentStep.action.args.file_path && (
                      <div className="col-span-1 sm:col-span-2">
                        <label className="text-sm text-gray-500">文件路径</label>
                        <p className="font-mono text-xs sm:text-sm bg-gray-50 p-2 rounded break-all">
                          {currentStep.action.args.file_path}
                        </p>
                      </div>
                    )}
                    {currentStep.action.args.timeout && (
                      <div>
                        <label className="text-sm text-gray-500">超时时间</label>
                        <p className="font-mono text-xs sm:text-sm bg-gray-50 p-2 rounded">
                          {currentStep.action.args.timeout}ms
                        </p>
                      </div>
                    )}
                  </>
                )}

                {/* Verify Args */}
                {currentStep.step_type === 'verify' && currentStep.verify?.args && (
                  <>
                    {currentStep.verify.args.use_context && (
                      <div>
                        <label className="text-sm text-gray-500">使用上下文</label>
                        <p className="font-mono text-xs sm:text-sm bg-gray-50 p-2 rounded">
                          ✓ 是
                        </p>
                      </div>
                    )}
                    {currentStep.verify.args.timeout && (
                      <div>
                        <label className="text-sm text-gray-500">超时时间</label>
                        <p className="font-mono text-xs sm:text-sm bg-gray-50 p-2 rounded">
                          {currentStep.verify.args.timeout}ms
                        </p>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
