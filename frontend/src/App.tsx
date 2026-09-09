import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";

import {
  AccountSummary,
  AnalysisResults,
  AnalysisRun,
  ApiClient,
  ApiError,
  AuditEvent,
  Membership,
  ModelRegistration,
  ModelVersion,
  Project,
  ProjectRole,
  User,
} from "./api";

type View = "models" | "runs" | "administration";

const tokenStorageKey = "logscope.access-token";
const api = new ApiClient();

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [models, setModels] = useState<ModelVersion[]>([]);
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [systemAuditEvents, setSystemAuditEvents] = useState<AuditEvent[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [view, setView] = useState<View>("models");
  const [isRestoringSession, setIsRestoringSession] = useState(true);
  const [isLoadingProject, setIsLoadingProject] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showAnalysisDialog, setShowAnalysisDialog] = useState(false);
  const [showRegistrationDialog, setShowRegistrationDialog] = useState(false);
  const [results, setResults] = useState<AnalysisResults | null>(null);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );
  const selectedModel = useMemo(
    () => models.find((model) => model.id === selectedModelId) ?? null,
    [models, selectedModelId],
  );
  const publishedModels = useMemo(
    () => models.filter((model) => model.status === "published"),
    [models],
  );

  useEffect(() => {
    const token = sessionStorage.getItem(tokenStorageKey);
    if (!token) {
      setIsRestoringSession(false);
      return;
    }

    api.setToken(token);
    void restoreSession();
  }, []);

  useEffect(() => {
    if (!selectedProjectId || !user) {
      setModels([]);
      setRuns([]);
      setAuditEvents([]);
      setAccounts([]);
      setMemberships([]);
      setSystemAuditEvents([]);
      return;
    }

    void refreshProjectData(selectedProjectId);
  }, [selectedProjectId, user?.id]);

  useEffect(() => {
    if (!selectedProjectId || !runs.some((run) => run.status === "queued")) {
      return;
    }

    const interval = window.setInterval(() => {
      void refreshRuns(selectedProjectId);
    }, 5_000);

    return () => window.clearInterval(interval);
  }, [selectedProjectId, runs]);

  async function restoreSession(): Promise<void> {
    try {
      await loadAuthenticatedData();
    } catch (error) {
      endSession("Your sign-in session is no longer valid. Please sign in again.");
    } finally {
      setIsRestoringSession(false);
    }
  }

  async function loadAuthenticatedData(): Promise<void> {
    const [currentUser, visibleProjects] = await Promise.all([api.getCurrentUser(), api.listProjects()]);
    setUser(currentUser);
    setProjects(visibleProjects);
    setSelectedProjectId((current) => {
      if (current && visibleProjects.some((project) => project.id === current)) {
        return current;
      }
      return visibleProjects[0]?.id ?? null;
    });
  }

  async function refreshProjectData(projectId: string): Promise<void> {
    setIsLoadingProject(true);
    setPageError(null);
    try {
      const [projectModels, projectRuns] = await Promise.all([
        api.listModels(projectId),
        api.listAnalysisRuns(projectId),
      ]);
      setModels(projectModels);
      setRuns(projectRuns);
      setSelectedModelId((current) => {
        if (current && projectModels.some((model) => model.id === current && model.status === "published")) {
          return current;
        }
        return projectModels.find((model) => model.status === "published")?.id ?? null;
      });

      if (user?.is_administrator) {
        const [projectAudit, projectMembers, allAccounts, systemAudit] = await Promise.all([
          api.listAuditEvents(projectId),
          api.listProjectMembers(projectId),
          api.listUsers(),
          api.listSystemAuditEvents(),
        ]);
        setAuditEvents(projectAudit);
        setMemberships(projectMembers);
        setAccounts(allAccounts);
        setSystemAuditEvents(systemAudit);
      } else {
        setAuditEvents([]);
        setAccounts([]);
        setMemberships([]);
        setSystemAuditEvents([]);
      }
    } catch (error) {
      handleRequestError(error);
    } finally {
      setIsLoadingProject(false);
    }
  }

  async function refreshRuns(projectId: string): Promise<void> {
    try {
      setRuns(await api.listAnalysisRuns(projectId));
    } catch (error) {
      handleRequestError(error);
    }
  }

  async function handleLogin(username: string, password: string): Promise<void> {
    const token = await api.login(username, password);
    api.setToken(token.access_token);
    sessionStorage.setItem(tokenStorageKey, token.access_token);

    try {
      await loadAuthenticatedData();
      setNotice(`Signed in. Your session expires after ${Math.floor(token.expires_in_seconds / 60)} minutes.`);
    } catch (error) {
      endSession("Signed in, but the session could not be initialized. Please try again.");
      throw error;
    }
  }

  function endSession(message?: string): void {
    api.setToken(null);
    sessionStorage.removeItem(tokenStorageKey);
    setUser(null);
    setProjects([]);
    setSelectedProjectId(null);
    setModels([]);
    setRuns([]);
    setAuditEvents([]);
    setAccounts([]);
    setMemberships([]);
    setSystemAuditEvents([]);
    setSelectedModelId(null);
    setResults(null);
    setPageError(null);
    setNotice(message ?? null);
  }

  function handleRequestError(error: unknown): void {
    if (error instanceof ApiError && error.status === 401) {
      endSession("Your sign-in session has expired. Please sign in again.");
      return;
    }
    setPageError(messageFor(error));
  }

  async function publishModel(model: ModelVersion): Promise<void> {
    if (!selectedProject) {
      return;
    }
    setPageError(null);
    try {
      await api.publishModel(selectedProject.id, model.id);
      await refreshProjectData(selectedProject.id);
      setNotice(`${model.model_identifier} ${model.version} is now published.`);
    } catch (error) {
      handleRequestError(error);
    }
  }

  async function registerModel(registration: ModelRegistration): Promise<void> {
    if (!selectedProject) {
      return;
    }
    const created = await api.registerModel(selectedProject.id, registration);
    await refreshProjectData(selectedProject.id);
    setNotice(`${created.model_identifier} ${created.version} was registered as eligible.`);
  }

  async function startAnalysis(logReference: string): Promise<void> {
    if (!selectedProject || !selectedModel) {
      return;
    }
    const run = await api.startAnalysis(selectedProject.id, selectedModel.id, logReference);
    await refreshProjectData(selectedProject.id);
    setView("runs");
    setNotice(
      run.status === "not_supported"
        ? "The HDFS dataset was validated, but inference is not available in the current API."
        : `Analysis run ${run.id} was created with status ${run.status}.`,
    );
  }

  async function showResults(run: AnalysisRun): Promise<void> {
    if (!selectedProject) {
      return;
    }
    setPageError(null);
    try {
      setResults(await api.getAnalysisResults(selectedProject.id, run.id));
    } catch (error) {
      handleRequestError(error);
    }
  }

  async function createProject(name: string): Promise<void> {
    const project = await api.createProject(name);
    setProjects((current) => [...current, project]);
    setSelectedProjectId(project.id);
    setNotice(`${project.name} was created.`);
  }

  if (isRestoringSession) {
    return <LoadingScreen />;
  }

  if (!user) {
    return <LoginScreen notice={notice} onLogin={handleLogin} />;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand" aria-label="Logscope home">
          <span className="brand-mark">L</span>
          <span>logscope</span>
        </div>

        <div className="project-switcher">
          <label htmlFor="project-selector">Active project</label>
          <select
            id="project-selector"
            value={selectedProjectId ?? ""}
            onChange={(event) => setSelectedProjectId(event.target.value || null)}
          >
            {projects.length === 0 && <option value="">No project access</option>}
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </div>

        <nav className="navigation" aria-label="Project workspace">
          <NavigationButton
            active={view === "models"}
            label="Models"
            detail={`${models.length}`}
            onClick={() => setView("models")}
          />
          <NavigationButton
            active={view === "runs"}
            label="Analysis runs"
            detail={`${runs.length}`}
            onClick={() => setView("runs")}
          />
          {user.is_administrator && (
            <NavigationButton
              active={view === "administration"}
              label="Administration"
              onClick={() => setView("administration")}
            />
          )}
        </nav>

        <div className="sidebar-footer">
          <div className="identity">
            <span className="identity-avatar">{user.username.slice(0, 1).toUpperCase()}</span>
            <span>
              <strong>{user.username}</strong>
              <small>{user.is_administrator ? "Administrator" : "Project user"}</small>
            </span>
          </div>
          <button className="text-button" type="button" onClick={() => endSession()}>
            Sign out
          </button>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <p className="eyebrow">HDFS anomaly detection</p>
            <h1>{selectedProject?.name ?? "Your projects"}</h1>
          </div>
          {selectedProject && (
            <button
              className="secondary-button"
              type="button"
              onClick={() => void refreshProjectData(selectedProject.id)}
              disabled={isLoadingProject}
            >
              {isLoadingProject ? "Refreshing…" : "Refresh"}
            </button>
          )}
        </header>

        {notice && <Banner tone="success" message={notice} onDismiss={() => setNotice(null)} />}
        {pageError && <Banner tone="error" message={pageError} onDismiss={() => setPageError(null)} />}

        {!selectedProject ? (
          <NoProjectState isAdministrator={user.is_administrator} onCreateProject={createProject} />
        ) : (
          <>
            {view === "models" && (
              <ModelsView
                models={models}
                selectedModelId={selectedModelId}
                onSelectModel={setSelectedModelId}
                onPublish={publishModel}
                onRegister={() => setShowRegistrationDialog(true)}
              />
            )}
            {view === "runs" && (
              <RunsView
                models={models}
                runs={runs}
                selectedModel={selectedModel}
                onOpenAnalysis={() => setShowAnalysisDialog(true)}
                onShowResults={showResults}
              />
            )}
            {view === "administration" && user.is_administrator && (
              <AdministrationView
                key={selectedProject.id}
                currentUserId={user.id}
                projectId={selectedProject.id}
                accounts={accounts}
                memberships={memberships}
                auditEvents={auditEvents}
                systemAuditEvents={systemAuditEvents}
                onCreateProject={createProject}
                onRefresh={() => void refreshProjectData(selectedProject.id)}
                onUnauthorized={handleRequestError}
              />
            )}
          </>
        )}
      </main>

      {showRegistrationDialog && selectedProject && (
        <ModelRegistrationDialog
          projectName={selectedProject.name}
          onClose={() => setShowRegistrationDialog(false)}
          onRegister={registerModel}
        />
      )}
      {showAnalysisDialog && selectedProject && (
        <AnalysisDialog
          projectName={selectedProject.name}
          selectedModel={selectedModel}
          onClose={() => setShowAnalysisDialog(false)}
          onStart={startAnalysis}
        />
      )}
      {results && <ResultsDialog results={results} onClose={() => setResults(null)} />}
    </div>
  );
}

function LoginScreen({
  notice,
  onLogin,
}: {
  notice: string | null;
  onLogin: (username: string, password: string) => Promise<void>;
}): JSX.Element {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await onLogin(username, password);
    } catch (loginError) {
      setError(messageFor(loginError));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      <section className="login-hero">
        <div className="brand">
          <span className="brand-mark">L</span>
          <span>logscope</span>
        </div>
        <div className="hero-copy">
          <p className="eyebrow">HDFS anomaly detection</p>
          <h1>Investigate log behavior with a traceable model.</h1>
          <p>
            Select a published project model, validate a stored HDFS dataset, and inspect the
            durable analysis outcome.
          </p>
        </div>
        <div className="hero-footer">Project-scoped access · HDFS only · No public sign-up</div>
      </section>

      <section className="login-card-container" aria-label="Sign in">
        <form className="login-card" onSubmit={(event) => void submit(event)}>
          <div>
            <p className="eyebrow">Welcome back</p>
            <h2>Sign in to your workspace</h2>
            <p className="muted">Use an account provisioned by an administrator.</p>
          </div>
          {notice && <Banner tone="success" message={notice} />}
          {error && <Banner tone="error" message={error} />}
          <label>
            Username
            <input
              autoComplete="username"
              name="username"
              onChange={(event) => setUsername(event.target.value)}
              required
              value={username}
            />
          </label>
          <label>
            Password
            <input
              autoComplete="current-password"
              minLength={12}
              name="password"
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          <button className="primary-button full-width" disabled={isSubmitting} type="submit">
            {isSubmitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </div>
  );
}

function LoadingScreen(): JSX.Element {
  return (
    <div className="loading-screen" aria-live="polite">
      <div className="brand">
        <span className="brand-mark">L</span>
        <span>logscope</span>
      </div>
      <span className="loading-dot" />
      Restoring your session…
    </div>
  );
}

function NavigationButton({
  active,
  detail,
  label,
  onClick,
}: {
  active: boolean;
  detail?: string;
  label: string;
  onClick: () => void;
}): JSX.Element {
  return (
    <button className={`navigation-button ${active ? "active" : ""}`} type="button" onClick={onClick}>
      <span>{label}</span>
      {detail && <small>{detail}</small>}
    </button>
  );
}

function ModelsView({
  models,
  selectedModelId,
  onPublish,
  onRegister,
  onSelectModel,
}: {
  models: ModelVersion[];
  selectedModelId: string | null;
  onPublish: (model: ModelVersion) => Promise<void>;
  onRegister: () => void;
  onSelectModel: (id: string) => void;
}): JSX.Element {
  return (
    <section className="content-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Model registry</p>
          <h2>Choose a model for analysis</h2>
          <p className="muted">
            Only published HDFS model versions can be selected. The API always enforces project
            access and model lifecycle rules.
          </p>
        </div>
        <button className="primary-button" type="button" onClick={onRegister}>
          Register trained model
        </button>
      </div>

      {models.length === 0 ? (
        <EmptyState
          title="No model versions yet"
          description="A Publisher can register a pre-staged HDFS model package directory for this project."
        />
      ) : (
        <div className="model-grid">
          {models.map((model) => {
            const isSelected = selectedModelId === model.id;
            const isPublished = model.status === "published";
            return (
              <article className={`model-card ${isSelected ? "selected" : ""}`} key={model.id}>
                <div className="card-title-row">
                  <div>
                    <p className="model-name">{model.model_identifier}</p>
                    <p className="muted">Version {model.version}</p>
                  </div>
                  <StatusBadge status={model.status} />
                </div>

                <dl className="metadata-list">
                  <div>
                    <dt>Source</dt>
                    <dd>HDFS</dd>
                  </div>
                  <div>
                    <dt>Pipeline run</dt>
                    <dd className="truncate">{model.pipeline_run_id}</dd>
                  </div>
                  <div>
                    <dt>Registered</dt>
                    <dd>{formatDate(model.created_at)}</dd>
                  </div>
                </dl>

                <MetricList metrics={model.metrics} />

                <div className="card-actions">
                  <button
                    className={isSelected ? "secondary-button selected-button" : "secondary-button"}
                    disabled={!isPublished}
                    type="button"
                    onClick={() => onSelectModel(model.id)}
                  >
                    {isSelected ? "Selected for analysis" : "Select model"}
                  </button>
                  {model.status === "eligible" && (
                    <button className="text-button" type="button" onClick={() => void onPublish(model)}>
                      Publish version
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      <div className="info-strip">
        <strong>Trusted artifact boundary</strong>
        <span>
          This client registers a pre-staged HDFS model package directory. It does not transmit
          model bytes, and the API never deserializes uploaded artifacts.
        </span>
      </div>
    </section>
  );
}

function RunsView({
  models,
  runs,
  selectedModel,
  onOpenAnalysis,
  onShowResults,
}: {
  models: ModelVersion[];
  runs: AnalysisRun[];
  selectedModel: ModelVersion | null;
  onOpenAnalysis: () => void;
  onShowResults: (run: AnalysisRun) => Promise<void>;
}): JSX.Element {
  return (
    <section className="content-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Analysis workspace</p>
          <h2>Validate an HDFS log dataset</h2>
          <p className="muted">
            {selectedModel
              ? `Using ${selectedModel.model_identifier} ${selectedModel.version}.`
              : "Select a published model in the Models view before starting an analysis."}
          </p>
        </div>
        <button className="primary-button" disabled={!selectedModel} type="button" onClick={onOpenAnalysis}>
          Start analysis
        </button>
      </div>

      {selectedModel && (
        <div className="selection-summary">
          <div>
            <span className="summary-label">Selected model</span>
            <strong>
              {selectedModel.model_identifier} <span>·</span> {selectedModel.version}
            </strong>
          </div>
          <StatusBadge status={selectedModel.status} />
        </div>
      )}

      {runs.length === 0 ? (
        <EmptyState
          title="No analysis runs yet"
          description="Start with a published model and an HDFS log reference stored in the controlled workspace."
        />
      ) : (
        <div className="runs-list">
          {runs.map((run) => {
            const model = models.find((candidate) => candidate.id === run.model_version_id);
            return (
              <article className="run-card" key={run.id}>
                <div className="run-primary">
                  <div className="run-status-line">
                    <StatusBadge status={run.status} />
                    <span className="run-id">Run {shortId(run.id)}</span>
                  </div>
                  <strong>{run.log_reference}</strong>
                  <span className="muted">
                    {model ? `${model.model_identifier} ${model.version}` : "Model version unavailable"} ·{" "}
                    {formatDate(run.created_at)}
                  </span>
                </div>
                <div className="run-outcome">
                  {run.error_code && <code>{run.error_code}</code>}
                  <button className="secondary-button" type="button" onClick={() => void onShowResults(run)}>
                    View outcome
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {runs.some((run) => run.status === "queued") && (
        <p className="auto-refresh-note">Queued runs refresh automatically every five seconds.</p>
      )}
    </section>
  );
}

function AdministrationView({
  currentUserId,
  projectId,
  accounts,
  memberships,
  auditEvents,
  systemAuditEvents,
  onCreateProject,
  onRefresh,
  onUnauthorized,
}: {
  currentUserId: string;
  projectId: string;
  accounts: AccountSummary[];
  memberships: Membership[];
  auditEvents: AuditEvent[];
  systemAuditEvents: AuditEvent[];
  onCreateProject: (name: string) => Promise<void>;
  onRefresh: () => void | Promise<void>;
  onUnauthorized: (error: unknown) => void;
}): JSX.Element {
  const [projectName, setProjectName] = useState("");
  const [provisionUsername, setProvisionUsername] = useState("");
  const [provisionPassword, setProvisionPassword] = useState("");
  const [provisionRole, setProvisionRole] = useState<ProjectRole>("operator");
  const [grantUserId, setGrantUserId] = useState("");
  const [grantRole, setGrantRole] = useState<ProjectRole>("operator");
  const [projectError, setProjectError] = useState<string | null>(null);
  const [provisionError, setProvisionError] = useState<string | null>(null);
  const [grantError, setGrantError] = useState<string | null>(null);
  const [membersError, setMembersError] = useState<string | null>(null);
  const [accountsError, setAccountsError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  const memberIds = new Set(memberships.map((membership) => membership.user_id));
  const grantableAccounts = accounts.filter((account) => !memberIds.has(account.id));

  async function runAction(
    key: string,
    work: () => Promise<void>,
    setError: (message: string | null) => void,
    successMessage: string,
  ): Promise<void> {
    setError(null);
    setSuccess(null);
    setPendingAction(key);
    try {
      await work();
      await onRefresh();
      setSuccess(successMessage);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        onUnauthorized(error);
        return;
      }
      setError(messageFor(error));
    } finally {
      setPendingAction(null);
    }
  }

  async function submitProject(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    await runAction(
      "create-project",
      async () => {
        await onCreateProject(projectName);
        setProjectName("");
      },
      setProjectError,
      "Project created.",
    );
  }

  async function submitProvision(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    await runAction(
      "provision",
      async () => {
        await api.provisionProjectAccount(projectId, provisionUsername, provisionPassword, provisionRole);
        setProvisionUsername("");
        setProvisionPassword("");
        setProvisionRole("operator");
      },
      setProvisionError,
      "Account provisioned with its initial project membership.",
    );
  }

  async function submitGrant(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!grantUserId) {
      setGrantError("Select an existing account to grant access.");
      return;
    }
    await runAction(
      "grant",
      async () => {
        await api.grantProjectMembership(projectId, grantUserId, grantRole);
        setGrantUserId("");
        setGrantRole("operator");
      },
      setGrantError,
      "Membership granted.",
    );
  }

  return (
    <section className="content-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Administrator oversight</p>
          <h2>Project accounts and audit trail</h2>
          <p className="muted">
            Provision Operator or Publisher access for this project. The server authorizes every
            request; this page only displays the current project membership and account state.
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={() => void onRefresh()} disabled={pendingAction !== null}>
          {pendingAction ? "Refreshing…" : "Refresh"}
        </button>
      </div>

        {success && <Banner tone="success" message={success} onDismiss={() => setSuccess(null)} />}

        <div className="admin-stack">
        <div className="admin-grid">
          <form className="admin-card" onSubmit={(event) => void submitProject(event)}>
            <p className="eyebrow">New isolation boundary</p>
            <h3>Create a project</h3>
            <p className="muted">Projects scope models, logs, runs, results, and audit records.</p>
            {projectError && <Banner tone="error" message={projectError} />}
            <label htmlFor="admin-project-name">Project name</label>
            <input
              id="admin-project-name"
              maxLength={128}
              minLength={1}
              onChange={(event) => setProjectName(event.target.value)}
              placeholder="e.g. incident-september"
              required
              value={projectName}
              disabled={pendingAction !== null}
            />
            <button className="primary-button" disabled={pendingAction !== null} type="submit">
              {pendingAction === "create-project" ? "Creating…" : "Create project"}
            </button>
          </form>

          <form className="admin-card" onSubmit={(event) => void submitProvision(event)}>
            <p className="eyebrow">Selected project</p>
            <h3>Provision a project account</h3>
            <p className="muted">
              Creates a lowercase username, an active non-administrator account, and its initial
              membership in one request. There is no public sign-up.
            </p>
            {provisionError && <Banner tone="error" message={provisionError} />}
            <label htmlFor="provision-username">Username</label>
            <input
              autoComplete="off"
              id="provision-username"
              maxLength={64}
              minLength={3}
              onChange={(event) => setProvisionUsername(event.target.value)}
              pattern="^[A-Za-z0-9_.-]+$"
              placeholder="operator.one"
              required
              value={provisionUsername}
              disabled={pendingAction !== null}
            />
            <label htmlFor="provision-password">Password</label>
            <input
              autoComplete="new-password"
              id="provision-password"
              minLength={12}
              onChange={(event) => setProvisionPassword(event.target.value)}
              required
              type="password"
              value={provisionPassword}
              disabled={pendingAction !== null}
            />
            <label htmlFor="provision-role">Initial role</label>
            <select
              id="provision-role"
              onChange={(event) => setProvisionRole(event.target.value as ProjectRole)}
              value={provisionRole}
              disabled={pendingAction !== null}
            >
              <option value="operator">Operator</option>
              <option value="publisher">Publisher</option>
            </select>
            <button className="primary-button" disabled={pendingAction !== null} type="submit">
              {pendingAction === "provision" ? "Provisioning…" : "Provision account"}
            </button>
          </form>
        </div>

        <div className="admin-card">
          <p className="eyebrow">Project members</p>
          <h3>Membership for this project</h3>
          <p className="muted">Role changes and revocations take effect on the next authorized request.</p>
          {membersError && <Banner tone="error" message={membersError} />}
          {memberships.length === 0 ? (
            <p className="muted">No project memberships have been granted yet.</p>
          ) : (
            <ul className="membership-list">
              {memberships.map((membership) => {
                const otherRole: ProjectRole = membership.role === "operator" ? "publisher" : "operator";
                return (
                  <li className="membership-row" key={membership.user_id}>
                    <div className="membership-identity">
                      <strong>{membership.username}</strong>
                      <div className="label-row">
                        <span className={`state-label ${membership.is_active ? "is-active" : "is-inactive"}`}>
                          {membership.is_active ? "Active" : "Inactive"}
                        </span>
                        <span className={`role-label role-${membership.role}`}>{membership.role}</span>
                      </div>
                    </div>
                    <div className="membership-actions">
                      <button
                        className="secondary-button"
                        disabled={pendingAction !== null}
                        type="button"
                        onClick={() =>
                          void runAction(
                            `role:${membership.user_id}`,
                            () => api.updateProjectMembershipRole(projectId, membership.user_id, otherRole).then(() => undefined),
                            setMembersError,
                            `Role changed to ${otherRole}.`,
                          )
                        }
                      >
                        {pendingAction === `role:${membership.user_id}`
                          ? "Updating…"
                          : `Change to ${otherRole}`}
                      </button>
                      <button
                        className="danger-button"
                        disabled={pendingAction !== null}
                        type="button"
                        onClick={() =>
                          void runAction(
                            `revoke:${membership.user_id}`,
                            () => api.revokeProjectMembership(projectId, membership.user_id),
                            setMembersError,
                            "Membership revoked.",
                          )
                        }
                      >
                        {pendingAction === `revoke:${membership.user_id}` ? "Revoking…" : "Revoke membership"}
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          <form className="grant-form" onSubmit={(event) => void submitGrant(event)}>
            <h4>Grant an existing account</h4>
            {grantError && <Banner tone="error" message={grantError} />}
            <label htmlFor="grant-user">Account</label>
            <select
              id="grant-user"
              onChange={(event) => setGrantUserId(event.target.value)}
              value={grantUserId}
              disabled={pendingAction !== null || grantableAccounts.length === 0}
              required
            >
              <option value="">
                {grantableAccounts.length === 0 ? "No remaining accounts to grant" : "Select an account"}
              </option>
              {grantableAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.username}
                  {account.is_active ? "" : " (inactive)"}
                </option>
              ))}
            </select>
            <label htmlFor="grant-role">Role</label>
            <select
              id="grant-role"
              onChange={(event) => setGrantRole(event.target.value as ProjectRole)}
              value={grantRole}
              disabled={pendingAction !== null}
            >
              <option value="operator">Operator</option>
              <option value="publisher">Publisher</option>
            </select>
            <button
              className="secondary-button"
              disabled={pendingAction !== null || grantableAccounts.length === 0}
              type="submit"
            >
              {pendingAction === "grant" ? "Granting…" : "Grant membership"}
            </button>
          </form>
        </div>

        <div className="admin-card">
          <p className="eyebrow">Account lifecycle</p>
          <h3>Activate or deactivate accounts</h3>
          <p className="muted">
            Deactivation preserves the account and immediately rejects its bearer token. Administrator
            accounts cannot be changed here.
          </p>
          {accountsError && <Banner tone="error" message={accountsError} />}
          <ul className="membership-list">
            {accounts.map((account) => {
              const isCurrentUser = account.id === currentUserId;
              return (
                <li className="membership-row" key={account.id}>
                  <div className="membership-identity">
                    <strong>{account.username}</strong>
                    <div className="label-row">
                      <span className={`state-label ${account.is_active ? "is-active" : "is-inactive"}`}>
                        {account.is_active ? "Active" : "Inactive"}
                      </span>
                      {isCurrentUser && <span className="role-label role-administrator">Administrator</span>}
                    </div>
                  </div>
                  <div className="membership-actions">
                    <button
                      className={account.is_active ? "danger-button" : "secondary-button"}
                      disabled={pendingAction !== null || isCurrentUser}
                      type="button"
                      onClick={() =>
                        void runAction(
                          `activation:${account.id}`,
                          () => api.setUserActivation(account.id, !account.is_active).then(() => undefined),
                          setAccountsError,
                          account.is_active ? "Account deactivated." : "Account reactivated.",
                        )
                      }
                    >
                      {pendingAction === `activation:${account.id}`
                        ? "Updating…"
                        : account.is_active
                          ? "Deactivate"
                          : "Reactivate"}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="admin-grid">
          <AuditPanel
            title="Project audit"
            description="Membership grants, role changes, and revocations for the selected project."
            emptyMessage="No audit events are recorded for this project yet."
            events={auditEvents}
          />
          <AuditPanel
            title="System audit"
            description="Bootstrap, provisioning, sign-in, deactivation, and reactivation events."
            emptyMessage="No system account events are recorded yet."
            events={systemAuditEvents}
          />
        </div>
      </div>
    </section>
  );
}

function AuditPanel({
  title,
  description,
  emptyMessage,
  events,
}: {
  title: string;
  description: string;
  emptyMessage: string;
  events: AuditEvent[];
}): JSX.Element {
  return (
    <div className="audit-card">
      <div className="audit-heading">
        <div>
          <p className="eyebrow">Immutable history</p>
          <h3>{title}</h3>
          <p className="muted">{description}</p>
        </div>
        <span className="event-count">{events.length} events</span>
      </div>
      {events.length === 0 ? (
        <p className="muted">{emptyMessage}</p>
      ) : (
        <ol className="audit-list">
          {events.map((event) => (
            <li key={event.id}>
              <span className="audit-marker" />
              <div>
                <strong>{event.action}</strong>
                <p>
                  {event.resource_type}
                  {event.project_id ? " · project-scoped" : " · system"} · {formatDate(event.created_at)}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function NoProjectState({
  isAdministrator,
  onCreateProject,
}: {
  isAdministrator: boolean;
  onCreateProject: (name: string) => Promise<void>;
}): JSX.Element {
  const [projectName, setProjectName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  if (!isAdministrator) {
    return (
      <EmptyState
        title="No projects available"
        description="Ask an administrator to grant you access to a project before you can view models or analysis runs."
      />
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setIsCreating(true);
    try {
      await onCreateProject(projectName);
      setProjectName("");
    } catch (creationError) {
      setError(messageFor(creationError));
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <section className="content-section">
      <EmptyState
        title="Create the first project"
        description="Projects provide the isolation boundary for models, HDFS datasets, analysis runs, results, and audit records."
      />
      <form className="admin-card create-project-card" onSubmit={(event) => void submit(event)}>
        <p className="eyebrow">New isolation boundary</p>
        <h3>Create a project</h3>
        {error && <Banner tone="error" message={error} />}
        <label htmlFor="first-project-name">Project name</label>
        <input
          id="first-project-name"
          maxLength={128}
          minLength={1}
          onChange={(event) => setProjectName(event.target.value)}
          placeholder="e.g. incident-september"
          required
          value={projectName}
          disabled={isCreating}
        />
        <button className="primary-button" disabled={isCreating} type="submit">
          {isCreating ? "Creating…" : "Create project"}
        </button>
      </form>
    </section>
  );
}

function ModelRegistrationDialog({
  projectName,
  onClose,
  onRegister,
}: {
  projectName: string;
  onClose: () => void;
  onRegister: (registration: ModelRegistration) => Promise<void>;
}): JSX.Element {
  const [packageReference, setPackageReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await onRegister({ package_reference: packageReference });
      onClose();
    } catch (submissionError) {
      setError(messageFor(submissionError));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog title="Register trained model" onClose={onClose}>
      <form className="dialog-form" onSubmit={(event) => void submit(event)}>
        <p className="muted">
          Register a pre-staged HDFS model package for <strong>{projectName}</strong>. Identity,
          metrics, and evidence come from the package manifest.
        </p>
        <div className="warning-strip">
          Browser artifact uploads are intentionally unavailable. This API only accepts a trusted
          workspace directory path and never receives model bytes.
        </div>
        {error && <Banner tone="error" message={error} />}
        <label>
          Package directory reference
          <input
            onChange={(event) => setPackageReference(event.target.value)}
            placeholder="packages/hdfs/package"
            required
            value={packageReference}
          />
        </label>
        <div className="dialog-actions">
          <button className="secondary-button" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="primary-button" disabled={isSubmitting} type="submit">
            {isSubmitting ? "Registering…" : "Register model"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function AnalysisDialog({
  projectName,
  selectedModel,
  onClose,
  onStart,
}: {
  projectName: string;
  selectedModel: ModelVersion | null;
  onClose: () => void;
  onStart: (logReference: string) => Promise<void>;
}): JSX.Element {
  const [logReference, setLogReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await onStart(logReference);
      onClose();
    } catch (submissionError) {
      setError(messageFor(submissionError));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog title="Start HDFS analysis" onClose={onClose}>
      <form className="dialog-form" onSubmit={(event) => void submit(event)}>
        <div className="analysis-model-summary">
          <span>Project</span>
          <strong>{projectName}</strong>
          <span>Model</span>
          <strong>
            {selectedModel?.model_identifier} {selectedModel && `· ${selectedModel.version}`}
          </strong>
        </div>
        <div className="warning-strip">
          Browser log-file upload is not implemented by the current API. Put a UTF-8 HDFS log in
          the controlled workspace, then enter its relative reference below.
        </div>
        <p className="muted">
          Valid requests currently finish as <code>not_supported</code> until the isolated,
          non-executable inference-artifact contract is implemented. Invalid HDFS datasets are
          fully rejected with a validation report.
        </p>
        {error && <Banner tone="error" message={error} />}
        <label>
          Stored HDFS log reference
          <input
            onChange={(event) => setLogReference(event.target.value)}
            placeholder="data/stored-hdfs.log"
            required
            value={logReference}
          />
        </label>
        <div className="dialog-actions">
          <button className="secondary-button" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="primary-button" disabled={isSubmitting || !selectedModel} type="submit">
            {isSubmitting ? "Submitting…" : "Validate and start"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ResultsDialog({
  results,
  onClose,
}: {
  results: AnalysisResults;
  onClose: () => void;
}): JSX.Element {
  const { run, summary } = results;
  const validationExamples = run.validation_report?.examples ?? [];

  return (
    <Dialog title="Analysis outcome" onClose={onClose}>
      <div className="results-dialog">
        <div className="results-header">
          <div>
            <span className="summary-label">Run {shortId(run.id)}</span>
            <h3>{run.log_reference}</h3>
          </div>
          <StatusBadge status={run.status} />
        </div>

        {run.validation_report?.execution && (
          <div className="warning-strip">{run.validation_report.execution}</div>
        )}
        {run.error_code && <p className="error-code">Error code: {run.error_code}</p>}

        <div className="outcome-summary">
          <SummaryMetric label="Anomalies" value={summary.anomaly_count} />
          <SummaryMetric label="Normal" value={summary.normal_count} />
          <SummaryMetric label="Rejected records" value={summary.rejected_records} />
          <SummaryMetric label="Invalid records" value={summary.invalid_records} />
        </div>

        {validationExamples.length > 0 && (
          <div className="validation-examples">
            <h4>Validation details</h4>
            <ul>
              {validationExamples.map((example, index) => (
                <li key={`${example.line_number ?? 0}-${index}`}>
                  Line {example.line_number ?? "—"}: {example.reason ?? "Invalid record"}
                </li>
              ))}
            </ul>
          </div>
        )}

        {results.anomalies.length > 0 && (
          <div className="anomaly-list">
            <h4>Detected anomalies</h4>
            {results.anomalies.map((anomaly) => (
              <article key={anomaly.record_reference}>
                <strong>{anomaly.record_reference}</strong>
                <span>
                  Score {formatMetric(anomaly.anomaly_score)} · threshold{" "}
                  {formatMetric(anomaly.decision_threshold)}
                </span>
              </article>
            ))}
          </div>
        )}

        <div className="dialog-actions">
          <button className="primary-button" type="button" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function Dialog({
  children,
  onClose,
  title,
}: {
  children: ReactNode;
  onClose: () => void;
  title: string;
}): JSX.Element {
  return (
    <div className="dialog-backdrop" role="presentation">
      <section aria-modal="true" aria-labelledby="dialog-title" className="dialog" role="dialog">
        <div className="dialog-heading">
          <h2 id="dialog-title">{title}</h2>
          <button aria-label="Close dialog" className="icon-button" type="button" onClick={onClose}>
            ×
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

function Banner({
  message,
  onDismiss,
  tone,
}: {
  message: string;
  onDismiss?: () => void;
  tone: "error" | "success";
}): JSX.Element {
  return (
    <div className={`banner ${tone}`} role={tone === "error" ? "alert" : "status"}>
      <span>{message}</span>
      {onDismiss && (
        <button aria-label="Dismiss message" className="icon-button" type="button" onClick={onDismiss}>
          ×
        </button>
      )}
    </div>
  );
}

function EmptyState({ description, title }: { description: string; title: string }): JSX.Element {
  return (
    <div className="empty-state">
      <span className="empty-state-icon">⌁</span>
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }): JSX.Element {
  return <span className={`status-badge status-${status.replace("_", "-")}`}>{status.replace("_", " ")}</span>;
}

function MetricList({ metrics }: { metrics: Record<string, unknown> }): JSX.Element | null {
  const entries = Object.entries(metrics).slice(0, 3);
  if (entries.length === 0) {
    return null;
  }

  return (
    <div className="metric-list">
      {entries.map(([name, value]) => (
        <span key={name}>
          <small>{humanize(name)}</small>
          <strong>{formatMetric(value)}</strong>
        </span>
      ))}
    </div>
  );
}

function SummaryMetric({ label, value }: { label: string; value: number }): JSX.Element {
  return (
    <div>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function messageFor(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function formatMetric(value: unknown): string {
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  if (typeof value === "string" || typeof value === "boolean") {
    return String(value);
  }
  return "—";
}

function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

function shortId(value: string): string {
  return value.slice(0, 8);
}
