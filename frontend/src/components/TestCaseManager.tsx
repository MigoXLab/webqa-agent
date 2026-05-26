import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, Play, Edit, Trash2, FileText, Download, Calendar, Settings, Loader2, LayoutList, Code, Key, AlertCircle, Check, Search, X, GripVertical } from 'lucide-react';
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
  rectSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Business, TestCase, Environment, TestStep, BatchExecution, BusinessFile } from '../App';
import { ConfigImportExport } from './ConfigImportExport';
import { FileManager } from './FileManager';
import { ScheduledTaskManager, ScheduledTask } from './ScheduledTaskManager';
import { BusinessManager } from './BusinessManager';
import { apiClient } from '../api/client';
import { ResolutionSelector } from './ResolutionSelector';
import {
  formToYaml,
  yamlToForm,
  testCasesToYaml,
  parseGlobalYaml,
  stepsToApiFormat,
  toFrontendTestCase,
} from '../utils/testCaseUtils';

// ============================================================================
// Sortable Case Card wrapper (drag-and-drop)
// ============================================================================

function SortableCaseCard({ id, children }: { id: string; children: (props: { dragHandleProps: Record<string, any>; isDragging: boolean }) => React.ReactNode }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 10 : undefined,
  };

  return (
    <div ref={setNodeRef} style={style} className="h-full">
      {children({ dragHandleProps: { ...attributes, ...listeners }, isDragging })}
    </div>
  );
}

type Props = {
  business: Business;
  testCases: TestCase[];
  setTestCases: (testCases: TestCase[]) => void;
  onBack: () => void;
  onDebug: (testCase: TestCase, environment: Environment) => void;
  onBatchExecute: (execution: BatchExecution) => void;
  onBusinessUpdate: (business: Business) => void;
  activeTab: 'cases' | 'schedules' | 'settings';
  setActiveTab: (tab: 'cases' | 'schedules' | 'settings') => void;
  availableModels: { models: string[], default: string };
};

export function TestCaseManager({
  business,
  testCases,
  setTestCases,
  onBack,
  onDebug,
  onBatchExecute,
  onBusinessUpdate,
  activeTab,
  setActiveTab,
  availableModels
}: Props) {
  const navigate = useNavigate();
  const [showModal, setShowModal] = useState(false);
  const [editingCase, setEditingCase] = useState<TestCase | null>(null);
  const [selectedCases, setSelectedCases] = useState<string[]>([]);
  const [selectedEnv, setSelectedEnv] = useState<string>('');
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [expandedArgs, setExpandedArgs] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [executing, setExecuting] = useState(false);

  // Schedule create modal control
  const [scheduleCreateOpen, setScheduleCreateOpen] = useState(false);

  // View mode: cards or yaml
  const [viewMode, setViewMode] = useState<'cards' | 'yaml'>('cards');
  const [globalYaml, setGlobalYaml] = useState<string>('');
  const [globalYamlError, setGlobalYamlError] = useState<string | null>(null);

  // Modal YAML editor state
  const [modalYaml, setModalYaml] = useState<string>('');
  const [modalYamlError, setModalYamlError] = useState<string | null>(null);
  const [isYamlEditing, setIsYamlEditing] = useState(false);

  // Model selection
  const [selectedModel, setSelectedModel] = useState<string>(availableModels.default);
  const [selectedResolutions, setSelectedResolutions] = useState<string[]>([]);
  const [workers, setWorkers] = useState<number>(1);
  const [businessFiles, setBusinessFiles] = useState<BusinessFile[]>([]);

  // Filter & search state
  const [searchQuery, setSearchQuery] = useState('');
  const [filterLogin, setFilterLogin] = useState<'all' | 'required' | 'not_required'>('all');
  const [filterSnapshot, setFilterSnapshot] = useState<'all' | 'has_snapshot' | 'use_snapshot' | 'none'>('all');
  const [filterVersion, setFilterVersion] = useState<string>('all');
  const [batchDeleting, setBatchDeleting] = useState(false);

  // Fetch business files
  useEffect(() => {
    apiClient.getFiles(business.id).then(response => {
      setBusinessFiles(response.items.map(f => ({
        id: f.id,
        name: f.name,
        size: f.size,
        type: f.type,
        uploadedAt: f.uploaded_at.split('T')[0],
        url: f.url
      })));
    }).catch(err => console.error('Failed to load business files:', err));
  }, [business.id]);

  // Update selected model if default changes or it's empty
  useEffect(() => {
    if (!selectedModel || !availableModels.models.includes(selectedModel)) {
      setSelectedModel(availableModels.default);
    }
  }, [availableModels]);

  // 弹窗打开时禁用背景滚动
  useEffect(() => {
    if (showModal || showConfigModal) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [showModal, showConfigModal]);

  const [formData, setFormData] = useState<Partial<TestCase>>({
    name: '',
    description: '',
    login_required: false,
    snapshot: '',
    use_snapshot: '',
    status: 'active',
    steps: [
      {
        id: crypto.randomUUID(),
        order: 1,
        step_type: 'action',
        action: { description: '' }
      },
    ],
  });

  // Helper to update form data and sync to YAML
  const updateFormData = (newData: Partial<TestCase>) => {
    setFormData(newData);
    try {
      setModalYaml(formToYaml(newData));
      setModalYamlError(null);
    } catch (error) {
      console.error('Failed to convert form to YAML:', error);
      setModalYamlError('YAML 生成失败: ' + (error as Error).message);
    }
  };

  // Initialize global YAML when switching to YAML view
  useEffect(() => {
    if (viewMode === 'yaml') {
      setGlobalYaml(testCasesToYaml(testCases));
      setGlobalYamlError(null);
    }
  }, [viewMode, testCases]);

  // Compute available versions for filter dropdown
  const availableVersions = Array.from(new Set(
    testCases.map(tc => tc.version).filter((v): v is string => !!v)
  )).sort();

  // Apply search + filters to test cases
  const filteredTestCases = testCases.filter(tc => {
    if (!tc || !tc.id || !tc.name) return false;
    // Search by name
    if (searchQuery && !tc.name.toLowerCase().includes(searchQuery.toLowerCase())) return false;
    // Login filter
    if (filterLogin === 'required' && !tc.login_required) return false;
    if (filterLogin === 'not_required' && tc.login_required) return false;
    // Snapshot filter
    if (filterSnapshot === 'has_snapshot' && !tc.snapshot) return false;
    if (filterSnapshot === 'use_snapshot' && !tc.use_snapshot) return false;
    if (filterSnapshot === 'none' && (tc.snapshot || tc.use_snapshot)) return false;
    // Version filter
    if (filterVersion !== 'all' && (tc.version || '') !== filterVersion) return false;
    return true;
  });

  // Check if any filter is active
  const hasActiveFilters = searchQuery !== '' || filterLogin !== 'all' || filterSnapshot !== 'all' || filterVersion !== 'all';
  const clearAllFilters = useCallback(() => {
    setSearchQuery('');
    setFilterLogin('all');
    setFilterSnapshot('all');
    setFilterVersion('all');
  }, []);

  // ---- Drag-and-drop for case list ----
  const caseSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleCaseDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = filteredTestCases.findIndex(tc => tc.id === active.id);
    const newIndex = filteredTestCases.findIndex(tc => tc.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    // Reorder filteredTestCases, then rebuild the full list
    const reordered = arrayMove([...filteredTestCases], oldIndex, newIndex);
    const filteredIds = new Set(filteredTestCases.map(tc => tc.id));
    const nonFiltered = testCases.filter(tc => !filteredIds.has(tc.id));
    // Place reordered items at the positions of the filtered items in the original order
    const newList: TestCase[] = [];
    let reorderedIdx = 0;
    for (const tc of testCases) {
      if (filteredIds.has(tc.id)) {
        newList.push(reordered[reorderedIdx++]);
      } else {
        newList.push(tc);
      }
    }
    setTestCases(newList);

    // Persist sort_order to backend (fire-and-forget)
    reordered.forEach((tc, i) => {
      apiClient.updateTestCase(tc.id, { sort_order: i + 1 }).catch(() => {});
    });
  };

  // Batch delete handler
  const handleBatchDelete = async () => {
    if (selectedCases.length === 0) return;
    if (!confirm(`确定要删除选中的 ${selectedCases.length} 个用例吗？此操作不可撤销。`)) return;
    setBatchDeleting(true);
    const failedIds: string[] = [];
    for (const id of selectedCases) {
      try {
        await apiClient.deleteTestCase(id);
      } catch {
        failedIds.push(id);
      }
    }
    const deletedIds = selectedCases.filter(id => !failedIds.includes(id));
    if (deletedIds.length > 0) {
      setTestCases(testCases.filter(tc => !deletedIds.includes(tc.id)));
    }
    setSelectedCases(failedIds);
    if (failedIds.length > 0) {
      alert(`${deletedIds.length} 个用例已删除，${failedIds.length} 个删除失败`);
    }
    setBatchDeleting(false);
  };

  const saveTestCase = async (data: Partial<TestCase>) => {
    if (saving) return;

    setError(null);
    setSaving(true);

    try {
      const apiSteps = stepsToApiFormat(data.steps!);

      if (editingCase) {
        const updatedApiCase = await apiClient.updateTestCase(editingCase.id, {
          name: data.name,
          description: data.description,
          login_required: data.login_required,
          account: data.account,
          version: data.version || undefined,
          snapshot: data.snapshot,
          use_snapshot: data.use_snapshot,
          steps: apiSteps,
        });
        const updatedCase = toFrontendTestCase(updatedApiCase);
        setTestCases(testCases.map(tc => tc.id === editingCase.id ? updatedCase : tc));
      } else {
        const createdApiCase = await apiClient.createTestCase({
          business_id: business.id,
          name: data.name!,
          description: data.description,
          login_required: data.login_required ?? false,
          account: data.account,
          version: data.version || undefined,
          snapshot: data.snapshot,
          use_snapshot: data.use_snapshot,
          steps: apiSteps,
        });
        const newCase = toFrontendTestCase(createdApiCase);
        setTestCases([...testCases, newCase]);
      }

      setShowModal(false);
      resetForm();
    } catch (err: any) {
      setError(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    await saveTestCase(formData);
  };

  const handleModalYamlSave = async () => {
    const { data, error } = yamlToForm(modalYaml);
    if (error) {
      setModalYamlError(error);
      return;
    }
    if (data) {
      await saveTestCase(data);
    }
  };

  const handleModalYamlCancel = () => {
    setModalYaml(formToYaml(formData));
    setModalYamlError(null);
    setIsYamlEditing(false);
  };

  const resetForm = () => {
    const newData: Partial<TestCase> = {
      name: '',
      description: '',
      login_required: false,
      version: '',
      snapshot: '',
      use_snapshot: '',
      status: 'active',
      steps: [
        {
          id: crypto.randomUUID(),
          order: 1,
          step_type: 'action',
          action: { description: '' }
        },
      ],
    };
    setEditingCase(null);
    setFormData(newData);
    // Set YAML template with list format for new test cases
    const template = `- name: ''
  login_required: false
  steps:
    - action: ''`;
    setModalYaml(template);
    setModalYamlError(null);
    setIsYamlEditing(false);
  };

  const handleEdit = (testCase: TestCase) => {
    // Navigate to the full-screen case editor page
    navigate(`/business/${business.id}/case/${testCase.id}`);
  };

  // Handle YAML change in modal - sync to form
  const handleModalYamlChange = useCallback((yaml: string) => {
    setModalYaml(yaml);
    setIsYamlEditing(true);

    const { data, error } = yamlToForm(yaml);
    if (error) {
      setModalYamlError(error);
    } else if (data) {
      setModalYamlError(null);
      setFormData(prev => ({
        ...prev,
        ...data,
      }));
    }
  }, []);

  const handleDelete = async (id: string) => {
    if (confirm('确定要删除这个测试用例吗？')) {
      try {
        await apiClient.deleteTestCase(id);
        setTestCases(testCases.filter(tc => tc.id !== id));
      } catch (err: any) {
        alert('删除失败: ' + (err.message || '未知错误'));
      }
    }
  };

  const handleToggleLoginRequired = async (testCase: TestCase, e: React.MouseEvent) => {
    e.stopPropagation();

    try {
      const updatedApiCase = await apiClient.updateTestCase(testCase.id, {
        login_required: !testCase.login_required,
      });

      setTestCases(testCases.map(tc =>
        tc.id === testCase.id
          ? toFrontendTestCase(updatedApiCase)
          : tc
      ));
    } catch (err: any) {
      alert('更新失败: ' + (err.message || '未知错误'));
    }
  };

  const addStep = () => {
    const newOrder = formData.steps!.length + 1;
    updateFormData({
      ...formData,
      steps: [
        ...formData.steps!,
        {
          id: crypto.randomUUID(),
          order: newOrder,
          step_type: 'action',
          action: { description: '' }
        },
      ],
    });
  };

  const updateStepType = (index: number, newType: 'action' | 'verify') => {
    const newSteps = [...formData.steps!];
    if (newType === 'action') {
      newSteps[index] = {
        ...newSteps[index],
        step_type: 'action',
        action: { description: newSteps[index].verify?.assertion || '' },
        verify: undefined,
      };
    } else {
      newSteps[index] = {
        ...newSteps[index],
        step_type: 'verify',
        verify: { assertion: newSteps[index].action?.description || '' },
        action: undefined,
      };
    }
    updateFormData({ ...formData, steps: newSteps });
  };

  const updateStepDescription = (index: number, value: string) => {
    const newSteps = [...formData.steps!];
    const step = newSteps[index];
    if (step.step_type === 'action' && step.action) {
      step.action.description = value;
    } else if (step.step_type === 'verify' && step.verify) {
      step.verify.assertion = value;
    }
    updateFormData({ ...formData, steps: newSteps });
  };

  const updateStepArg = (index: number, argName: string, value: any) => {
    const newSteps = [...formData.steps!];
    const step = newSteps[index];

    if (step.step_type === 'action' && step.action) {
      if (!step.action.args) step.action.args = {};
      if (value === '' || value === null) {
        delete step.action.args[argName as keyof typeof step.action.args];
      } else {
        (step.action.args as any)[argName] = value;
      }
    } else if (step.step_type === 'verify' && step.verify) {
      if (!step.verify.args) step.verify.args = {};
      if (value === '' || value === null) {
        delete step.verify.args[argName as keyof typeof step.verify.args];
      } else {
        (step.verify.args as any)[argName] = value;
      }
    }

    updateFormData({ ...formData, steps: newSteps });
  };

  const removeStep = (index: number) => {
    if (formData.steps!.length > 1) {
      const newSteps = formData.steps!.filter((_, i) => i !== index);
      newSteps.forEach((step, i) => {
        step.order = i + 1;
      });
      updateFormData({ ...formData, steps: newSteps });
    }
  };

  const toggleArgs = (stepId: string) => {
    setExpandedArgs(prev => ({ ...prev, [stepId]: !prev[stepId] }));
  };

  const toggleCaseSelection = (caseId: string) => {
    setSelectedCases(prev =>
      prev.includes(caseId)
        ? prev.filter(id => id !== caseId)
        : [...prev, caseId]
    );
  };

  const handleBatchRun = async () => {
    // Prevent multiple simultaneous executions
    if (executing) return;

    if (selectedCases.length === 0) {
      alert('请至少选择一个测试用例');
      return;
    }

    if (!selectedEnv) {
      alert('请选择执行环境');
      return;
    }

    setExecuting(true);

    try {
      // Call API to create execution with selected model
      const execution = await apiClient.createExecution({
        business_id: business.id,
        environment_id: selectedEnv,
        test_case_ids: selectedCases,
        model: selectedModel,
        workers: workers,
        resolutions: selectedResolutions.length > 0 ? selectedResolutions : undefined,
      });

      // Create frontend execution object
      const batchExecution: BatchExecution = {
        id: execution.id,
        businessId: business.id,
        environmentId: selectedEnv,
        testCases: selectedCases,
        status: 'running',
        startTime: new Date().toISOString(),
        results: [],
      };

      onBatchExecute(batchExecution);
      setSelectedCases([]);
    } catch (err: any) {
      alert('执行失败: ' + (err.message || '未知错误'));
    } finally {
      setExecuting(false);
    }
  };

  const getStepDescription = (step: TestStep) => {
    if (!step) return '';

    if (step.step_type === 'action') {
      const desc = step.action?.description;
      // Ensure it's a string
      if (typeof desc === 'string') return desc;
      if (typeof desc === 'object' && desc !== null) {
        console.error('Action description is an object:', desc);
        return JSON.stringify(desc);
      }
      return '';
    } else if (step.step_type === 'switch_account') {
      return `切换账户: ${step.switch_account || ''}`;
    } else if (step.step_type === 'verify') {
      const assertion = step.verify?.assertion;
      // Ensure it's a string
      if (typeof assertion === 'string') return assertion;
      if (typeof assertion === 'object' && assertion !== null) {
        console.error('Verify assertion is an object:', assertion);
        return JSON.stringify(assertion);
      }
      return '';
    }
    return '';
  };

  const handleImportCases = (importedCases: TestCase[]) => {
    console.log('Importing cases:', importedCases);

    // Validate imported cases
    const validatedCases = importedCases.map(tc => {
      if (!tc || !tc.id || !tc.name) {
        console.error('Invalid test case:', tc);
        return null;
      }

      // Ensure steps is an array
      if (!Array.isArray(tc.steps)) {
        console.error('Test case has invalid steps:', tc);
        tc.steps = [];
      }

      // Validate each step
      tc.steps = tc.steps.map((step, idx) => {
        if (!step || !step.step_type) {
          console.error('Invalid step:', step);
          return null;
        }

        // Ensure description/assertion is a string, not an object
        if (step.step_type === 'action' && step.action) {
          if (typeof step.action.description === 'object') {
            console.error('Action description is an object:', step.action.description);
            const descObj = step.action.description as any;
            step.action.description = descObj.description || JSON.stringify(descObj);
          }
        }

        if (step.step_type === 'verify' && step.verify) {
          if (typeof step.verify.assertion === 'object') {
            console.error('Verify assertion is an object:', step.verify.assertion);
            const assertObj = step.verify.assertion as any;
            step.verify.assertion = assertObj.assertion || JSON.stringify(assertObj);
          }
        }

        return {
          ...step,
          id: step.id || crypto.randomUUID(),
          order: step.order || idx + 1,
        };
      }).filter(Boolean) as TestStep[];

      return tc;
    }).filter(Boolean) as TestCase[];

    console.log('Validated cases:', validatedCases);
    setTestCases([...testCases, ...validatedCases]);
  };

  const handleGlobalSave = async () => {
    // Prevent multiple simultaneous saves
    if (saving) return;

    setSaving(true);

    try {
      const parsedCases = parseGlobalYaml(globalYaml, business.id);

      // Build maps for diffing
      const currentMap = new Map(testCases.map(tc => [tc.name, tc]));
      const newMap = new Map(parsedCases.map(tc => [tc.name, tc]));

      // Find cases to delete (in old but not in new)
      const casesToDelete: string[] = [];
      for (const oldCase of testCases) {
        if (!newMap.has(oldCase.name)) {
          casesToDelete.push(oldCase.id);
        }
      }

      // 1. Delete removed cases
      for (const id of casesToDelete) {
        await apiClient.deleteTestCase(id);
      }

      // 2. Process all cases in YAML order, passing sort_order
      const newTestCasesList: TestCase[] = [];

      for (let i = 0; i < parsedCases.length; i++) {
        const tc = parsedCases[i];
        const sortOrder = i + 1;
        const existing = currentMap.get(tc.name);
        const apiSteps = stepsToApiFormat(tc.steps);

        let apiCase;
        if (existing) {
          apiCase = await apiClient.updateTestCase(existing.id, {
            name: tc.name,
            description: tc.description,
            login_required: tc.login_required,
            account: tc.account,
            version: tc.version,
            snapshot: tc.snapshot,
            use_snapshot: tc.use_snapshot,
            steps: apiSteps,
            sort_order: sortOrder,
          });
        } else {
          apiCase = await apiClient.createTestCase({
            business_id: tc.businessId,
            name: tc.name,
            description: tc.description,
            login_required: tc.login_required,
            account: tc.account,
            version: tc.version,
            snapshot: tc.snapshot,
            use_snapshot: tc.use_snapshot,
            steps: apiSteps,
          });
          apiCase = await apiClient.updateTestCase(apiCase.id, {
            sort_order: sortOrder,
          });
        }

        newTestCasesList.push(toFrontendTestCase(apiCase));
      }

      setTestCases(newTestCasesList);
      // Update global YAML to reflect saved data
      setGlobalYaml(testCasesToYaml(newTestCasesList));
      setGlobalYamlError(null);
      alert('全局修改已保存');

    } catch (err: any) {
      const errorMsg = err.message || '未知错误';
      setGlobalYamlError(errorMsg);
      alert('保存失败: ' + errorMsg);
    } finally {
      setSaving(false);
    }
  };

  const handleGlobalCancel = () => {
    setGlobalYaml(testCasesToYaml(testCases));
    setGlobalYamlError(null);
  };

  return (
    <div className="min-h-screen px-4 sm:px-6 py-4 sm:py-6 max-w-7xl mx-auto">
      {/* Layer 1: Navigation + Page Tabs */}
      <div className="mb-4">
        <div className="flex items-center justify-between border-b border-blue-100 bg-gradient-to-r from-white via-blue-50/40 to-purple-50/30">
          {/* Left: Breadcrumb */}
          <div className="flex items-center gap-2 pb-2.5">
            <button
              onClick={onBack}
              className="flex items-center gap-1.5 text-gray-500 hover:text-blue-700 transition-colors text-sm"
            >
              <ArrowLeft className="w-4 h-4" />
              返回
            </button>
            <span className="text-gray-300">/</span>
            <h1 className="text-xl font-semibold text-gray-900">{business.name}</h1>
          </div>

          {/* Right: Tabs + Management */}
          <div className="flex items-center">
            <button
              onClick={() => setActiveTab('cases')}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'cases'
                  ? 'border-blue-600 text-blue-700 bg-blue-50/70 rounded-t-md'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <FileText className="w-4 h-4" />
              测试用例
            </button>
            <button
              onClick={() => setActiveTab('schedules')}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'schedules'
                  ? 'border-blue-600 text-blue-700 bg-blue-50/70 rounded-t-md'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <Calendar className="w-4 h-4" />
              测试任务
            </button>
            <div className="w-px h-5 bg-gray-200 mx-2" />
            <button
              onClick={() => setActiveTab('settings')}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'settings'
                  ? 'border-blue-600 text-blue-700 bg-blue-50/70 rounded-t-md'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <Settings className="w-4 h-4" />
              设置
            </button>
          </div>
        </div>
      </div>

      {activeTab === 'cases' && (
        <>
          {/* Layer 2: Search/Filter + Management Actions */}
          <div className="mb-3">
            <div className="flex items-center gap-3">
              {/* View Mode Toggle */}
              <div className="flex bg-blue-50/60 border border-blue-100 p-1 rounded-lg flex-shrink-0">
                <button
                  onClick={() => setViewMode('cards')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-all ${
                    viewMode === 'cards' ? 'bg-white text-blue-700 border border-blue-200 shadow-sm' : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  <LayoutList className="w-4 h-4" />
                  卡片
                </button>
                <button
                  onClick={() => setViewMode('yaml')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-all ${
                    viewMode === 'yaml' ? 'bg-white text-blue-700 border border-blue-200 shadow-sm' : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  <Code className="w-4 h-4" />
                  YAML
                </button>
              </div>

              {/* Search + Filters: only in cards mode with test cases */}
              {viewMode === 'cards' && testCases.length > 0 && (
                <>
                  {/* Search */}
                  <div className="relative w-[200px] flex-shrink-0">
                    <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="搜索用例名称..."
                      className="w-full pl-9 pr-7 py-1.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-400 text-sm bg-white"
                    />
                    {searchQuery && (
                      <button
                        onClick={() => setSearchQuery('')}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>

                  {/* Filters with active state highlight */}
                  <select
                    value={filterLogin}
                    onChange={(e) => setFilterLogin(e.target.value as any)}
                    className={`px-3 py-1.5 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm flex-shrink-0 cursor-pointer ${
                      filterLogin !== 'all' ? 'border-blue-300 text-blue-700 bg-blue-50' : 'border-gray-300 text-gray-600'
                    }`}
                  >
                    <option value="all">登录状态: 全部</option>
                    <option value="required">需要登录</option>
                    <option value="not_required">无需登录</option>
                  </select>

                  <select
                    value={filterSnapshot}
                    onChange={(e) => setFilterSnapshot(e.target.value as any)}
                    className={`px-3 py-1.5 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm flex-shrink-0 cursor-pointer ${
                      filterSnapshot !== 'all' ? 'border-blue-300 text-blue-700 bg-blue-50' : 'border-gray-300 text-gray-600'
                    }`}
                  >
                    <option value="all">快照状态: 全部</option>
                    <option value="has_snapshot">创建快照</option>
                    <option value="use_snapshot">使用快照</option>
                    <option value="none">无快照</option>
                  </select>

                  <select
                    value={filterVersion}
                    onChange={(e) => setFilterVersion(e.target.value)}
                    className={`px-3 py-1.5 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm flex-shrink-0 cursor-pointer ${
                      filterVersion !== 'all' ? 'border-blue-300 text-blue-700 bg-blue-50' : 'border-gray-300 text-gray-600'
                    }`}
                  >
                    <option value="all">用例版本: 全部</option>
                    <option value="">未设置版本</option>
                    {availableVersions.map(v => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                  </select>

                  {/* Match count + clear filters */}
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <span className="text-xs text-gray-500 whitespace-nowrap tabular-nums">
                      {filteredTestCases.length}/{testCases.length}
                    </span>
                    {hasActiveFilters && (
                      <button
                        onClick={clearAllFilters}
                        className="p-0.5 text-gray-400 hover:text-gray-600 rounded transition-colors"
                        title="清除筛选"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </>
              )}

              {/* Spacer */}
              <div className="flex-1" />

              {/* Import/Export YAML - only in yaml mode */}
              {viewMode === 'yaml' && (
                <button
                  onClick={() => setShowConfigModal(true)}
                  className="flex items-center justify-center gap-2 px-3 py-1.5 bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 border border-blue-200 transition-colors text-sm font-medium flex-shrink-0"
                >
                  <Download className="w-4 h-4 text-blue-600" />
                  导入/导出 YAML
                </button>
              )}

              {/* Create button - only in cards mode */}
              {viewMode === 'cards' && (
                <button
                  onClick={() => navigate(`/business/${business.id}/case/new`)}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium flex-shrink-0"
                >
                  <Plus className="w-4 h-4" />
                  创建用例
                </button>
              )}
            </div>
          </div>

          {/* Layer 3: Selection + Execution */}
          {testCases.length > 0 && viewMode === 'cards' && (
            <div className="bg-white rounded-lg border border-gray-200 px-4 py-2.5 mb-3">
              <div className="flex items-center gap-3">
                {/* Select all */}
                <label className="flex items-center gap-2 flex-shrink-0 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={filteredTestCases.length > 0 && filteredTestCases.every(tc => selectedCases.includes(tc.id))}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedCases(prev => {
                          const filteredIds = new Set(filteredTestCases.map(tc => tc.id));
                          const merged = new Set([...prev, ...filteredIds]);
                          return Array.from(merged);
                        });
                      } else {
                        setSelectedCases(prev => {
                          const filteredIds = new Set(filteredTestCases.map(tc => tc.id));
                          return prev.filter(id => !filteredIds.has(id));
                        });
                      }
                    }}
                    className="w-4 h-4 rounded border-gray-300"
                  />
                  <span className="text-sm text-gray-600">全选</span>
                </label>

                {/* Selection count - fixed width to prevent layout shift */}
                <span className="text-sm text-gray-500 min-w-[110px]">
                  {selectedCases.length > 0 ? `已选 ${selectedCases.length} 个用例` : '未选择用例'}
                </span>

                {/* Batch delete */}
                {selectedCases.length > 0 && (
                  <button
                    onClick={handleBatchDelete}
                    disabled={batchDeleting}
                    className="flex items-center gap-1 px-2 py-1.5 text-red-600 hover:bg-red-50 rounded-lg transition-colors text-xs flex-shrink-0"
                    title={`删除选中的 ${selectedCases.length} 个用例`}
                  >
                    {batchDeleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4 text-red-600" />}
                    <span>删除({selectedCases.length})</span>
                  </button>
                )}

                {/* Spacer */}
                <div className="flex-1" />

                {/* Execute section */}
                <select
                  value={selectedEnv}
                  onChange={(e) => setSelectedEnv(e.target.value)}
                  className={`px-3 py-1.5 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm flex-shrink-0 ${
                    selectedEnv
                      ? 'border-blue-200 bg-blue-50 text-blue-700'
                      : 'border-gray-300 bg-white text-gray-600'
                  }`}
                >
                  <option value="">选择环境</option>
                  {business.environments.map(env => (
                    <option key={env.id} value={env.id}>{env.name}</option>
                  ))}
                </select>

                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="px-3 py-1.5 border border-blue-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm flex-shrink-0 bg-blue-50 text-blue-700 max-w-[180px]"
                >
                  {availableModels.models.map(model => (
                    <option key={model} value={model}>{model}</option>
                  ))}
                </select>

                <select
                  value={workers}
                  onChange={(e) => setWorkers(parseInt(e.target.value))}
                  className="px-3 py-1.5 border border-blue-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm flex-shrink-0 bg-blue-50 text-blue-700"
                >
                  {[1, 2, 3, 4, 5].map(n => (
                    <option key={n} value={n}>并发 {n}</option>
                  ))}
                </select>

                <ResolutionSelector
                  selectedResolutions={selectedResolutions}
                  onChange={setSelectedResolutions}
                  className="w-40 px-3 py-1.5 border border-blue-200 rounded-lg text-sm flex-shrink-0 bg-blue-50 text-blue-700"
                  style={{ minWidth: '160px' }}
                />

                <button
                  onClick={handleBatchRun}
                  disabled={selectedCases.length === 0 || !selectedEnv || executing}
                  className="flex items-center justify-center gap-2 px-4 py-1.5 bg-green-50 text-green-700 rounded-lg hover:bg-green-100 border border-green-200 disabled:bg-gray-100 disabled:text-gray-400 disabled:border-gray-200 disabled:cursor-not-allowed transition-colors text-sm font-medium flex-shrink-0"
                  title={!selectedEnv ? '请先选择执行环境' : selectedCases.length === 0 ? '请先选择测试用例' : ''}
                >
                  {executing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                  {executing ? '执行中...' : '执行'}
                </button>
              </div>
            </div>
          )}

            {/* Cards View */}
            {viewMode === 'cards' && (
              <>
              {testCases.length === 0 && (
                <div className="text-center py-12 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-lg border border-blue-100 border-dashed">
                    <FileText className="w-12 h-12 text-blue-300 mx-auto mb-4" />
                    <p className="text-gray-500 mb-4">还没有测试用例</p>
                    <button
                    onClick={() => navigate(`/business/${business.id}/case/new`)}
                    className="text-blue-600 hover:text-blue-700 font-medium"
                    >
                    创建第一个测试用例
                    </button>
                </div>
              )}

              {testCases.length > 0 && filteredTestCases.length === 0 && (
                <div className="text-center py-8 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-lg border border-blue-100 border-dashed">
                    <p className="text-gray-500">没有符合筛选条件的用例</p>
                </div>
              )}

              <DndContext sensors={caseSensors} collisionDetection={closestCenter} onDragEnd={handleCaseDragEnd}>
                <SortableContext items={filteredTestCases.map(tc => tc.id)} strategy={rectSortingStrategy}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {filteredTestCases.map((testCase) => {
                  // Defensive check: ensure steps is an array
                  if (!Array.isArray(testCase.steps)) {
                    console.error('Invalid testCase.steps:', testCase);
                    return null;
                  }
                  return (
                <SortableCaseCard key={testCase.id} id={testCase.id}>
                  {({ dragHandleProps }) => (
                <div
                    className="group bg-white rounded-lg border border-gray-200 hover:border-blue-200 hover:shadow-sm transition-all h-full flex"
                >
                    {/* Drag handle — left edge strip */}
                    <button
                      type="button"
                      className="cursor-grab active:cursor-grabbing text-gray-300 hover:text-blue-500 hover:bg-blue-50/60 touch-none flex items-center px-1.5 flex-shrink-0 rounded-l-lg transition-colors"
                      {...dragHandleProps}
                    >
                      <GripVertical className="w-4 h-4" />
                    </button>

                    {/* Card content */}
                    <div className="flex-1 min-w-0 p-4 flex flex-col overflow-hidden">
                        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-3">
                        <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 mb-1">
                              <input
                                type="checkbox"
                                checked={selectedCases.includes(testCase.id)}
                                onChange={() => toggleCaseSelection(testCase.id)}
                                className="w-4 h-4 rounded border-gray-300 flex-shrink-0"
                              />
                              <h3 className="truncate text-base font-semibold text-gray-800">
                                {testCase.name}
                              </h3>
                            </div>
                            {testCase.description && (
                              <p className="text-sm text-gray-600 line-clamp-2">{testCase.description}</p>
                            )}
                            <div className="flex items-center gap-2 mt-2 flex-wrap">
                              <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); handleToggleLoginRequired(testCase, e as any); }}
                                title={testCase.login_required ? '点击关闭登录' : '点击开启登录'}
                                className={`px-2 py-1.5 rounded-lg text-xs font-medium flex-shrink-0 border transition-colors ${
                                  testCase.login_required
                                    ? 'bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100'
                                    : 'bg-white text-blue-600 border-blue-200 hover:bg-blue-50'
                                }`}
                              >
                                {testCase.login_required ? '🔑 需登录' : '🔓 免登录'}
                              </button>
                              {testCase.version && (
                                <span className="px-2 py-1.5 bg-purple-50 text-purple-700 rounded-lg text-xs font-medium flex-shrink-0 border border-purple-200">
                                  🏷️ {testCase.version}
                                </span>
                              )}
                              {testCase.snapshot && (
                                <span className="px-2 py-1.5 text-gray-700 rounded-lg text-xs font-medium flex-shrink-0 border border-gray-300">
                                  📸 快照: {testCase.snapshot}
                                </span>
                              )}
                              {testCase.use_snapshot && (
                                <span className="px-2 py-1.5 text-gray-700 rounded-lg text-xs font-medium flex-shrink-0 border border-gray-300">
                                  🔄 使用: {testCase.use_snapshot}
                                </span>
                              )}
                            </div>
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                            <button
                            onClick={() => handleEdit(testCase)}
                            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
                            title="编辑"
                            >
                            <Edit className="w-4 h-4 text-gray-600" />
                            </button>
                            <button
                            onClick={() => handleDelete(testCase.id)}
                            className="p-2 hover:bg-red-50 rounded-lg transition-colors"
                            title="删除"
                            >
                            <Trash2 className="w-4 h-4 text-red-600" />
                            </button>
                        </div>
                        </div>

                        <div className="bg-gray-50 rounded-lg p-3 sm:p-4 flex-1">
                        <div className="flex items-center gap-2 mb-3 text-sm text-gray-600">
                            <FileText className="w-4 h-4 text-blue-600" />
                            <span>测试步骤 ({testCase.steps?.length || 0})</span>
                        </div>
                        <div className="space-y-2">
                            {(testCase.steps || []).slice(0, 3).map((step) => {
                              if (!step || !step.id) return null;
                              const filePath = step.step_type === 'action' && step.action?.args?.file_path;
                              const fileCount = filePath ? (Array.isArray(filePath) ? filePath.length : 1) : 0;

                              return (
                            <div key={step.id} className="flex items-center gap-3 text-sm">
                                <span className="w-6 h-6 bg-white rounded-full border border-gray-200 flex items-center justify-center text-gray-600 flex-shrink-0 text-xs font-medium">
                                {step.order || 0}
                                </span>
                                <span className="text-gray-700 flex-1 truncate">{getStepDescription(step)}</span>
                                <div className="flex items-center gap-2 flex-shrink-0">
                                  {fileCount > 0 && (
                                    <span className="px-1.5 py-0.5 text-xs bg-orange-100 text-orange-700 rounded">
                                      📎 {fileCount}
                                    </span>
                                  )}
                                  <span className="text-gray-400 text-xs">({step.step_type || 'unknown'})</span>
                                </div>
                            </div>
                              );
                            })}
                            {(testCase.steps?.length || 0) > 3 && (
                            <p className="text-sm text-gray-500 pl-9">
                                还有 {(testCase.steps?.length || 0) - 3} 个步骤...
                            </p>
                            )}
                        </div>
                        </div>
                    </div>
                </div>
                  )}
                </SortableCaseCard>
                  );
                }).filter(Boolean)}

              </div>
                </SortableContext>
              </DndContext>
              </>
            )}

            {/* Global YAML View */}
            {viewMode === 'yaml' && (
              <div className="bg-slate-900 rounded-xl border border-slate-700 overflow-hidden">
                {/* Header with Save/Cancel buttons */}
                <div className="px-4 py-3 bg-slate-800 border-b border-slate-700 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-2">
                      <Code className="w-4 h-4 text-emerald-400" />
                      <span className="font-medium text-slate-200">全局 YAML 编辑</span>
                    </div>
                    <span className="text-sm text-slate-400">({testCases.length} 个用例)</span>
                    {globalYamlError ? (
                      <span className="text-xs text-red-400 flex items-center gap-1 bg-red-900/30 px-2 py-1 rounded">
                        <AlertCircle className="w-3 h-3" />
                        {globalYamlError}
                      </span>
                    ) : (
                      <span className="text-xs text-emerald-400 bg-emerald-900/30 px-2 py-1 rounded">✓ 有效</span>
                    )}
                  </div>
                  <button
                    onClick={handleGlobalSave}
                    disabled={saving || !!globalYamlError}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                    {saving ? '保存中...' : '保存'}
                  </button>
                </div>

                {/* YAML Editor */}
                <div className="p-4">
                  <textarea
                    value={globalYaml}
                    onChange={(e) => {
                      const newYaml = e.target.value;
                      setGlobalYaml(newYaml);
                      // Real-time validation
                      try {
                        parseGlobalYaml(newYaml, business.id);
                        setGlobalYamlError(null);
                      } catch (err: any) {
                        setGlobalYamlError(err.message || 'YAML 格式错误');
                      }
                    }}
                    className={`w-full bg-transparent font-mono text-sm leading-relaxed focus:outline-none resize-none ${
                      globalYamlError ? 'text-red-400' : 'text-emerald-300'
                    }`}
                    style={{ height: '500px' }}
                    placeholder={`cases:
  - name: 用例名称
    login_required: false
    steps:
      - action: 操作描述
      - verify: 验证描述`}
                    spellCheck={false}
                  />
                </div>
              </div>
            )}
        </>
      )}

      {activeTab === 'schedules' && (
        <>
        <div className="flex justify-end mb-3">
          <button
            onClick={() => setScheduleCreateOpen(true)}
            className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
          >
            <Plus className="w-4 h-4" />
            创建任务
          </button>
        </div>
        <ScheduledTaskManager
            businessId={business.id}
            businessName={business.name}
            environments={business.environments}
            testCases={testCases}
            showHeader={false}
            showCreateButton={false}
            availableModels={availableModels}
            openCreateModal={scheduleCreateOpen}
            onCreateModalClose={() => setScheduleCreateOpen(false)}
        />
        </>
      )}

      {activeTab === 'settings' && (
        <div className="space-y-4">
          {/* 环境配置 */}
          <div className="bg-white rounded-lg border border-gray-200">
            <div style={{ padding: '24px 28px' }}>
              <BusinessManager
                businesses={[business]}
                setBusinesses={(updatedList) => {
                  onBusinessUpdate(updatedList[0]);
                }}
                onSelectBusiness={() => {}}
                initialEditId={business.id}
                inline={true}
              />
            </div>
          </div>

          {/* 文件管理 */}
          <div className="bg-white rounded-lg border border-gray-200">
            <div style={{ padding: '24px 28px' }}>
              <h3 className="text-sm text-gray-700 mb-3">文件管理</h3>
              <FileManager
                businessId={business.id}
                files={businessFiles}
                onFilesChange={(files) => {
                  setBusinessFiles(files);
                  onBusinessUpdate({ ...business, files });
                }}
                inline={true}
              />
            </div>
          </div>
        </div>
      )}

      {/* TestCase Modal - Left-Right Split Layout */}
      {showModal && activeTab === 'cases' && (
        <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ backgroundColor: 'rgba(0, 0, 0, 0.75)' }}>
          <div className="bg-white rounded-lg flex flex-col shadow-2xl" style={{ width: '960px', maxWidth: '90vw', height: '600px', maxHeight: 'calc(100vh - 64px)' }}>
            <div className="border border-gray-200 rounded-lg flex flex-col flex-1 min-h-0 overflow-hidden">
              {/* Header */}
              <div className="border-b border-gray-200 flex-shrink-0" style={{ padding: '16px 28px' }}>
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-gray-900">{editingCase ? '编辑测试用例' : '创建测试用例'}</h2>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => {
                        setShowModal(false);
                        resetForm();
                      }}
                      className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium"
                    >
                      关闭
                    </button>
                    <button
                      onClick={handleModalYamlSave}
                      disabled={saving || !!modalYamlError}
                      className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {saving && <Loader2 className="w-4 h-4 animate-spin mr-2 inline-block" />}
                      保存
                    </button>
                  </div>
                </div>
                {error && (
                  <div className="mt-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    <span>{error}</span>
                  </div>
                )}
              </div>

              {/* Main Content - Split View */}
              <div className="flex flex-1 overflow-hidden">
              {/* Left Panel - Form Editor */}
              <div className="flex-1 flex flex-col border-r border-gray-200 bg-gray-50 overflow-hidden">
                {/* Left Panel Header */}
                <div className="px-4 py-2 border-b border-gray-200 flex items-center gap-2 bg-white flex-shrink-0">
                  <LayoutList className="w-4 h-4 text-blue-600" />
                  <span className="text-sm font-medium text-gray-700">表单编辑</span>
                </div>

                {/* Left Panel Content */}
                <div className="flex-1 p-4 overflow-y-auto">
                  <div className="space-y-4">
                    {/* Name */}
                    <div>
                      <label className="block text-sm font-medium mb-1.5 text-gray-700">
                        用例名称 *
                      </label>
                      <input
                        type="text"
                        required
                        value={formData.name}
                        onChange={(e) => updateFormData({ ...formData, name: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm bg-white"
                        placeholder="例如：登录校验-登录按钮"
                      />
                    </div>

                    {/* Login Required */}
                    <label className="flex items-center gap-2 cursor-pointer p-2 rounded-lg hover:bg-white">
                      <input
                        type="checkbox"
                        checked={formData.login_required ?? false}
                        onChange={(e) => updateFormData({ ...formData, login_required: e.target.checked })}
                        className="w-4 h-4 rounded border-gray-300 text-amber-600 focus:ring-amber-500"
                      />
                      <Key className="w-4 h-4 text-amber-500" />
                      <span className="text-sm text-gray-700">需要登录</span>
                    </label>

                    {/* Snapshot Configuration */}
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-sm font-medium mb-1.5 text-gray-700">
                          创建快照 (Snapshot)
                        </label>
                        <input
                          type="text"
                          value={formData.snapshot || ''}
                          onChange={(e) => updateFormData({ ...formData, snapshot: e.target.value })}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm bg-white"
                          placeholder="例如：global_before"
                        />
                        <p className="mt-1 text-xs text-gray-500">此用例执行后创建快照</p>
                      </div>
                      <div>
                        <label className="block text-sm font-medium mb-1.5 text-gray-700">
                          使用快照 (Use Snapshot)
                        </label>
                        <input
                          type="text"
                          value={formData.use_snapshot || ''}
                          onChange={(e) => updateFormData({ ...formData, use_snapshot: e.target.value })}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm bg-white"
                          placeholder="例如：global_before"
                        />
                        <p className="mt-1 text-xs text-gray-500">从指定快照开始执行</p>
                      </div>
                    </div>

                    {/* Steps */}
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <label className="text-sm font-medium text-gray-700">
                          测试步骤 *
                        </label>
                        <button
                          type="button"
                          onClick={addStep}
                          className="text-xs text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1"
                        >
                          + 添加
                        </button>
                      </div>

                      <div className="space-y-2">
                        {formData.steps!.map((step, index) => (
                          <div key={step.id} className="border border-gray-200 rounded-lg p-3 bg-white">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="w-5 h-5 bg-blue-600 text-white rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0">
                                {step.order}
                              </span>
                              <select
                                value={step.step_type}
                                onChange={(e) => updateStepType(index, e.target.value as 'action' | 'verify')}
                                className={`px-2 py-0.5 rounded text-xs font-medium border-0 cursor-pointer ${
                                  step.step_type === 'action'
                                    ? 'bg-blue-100 text-blue-700'
                                    : 'bg-purple-100 text-purple-700'
                                }`}
                              >
                                <option value="action">Action</option>
                                <option value="verify">Verify</option>
                              </select>

                              {formData.steps!.length > 1 && (
                                <button
                                  type="button"
                                  onClick={() => removeStep(index)}
                                  className="ml-auto p-1.5 hover:bg-red-50 rounded-lg transition-colors"
                                  title="删除步骤"
                                >
                                  <Trash2 className="w-4 h-4 text-red-600" />
                                </button>
                              )}
                            </div>

                            <textarea
                              required
                              value={step.step_type === 'action' ? step.action?.description || '' : step.verify?.assertion || ''}
                              onChange={(e) => updateStepDescription(index, e.target.value)}
                              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono resize-y"
                              placeholder={step.step_type === 'action' ? '操作描述（支持多行文本）' : '验证条件'}
                              rows={3}
                            />

                            <div className="mt-2 flex items-center gap-2 flex-wrap">
                              <button
                                type="button"
                                onClick={() => toggleArgs(step.id)}
                                className={`text-xs px-2 py-1 rounded ${
                                  expandedArgs[step.id]
                                    ? 'bg-purple-100 text-purple-700'
                                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                                }`}
                              >
                                {expandedArgs[step.id] ? '▼ 参数' : '▶ 参数'}
                              </button>
                              {step.step_type === 'action' && step.action?.args?.file_path && (() => {
                                const fp = step.action.args.file_path;
                                const fileCount = Array.isArray(fp) ? fp.length : 1;
                                return (
                                  <span className="px-2 py-0.5 text-xs bg-orange-100 text-orange-700 rounded">
                                    📎 {fileCount > 1 ? `${fileCount} 个文件` : ''}
                                  </span>
                                );
                              })()}
                              {step.step_type === 'verify' && step.verify?.args?.use_context && (
                                <span className="px-2 py-0.5 text-xs bg-purple-100 text-purple-700 rounded">🔗</span>
                              )}
                            </div>

                            {expandedArgs[step.id] && (
                              <div className="mt-2 bg-gray-50 rounded p-2">
                                {step.step_type === 'action' && (
                                  <div className="space-y-2">
                                    <div className="text-xs text-gray-600 font-medium mb-1">选择上传文件（可多选）:</div>
                                    {businessFiles.length === 0 ? (
                                      <div className="text-xs text-gray-400 italic">暂无可用文件，请先在业务管理中上传文件</div>
                                    ) : (
                                      <div className="space-y-1 max-h-40 overflow-y-auto">
                                        {businessFiles.map(file => {
                                          const currentFiles = (() => {
                                            const fp = step.action?.args?.file_path;
                                            if (!fp) return [];
                                            if (Array.isArray(fp)) return fp;
                                            return [fp];
                                          })();
                                          const isChecked = currentFiles.includes(file.name);

                                          return (
                                            <label
                                              key={file.id}
                                              className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer hover:bg-gray-100 p-1 rounded"
                                            >
                                              <input
                                                type="checkbox"
                                                checked={isChecked}
                                                onChange={(e) => {
                                                  const currentFiles = (() => {
                                                    const fp = step.action?.args?.file_path;
                                                    if (!fp) return [];
                                                    if (Array.isArray(fp)) return fp;
                                                    return [fp];
                                                  })();

                                                  let newFiles: string[];
                                                  if (e.target.checked) {
                                                    newFiles = [...currentFiles, file.name];
                                                  } else {
                                                    newFiles = currentFiles.filter(f => f !== file.name);
                                                  }

                                                  // If only one file, store as string for backward compatibility
                                                  // If multiple files, store as array
                                                  const valueToStore = newFiles.length === 0 ? '' :
                                                                      newFiles.length === 1 ? newFiles[0] :
                                                                      newFiles;
                                                  updateStepArg(index, 'file_path', valueToStore);
                                                }}
                                                className="w-3.5 h-3.5 rounded border-gray-300 text-blue-600"
                                              />
                                              <span className="flex-1">{file.name}</span>
                                            </label>
                                          );
                                        })}
                                      </div>
                                    )}
                                    {(() => {
                                      const fp = step.action?.args?.file_path;
                                      const selectedCount = !fp ? 0 : Array.isArray(fp) ? fp.length : 1;
                                      return selectedCount > 0 ? (
                                        <div className="text-xs text-blue-600 font-medium pt-1 border-t border-gray-200">
                                          已选择 {selectedCount} 个文件
                                        </div>
                                      ) : null;
                                    })()}
                                  </div>
                                )}
                                {step.step_type === 'verify' && (
                                  <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
                                    <input
                                      type="checkbox"
                                      checked={step.verify?.args?.use_context || false}
                                      onChange={(e) => updateStepArg(index, 'use_context', e.target.checked)}
                                      className="w-3.5 h-3.5 rounded border-gray-300 text-blue-600"
                                    />
                                    使用上下文验证
                                  </label>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Right Panel - YAML Editor */}
              <div className="flex-1 flex flex-col bg-slate-900 overflow-hidden">
                {/* Right Panel Header with Save/Cancel */}
                <div className="px-4 py-2 bg-slate-800 border-b border-slate-700 flex items-center justify-between flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <Code className="w-4 h-4 text-emerald-400" />
                    <span className="text-sm font-medium text-slate-200">YAML 编辑</span>
                    {modalYamlError ? (
                      <span className="text-xs text-red-400 flex items-center gap-1">
                        <AlertCircle className="w-3 h-3" /> 格式错误
                      </span>
                    ) : (
                      <span className="text-xs text-emerald-400">✓ 有效</span>
                    )}
                  </div>
                </div>

                {/* YAML Content */}
                <div className="flex-1 p-4 overflow-auto">
                  <textarea
                    value={modalYaml}
                    onChange={(e) => handleModalYamlChange(e.target.value)}
                    className={`w-full h-full bg-transparent font-mono text-sm leading-relaxed focus:outline-none resize-none ${
                      modalYamlError ? 'text-red-400' : 'text-emerald-300'
                    }`}
                    spellCheck={false}
                    placeholder={`# 格式1（推荐）：
name: 用例名称
login_required: false
snapshot: global_before
use_snapshot: global_before
steps:
  - action: 点击按钮
  - verify: 验证结果
  - action: 上传文件
    args:
      file_path: ./file.pdf

# 格式2（也支持）：
- name: 用例名称
  login_required: false
  use_snapshot: global_before
  steps:
    - action: 点击按钮
    - verify: 验证结果`}
                  />
                </div>
              </div>
              </div>
            </div>

          </div>
        </div>
      )}

      {/* Config Modal */}
      {showConfigModal && (
        <ConfigImportExport
          business={business}
          testCases={testCases}
          onImport={handleImportCases}
          onClose={() => setShowConfigModal(false)}
        />
      )}


    </div>
  );
}
