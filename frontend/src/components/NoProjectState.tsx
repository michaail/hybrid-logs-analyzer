import { FormEvent, useState } from "react";

import { Banner } from "./Banner";
import { EmptyState } from "./EmptyState";
import { messageFor } from "../lib/errors";

export function NoProjectState({
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
