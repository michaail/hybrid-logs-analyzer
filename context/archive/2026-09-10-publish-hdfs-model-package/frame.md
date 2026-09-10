# Frame Brief: publish-hdfs-model-package

> Framing step before /10x-plan. This document captures what is *actually*
> at issue, separated from what was initially assumed.

## Reported Observation

A Publisher cannot get a complete HDFS model package from their machine into the web workflow. Registration only accepts a pre-staged trusted-workspace directory; Railway staging has no usable workspace for that. Ineligible packages already get a structured 422, and explicit publish already exists for eligible versions.

## Initial Framing (preserved)

- **User's stated cause or approach**: Roadmap S-02 / change title treat “upload + reject + explicit publish” as one north-star slice (`publish-hdfs-model-package`). Research’s hypothesis is that the remaining gap is bytes intake, not the publish gate. Frame only if that premise still needs checking.
- **User's proposed direction**: Challenge the framing if needed, then plan S-02.
- **Pre-dispatch narrowing**: Leading concern not separated yet. Slice observable stops at: a Publisher can submit a package from outside the API host and get either a clear rejection or an eligible version. Explicit publish and analysis-runnability are out of this observation.

## Dimension Map

The observation could originate at any of these dimensions:

1. **Admission surface (API + UI)** — there is no byte channel; only a host directory path is accepted
2. **Durable materialization** — arrived bytes have no shared immutable home (workspace-only pointers; Railway has no trusted workspace)
3. **Eligibility contract** — the validator rejects packages so nothing becomes eligible
4. **Publication lifecycle** — eligible → published is what’s actually missing ← initial framing (slice title)

## Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| Admission surface: HTTP/UI only accept a workspace directory `package_reference`; no package-byte channel | JSON-only request `src/api/schemas.py:152-155`; directory gate `src/api/validation.py:48-56`; register `src/api/main.py:376-393`; no `UploadFile`/`FormData`/`type="file"` in `src/` or `frontend/`; UI path dialog `frontend/src/App.tsx:1272-1284`; ZIP 422 locked `tests/test_api.py:878-891` | STRONG |
| Durable materialization: no immutable shared place; register writes `workspace` / null checksum | Defaults `src/api/storage.py:487-493`; HTTP omits object kwargs `src/api/main.py:423-435`; no Bucket client `src/api/settings.py:13-21`; deploy-plan workspace unusable / Bucket unattached `context/deployment/deploy-plan.md:57-64`. **Follow-on once bytes exist**, not why they never arrive | STRONG as follow-on; WEAK as origin of off-host submit |
| Eligibility contract: packages cannot become eligible | Inverse: directory packages register 201 eligible `tests/test_api.py:416-419`, `:977-981`; 422 is for ineligible packages, 503 only for validator crash | NONE |
| Publication lifecycle (slice title): publish gate is the gap | Inverse: `/publish` `src/api/main.py:460-485`; CAS `src/api/storage.py:572-581`; Operator 403 `tests/test_api.py:429-435`; Publisher 200 `:436-441`; analysis requires published `src/api/main.py:516-520`; UI Publish `frontend/src/App.tsx:621-624` | NONE |

## Narrowing Signals

- User placed the slice’s observable at **off-host submit → structured rejection or eligible version**, not at publish or analysis-runnability.
- Step 3 found strong evidence for admission, none for eligibility or publish. Extra narrowing questions skipped.
- Independent search (no hypothesized cause in the prompt) ranked the same API admission boundary first; UI and storage as followers.
- Inverse: if admission were *not* the break, a working byte channel would exist. It does not.
- Prior decisions match: F-02 “S-02 still owns browser upload”; PRD Open Question 2 defers browser upload of package bytes; F-01 out-of-scope “Browser or API multipart upload of models (S-02)”.

## Cross-System Convention

This project already splits **eligibility** (completeness/compatibility check, no quality claim) from **publication** (explicit audited gate) from **inference**. F-02 closed the contract and directory admission and parked byte intake. The class of observation “Publisher cannot get a package in” is handled by adding an admission channel in front of that pipeline, not by rebuilding publish. Storage materialization is the usual companion once bytes exist (declared files only, object-kind pointers) — a constraint on staying eligible after arrival, not the origin of the missing submit.

## Reframed (or Confirmed) Problem Statement

> **The actual problem to plan around is**: a Publisher has no way to submit a complete HDFS model package from outside the API host and receive either a structured rejection or an eligible version.

The slice title and US-01 wording bundle upload, reject, and publish. Explicit publish and eligibility-for-on-disk-packages already work. Planning “publish an HDFS model package” as if the gate were missing would rebuild a finished lifecycle and still leave the Publisher unable to get bytes in. Addressing admission (with durable placement so an off-host submit can become an eligible row) is what changes the observation.

## Confidence

- **HIGH** — strong evidence + matches convention + decisive narrowing signal

Independent search confirmed the same origin. User narrowing already excluded publish and analysis as this slice’s observable.

## What Changes for /10x-plan

The plan should be about **admitting a complete HDFS package from outside the API host through to a structured 422 or an eligible version**, keeping the existing explicit-publish gate. Durable materialization belongs only insofar as arrival cannot become a lasting eligible row without it — not as a substitute for the missing intake surface, and not as inference (S-04).

## References

- Source files: `src/api/validation.py:48-56`, `src/api/schemas.py:152-155`, `src/api/main.py:376-485`, `src/api/storage.py:487-581`, `frontend/src/App.tsx:1272-1284`, `tests/test_api.py:416-441`, `tests/test_api.py:878-891`
- Related research: `context/changes/publish-hdfs-model-package/research.md`
- Prior decisions: `context/archive/2026-09-09-trusted-model-package-contract/plan-brief.md`, `context/foundation/prd.md` Open Question 2, `context/deployment/deploy-plan.md:57-64`
- Investigation tasks: `2272bc0d-4faa-438c-8c46-3d3962521d65` (admission), `9d369ef8-5cef-47c6-9e96-cfff3b103643` (storage), `afef2d4c-5757-4f5b-bbff-4c2d36f54ac6` (eligibility), `19811b4a-c3c7-49ae-b19f-109b335666a1` (publish), `8c5460f5-cf71-43b1-a17d-1f47669ef882` (independent origin)
