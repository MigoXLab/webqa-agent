import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Save,
  Loader2,
  LayoutList,
  Code,
  AlertCircle,
  Key,
  Play,
  Square,
  ExternalLink,
  Monitor,
  FileText,
  Maximize2,
  Minimize2,
  ChevronDown,
  ChevronRight,
  Settings2,
  GripVertical,
  Trash2,
} from 'lucide-react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { apiClient, ExecutionProgress, TestCase as APITestCase } from '../api/client';
import { TestCase, TestStep, Environment, BusinessFile } from '../App';
import yaml from 'js-yaml';

// ============================================================================
// YAML Helpers (shared with TestCaseManager)
// ============================================================================

const validateYamlSyntax = (yamlText: string): { valid: boolean; error: string | null } => {
  try {
    yaml.load(yamlText);
    return { valid: true, error: null };
  } catch (err: any) {
    const match = err.message?.match(/at line (\d+)/);
    const lineInfo = match ? ` (第 ${match[1]} 行)` : '';
    return { valid: false, error: `YAML 格式错误${lineInfo}: ${err.reason || err.message}` };
  }
};

const convertArraysToFlowStyle = (yamlText: string): string => {
  const lines = yamlText.split('\n');
  const result: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const filePathMatch = line.match(/^(\s*)file_path:\s*$/);
    if (filePathMatch) {
      const baseIndent = filePathMatch[1].length;
      const arrayIndent = baseIndent + 2;
      const items: string[] = [];
      let j = i + 1;
      while (j < lines.length) {
        const nextLine = lines[j];
        const itemMatch = nextLine.match(new RegExp(`^\\s{${arrayIndent}}-\\s+(.+)$`));
        if (itemMatch) { items.push(itemMatch[1].trim()); j++; } else break;
      }
      if (items.length > 0) {
        result.push(`${filePathMatch[1]}file_path: [${items.join(', ')}]`);
        i = j;
        continue;
      }
    }
    result.push(line);
    i++;
  }
  return result.join('\n');
};

const formToYaml = (formData: Partial<TestCase>): string => {
  const obj: any = { name: formData.name || '', login_required: formData.login_required ?? false };
  if (formData.description) obj.description = formData.description;
  if (formData.version) obj.version = formData.version;
  if (formData.snapshot) obj.snapshot = formData.snapshot;
  if (formData.use_snapshot) obj.use_snapshot = formData.use_snapshot;
  obj.steps = formData.steps?.map(step => {
    if (step.step_type === 'action') {
      const s: any = { action: step.action?.description || '' };
      if (step.action?.args && Object.keys(step.action.args).length > 0) {
        const filteredArgs: Record<string, any> = {};
        Object.entries(step.action.args).forEach(([k, v]) => {
          if (v !== undefined && v !== null && v !== '') {
            if (k === 'file_path' && typeof v === 'string' && v.includes(','))
              filteredArgs[k] = v.split(',').map((x: string) => x.trim());
            else filteredArgs[k] = v;
          }
        });
        if (Object.keys(filteredArgs).length > 0) s.args = filteredArgs;
      }
      return s;
    } else {
      const s: any = { verify: step.verify?.assertion || '' };
      if (step.verify?.args && Object.keys(step.verify.args).length > 0) {
        const filteredArgs: Record<string, any> = {};
        Object.entries(step.verify.args).forEach(([k, v]) => {
          if (v !== undefined && v !== null && String(v) !== '') filteredArgs[k] = v;
        });
        if (Object.keys(filteredArgs).length > 0) s.args = filteredArgs;
      }
      return s;
    }
  }) || [];
  const yamlText = yaml.dump([obj], { lineWidth: -1, noRefs: true });
  return convertArraysToFlowStyle(yamlText);
};

const yamlToForm = (yamlText: string): { data: Partial<TestCase> | null; error: string | null } => {
  const syntaxCheck = validateYamlSyntax(yamlText);
  if (!syntaxCheck.valid) return { data: null, error: syntaxCheck.error };
  try {
    let parsed: any = yaml.load(yamlText);
    if (!parsed || typeof parsed !== 'object') return { data: null, error: 'YAML 格式错误: 必须是一个对象或数组' };
    if (Array.isArray(parsed)) {
      if (parsed.length === 0) return { data: null, error: 'YAML 格式错误: 数组不能为空' };
      if (parsed.length > 1) return { data: null, error: 'YAML 格式错误: 单个用例编辑器只能包含一个测试用例' };
      parsed = parsed[0];
    }
    const result: Partial<TestCase> = {
      name: parsed.name || '', description: parsed.description || '',
      login_required: parsed.login_required ?? false,
      version: parsed.version,
      snapshot: parsed.snapshot, use_snapshot: parsed.use_snapshot,
      status: 'active', steps: [],
    };
    if (!Array.isArray(parsed.steps)) return { data: null, error: 'YAML 格式错误: steps 必须是一个列表' };
    for (const rawStep of parsed.steps) {
      if (!rawStep || typeof rawStep !== 'object') continue;
      let step_type: 'action' | 'verify' | null = null;
      let description: string | undefined;
      let assertion: string | undefined;
      let args: Record<string, any> | undefined;
      if (rawStep.action !== undefined) { step_type = 'action'; description = String(rawStep.action); args = rawStep.args; }
      else if (rawStep.verify !== undefined) { step_type = 'verify'; assertion = String(rawStep.verify); args = rawStep.args; }
      if (!step_type) continue;
      result.steps!.push({
        id: crypto.randomUUID(), order: result.steps!.length + 1, step_type,
        action: step_type === 'action' ? { description: description || '', args } : undefined,
        verify: step_type === 'verify' ? { assertion: assertion || '', args } : undefined,
      });
    }
    if (!result.name || result.name.trim() === '') return { data: null, error: '用例名称不能为空' };
    const validSteps = result.steps!.filter(s =>
      s.step_type === 'action' ? s.action?.description?.trim() : s.verify?.assertion?.trim()
    );
    if (validSteps.length === 0) return { data: null, error: '至少需要一个有效的测试步骤' };
    result.steps = validSteps;
    return { data: result, error: null };
  } catch (err) {
    return { data: null, error: 'YAML 解析失败: ' + (err as Error).message };
  }
};

// Convert API TestCase to frontend TestCase
function toFrontendTestCase(apiCase: APITestCase): TestCase {
  return {
    id: apiCase.id,
    businessId: apiCase.business_id,
    name: apiCase.name,
    description: apiCase.description || '',
    login_required: apiCase.login_required ?? false,
    steps: (apiCase.steps || []).map((step, idx) => {
      let description = '';
      let assertion = '';
      let args = step.args || {};
      if (step.step_type === 'action') {
        if (typeof step.description === 'object' && step.description !== null) {
          const descObj = step.description as any;
          description = descObj.description || JSON.stringify(step.description);
          if (descObj.args) args = { ...args, ...descObj.args };
        } else {
          description = step.description || '';
        }
      } else {
        assertion = step.assertion || '';
      }
      return {
        id: crypto.randomUUID(), order: idx + 1, step_type: step.step_type,
        action: step.step_type === 'action' ? { description, args } : undefined,
        verify: step.step_type === 'verify' ? { assertion, args } : undefined,
      };
    }),
    version: apiCase.version,
    snapshot: apiCase.snapshot,
    use_snapshot: apiCase.use_snapshot,
    createdAt: (apiCase.created_at || new Date().toISOString()).split('T')[0],
    status: (apiCase.status || 'active') as 'draft' | 'active' | 'disabled',
  };
}

// ============================================================================
// Types
// ============================================================================

type EditorTab = 'form' | 'yaml';

type DebugState = 'idle' | 'configuring' | 'running' | 'completed' | 'failed';

// ============================================================================
// Sortable Step Item (drag-and-drop)
// ============================================================================

function SortableStepItem({
  step,
  index,
  stepsCount,
  expandedArgs,
  setExpandedArgs,
  updateStepType,
  updateStepDescription,
  updateStepArg,
  removeStep,
  businessFiles,
}: {
  step: TestStep;
  index: number;
  stepsCount: number;
  expandedArgs: Record<string, boolean>;
  setExpandedArgs: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  updateStepType: (index: number, newType: 'action' | 'verify') => void;
  updateStepDescription: (index: number, value: string) => void;
  updateStepArg: (index: number, argName: string, value: any) => void;
  removeStep: (index: number) => void;
  businessFiles: BusinessFile[];
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: step.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 10 : undefined,
  };

  return (
    <div ref={setNodeRef} style={style} className="border border-gray-200 rounded-lg p-3 bg-white">
      <div className="flex items-center gap-2 mb-2">
        <button
          type="button"
          className="cursor-grab active:cursor-grabbing text-gray-400 hover:text-gray-600 flex-shrink-0 touch-none"
          {...attributes}
          {...listeners}
        >
          <GripVertical className="w-4 h-4" />
        </button>
        <span className="w-6 h-6 bg-white rounded-full border border-gray-200 flex items-center justify-center text-gray-600 flex-shrink-0 text-xs font-medium">
          {index + 1}
        </span>
        <select
          value={step.step_type}
          onChange={(e) => updateStepType(index, e.target.value as 'action' | 'verify')}
          className={`px-2 py-0.5 rounded text-xs font-medium border-0 cursor-pointer ${
            step.step_type === 'action' ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700'
          }`}
        >
          <option value="action">Action</option>
          <option value="verify">Verify</option>
        </select>
        {stepsCount > 1 && (
          <button type="button" onClick={() => removeStep(index)} className="ml-auto p-1.5 hover:bg-red-50 rounded-lg transition-colors" title="删除步骤">
            <Trash2 className="w-4 h-4 text-red-600" />
          </button>
        )}
      </div>
      <textarea
        required
        value={step.step_type === 'action' ? step.action?.description || '' : step.verify?.assertion || ''}
        onChange={(e) => updateStepDescription(index, e.target.value)}
        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono resize-y"
        placeholder={step.step_type === 'action' ? '操作描述' : '验证条件'}
        rows={2}
      />
      <div className="mt-2 flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={() => setExpandedArgs(prev => ({ ...prev, [step.id]: !prev[step.id] }))}
          className={`text-xs px-2 py-1 rounded ${expandedArgs[step.id] ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}
        >
          {expandedArgs[step.id] ? '▼ 参数' : '▶ 参数'}
        </button>
      </div>
      {expandedArgs[step.id] && (
        <div className="mt-2 bg-gray-50 rounded p-2">
          {step.step_type === 'action' && (
            <div className="space-y-2">
              <div className="text-xs text-gray-600 font-medium mb-1">选择上传文件（可多选）:</div>
              {businessFiles.length === 0 ? (
                <div className="text-xs text-gray-400 italic">暂无可用文件</div>
              ) : (
                <div className="space-y-1 max-h-40 overflow-y-auto">
                  {businessFiles.map(file => {
                    const currentFiles = (() => { const fp = step.action?.args?.file_path; if (!fp) return []; if (Array.isArray(fp)) return fp; return [fp]; })();
                    const isChecked = currentFiles.includes(file.name);
                    return (
                      <label key={file.id} className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer hover:bg-gray-100 p-1 rounded">
                        <input type="checkbox" checked={isChecked} onChange={(e) => {
                          const curr = (() => { const fp = step.action?.args?.file_path; if (!fp) return []; if (Array.isArray(fp)) return fp; return [fp]; })();
                          let newFiles: string[];
                          if (e.target.checked) newFiles = [...curr, file.name];
                          else newFiles = curr.filter((f: string) => f !== file.name);
                          const val = newFiles.length === 0 ? '' : newFiles.length === 1 ? newFiles[0] : newFiles;
                          updateStepArg(index, 'file_path', val);
                        }} className="w-3.5 h-3.5 rounded border-gray-300 text-blue-600" />
                        <span className="flex-1">{file.name}</span>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          )}
          {step.step_type === 'verify' && (
            <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
              <input type="checkbox" checked={step.verify?.args?.use_context || false} onChange={(e) => updateStepArg(index, 'use_context', e.target.checked)} className="w-3.5 h-3.5 rounded border-gray-300 text-blue-600" />
              使用上下文验证
            </label>
          )}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// CaseEditorPage Component
// ============================================================================

export function CaseEditorPage() {
  const { businessId, caseId } = useParams<{ businessId: string; caseId: string }>();
  const navigate = useNavigate();
  const isNewCase = !caseId || caseId === 'new';

  // ---- Loading state ----
  const [pageLoading, setPageLoading] = useState(true);
  const [business, setBusiness] = useState<{ id: string; name: string; environments: Environment[] } | null>(null);

  // ---- Editor state ----
  const [activeTab, setActiveTab] = useState<EditorTab>('yaml');
  const [formData, setFormData] = useState<Partial<TestCase>>({
    name: '', description: '', login_required: false, version: '', snapshot: '', use_snapshot: '', status: 'active',
    steps: [{ id: crypto.randomUUID(), order: 1, step_type: 'action', action: { description: '' } }],
  });
  const [modalYaml, setModalYaml] = useState('');
  const [modalYamlError, setModalYamlError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [expandedArgs, setExpandedArgs] = useState<Record<string, boolean>>({});
  const [businessFiles, setBusinessFiles] = useState<BusinessFile[]>([]);
  const [settingsExpanded, setSettingsExpanded] = useState(false);

  // ---- Unsaved changes state ----
  const [isDirty, setIsDirty] = useState(false);
  const [showLeaveConfirm, setShowLeaveConfirm] = useState(false);

  // ---- Debug state ----
  const [debugState, setDebugState] = useState<DebugState>('idle');
  const [debugEnvironmentId, setDebugEnvironmentId] = useState('');
  const [debugModel, setDebugModel] = useState('');
  const [debugExecutionId, setDebugExecutionId] = useState<string | null>(null);
  const [debugProgress, setDebugProgress] = useState<ExecutionProgress | null>(null);
  const [debugReportUrl, setDebugReportUrl] = useState<string | null>(null);
  const [debugError, setDebugError] = useState<string | null>(null);
  const [debugInfo, setDebugInfo] = useState<string | null>(null);
  const [availableModels, setAvailableModels] = useState<{ models: string[]; default: string }>({ models: [], default: '' });
  const [isLogFullscreen, setIsLogFullscreen] = useState(false);
  const pollTimerRef = useRef<number | null>(null);
  const logContainerRef = useRef<HTMLDivElement>(null);

  // Escape key to exit fullscreen log
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isLogFullscreen) {
        setIsLogFullscreen(false);
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isLogFullscreen]);

  // ---- Load business, case, models on mount ----
  useEffect(() => {
    if (!businessId) return;
    const load = async () => {
      try {
        setPageLoading(true);
        const [biz, models] = await Promise.all([
          apiClient.getBusiness(businessId),
          apiClient.getAvailableModels(),
        ]);
        setBusiness({
          id: biz.id,
          name: biz.name,
          environments: (biz.environments || []).map(e => ({
            id: e.id || '', name: e.name, url: e.url,
            auth_type: e.auth_type || 'none',
            sso_username: e.sso_username, sso_password: e.sso_password,
            cookies: e.cookies, ignore_rules: e.ignore_rules, browser_config: e.browser_config,
          })),
        });
        setAvailableModels(models);
        setDebugModel(models.default);

        // Set first environment as default
        if (biz.environments && biz.environments.length > 0) {
          setDebugEnvironmentId(biz.environments[0].id || '');
        }

        // Load test case data (edit mode)
        if (!isNewCase && caseId) {
          const apiCase = await apiClient.getTestCase(caseId);
          const tc = toFrontendTestCase(apiCase);
          const data: Partial<TestCase> = {
            name: tc.name, description: tc.description, login_required: tc.login_required,
            version: tc.version, snapshot: tc.snapshot, use_snapshot: tc.use_snapshot, status: tc.status,
            steps: tc.steps.length > 0 ? tc.steps : [{ id: crypto.randomUUID(), order: 1, step_type: 'action', action: { description: '' } }],
          };
          setFormData(data);
          try { setModalYaml(formToYaml(data)); } catch {}
        } else {
          // New case — set YAML template
          setModalYaml(`- name: ''\n  login_required: false\n  steps:\n    - action: ''`);
        }

        // Load business files
        try {
          const files = await apiClient.getFiles(businessId);
          setBusinessFiles(files.items.map((f: any) => ({
            id: f.id, name: f.name, size: f.size, type: f.type || f.mime_type,
            uploadedAt: f.uploaded_at || f.created_at, url: f.url || f.oss_url,
          })));
        } catch {}
      } catch (err) {
        console.error('Failed to load data:', err);
      } finally {
        setPageLoading(false);
      }
    };
    load();
    // Cleanup polling on unmount
    return () => { if (pollTimerRef.current) clearInterval(pollTimerRef.current); };
  }, [businessId, caseId, isNewCase]);

  // ---- Sync form to YAML ----
  const updateFormData = useCallback((newData: Partial<TestCase>) => {
    setFormData(newData);
    setIsDirty(true);
    try {
      setModalYaml(formToYaml(newData));
      setModalYamlError(null);
    } catch (e) {
      setModalYamlError('YAML 生成失败');
    }
  }, []);

  // ---- Sync YAML to form ----
  const handleYamlChange = useCallback((yamlStr: string) => {
    setModalYaml(yamlStr);
    setIsDirty(true);
    const { data, error } = yamlToForm(yamlStr);
    if (error) setModalYamlError(error);
    else if (data) { setModalYamlError(null); setFormData(prev => ({ ...prev, ...data })); }
  }, []);

  // ---- Save ----
  const handleSave = async () => {
    if (saving) return;
    setSaveError(null);
    setSaving(true);
    try {
      // If on YAML tab, sync from YAML first
      if (activeTab === 'yaml') {
        const { data, error } = yamlToForm(modalYaml);
        if (error) { setSaveError(error); setSaving(false); return; }
        if (data) setFormData(prev => ({ ...prev, ...data }));
      }

      const dataToSave = activeTab === 'yaml' ? (() => { const r = yamlToForm(modalYaml); return r.data || formData; })() : formData;

      const apiSteps = dataToSave.steps!.map(step => ({
        step_type: step.step_type,
        description: step.step_type === 'action' ? step.action?.description : undefined,
        assertion: step.step_type === 'verify' ? step.verify?.assertion : undefined,
        args: step.step_type === 'action' ? step.action?.args : step.verify?.args,
      }));

      if (isNewCase) {
        const created = await apiClient.createTestCase({
          business_id: businessId!,
          name: dataToSave.name!,
          description: dataToSave.description,
          login_required: dataToSave.login_required ?? false,
          version: dataToSave.version || undefined,
          snapshot: dataToSave.snapshot,
          use_snapshot: dataToSave.use_snapshot,
          steps: apiSteps,
        });
        // Navigate to the newly created case's editor page
        navigate(`/business/${businessId}/case/${created.id}`, { replace: true });
      } else {
        await apiClient.updateTestCase(caseId!, {
          name: dataToSave.name,
          description: dataToSave.description,
          login_required: dataToSave.login_required,
          version: dataToSave.version,
          snapshot: dataToSave.snapshot,
          use_snapshot: dataToSave.use_snapshot,
          steps: apiSteps,
        });
      }
      setSaveError(null);
      setIsDirty(false);
    } catch (err: any) {
      setSaveError(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  // ---- Back navigation with unsaved changes check ----
  const handleBack = () => {
    if (isDirty) {
      setShowLeaveConfirm(true);
    } else {
      navigate(`/business/${businessId}`);
    }
  };

  const handleLeaveWithSave = async () => {
    setShowLeaveConfirm(false);
    await handleSave();
    navigate(`/business/${businessId}`);
  };

  const handleLeaveWithoutSave = () => {
    setShowLeaveConfirm(false);
    navigate(`/business/${businessId}`);
  };

  // ---- Form step helpers ----
  const addStep = () => {
    const newOrder = formData.steps!.length + 1;
    updateFormData({
      ...formData,
      steps: [...formData.steps!, { id: crypto.randomUUID(), order: newOrder, step_type: 'action', action: { description: '' } }],
    });
  };

  const updateStepType = (index: number, newType: 'action' | 'verify') => {
    const newSteps = [...formData.steps!];
    if (newType === 'action') {
      newSteps[index] = { ...newSteps[index], step_type: 'action', action: { description: newSteps[index].verify?.assertion || '' }, verify: undefined };
    } else {
      newSteps[index] = { ...newSteps[index], step_type: 'verify', verify: { assertion: newSteps[index].action?.description || '' }, action: undefined };
    }
    updateFormData({ ...formData, steps: newSteps });
  };

  const updateStepDescription = (index: number, value: string) => {
    const newSteps = [...formData.steps!];
    const step = newSteps[index];
    if (step.step_type === 'action' && step.action) step.action.description = value;
    else if (step.step_type === 'verify' && step.verify) step.verify.assertion = value;
    updateFormData({ ...formData, steps: newSteps });
  };

  const updateStepArg = (index: number, argName: string, value: any) => {
    const newSteps = [...formData.steps!];
    const step = newSteps[index];
    if (step.step_type === 'action' && step.action) {
      if (!step.action.args) step.action.args = {};
      if (value === '' || value === null) delete step.action.args[argName as keyof typeof step.action.args];
      else (step.action.args as any)[argName] = value;
    } else if (step.step_type === 'verify' && step.verify) {
      if (!step.verify.args) step.verify.args = {};
      if (value === '' || value === null) delete step.verify.args[argName as keyof typeof step.verify.args];
      else (step.verify.args as any)[argName] = value;
    }
    updateFormData({ ...formData, steps: newSteps });
  };

  const removeStep = (index: number) => {
    if (formData.steps!.length > 1) {
      const newSteps = formData.steps!.filter((_, i) => i !== index);
      newSteps.forEach((s, i) => { s.order = i + 1; });
      updateFormData({ ...formData, steps: newSteps });
    }
  };

  // ---- Drag-and-drop sensors ----
  const stepSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleStepDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = formData.steps!.findIndex(s => s.id === active.id);
    const newIndex = formData.steps!.findIndex(s => s.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    const newSteps = arrayMove([...formData.steps!], oldIndex, newIndex);
    newSteps.forEach((s: TestStep, i: number) => { s.order = i + 1; });
    updateFormData({ ...formData, steps: newSteps });
  };

  // ---- Debug ----
  const startDebug = async () => {
    if (!debugEnvironmentId || !debugModel) {
      setDebugError('请选择环境和模型');
      return;
    }

    // Resolve current form data (sync from YAML tab if needed)
    let dataToUse = formData;
    if (activeTab === 'yaml') {
      const { data, error } = yamlToForm(modalYaml);
      if (error) {
        setDebugError(`表单数据无效: ${error}`);
        return;
      }
      if (data) dataToUse = { ...formData, ...data };
    }

    // Validate minimum requirements
    if (!dataToUse.name?.trim()) {
      setDebugError('用例名称不能为空');
      return;
    }
    const validSteps = (dataToUse.steps || []).filter(s =>
      s.step_type === 'action' ? s.action?.description?.trim() : s.verify?.assertion?.trim()
    );
    if (validSteps.length === 0) {
      setDebugError('至少需要一个有效的测试步骤');
      return;
    }

    // Check use_snapshot dependency BEFORE entering running state
    const snapshotName = dataToUse.use_snapshot?.trim();
    let snapshotCase: APITestCase | null = null;

    if (snapshotName) {
      try {
        const allCases = await apiClient.getTestCases(businessId!);
        snapshotCase = allCases.items.find(
          (c: APITestCase) => c.snapshot === snapshotName
        ) || null;

        if (!snapshotCase) {
          setDebugError(
            `未找到快照用例：当前用例依赖快照 "${snapshotName}"，` +
            `请先创建并运行一个包含 snapshot: "${snapshotName}" 的用例。`
          );
          return;
        }
      } catch (err: any) {
        setDebugError(`查找快照用例失败: ${err.message || '未知错误'}`);
        return;
      }
    }

    // Set info message in debug panel
    if (snapshotCase) {
      setDebugInfo(`将先执行快照用例「${snapshotCase.name}」，再执行当前用例`);
    } else if (dataToUse.login_required) {
      setDebugInfo('已开启登录，将注入环境 cookies');
    } else {
      setDebugInfo(null);
    }

    setDebugState('running');
    setDebugError(null);
    setDebugProgress(null);
    setDebugReportUrl(null);

    try {
      // Build case data for execution
      const effectiveCaseId = isNewCase ? crypto.randomUUID() : caseId!;
      const testCaseIds: string[] = [];
      let caseData: Record<string, any> | undefined;

      // If there's a snapshot dependency, prepend it so it runs first
      if (snapshotCase) {
        testCaseIds.push(snapshotCase.id);
      }
      testCaseIds.push(effectiveCaseId);

      if (isNewCase || isDirty) {
        const steps = validSteps.map(step => ({
          step_type: step.step_type,
          description: step.step_type === 'action' ? step.action?.description : undefined,
          assertion: step.step_type === 'verify' ? step.verify?.assertion : undefined,
          args: step.step_type === 'action' ? step.action?.args : step.verify?.args,
        }));

        caseData = {
          [effectiveCaseId]: {
            login_required: dataToUse.login_required ?? false,
            name: dataToUse.name,
            steps,
            snapshot: dataToUse.snapshot || undefined,
            use_snapshot: dataToUse.use_snapshot || undefined,
          },
        };
      }

      const exec = await apiClient.createExecution({
        business_id: businessId!,
        environment_id: debugEnvironmentId,
        test_case_ids: testCaseIds,
        model: debugModel,
        workers: 1,
        trigger_type: 'debug',
        case_data: caseData,
      });
      setDebugExecutionId(exec.id);

      // Start polling progress
      const pollInterval = setInterval(async () => {
        try {
          const progress = await apiClient.getExecutionProgress(exec.id);
          console.log('[Debug] Progress status:', progress.status, 'Logs:', progress.logs?.length || 0);
          setDebugProgress(progress);

          // Auto scroll logs — only scroll the log container, not the page
          setTimeout(() => {
            if (logContainerRef.current) {
              logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
            }
          }, 100);

          // Check if execution is finished (case-insensitive)
          const statusLower = progress.status?.toLowerCase() || '';
          const finishedStatuses = ['completed', 'failed', 'timeout', 'passed', 'warning', 'success', 'error'];
          const isFinished = finishedStatuses.some(s => statusLower.includes(s));

          if (isFinished) {
            console.log('[Debug] ✅ Execution finished with status:', progress.status);
            clearInterval(pollInterval);
            pollTimerRef.current = null;

            // Wait a bit to ensure backend has saved everything
            await new Promise(resolve => setTimeout(resolve, 500));

            // Fetch final execution to get report URL
            try {
              const finalExec = await apiClient.getExecution(exec.id);
              console.log('[Debug] Final execution:', {
                id: finalExec.id,
                status: finalExec.status,
                report_url: finalExec.report_url,
              });

              if (finalExec.report_url) {
                console.log('[Debug] ✅ Setting report URL:', finalExec.report_url);
                setDebugReportUrl(finalExec.report_url);
              } else {
                console.warn('[Debug] ⚠️ No report_url in final execution');
              }
            } catch (err) {
              console.error('[Debug] ❌ Failed to fetch final execution:', err);
            }

            // Set final state
            const successStatuses = ['completed', 'passed', 'success'];
            const isSuccess = successStatuses.some(s => statusLower.includes(s));
            const finalState = isSuccess ? 'completed' : 'failed';
            console.log('[Debug] ✅ Setting debug state to:', finalState);
            setDebugState(finalState);
          }
        } catch (err) {
          console.error('[Debug] ❌ Progress poll error:', err);
        }
      }, 2000);

      pollTimerRef.current = pollInterval as unknown as number;
    } catch (err: any) {
      setDebugError(err.message || '调试启动失败');
      setDebugState('idle');
    }
  };

  const stopDebug = async () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }

    // Try to fetch final execution status when manually stopped
    if (debugExecutionId) {
      try {
        const finalExec = await apiClient.getExecution(debugExecutionId);
        console.log('[Debug] Manual stop - Final execution:', finalExec);
        if (finalExec.report_url) {
          setDebugReportUrl(finalExec.report_url);
        }
        // Set state based on actual status
        const successStatuses = ['completed', 'passed', 'success'];
        const statusLower = finalExec.status?.toLowerCase() || '';
        if (successStatuses.some(s => statusLower.includes(s))) {
          setDebugState('completed');
        } else if (['failed', 'error', 'timeout'].some(s => statusLower.includes(s))) {
          setDebugState('failed');
        } else {
          setDebugState('idle');
        }
      } catch (err) {
        console.error('[Debug] Failed to fetch final execution on stop:', err);
        setDebugState('idle');
      }
    } else {
      setDebugState('idle');
    }
  };

  // ---- Render ----
  if (pageLoading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 text-blue-600 animate-spin" />
          <p className="text-gray-500 text-sm">加载中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col bg-gray-50 flex-1 h-0">
      {/* ===== Leave Confirmation Modal ===== */}
      {showLeaveConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0,0,0,0.45)' }}
          onClick={() => setShowLeaveConfirm(false)}
        >
          <div
            className="bg-white shadow-2xl"
            style={{ width: 400, borderRadius: 16, padding: '28px 32px' }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold text-gray-900 mb-2">未保存的修改</h3>
            <p className="text-sm text-gray-500 mb-6 leading-relaxed">当前用例有未保存的修改，是否保存后再离开？</p>
            <div className="flex items-center justify-end gap-3">
              <button
                onClick={() => setShowLeaveConfirm(false)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors"
                style={{ borderRadius: 8 }}
              >
                取消
              </button>
              <button
                onClick={handleLeaveWithoutSave}
                className="px-4 py-2 border border-gray-200 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                style={{ borderRadius: 8 }}
              >
                不保存离开
              </button>
              <button
                onClick={handleLeaveWithSave}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition-colors"
                style={{ borderRadius: 8 }}
              >
                保存并离开
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== Header (consistent with TestCaseManager) ===== */}
      <div className="flex-shrink-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 pt-4 sm:pt-6 pb-0">
          {/* Row 1: Back button — same position as TestCaseManager's "返回业务列表" */}
          <div className="flex items-center gap-3 mb-4">
            {business && (
              <span className="text-sm font-medium text-gray-400">{business.name}</span>
            )}
            {business && <span className="text-gray-300">/</span>}
            <button
              onClick={handleBack}
              className="flex items-center gap-1.5 text-gray-500 hover:text-gray-900 transition-colors text-sm"
            >
              <ArrowLeft className="w-4 h-4" />
              返回用例列表
            </button>
          </div>

          {/* Row 2: Title + Save button on the same line */}
          <div className="flex items-center justify-between gap-4 mb-4">
            <h1 className="text-xl font-semibold text-gray-900">
              {isNewCase ? '新建用例' : (formData.name || '编辑用例')}
            </h1>
            <div className="flex items-center gap-3 flex-shrink-0">
              {saveError && (
                <span className="text-xs text-red-500 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" /> {saveError}
                </span>
              )}
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium disabled:opacity-50"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                保存
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ===== Main Content ===== */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 pb-4 sm:pb-6 flex flex-col gap-4">
          {/* ===== Two-column area (fixed height, scrollable) ===== */}
          <div className="flex gap-4" style={{ overflow: 'hidden', width: '100%' }}>
            {/* ===== Left Panel: Editor (Tab: Form / YAML) ===== */}
            <div className="flex-1 flex flex-col bg-white rounded-lg border border-gray-200" style={{ height: 800, maxHeight: 800, minWidth: 0, overflow: 'hidden' }}>
              {/* Tabs */}
              <div className="flex items-center border-b border-gray-200 bg-white flex-shrink-0 px-4">
                <button
                  onClick={() => setActiveTab('yaml')}
                  className={`flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === 'yaml'
                      ? 'border-blue-600 text-blue-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  <Code className="w-4 h-4" />
                  YAML 编辑
                  {modalYamlError ? (
                    <span className="ml-1 text-xs text-red-500">✗</span>
                  ) : (
                    <span className="ml-1 text-xs text-green-500">✓</span>
                  )}
                </button>
                <button
                  onClick={() => setActiveTab('form')}
                  className={`flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === 'form'
                      ? 'border-blue-600 text-blue-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  <LayoutList className="w-4 h-4" />
                  表单编辑
                </button>
              </div>

              {/* Tab Content — flex column so each mode fills & scrolls independently */}
              <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
                {activeTab === 'form' ? (
                  /* ===== Form Mode ===== */
                  <div className="flex-1 overflow-y-auto min-h-0 p-4 sm:p-6">
                  <div className="space-y-4 max-w-2xl">
                    {/* Name */}
                    <div>
                      <label className="block text-sm font-medium mb-1.5 text-gray-700">用例名称 *</label>
                      <input
                        type="text"
                        required
                        value={formData.name}
                        onChange={(e) => updateFormData({ ...formData, name: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                        placeholder="例如：登录校验-登录按钮"
                      />
                    </div>

                    {/* Collapsible Settings Section */}
                    <div className="w-full border border-gray-200 rounded-lg overflow-hidden">
                      {/* Settings Header — always visible */}
                      <button
                        type="button"
                        onClick={() => setSettingsExpanded(!settingsExpanded)}
                        className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
                      >
                        {settingsExpanded
                          ? <ChevronDown className="w-3 h-3 text-gray-400 flex-shrink-0" />
                          : <ChevronRight className="w-3 h-3 text-gray-400 flex-shrink-0" />
                        }
                        <Settings2 className="w-3 h-3 text-gray-400 flex-shrink-0" />
                        <span className="text-xs font-medium text-gray-500">用例设置</span>

                        {/* Tag summary — always visible */}
                        <div className="flex items-center gap-2 ml-2 flex-wrap">
                          {formData.login_required && (
                            <span className="inline-flex items-center gap-1 px-3 py-1.5 bg-blue-50 text-blue-700 rounded-lg text-xs font-medium flex-shrink-0 border border-blue-200">
                              <Key className="w-3 h-3" />需登录
                            </span>
                          )}
                          {formData.version && (
                            <span className="px-3 py-1.5 bg-purple-50 text-purple-700 rounded-lg text-xs font-medium flex-shrink-0 border border-purple-200">
                              🏷️ {formData.version}
                            </span>
                          )}
                          {formData.snapshot && (
                            <span className="px-3 py-1.5 bg-gray-50 text-gray-500 rounded-lg text-xs font-medium flex-shrink-0 border border-gray-200">
                              📸 快照: {formData.snapshot}
                            </span>
                          )}
                          {formData.use_snapshot && (
                            <span className="px-3 py-1.5 bg-gray-50 text-gray-500 rounded-lg text-xs font-medium flex-shrink-0 border border-gray-200">
                              🔄 使用: {formData.use_snapshot}
                            </span>
                          )}
                          {!formData.login_required && !formData.version && !formData.snapshot && !formData.use_snapshot && (
                            <span className="text-xs text-gray-400">未设置</span>
                          )}
                        </div>
                      </button>

                      {/* Settings Body — collapsible */}
                      {settingsExpanded && (
                        <div className="px-4 py-4 border-t border-gray-200">
                          <div className="grid grid-cols-4 gap-4">
                            {/* Login */}
                            <div className="flex flex-col justify-end">
                              <label className="flex items-center gap-2 cursor-pointer h-[38px]">
                                <input
                                  type="checkbox"
                                  checked={formData.login_required ?? false}
                                  onChange={(e) => updateFormData({ ...formData, login_required: e.target.checked })}
                                  className="w-4 h-4 rounded border-gray-300 text-amber-600 focus:ring-amber-500"
                                />
                                <span className="text-sm text-gray-700">需要登录</span>
                              </label>
                            </div>
                            {/* Version */}
                            <div>
                              <label className="block text-sm font-medium mb-1.5 text-gray-700">用例版本</label>
                              <input
                                type="text"
                                value={formData.version || ''}
                                onChange={(e) => updateFormData({ ...formData, version: e.target.value })}
                                className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                                placeholder="v1.0"
                              />
                            </div>
                            {/* Snapshot */}
                            <div>
                              <label className="block text-sm font-medium mb-1.5 text-gray-700">创建快照</label>
                              <input
                                type="text"
                                value={formData.snapshot || ''}
                                onChange={(e) => updateFormData({ ...formData, snapshot: e.target.value })}
                                className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                                placeholder="global_before"
                              />
                            </div>
                            {/* Use Snapshot */}
                            <div>
                              <label className="block text-sm font-medium mb-1.5 text-gray-700">使用快照</label>
                              <input
                                type="text"
                                value={formData.use_snapshot || ''}
                                onChange={(e) => updateFormData({ ...formData, use_snapshot: e.target.value })}
                                className="w-full px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                                placeholder="global_before"
                              />
                            </div>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Steps */}
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <label className="text-sm font-medium text-gray-700">测试步骤 *</label>
                        <button type="button" onClick={addStep} className="text-xs text-blue-600 hover:text-blue-700 font-medium">
                          + 添加步骤
                        </button>
                      </div>
                      <DndContext sensors={stepSensors} collisionDetection={closestCenter} onDragEnd={handleStepDragEnd}>
                        <SortableContext items={formData.steps!.map(s => s.id)} strategy={verticalListSortingStrategy}>
                          <div className="space-y-2">
                            {formData.steps!.map((step, index) => (
                              <SortableStepItem
                                key={step.id}
                                step={step}
                                index={index}
                                stepsCount={formData.steps!.length}
                                expandedArgs={expandedArgs}
                                setExpandedArgs={setExpandedArgs}
                                updateStepType={updateStepType}
                                updateStepDescription={updateStepDescription}
                                updateStepArg={updateStepArg}
                                removeStep={removeStep}
                                businessFiles={businessFiles}
                              />
                            ))}
                          </div>
                        </SortableContext>
                      </DndContext>
                    </div>
                  </div>
                  </div>
                ) : (
                  /* ===== YAML Mode ===== */
                  <div className="flex-1 flex flex-col min-h-0 bg-slate-900">
                    <div className="px-4 py-2 bg-slate-800 flex items-center justify-between flex-shrink-0">
                      <div className="flex items-center gap-2">
                        <Code className="w-4 h-4 text-emerald-400" />
                        <span className="text-sm font-medium text-slate-200">YAML</span>
                        {modalYamlError ? (
                          <span className="text-xs text-red-400 flex items-center gap-1"><AlertCircle className="w-3 h-3" /> 格式错误</span>
                        ) : (
                          <span className="text-xs text-emerald-400">✓ 有效</span>
                        )}
                      </div>
                    </div>
                    <div className="flex-1 min-h-0 p-4 overflow-y-auto">
                      <textarea
                        value={modalYaml}
                        onChange={(e) => handleYamlChange(e.target.value)}
                        className={`w-full h-full bg-transparent font-mono text-sm leading-relaxed focus:outline-none resize-none ${
                          modalYamlError ? 'text-red-400' : 'text-emerald-300'
                        }`}
                        spellCheck={false}
                        placeholder={`- name: 用例名称\n  login_required: false\n  steps:\n    - action: 点击按钮\n    - verify: 验证结果`}
                      />
                    </div>
                    {modalYamlError && (
                      <div className="px-4 py-2 bg-red-900/50 text-red-300 text-xs border-t border-red-800">
                        {modalYamlError}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* ===== Right Panel: Debug ===== */}
            <div
              className="flex-shrink-0 flex flex-col bg-white rounded-lg border border-gray-200"
              style={{
                width: '400px',
                minWidth: '400px',
                maxWidth: '400px',
                height: 800,
                maxHeight: 800,
                overflow: 'hidden',
                boxSizing: 'border-box'
              }}
            >
              {/* Debug Header + Config: env, model, button on same row */}
              <div
                className="px-4 py-3 border-b border-gray-200 flex-shrink-0 space-y-3"
                style={{
                  width: '100%',
                  minWidth: 0,
                  maxWidth: '100%',
                  overflow: 'hidden',
                  boxSizing: 'border-box'
                }}
              >
                <h3
                  className="text-sm font-semibold text-gray-900 flex items-center gap-2"
                  style={{ width: '100%', minWidth: 0, overflow: 'hidden' }}
                >
                  <Play className="w-4 h-4 text-blue-600 flex-shrink-0" />
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>Debug 调试</span>
                </h3>
                {/* Env + Model + Debug Button — all on one line */}
                <div className="flex items-center gap-2" style={{ width: '100%', minWidth: 0, maxWidth: '100%', overflow: 'hidden' }}>
                  <select
                    value={debugEnvironmentId}
                    onChange={(e) => setDebugEnvironmentId(e.target.value)}
                    disabled={debugState === 'running'}
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white disabled:bg-gray-100 disabled:cursor-not-allowed"
                    style={{ minWidth: 0, maxWidth: '100%' }}
                  >
                    <option value="">选择环境</option>
                    {business?.environments.map(env => (
                      <option key={env.id} value={env.id}>{env.name}</option>
                    ))}
                  </select>
                  <select
                    value={debugModel}
                    onChange={(e) => setDebugModel(e.target.value)}
                    disabled={debugState === 'running'}
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white disabled:bg-gray-100 disabled:cursor-not-allowed"
                    style={{ minWidth: 0, maxWidth: '100%' }}
                  >
                    {availableModels.models.map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                  {debugState === 'running' ? (
                    <button
                      onClick={stopDebug}
                      className="flex items-center justify-center gap-1.5 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm font-medium flex-shrink-0"
                    >
                      <Square className="w-4 h-4" />
                      停止
                    </button>
                  ) : (
                    <button
                      onClick={startDebug}
                      disabled={!debugEnvironmentId}
                      className="flex items-center justify-center gap-2 px-4 py-2 bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 border border-blue-200 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
                    >
                      <Play className="w-4 h-4" />
                      调试
                    </button>
                  )}
                </div>
                {debugError && (
                  <div
                    className="text-xs text-red-600 flex items-start gap-1 leading-relaxed"
                    style={{ width: '100%', minWidth: 0 }}
                  >
                    <AlertCircle className="w-3 h-3 flex-shrink-0 mt-0.5" />
                    <span>{debugError}</span>
                  </div>
                )}
                {debugInfo && !debugError && (
                  <div
                    className="text-xs text-blue-600 flex items-start gap-1 leading-relaxed"
                    style={{ width: '100%', minWidth: 0 }}
                  >
                    <AlertCircle className="w-3 h-3 flex-shrink-0 mt-0.5" />
                    <span>{debugInfo}</span>
                  </div>
                )}
              </div>

              {/* Debug log + status area */}
              <div
                className={isLogFullscreen
                  ? "fixed inset-0 z-50 flex flex-col bg-gray-900"
                  : "flex-1 flex flex-col"
                }
                style={isLogFullscreen ? {} : {
                  width: '100%',
                  minWidth: 0,
                  maxWidth: '100%',
                  minHeight: 0,
                  overflow: 'hidden',
                  boxSizing: 'border-box'
                }}
              >
                <div
                  className={`flex items-center justify-between px-4 py-2 flex-shrink-0 ${
                    isLogFullscreen
                      ? 'bg-gray-800 border-b border-gray-700'
                      : 'bg-gray-50 border-b border-gray-200'
                  }`}
                  style={{
                    width: '100%',
                    minWidth: 0,
                    maxWidth: '100%',
                    overflow: 'hidden',
                    boxSizing: 'border-box'
                  }}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    {isLogFullscreen ? (
                      <span className="text-xs text-gray-400 font-medium">📜 执行日志</span>
                    ) : (
                      <>
                        <FileText className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
                        <span className="text-xs font-medium text-gray-600" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>执行日志</span>
                      </>
                    )}
                    {debugState === 'running' && (
                      <span className="flex items-center gap-1 text-xs text-blue-600 flex-shrink-0">
                        <Loader2 className="w-3 h-3 animate-spin" /> 执行中
                      </span>
                    )}
                    {debugState === 'completed' && (
                      <span className="text-xs text-green-600 font-medium flex-shrink-0">✓ 完成</span>
                    )}
                    {debugState === 'failed' && (
                      <span className="text-xs text-red-600 font-medium flex-shrink-0">✗ 失败</span>
                    )}
                  </div>
                  <button
                    onClick={() => setIsLogFullscreen(!isLogFullscreen)}
                    className="p-1.5 rounded hover:bg-gray-700 text-gray-400 hover:text-gray-200 transition-colors flex-shrink-0"
                    title={isLogFullscreen ? '退出全屏 (Esc)' : '全屏显示'}
                  >
                    {isLogFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                  </button>
                </div>
                <div
                  ref={logContainerRef}
                  className="flex-1 bg-gray-900 font-mono text-xs text-green-400 leading-relaxed"
                  style={{
                    width: '100%',
                    minWidth: 0,
                    maxWidth: '100%',
                    minHeight: 0,
                    padding: '1rem',
                    overflowY: 'auto',
                    overflowX: 'hidden',
                    overflowWrap: 'break-word',
                    wordBreak: 'break-word',
                    boxSizing: 'border-box',
                  }}
                >
                  {debugProgress && debugProgress.logs.length > 0 ? (
                    debugProgress.logs.map((log, i) => (
                      <div
                        key={i}
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-all',
                          overflowWrap: 'break-word',
                          width: '100%',
                          minWidth: 0,
                          maxWidth: '100%',
                          boxSizing: 'border-box',
                          overflow: 'hidden',
                        }}
                      >
                        {log}
                      </div>
                    ))
                  ) : (
                    <div className="text-gray-400 text-center py-8">
                      {debugState === 'running' ? '等待日志输出...' : '点击「调试」执行当前用例'}
                    </div>
                  )}
                </div>

                {/* Task progress info (running state) */}
                {debugProgress && debugProgress.running.length > 0 && (
                  <div
                    className="px-3 py-2 bg-gray-800 border-t border-gray-700 flex-shrink-0"
                    style={{ width: '100%', maxWidth: '100%', overflow: 'hidden', boxSizing: 'border-box' }}
                  >
                    {debugProgress.running.map((task, i) => (
                      <div
                        key={i}
                        className="text-xs text-blue-400 flex items-center gap-1.5"
                        style={{
                          width: '100%',
                          maxWidth: '100%',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        <Loader2 className="w-3 h-3 animate-spin flex-shrink-0" />
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {task.name} ({task.elapsed?.toFixed(0)}s)
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* View Report Button — compact, only after debug ends */}
              {(() => {
                // Debug render logic
                const shouldShowButton = debugReportUrl && (debugState === 'completed' || debugState === 'failed');
                if (debugExecutionId && !shouldShowButton) {
                  console.log('[Debug] Report button not shown:', {
                    debugReportUrl: !!debugReportUrl,
                    debugState,
                    shouldShow: shouldShowButton
                  });
                }
                return shouldShowButton ? (
                  <div
                    className="px-4 py-2.5 border-t border-gray-200 flex-shrink-0 flex justify-end"
                    style={{ width: '100%', maxWidth: '100%', overflow: 'hidden', boxSizing: 'border-box' }}
                  >
                    <button
                      onClick={() => window.open(debugReportUrl, '_blank')}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-600 hover:bg-blue-100 rounded-lg transition-colors text-sm font-medium"
                    >
                      查看报告
                      <ExternalLink className="w-3 h-3" />
                    </button>
                  </div>
                ) : null;
              })()}
            </div>
          </div>

          {/* ===== Browser Monitor — compact bar below panels ===== */}
          <div className="flex-shrink-0 bg-white rounded-lg border border-gray-200 px-4 py-2 flex items-center justify-center gap-3 opacity-50">
            <Monitor className="w-4 h-4 text-gray-400" />
            <span className="text-xs text-gray-400">浏览器回放 · 功能开发中</span>
          </div>
        </div>
      </div>
    </div>
  );
}
