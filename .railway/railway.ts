import { bucket, defineRailway, postgres, preserve, project, ref, service } from "railway/iac";

// Immutable Bucket region. Must match the staging project used by web and PostgreSQL.
const STAGING_BUCKET_REGION = "ams" as const;
const INFERENCE_PRIVATE_URL = "http://inference.railway.internal:8080";

export default defineRailway((ctx) => {
  if (!ctx.isEnvironment("staging")) {
    throw new Error("This Railway configuration is restricted to the staging environment.");
  }

  const database = postgres("postgres");
  const objects = bucket("models", { region: STAGING_BUCKET_REGION });
  const sharedStore = {
    DATABASE_URL: database.env.DATABASE_URL,
    API_OBJECT_STORE_ENDPOINT: ref(objects, "ENDPOINT"),
    API_OBJECT_STORE_BUCKET: ref(objects, "BUCKET"),
    API_OBJECT_STORE_ACCESS_KEY_ID: ref(objects, "ACCESS_KEY_ID"),
    API_OBJECT_STORE_SECRET_ACCESS_KEY: ref(objects, "SECRET_ACCESS_KEY"),
    API_OBJECT_STORE_REGION: ref(objects, "REGION"),
  };
  const web = service("web", {
    build: {
      builder: "DOCKERFILE",
      dockerfilePath: "Dockerfile",
    },
    preDeploy: "python -m src.api.migrations",
    start: "uvicorn src.api.main:create_app --factory --host 0.0.0.0 --port $PORT",
    healthcheck: "/health",
    healthcheckTimeout: 100,
    replicas: 1,
    env: {
      API_JWT_TTL_MINUTES: "30",
      API_TRUSTED_WORKSPACE_ROOT: "workspace",
      INFERENCE_SERVICE_URL: INFERENCE_PRIVATE_URL,
      INFERENCE_INTERNAL_TOKEN: preserve(),
      ...sharedStore,
    },
  });
  const inference = service("inference", {
    build: {
      builder: "DOCKERFILE",
      dockerfilePath: "Dockerfile.inference",
    },
    start: "python -m src.inference_service",
    healthcheck: "/health",
    healthcheckTimeout: 300,
    replicas: 1,
    deploy: {
      sleepApplication: true,
    },
    env: {
      INFERENCE_INTERNAL_TOKEN: preserve(),
      ...sharedStore,
    },
  });

  return project("log-analyzer-staging", {
    resources: [database, web, inference, objects],
  });
});
