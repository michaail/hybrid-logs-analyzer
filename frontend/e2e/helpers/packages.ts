import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const venvPython = path.join(repoRoot, ".venv", "bin", "python");
const python =
  process.env.E2E_PYTHON ?? (fs.existsSync(venvPython) ? venvPython : "python3");

export interface UniquePackageIdentity {
  identifier: string;
  version: string;
  zipPath: string;
  bundleZipPath: string;
}

export function uniquePackageIdentity(prefix: string): { identifier: string; version: string } {
  const suffix = `${Date.now()}-${randomUUID().slice(0, 8)}`;
  return {
    identifier: `${prefix}.${suffix}`,
    version: `v.${suffix}`,
  };
}

export function writePackageZip(
  kind: "eligible" | "ineligible",
  identity: { identifier: string; version: string },
): UniquePackageIdentity {
  const zipPath = path.join(repoRoot, ".e2e", "packages", `${identity.identifier}.zip`);
  const bundleZipPath = path.join(
    repoRoot,
    ".e2e",
    "packages",
    `${identity.identifier}.bundle.zip`,
  );
  execFileSync(
    python,
    [
      path.join(repoRoot, "scripts", "e2e_package.py"),
      "--kind",
      kind,
      "--identifier",
      identity.identifier,
      "--version",
      identity.version,
      "--output",
      zipPath,
      "--bundle-output",
      bundleZipPath,
    ],
    { cwd: repoRoot, stdio: "pipe" },
  );
  return { ...identity, zipPath, bundleZipPath };
}
