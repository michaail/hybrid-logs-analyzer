export type ModelStatus = "eligible" | "published";
export type AnalysisRunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "rejected"
  | "not_supported";
export type ProjectRole = "operator" | "publisher";
export type StorageKind = "workspace" | "object";

export interface User {
  id: string;
  username: string;
  is_administrator: boolean;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
}

export interface AccountSummary {
  id: string;
  username: string;
  is_active: boolean;
  created_at: string;
}

export interface Membership {
  project_id: string;
  user_id: string;
  role: ProjectRole;
  username: string;
  is_active: boolean;
}

export interface ProjectAccount {
  account: AccountSummary;
  membership: Membership;
}

export interface ModelVersion {
  id: string;
  project_id: string;
  model_identifier: string;
  version: string;
  source_compatibility: "hdfs";
  status: ModelStatus;
  pipeline_run_id: string;
  artifact_reference: string;
  metrics: Record<string, unknown>;
  metadata: Record<string, unknown>;
  external_evaluation_evidence: string;
  created_at: string;
  published_at: string | null;
  published_by_user_id: string | null;
  storage_kind: StorageKind;
  checksum: string | null;
}

export interface AnalysisRun {
  id: string;
  project_id: string;
  model_version_id: string;
  requested_by_user_id: string;
  source_compatibility: "hdfs";
  log_reference: string;
  status: AnalysisRunStatus;
  validation_report: ValidationReport | null;
  error_code: string | null;
  created_at: string;
  completed_at: string | null;
  dataset_id: string | null;
  storage_kind: StorageKind | null;
  checksum: string | null;
}

export interface Dataset {
  id: string;
  project_id: string;
  storage_kind: StorageKind;
  object_reference: string;
  checksum: string | null;
  source_compatibility: "hdfs";
  created_at: string;
}

export interface ValidationReport {
  valid?: boolean;
  total_records?: number;
  invalid_records?: number;
  examples?: Array<{ line_number?: number; reason?: string }>;
  execution?: string;
}

export interface AnalysisResults {
  run: AnalysisRun;
  summary: {
    anomaly_count: number;
    normal_count: number;
    rejected_records: number;
    invalid_records: number;
  };
  anomalies: Array<{
    record_reference: string;
    anomaly_score: number | null;
    anomaly_level: string | null;
    decision_threshold: number | null;
    context: Record<string, unknown>;
  }>;
}

export interface AuditEvent {
  id: string;
  actor_user_id: string | null;
  project_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface ModelRegistration {
  model_identifier: string;
  version: string;
  pipeline_run_manifest: string;
  external_evaluation_evidence: string;
  metadata: Record<string, unknown>;
}

interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in_seconds: number;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiClient {
  private token: string | null = null;

  setToken(token: string | null): void {
    this.token = token;
  }

  async login(username: string, password: string): Promise<TokenResponse> {
    return this.request<TokenResponse>("/auth/token", {
      method: "POST",
      body: { username, password },
      includeToken: false,
    });
  }

  getCurrentUser(): Promise<User> {
    return this.request<User>("/users/me");
  }

  listProjects(): Promise<Project[]> {
    return this.request<Project[]>("/projects");
  }

  createProject(name: string): Promise<Project> {
    return this.request<Project>("/projects", { method: "POST", body: { name } });
  }

  listModels(projectId: string): Promise<ModelVersion[]> {
    return this.request<ModelVersion[]>(`/projects/${projectId}/models`);
  }

  registerModel(projectId: string, model: ModelRegistration): Promise<ModelVersion> {
    return this.request<ModelVersion>(`/projects/${projectId}/models`, {
      method: "POST",
      body: { ...model, source_compatibility: "hdfs" },
    });
  }

  publishModel(projectId: string, modelId: string): Promise<ModelVersion> {
    return this.request<ModelVersion>(`/projects/${projectId}/models/${modelId}/publish`, {
      method: "POST",
    });
  }

  listAnalysisRuns(projectId: string): Promise<AnalysisRun[]> {
    return this.request<AnalysisRun[]>(`/projects/${projectId}/analysis-runs`);
  }

  startAnalysis(projectId: string, modelVersionId: string, logReference: string): Promise<AnalysisRun> {
    return this.request<AnalysisRun>(`/projects/${projectId}/analysis-runs`, {
      method: "POST",
      body: { model_version_id: modelVersionId, log_reference: logReference },
    });
  }

  listDatasets(projectId: string): Promise<Dataset[]> {
    return this.request<Dataset[]>(`/projects/${projectId}/datasets`);
  }

  getDataset(projectId: string, datasetId: string): Promise<Dataset> {
    return this.request<Dataset>(`/projects/${projectId}/datasets/${datasetId}`);
  }

  getAnalysisResults(projectId: string, analysisRunId: string): Promise<AnalysisResults> {
    return this.request<AnalysisResults>(`/projects/${projectId}/analysis-runs/${analysisRunId}/results`);
  }

  listAuditEvents(projectId: string): Promise<AuditEvent[]> {
    return this.request<AuditEvent[]>(`/projects/${projectId}/audit-events`);
  }

  listUsers(): Promise<AccountSummary[]> {
    return this.request<AccountSummary[]>("/admin/users");
  }

  provisionProjectAccount(
    projectId: string,
    username: string,
    password: string,
    role: ProjectRole,
  ): Promise<ProjectAccount> {
    return this.request<ProjectAccount>("/admin/project-accounts", {
      method: "POST",
      body: { username, password, project_id: projectId, role },
    });
  }

  setUserActivation(userId: string, isActive: boolean): Promise<AccountSummary> {
    return this.request<AccountSummary>(`/admin/users/${userId}/activation`, {
      method: "PATCH",
      body: { is_active: isActive },
    });
  }

  listProjectMembers(projectId: string): Promise<Membership[]> {
    return this.request<Membership[]>(`/projects/${projectId}/members`);
  }

  grantProjectMembership(projectId: string, userId: string, role: ProjectRole): Promise<Membership> {
    return this.request<Membership>(`/projects/${projectId}/members`, {
      method: "POST",
      body: { user_id: userId, role },
    });
  }

  updateProjectMembershipRole(projectId: string, userId: string, role: ProjectRole): Promise<Membership> {
    return this.request<Membership>(`/projects/${projectId}/members/${userId}`, {
      method: "PATCH",
      body: { role },
    });
  }

  revokeProjectMembership(projectId: string, userId: string): Promise<void> {
    return this.request<void>(`/projects/${projectId}/members/${userId}`, { method: "DELETE" });
  }

  listSystemAuditEvents(): Promise<AuditEvent[]> {
    return this.request<AuditEvent[]>("/admin/audit-events");
  }

  private async request<T>(
    path: string,
    options: {
      method?: string;
      body?: unknown;
      includeToken?: boolean;
    } = {},
  ): Promise<T> {
    const headers = new Headers();
    const includeToken = options.includeToken ?? true;

    if (options.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    if (includeToken && this.token) {
      headers.set("Authorization", `Bearer ${this.token}`);
    }

    const response = await fetch(`${apiBaseUrl}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });

    if (!response.ok) {
      throw new ApiError(await responseMessage(response), response.status);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    const payload = await response.text();
    if (!payload) {
      return undefined as T;
    }
    return JSON.parse(payload) as T;
  }
}

async function responseMessage(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (
      typeof payload === "object" &&
      payload !== null &&
      "detail" in payload &&
      typeof payload.detail === "string"
    ) {
      return payload.detail;
    }
  } catch {
    // A non-JSON response is still a useful HTTP failure.
  }

  return `Request failed (${response.status}).`;
}
