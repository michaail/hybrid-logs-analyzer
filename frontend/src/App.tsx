import { useEffect, useMemo, useState } from "react";

import {
  AccountSummary,
  AnalysisRun,
  ApiError,
  AuditEvent,
  Dataset,
  Membership,
  ModelVersion,
  Project,
  User,
} from "./api";
import { Banner } from "./components/Banner";
import { LoadingScreen } from "./components/LoadingScreen";
import { NavigationButton } from "./components/NavigationButton";
import { NoProjectState } from "./components/NoProjectState";
import { AdministrationView } from "./features/admin/AdministrationView";
import { LoginScreen } from "./features/auth/LoginScreen";
import { ModelRegistrationDialog } from "./features/models/ModelRegistrationDialog";
import { ModelsView } from "./features/models/ModelsView";
import { publishModelWithStatus, registeredStatusMessage } from "./features/models/status";
import { ResultsDialog } from "./features/results/ResultsDialog";
import { AnalysisDialog } from "./features/runs/AnalysisDialog";
import { RunsView } from "./features/runs/RunsView";
import { messageFor } from "./lib/errors";
import { shortId } from "./lib/format";
import { api, tokenStorageKey } from "./session";

type View = "models" | "runs" | "administration";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [models, setModels] = useState<ModelVersion[]>([]);
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
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
  const [inspectedRun, setInspectedRun] = useState<AnalysisRun | null>(null);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );
  const selectedModel = useMemo(
    () => models.find((model) => model.id === selectedModelId) ?? null,
    [models, selectedModelId],
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
      setDatasets([]);
      setAuditEvents([]);
      setAccounts([]);
      setMemberships([]);
      setSystemAuditEvents([]);
      return;
    }

    void refreshProjectData(selectedProjectId);
  }, [selectedProjectId, user?.id]);

  useEffect(() => {
    if (!selectedProjectId || !runs.some((run) => run.status === "queued" || run.status === "running")) {
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
    } catch {
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
      await Promise.all([
        loadProjectResources(projectId),
        loadProjectAdministration(projectId),
      ]);
    } finally {
      setIsLoadingProject(false);
    }
  }

  async function loadProjectResources(projectId: string): Promise<void> {
    try {
      const [projectModels, projectRuns, projectDatasets] = await Promise.all([
        api.listModels(projectId),
        api.listAnalysisRuns(projectId),
        api.listDatasets(projectId),
      ]);
      setModels(projectModels);
      setRuns(projectRuns);
      setDatasets(projectDatasets);
      setSelectedModelId((current) => {
        return projectModels.find((model) => model.id === current && model.status === "published")
          ? current
          : projectModels.find((model) => model.status === "published" && model.inference_ready)?.id
            ?? projectModels.find((model) => model.status === "published")?.id
            ?? null;
      });
    } catch (error) {
      handleRequestError(error);
    }
  }

  async function loadProjectAdministration(projectId: string): Promise<void> {
    if (!user?.is_administrator) {
      setAuditEvents([]);
      setAccounts([]);
      setMemberships([]);
      setSystemAuditEvents([]);
      return;
    }
    try {
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
    } catch (error) {
      handleRequestError(error);
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
    setDatasets([]);
    setAuditEvents([]);
    setAccounts([]);
    setMemberships([]);
    setSystemAuditEvents([]);
    setSelectedModelId(null);
    setInspectedRun(null);
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
      const notice = await publishModelWithStatus(
        () => api.publishModel(selectedProject.id, model.id),
        model,
      );
      await refreshProjectData(selectedProject.id);
      setNotice(notice);
    } catch (error) {
      handleRequestError(error);
    }
  }

  async function registerModel(
    packageFile: File,
    preprocessingBundleFile: File,
  ): Promise<void> {
    if (!selectedProject) {
      return;
    }
    const created = await api.registerModel(selectedProject.id, packageFile, preprocessingBundleFile);
    await refreshProjectData(selectedProject.id);
    setNotice(registeredStatusMessage(created));
  }

  async function uploadDataset(logFile: File): Promise<void> {
    if (!selectedProject) {
      return;
    }
    const created = await api.uploadDataset(selectedProject.id, logFile);
    await refreshProjectData(selectedProject.id);
    setNotice(`HDFS dataset ${shortId(created.id)} was accepted.`);
  }

  async function startAnalysis(datasetId: string): Promise<void> {
    if (!selectedProject || !selectedModel) {
      return;
    }
    const run = await api.startAnalysis(selectedProject.id, selectedModel.id, datasetId);
    await refreshProjectData(selectedProject.id);
    setView("runs");
    setNotice(
      run.status === "queued"
        ? `Analysis ${shortId(run.id)} is queued. Status refreshes automatically every five seconds.`
        : `Analysis run ${run.id} was created with status ${run.status}.`,
    );
  }

  function showResults(run: AnalysisRun): void {
    if (!selectedProject) {
      return;
    }
    setPageError(null);
    setInspectedRun(run);
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
                datasets={datasets}
                selectedModel={selectedModel}
                onOpenAnalysis={() => setShowAnalysisDialog(true)}
                onShowResults={showResults}
                onUploadDataset={uploadDataset}
                onUnauthorized={handleRequestError}
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
          datasets={datasets}
          onClose={() => setShowAnalysisDialog(false)}
          onStart={startAnalysis}
        />
      )}
      {inspectedRun && selectedProject && (
        <ResultsDialog
          key={`${selectedProject.id}:${inspectedRun.id}`}
          projectId={selectedProject.id}
          runId={inspectedRun.id}
          onClose={() => setInspectedRun(null)}
          onUnauthorized={handleRequestError}
        />
      )}
    </div>
  );
}
