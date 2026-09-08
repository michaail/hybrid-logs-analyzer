import { defineRailway, postgres, project, service } from "railway/iac";

export default defineRailway((ctx) => {
  if (!ctx.isEnvironment("staging")) {
    throw new Error("This Railway configuration is restricted to the staging environment.");
  }

  const database = postgres("postgres");
  const web = service("web", {
    preDeploy: "python -m src.api.migrations",
    start: "uvicorn src.api.main:create_app --factory --host 0.0.0.0 --port $PORT",
    healthcheck: "/health",
    healthcheckTimeout: 100,
    replicas: 1,
    env: {
      API_JWT_TTL_MINUTES: "30",
      API_TRUSTED_WORKSPACE_ROOT: "workspace",
      DATABASE_URL: database.env.DATABASE_URL,
    },
  });

  return project("log-analyzer-staging", {
    resources: [database, web],
  });
});
