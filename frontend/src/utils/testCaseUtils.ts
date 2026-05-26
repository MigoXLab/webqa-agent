/**
 * Shared utilities for test case YAML conversion, API format mapping,
 * and frontend/API type conversion.
 *
 * Used by TestCaseManager.tsx, CaseEditorPage.tsx, and App.tsx.
 */
import yaml from 'js-yaml';
import { TestCase, TestStep } from '../App';
import { TestCase as APITestCase, TestStep as APITestStep } from '../api/client';

// ============================================================================
// YAML Helpers
// ============================================================================

/**
 * Validate YAML syntax using js-yaml.
 */
export function validateYamlSyntax(yamlText: string): { valid: boolean; error: string | null } {
  try {
    yaml.load(yamlText);
    return { valid: true, error: null };
  } catch (err: any) {
    const match = err.message?.match(/at line (\d+)/);
    const lineInfo = match ? ` (第 ${match[1]} 行)` : '';
    return {
      valid: false,
      error: `YAML 格式错误${lineInfo}: ${err.reason || err.message}`,
    };
  }
}

/**
 * Convert YAML block-style file_path arrays to flow-style [a, b].
 */
export function convertArraysToFlowStyle(yamlText: string): string {
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
        if (itemMatch) {
          items.push(itemMatch[1].trim());
          j++;
        } else {
          break;
        }
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
}

// ============================================================================
// Step Conversion Helpers
// ============================================================================

/**
 * Filter args, removing empty/null values.
 * Handles file_path comma-separated string to array conversion.
 */
function filterStepArgs(args: Record<string, any>, isAction: boolean): Record<string, any> | undefined {
  const filtered: Record<string, any> = {};
  for (const [key, value] of Object.entries(args)) {
    if (value === undefined || value === null) continue;
    if (isAction && value === '') continue;
    if (!isAction && String(value) === '') continue;

    if (isAction && key === 'file_path' && typeof value === 'string' && value.includes(',')) {
      filtered[key] = value.split(',').map((item: string) => item.trim());
    } else {
      filtered[key] = value;
    }
  }
  return Object.keys(filtered).length > 0 ? filtered : undefined;
}

/**
 * Convert a single frontend TestStep to a YAML-compatible plain object.
 */
function stepToYamlObj(step: TestStep): Record<string, any> {
  if (step.step_type === 'action') {
    const obj: any = { action: step.action?.description || '' };
    if (step.action?.args && Object.keys(step.action.args).length > 0) {
      const filtered = filterStepArgs(step.action.args, true);
      if (filtered) obj.args = filtered;
    }
    return obj;
  }

  if (step.step_type === 'switch_account') {
    return { switch_account: step.switch_account || '' };
  }

  // verify
  const obj: any = { verify: step.verify?.assertion || '' };
  if (step.verify?.args && Object.keys(step.verify.args).length > 0) {
    const filtered = filterStepArgs(step.verify.args, false);
    if (filtered) obj.args = filtered;
  }
  return obj;
}

// ============================================================================
// Form <-> YAML Conversion
// ============================================================================

/**
 * Convert form data (single test case) to YAML string.
 */
export function formToYaml(formData: Partial<TestCase>): string {
  const obj: any = {
    name: formData.name || '',
    login_required: formData.login_required ?? false,
  };

  if (formData.account) obj.account = formData.account;
  if (formData.description) obj.description = formData.description;
  if (formData.version) obj.version = formData.version;
  if (formData.snapshot) obj.snapshot = formData.snapshot;
  if (formData.use_snapshot) obj.use_snapshot = formData.use_snapshot;

  obj.steps = formData.steps?.map(stepToYamlObj) || [];

  const yamlText = yaml.dump([obj], { lineWidth: -1, noRefs: true });
  return convertArraysToFlowStyle(yamlText);
}

/**
 * Parse YAML string into form data (single test case).
 */
export function yamlToForm(yamlText: string): { data: Partial<TestCase> | null; error: string | null } {
  const syntaxCheck = validateYamlSyntax(yamlText);
  if (!syntaxCheck.valid) return { data: null, error: syntaxCheck.error };

  try {
    let parsed: any = yaml.load(yamlText);

    if (!parsed || typeof parsed !== 'object') {
      return { data: null, error: 'YAML 格式错误: 必须是一个对象或数组' };
    }

    if (Array.isArray(parsed)) {
      if (parsed.length === 0) return { data: null, error: 'YAML 格式错误: 数组不能为空' };
      if (parsed.length > 1) return { data: null, error: 'YAML 格式错误: 单个用例编辑器只能包含一个测试用例' };
      parsed = parsed[0];
    }

    const result: Partial<TestCase> = {
      name: parsed.name || '',
      description: parsed.description || '',
      login_required: parsed.login_required ?? false,
      account: parsed.account,
      version: parsed.version,
      snapshot: parsed.snapshot,
      use_snapshot: parsed.use_snapshot,
      status: 'active',
      steps: [],
    };

    if (!Array.isArray(parsed.steps)) {
      return { data: null, error: 'YAML 格式错误: steps 必须是一个列表' };
    }

    result.steps = parseYamlSteps(parsed.steps);

    if (!result.name || result.name.trim() === '') {
      return { data: null, error: '用例名称不能为空' };
    }

    const validSteps = result.steps.filter(isStepValid);
    if (validSteps.length === 0) {
      return { data: null, error: '至少需要一个有效的测试步骤' };
    }

    result.steps = validSteps;
    return { data: result, error: null };
  } catch (err) {
    return { data: null, error: 'YAML 解析失败: ' + (err as Error).message };
  }
}

// ============================================================================
// Step Parsing & Validation
// ============================================================================

/**
 * Parse raw YAML step objects into typed TestStep array.
 */
export function parseYamlSteps(rawSteps: any[]): TestStep[] {
  const steps: TestStep[] = [];
  for (const rawStep of rawSteps) {
    if (!rawStep || typeof rawStep !== 'object') continue;

    let step_type: 'action' | 'verify' | 'switch_account' | null = null;
    let description: string | undefined;
    let assertion: string | undefined;
    let switchAccountTarget: string | undefined;
    let args: Record<string, any> | undefined;

    if (rawStep.action !== undefined) {
      step_type = 'action';
      description = String(rawStep.action);
      args = rawStep.args;
    } else if (rawStep.verify !== undefined) {
      step_type = 'verify';
      assertion = String(rawStep.verify);
      args = rawStep.args;
    } else if (rawStep.switch_account !== undefined) {
      step_type = 'switch_account';
      switchAccountTarget = String(rawStep.switch_account);
    }

    if (!step_type) continue;

    steps.push({
      id: crypto.randomUUID(),
      order: steps.length + 1,
      step_type,
      action: step_type === 'action' ? { description: description || '', args } : undefined,
      verify: step_type === 'verify' ? { assertion: assertion || '', args } : undefined,
      switch_account: step_type === 'switch_account' ? switchAccountTarget : undefined,
    });
  }
  return steps;
}

/**
 * Check whether a step has non-empty content.
 */
export function isStepValid(step: TestStep): boolean {
  if (step.step_type === 'action') {
    return !!(step.action?.description?.trim());
  }
  if (step.step_type === 'switch_account') {
    return !!(step.switch_account?.trim());
  }
  return !!(step.verify?.assertion?.trim());
}

// ============================================================================
// Frontend <-> API Type Conversion
// ============================================================================

/**
 * Convert frontend TestStep[] to the flat API step format used by createTestCase/updateTestCase.
 */
export function stepsToApiFormat(steps: TestStep[]): APITestStep[] {
  return steps.map(step => ({
    step_type: step.step_type,
    description: step.step_type === 'action' ? step.action?.description : undefined,
    assertion: step.step_type === 'verify' ? step.verify?.assertion : undefined,
    switch_account: step.step_type === 'switch_account' ? step.switch_account : undefined,
    args: step.step_type === 'action'
      ? step.action?.args
      : step.step_type === 'verify'
        ? step.verify?.args
        : undefined,
  }));
}

/**
 * Convert an API TestCase response to the frontend TestCase type.
 *
 * Handles malformed data where description/assertion might be nested objects.
 */
export function toFrontendTestCase(apiCase: APITestCase): TestCase {
  return {
    id: apiCase.id,
    businessId: apiCase.business_id,
    name: apiCase.name,
    description: apiCase.description || '',
    login_required: apiCase.login_required ?? false,
    account: apiCase.account,
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
      } else if (step.step_type === 'verify') {
        assertion = step.assertion || '';
      }

      return {
        id: crypto.randomUUID(),
        order: idx + 1,
        step_type: step.step_type,
        action: step.step_type === 'action' ? { description, args } : undefined,
        verify: step.step_type === 'verify' ? { assertion, args } : undefined,
        switch_account: step.step_type === 'switch_account' ? (step.switch_account || '') : undefined,
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
// Multi-case YAML Conversion (used by TestCaseManager global YAML view)
// ============================================================================

/**
 * Convert all test cases to a global YAML string (cases: [...] format).
 */
export function testCasesToYaml(cases: TestCase[]): string {
  const obj = {
    cases: cases.map(tc => {
      const caseObj: any = {
        name: tc.name,
        login_required: tc.login_required ?? false,
      };
      if (tc.account) caseObj.account = tc.account;
      if (tc.description) caseObj.description = tc.description;
      if (tc.version) caseObj.version = tc.version;
      if (tc.snapshot) caseObj.snapshot = tc.snapshot;
      if (tc.use_snapshot) caseObj.use_snapshot = tc.use_snapshot;
      caseObj.steps = tc.steps.map(stepToYamlObj);
      return caseObj;
    }),
  };
  const yamlText = yaml.dump(obj, { lineWidth: -1, noRefs: true });
  return convertArraysToFlowStyle(yamlText);
}

/**
 * Parse a global YAML string (cases: [...]) into TestCase[].
 */
export function parseGlobalYaml(yamlText: string, businessId: string): TestCase[] {
  const syntaxCheck = validateYamlSyntax(yamlText);
  if (!syntaxCheck.valid) {
    throw new Error(syntaxCheck.error || 'YAML 语法错误');
  }

  try {
    const parsed: any = yaml.load(yamlText);
    if (!parsed || typeof parsed !== 'object') {
      throw new Error('YAML 格式错误: 必须是一个对象');
    }
    if (!parsed.cases) return [];
    if (!Array.isArray(parsed.cases)) {
      throw new Error('YAML 格式错误: cases 必须是一个列表');
    }

    const cases: TestCase[] = [];
    const caseNames = new Set<string>();
    const errors: string[] = [];

    for (const rawCase of parsed.cases) {
      if (!rawCase || typeof rawCase !== 'object') {
        errors.push('YAML 格式错误: 每个用例必须是一个对象');
        continue;
      }

      const name = rawCase.name;
      if (!name || typeof name !== 'string' || name.trim() === '') {
        errors.push('用例名称不能为空');
        continue;
      }
      if (caseNames.has(name)) {
        errors.push(`测试用例名称重复: "${name}"`);
        continue;
      }
      caseNames.add(name);

      if (!Array.isArray(rawCase.steps) || rawCase.steps.length === 0) {
        errors.push(`测试用例 "${name}" 没有有效的测试步骤`);
        continue;
      }

      const parsedSteps = parseYamlStepsStrict(rawCase.steps, name, errors);
      if (parsedSteps.length === 0) {
        errors.push(`测试用例 "${name}" 没有有效的测试步骤`);
        continue;
      }

      cases.push({
        id: rawCase.id || crypto.randomUUID(),
        businessId,
        name,
        description: rawCase.description || '',
        login_required: rawCase.login_required ?? false,
        account: rawCase.account,
        version: rawCase.version,
        snapshot: rawCase.snapshot,
        use_snapshot: rawCase.use_snapshot,
        status: rawCase.status || 'active',
        steps: parsedSteps,
        createdAt: rawCase.createdAt || new Date().toISOString().split('T')[0],
      });
    }

    if (errors.length > 0) {
      throw new Error(errors.join('\n'));
    }

    return cases;
  } catch (error) {
    throw new Error('YAML 解析失败：' + (error as Error).message);
  }
}

/**
 * Parse steps with strict validation and error collection (for global YAML).
 */
function parseYamlStepsStrict(rawSteps: any[], caseName: string, errors: string[]): TestStep[] {
  const steps: TestStep[] = [];

  for (const rawStep of rawSteps) {
    if (!rawStep || typeof rawStep !== 'object') {
      errors.push(`测试用例 "${caseName}" 的步骤格式错误`);
      continue;
    }

    let step_type: 'action' | 'verify' | 'switch_account' | null = null;
    let description: string | undefined;
    let assertion: string | undefined;
    let switchAccountTarget: string | undefined;
    let args: Record<string, any> | undefined;

    if (rawStep.action !== undefined) {
      step_type = 'action';
      description = String(rawStep.action);
      args = rawStep.args;
    } else if (rawStep.verify !== undefined) {
      step_type = 'verify';
      assertion = String(rawStep.verify);
      args = rawStep.args;
    } else if (rawStep.switch_account !== undefined) {
      step_type = 'switch_account';
      switchAccountTarget = String(rawStep.switch_account);
    } else {
      errors.push(`测试用例 "${caseName}" 的步骤类型无效 (必须是 action、verify 或 switch_account)`);
      continue;
    }

    if (step_type === 'action' && (!description || description.trim() === '')) {
      errors.push(`测试用例 "${caseName}" 的 action 描述不能为空`);
      continue;
    }
    if (step_type === 'verify' && (!assertion || assertion.trim() === '')) {
      errors.push(`测试用例 "${caseName}" 的 verify 断言不能为空`);
      continue;
    }
    if (step_type === 'switch_account' && (!switchAccountTarget || switchAccountTarget.trim() === '')) {
      errors.push(`测试用例 "${caseName}" 的 switch_account 目标不能为空`);
      continue;
    }

    steps.push({
      id: crypto.randomUUID(),
      order: steps.length + 1,
      step_type,
      action: step_type === 'action' ? { description: description || '', args } : undefined,
      verify: step_type === 'verify' ? { assertion: assertion || '', args } : undefined,
      switch_account: step_type === 'switch_account' ? switchAccountTarget : undefined,
    });
  }

  return steps;
}