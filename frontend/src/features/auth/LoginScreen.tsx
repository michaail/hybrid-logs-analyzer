import { FormEvent, useState } from "react";

import { Banner } from "../../components/Banner";
import { messageFor } from "../../lib/errors";

export function LoginScreen({
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
