/// <reference types="vite/client" />

/**
 * API Client for WebQA Backend
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

// Types matching backend schemas
export interface Environment {
  id?: string;
  name: string;
  url: string;
  browser_config?: Record<string, any>;
  ignore_rules?: Record<string, any>;
  auth_type: 'none' | 'sso' | 'cookies';
  sso_username?: string;
  sso_password?: string;
  sso_env?: 'prod' | 'staging';
  cookies?: Array<Record<string, any>>;
  created_at?: string;
}

export interface Business {
  id: string;
  name: string;
  description?: string;
  created_at: string;
  environments: Environment[];
}

export interface TestStep {
  step_type: 'action' | 'verify';
  description?: string;
  assertion?: string;
  args?: Record<string, any>;
}

export interface TestCase {
  id: string;
  business_id: string;
  name: string;
  description?: string;
  login_required: boolean;
  steps: TestStep[];
  version?: string;
  snapshot?: string;
  use_snapshot?: string;
  status: 'active' | 'draft' | 'disabled';
  sort_order?: number;
  created_at: string;
}

export interface Execution {
  id: string;
  business_id?: string;
  business_name?: string;
  environment_id?: string;
  environment_name?: string;
  trigger_type: 'manual' | 'scheduled' | 'debug' | 'gen';
  scheduled_task_id?: string;
  model: string;
  workers: number;
  test_case_ids: string[];
  status: 'pending' | 'running' | 'passed' | 'failed' | 'warning' | 'timeout' | 'completed';
  oss_report_url?: string;
  report_url?: string;
  data_flow_report_url?: string;
  local_report_path?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
  error_message?: string;
  result_count?: {
    total: number;
    passed: number;
    failed: number;
    warning: number;
  };
  config?: Record<string, any>;
}

// Progress types for real-time execution tracking
export interface TaskProgress {
  name: string;
  duration?: number;
  elapsed?: number;
  status?: string;  // 执行状态: 'success' | 'failed'
  error?: string;
  result?: string;  // 测试结果: 'passed' | 'failed' | 'warning'
}

export interface ExecutionProgress {
  execution_id: string;
  status: string;
  updated_at?: string;
  completed: TaskProgress[];
  running: TaskProgress[];
  logs: string[];
}

export interface APIResponse<T> {
  code: number;
  message: string;
  data: T;
}

export interface EnvironmentCookiesResponse {
  cookies: Array<Record<string, any>>;
  source: 'sso' | 'environment' | 'none';
}

export interface ListResponse<T> {
  items: T[];
  total: number;
}

// API Client class
class APIClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail?.message || `HTTP ${response.status}`);
    }

    const data: APIResponse<T> = await response.json();

    if (data.code !== 0) {
      throw new Error(data.message || 'API Error');
    }

    return data.data;
  }

  // Business APIs
  async getBusinesses(): Promise<ListResponse<Business>> {
    return this.request<ListResponse<Business>>('/businesses');
  }

  async getBusiness(id: string): Promise<Business> {
    return this.request<Business>(`/businesses/${id}`);
  }

  async createBusiness(data: {
    name: string;
    description?: string;
    environments: Omit<Environment, 'id' | 'created_at'>[];
  }): Promise<Business> {
    return this.request<Business>('/businesses', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateBusiness(
    id: string,
    data: {
      name?: string;
      description?: string;
      environments?: Environment[];
    }
  ): Promise<Business> {
    return this.request<Business>(`/businesses/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteBusiness(id: string): Promise<void> {
    await this.request(`/businesses/${id}`, {
      method: 'DELETE',
    });
  }

  async deleteEnvironment(id: string): Promise<void> {
    await this.request(`/environments/${id}`, {
      method: 'DELETE',
    });
  }

  async generateEnvironmentCookies(id: string): Promise<EnvironmentCookiesResponse> {
    return this.request<EnvironmentCookiesResponse>(`/environments/${id}/generate-cookies`, {
      method: 'POST',
    });
  }

  // Test Case APIs
  async getTestCases(businessId: string): Promise<ListResponse<TestCase>> {
    return this.request<ListResponse<TestCase>>(`/businesses/${businessId}/cases`);
  }

  async getTestCase(id: string): Promise<TestCase> {
    return this.request<TestCase>(`/cases/${id}`);
  }

  async createTestCase(data: {
    business_id: string;
    name: string;
    description?: string;
    login_required?: boolean;
    steps: TestStep[];
    version?: string;
    snapshot?: string;
    use_snapshot?: string;
    status?: string;
  }): Promise<TestCase> {
    return this.request<TestCase>('/cases', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateTestCase(
    id: string,
    data: Partial<Omit<TestCase, 'id' | 'business_id' | 'created_at'>>
  ): Promise<TestCase> {
    return this.request<TestCase>(`/cases/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteTestCase(id: string): Promise<void> {
    await this.request(`/cases/${id}`, {
      method: 'DELETE',
    });
  }

  async importTestCases(businessId: string, yamlContent: string): Promise<{
    imported_count: number;
    cases: TestCase[];
  }> {
    return this.request<{ imported_count: number; cases: TestCase[] }>(
      `/cases/import/${businessId}`,
      {
        method: 'POST',
        body: JSON.stringify({ yaml_content: yamlContent }),
      }
    );
  }

  async exportTestCases(businessId: string): Promise<{
    yaml_content: string;
    count: number;
  }> {
    return this.request<{ yaml_content: string; count: number }>(
      `/cases/export/${businessId}`
    );
  }

  // Execution APIs
  async getExecutions(params?: {
    business_id?: string;
    trigger_type?: string;
    status?: string;
    url_search?: string;
    limit?: number;
    offset?: number;
  }): Promise<ListResponse<Execution>> {
    const searchParams = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined) {
          searchParams.append(key, String(value));
        }
      });
    }
    const query = searchParams.toString();
    return this.request<ListResponse<Execution>>(`/executions${query ? `?${query}` : ''}`);
  }

  async getExecution(id: string): Promise<Execution> {
    return this.request<Execution>(`/executions/${id}`);
  }

  async createExecution(data: {
    business_id?: string;
    environment_id?: string;
    test_case_ids?: string[];
    model?: string;
    workers?: number;
    trigger_type?: 'manual' | 'debug' | 'gen';
    case_data?: Record<string, any>;
    gen_config?: {
      target_url: string;
      llm_config: {
        model: string;
        api_key?: string;
        [key: string]: any;
      };
      business_objectives?: string;
      custom_tools?: {
        enabled: string[];
      };
      skip_reflection?: boolean;
      dynamic_step_generation?: {
        enabled: boolean;
      };
      browser_config?: {
        cookies?: Array<Record<string, any>>;
        [key: string]: any;
      };
      [key: string]: any;
    };
  }): Promise<Execution> {
    // Ensure business_id/environment_id are not undefined if empty string passed
    const payload = { ...data };
    if (!payload.business_id) delete payload.business_id;
    if (!payload.environment_id) delete payload.environment_id;

    return this.request<Execution>('/executions', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async stopExecution(id: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/executions/${id}/stop`, {
      method: 'POST',
    });
  }

  async getExecutionStatus(id: string): Promise<{
    id: string;
    status: string;
    oss_report_url?: string;
    report_url?: string;
    data_flow_report_url?: string;
    result_count?: Record<string, number>;
    error_message?: string;
  }> {
    return this.request(`/executions/${id}/status`);
  }

  async getExecutionProgress(id: string): Promise<ExecutionProgress> {
    return this.request<ExecutionProgress>(`/executions/${id}/progress`);
  }

  // Config APIs
  async getAvailableModels(mode?: 'gen' | 'run'): Promise<{
    models: string[];
    default: string;
  }> {
    const params = mode ? `?mode=${mode}` : '';
    return this.request(`/config/models${params}`);
  }

  // File APIs
  async getFiles(businessId: string): Promise<ListResponse<{
    id: string;
    name: string;
    size: number;
    type: string;
    uploaded_at: string;
    url: string;
  }>> {
    return this.request(`/files/${businessId}`);
  }

  async uploadFile(businessId: string, file: File): Promise<{
    id: string;
    name: string;
    size: number;
    type: string;
    uploaded_at: string;
    url: string;
  }> {
    const formData = new FormData();
    formData.append('file', file);

    // For FormData, we let the browser set the Content-Type header with the boundary
    const response = await fetch(`${this.baseUrl}/files/${businessId}/upload`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail?.message || `HTTP ${response.status}`);
    }

    const data = await response.json();
    if (data.code !== 0) {
      throw new Error(data.message || 'API Error');
    }
    return data.data;
  }

  async deleteFile(businessId: string, filename: string): Promise<void> {
    await this.request(`/files/${businessId}/${filename}`, {
      method: 'DELETE',
    });
  }

  // Scheduled Task APIs
  async getScheduledTasks(params?: {
    business_id?: string;
    enabled?: boolean;
    limit?: number;
    offset?: number;
  }): Promise<ListResponse<{
    id: string;
    business_id: string;
    business_name?: string;
    name: string;
    description?: string;
    environment_id: string;
    environment_name?: string;
    test_case_ids: string[];
    model: string;
    workers: number;
    cron_expression: string;
    enabled: boolean;
    webhook_url?: string;
    feishu_notify_user_id?: string;
    last_run_at?: string;
    next_run_at?: string;
    created_at: string;
    updated_at: string;
  }>> {
    const searchParams = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined) {
          searchParams.append(key, String(value));
        }
      });
    }
    const query = searchParams.toString();
    return this.request(`/schedules${query ? `?${query}` : ''}`);
  }

  async getScheduledTask(id: string) {
    return this.request(`/schedules/${id}`);
  }

  async createScheduledTask(data: {
    business_id: string;
    name: string;
    description?: string;
    environment_id: string;
    test_case_ids: string[];
    model: string;
    workers: number;
    cron_expression: string;
    enabled: boolean;
    webhook_url?: string;
    feishu_notify_user_id?: string | null;
  }) {
    return this.request('/schedules', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateScheduledTask(id: string, data: {
    name?: string;
    description?: string;
    environment_id?: string;
    test_case_ids?: string[];
    model?: string;
    workers?: number;
    cron_expression?: string;
    enabled?: boolean;
    webhook_url?: string | null;
    feishu_notify_user_id?: string | null;
  }) {
    return this.request(`/schedules/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteScheduledTask(id: string): Promise<void> {
    await this.request(`/schedules/${id}`, {
      method: 'DELETE',
    });
  }

  async toggleScheduledTask(id: string, enabled: boolean) {
    return this.request(`/schedules/${id}/toggle`, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    });
  }

  async triggerScheduledTask(id: string): Promise<Execution> {
    return this.request<Execution>(`/schedules/${id}/trigger`, {
      method: 'POST',
    });
  }

  async validateCron(cronExpression: string): Promise<{
    is_valid: boolean;
    error?: string;
    next_run_times?: string[];
  }> {
    return this.request('/schedules/validate-cron', {
      method: 'POST',
      body: JSON.stringify({ cron_expression: cronExpression }),
    });
  }
}

// Export singleton instance
export const apiClient = new APIClient();
export default apiClient;
