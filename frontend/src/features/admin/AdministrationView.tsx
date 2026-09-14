import { FormEvent, useState } from "react";

import { AccountSummary, ApiError, AuditEvent, Membership, ProjectRole } from "../../api";
import { Banner } from "../../components/Banner";
import { messageFor } from "../../lib/errors";
import { api } from "../../session";
import { AuditPanel } from "./AuditPanel";

export function AdministrationView({
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
