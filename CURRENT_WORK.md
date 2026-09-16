# Current Work: Vercel Streamlit Demo Deployment

Status: paused at human/platform gate — automatic `Dockerfile.vercel` repository exists, but VCR denies Vercel's own build push
Started: 2026-07-31
Branch/Worktree: `codex/technical-review-o1` / `F:\外贸化工\.worktrees\technical-review-o1`

## Objective

Deploy the existing bilingual Streamlit chemical inquiry workspace to a public Vercel URL with the approved public, sanitized materials bundled read-only, leaving only `DEEPSEEK_API_KEY` for the user to enter in Vercel.

## Scope

- Add the minimum Vercel Docker deployment configuration for the existing Streamlit entry point.
- Bundle only the already approved public, sanitized catalog, PDFs, and Chroma index needed by the demo.
- Make the container bind to Vercel's assigned port and expose a health-checkable public service.
- Keep the DeepSeek key out of source, Git, build output, logs, and conversation output.
- Create and deploy the Vercel project, then verify the public no-key state; provide the exact final key-entry and redeploy steps.

## Non-goals

- No Next.js rewrite, serverless-function rewrite, external vector database, durable user storage, account system, email sending, production hardening, or long-term hosting migration.
- No modification, regeneration, deletion, or write-back of controlled source materials or indexes.
- No app-level password or additional user-managed environment variable in this phase.
- No commit, push, PR, or secret entry by Codex.
- No automated choice of Vercel account, team, plan, billing setting, production domain, data-publication exception, or other decision where the user's direct judgment is safer or more effective.

## Starting Evidence

- The prior task `019fb33c-feaa-7261-af87-522670602c1c` explicitly authorized Codex to prepare and deploy everything except entering the user's API key.
- The user confirmed the materials are public and already sanitized.
- Branch `codex/technical-review-o1` is at `79c1cab` with substantial uncommitted application changes from the completed UI/review stages; they must be preserved.
- The worktree has no existing Dockerfile, Vercel configuration, or `.vercel` project link.
- Local Streamlit uses Python 3.11-compatible dependencies from `pyproject.toml`; the approved application entry point is `src/chemical_trade_copilot/streamlit_app.py`.
- Historical verification from the prior task reported 339 passing tests and a working desktop BAT; this is baseline context, not current deployment evidence.

## Acceptance Evidence

- A deployment-focused test fails before configuration and passes after the minimal deployment files are added.
- A local container build succeeds from a clean build context and starts the real Streamlit app on an injected `PORT` without writing the bundled index or materials.
- The no-key app returns HTTP 200 and presents a clear configuration-required state rather than crashing or leaking internals.
- Vercel deployment reaches a public URL and returns HTTP 200 in the no-key state.
- Fresh related tests, the full suite, `compileall`, `pip check`, `git diff --check`, credential scans, and deployment artifact audits pass.
- The user receives exact Vercel steps for setting `DEEPSEEK_API_KEY` and triggering the resulting production redeploy.

## Milestones

- [x] M1: Confirm current Vercel Docker requirements, CLI authentication, build context, and public-data paths.
- [x] M2: Add a failing deployment contract test, confirm the expected failure, then implement the minimum configuration.
- [x] M3: Verify the real Streamlit process with deployment paths, HTTP 200, bilingual no-key behavior, catalog hashes, and runtime index isolation. A local container build is unavailable because Docker is not installed and is explicitly not claimed.
- [ ] M4: Create/deploy the Vercel project, verify the public no-key URL, and record the rollback target.
- [ ] M5: Run fresh full verification, audit scope/credentials/artifacts, remove only task-owned probes, and close the temporary record.

## Decisions and Constraints

- Use Vercel's official Dockerfile deployment path; do not add a second application implementation.
- The approved deployment is public and has no app password. Consequently, after the key is configured, any visitor can consume the associated DeepSeek quota; this is an accepted demo limitation, not a production security posture.
- `DEEPSEEK_API_KEY` remains user-managed in Vercel and is never requested or inspected by Codex.
- External-write approval point: the user's latest instruction authorizes creation and deployment of the Vercel project only when the authenticated account, scope, plan, cost, public-data set, and rollback target are already unambiguous. Stop and transfer the step to the user whenever Vercel login, account/team/plan/billing selection, API-key entry, public-scope judgment, CAPTCHA/MFA, or another human decision would produce a safer or better result.
- Human-first stop rule: do not work around an interactive or judgment-dependent platform gate. Report the exact completed evidence, the exact manual action required, and the single safe resume point, then stop execution promptly.
- Documentation lifecycle: this `CURRENT_WORK.md` is the authoritative temporary deployment plan. Do not update a permanent runbook until the deployment workflow has succeeded once and is demonstrably reusable; if it succeeds, record only the repeatable manual steps and safety gates before deleting this temporary file.
- Rollback: remove the exact Vercel project created for this task and delete only the deployment files introduced by this task. Preserve all pre-existing application changes, materials, indexes, and local launcher behavior.

## Findings and Failures

- Streamlit skill discovery initially selected system `python3` because the isolated worktree's virtual environment lives at the main repository root. Setting `VIRTUAL_ENV=F:\外贸化工\.venv` resolved the installed Streamlit 1.60 reference path without changing the environment.
- `rg` is not executable in the current PowerShell host, so repository searches use Git and PowerShell fallbacks.
- Official Vercel guidance current on 2026-07-31 confirms root-level `Dockerfile.vercel`, `$PORT` HTTP serving, stateless container images, and native WebSocket support on Fluid Compute in public beta. New projects created after 2026-06-30 are automatically eligible for Large Functions up to 5 GB; the current local dependency footprint does not require a pre-deployment architecture change.
- Docker is not installed locally. The task therefore verified the same Streamlit command and deployment data paths as a host process, but did not perform or claim a local OCI image build.
- No cached Vercel authentication was found. Account, team, plan, and billing scope cannot be safely inferred and require the user's manual login and explicit confirmation before project creation.
- The user completed Vercel login and explicitly selected the personal Hobby scope. Project `chemical-trade-copilot-demo` was then created under that personal scope and linked locally. Vercel generated ignored local authentication state; its contents were not read, printed, or committed.
- The first real browser probe imported the main checkout's older editable package because the isolated worktree shares a root virtual environment. A single-variable check proved that setting `PYTHONPATH` to the worktree `src` selects the correct module. This affects only local validation; `pip install .` inside the container installs the worktree source directly.
- Opening Chroma directly against the bundled deployment index changed the task-owned SQLite copy by 4096 bytes. The Docker command now copies the immutable image index to a unique `/tmp` runtime directory before Streamlit starts. A fresh runtime fingerprint check passed while the bundled six-file index remained byte-identical to the formal source index.
- The first full-suite invocation omitted the controlled deployment environment and produced UI failures after workspace restoration. A representative failure passed when only the three approved deployment paths were restored, and the fresh full suite then passed under the deployment environment. No assertions or acceptance targets were relaxed.
- The first preview upload ended with a client-side `fetch failed` and created no deployment. Five subsequent Node fetch probes reached Vercel normally, so one bounded standard deploy was attempted without log streaming.
- The bounded deploy completed the full 11-step container build and installed the application dependencies, but Vercel denied the final push to `vcr.vercel.com/.../dockerfile`. In the same build, the platform first reported that it had ensured/created the project-scoped `dockerfile` repository. The user then confirmed that the personal Hobby project's Sandboxes page has only Overview and Snapshots, did not create a Sandbox or upgrade, and explicitly directed the task to continue through the automatic `Dockerfile.vercel` path.
- Official Vercel documentation current on 2026-07-31 confirms that a root-level `Dockerfile.vercel` requires no separately configured registry: `vercel deploy` detects it, builds the image, stores it in the project-scoped VCR, and deploys it as a Function. Sandbox is a separate execution product and is not required for this route. Because the first completed build created the repository only after its deployment token had already been issued, one fresh deployment is an evidence-based test of newly issued access to the now-existing repository, not a request to create a Sandbox or change plans.
- The authorized fresh deployment `dpl_ESi6VGbNipjf614xvABLHoTnR7tP` disproved the token-timing hypothesis. Vercel authenticated successfully, reported `repository "dockerfile" already exists`, rebuilt all 11 image steps, and again failed only at its own final `buildah push` with exit code 125/access denial. The automatic repository therefore exists; the remaining blocker is Vercel-side VCR authorization/entitlement for this personal Hobby project. The human-first stop condition is met. No Sandbox was created, no plan was changed, and no further deployment or dependency redesign is authorized.

## Verification Log

- 2026-07-31: Read repository engineering rules and playbook; captured main-repository and isolated-worktree Git status. No deployment files or external Vercel state changed yet.
- 2026-07-31: User added a human-first execution rule. Deployment boundaries now require an immediate stop for login, MFA/CAPTCHA, account/team/plan/billing choice, API-key entry, public-scope judgment, or any step where manual handling is safer or more effective.
- 2026-07-31: Deployment contract tests first failed for the expected missing Dockerfile, ignore rules, bundled PDFs/index, public-demo copy, and no-key UI notice. After the minimum implementation, all deployment-focused tests passed.
- 2026-07-31: All six enabled public PDFs matched the approved catalog SHA-256 values. The deployment package contains 12 data files totaling 6,767,854 bytes: six PDFs and six index files.
- 2026-07-31: Real Streamlit started on `127.0.0.1:8514` with deployment materials/catalog/index paths and returned health HTTP 200. Real Chromium rendered the English and Chinese no-key notices and the public-demo footer.
- 2026-07-31: Fresh deployment-environment full suite passed 344/344. `compileall -q src tests`, `pip check`, `git diff --check`, and the task-text credential-shape scan completed successfully; credential-shape matches were zero.
- 2026-07-31: Task-owned port 8514 and both Playwright sessions were stopped. The task-only probe directory and four task-created snapshots were removed after exact-path inspection; 35 pre-existing Playwright artifacts, the output root, formal materials, and formal index were preserved.
- 2026-07-31: User confirmed personal Hobby scope after manual Vercel login. Vercel project `chemical-trade-copilot-demo` was created and linked. The initial preview upload failed with `fetch failed` and left no deployment. One evidence-based bounded retry built the complete image but failed at the final Vercel Container Registry push with an access-denied error. No live preview or production deployment exists yet.
- 2026-07-31: User confirmed the Hobby UI has no Container Registry entry and explicitly selected Vercel's automatic `Dockerfile.vercel` repository workflow without creating a Sandbox or upgrading. Official documentation supports that boundary. A single fresh deployment is authorized to test whether a new deployment credential can push to the repository the preceding build created; an identical denial is the immediate stop condition.
- 2026-07-31: The single authorized fresh deployment (`dpl_ESi6VGbNipjf614xvABLHoTnR7tP`, preview URL `https://chemical-trade-copilot-demo-lmsz6ngw8.vercel.app`) authenticated to VCR and found the automatic `dockerfile` repository, but the final VCR push failed again after the full image build. This is fresh proof that repository auto-creation is working and the Vercel-side push permission is not. Execution stopped immediately under the human-first rule; the URL is a failed deployment, not a live preview.

## Next Action

Human action: report the Vercel-side VCR authorization defect for project `lujiamingsssss-cpus-projects/chemical-trade-copilot-demo` to Vercel, including failed deployment IDs `dpl_CjKST3vyEYvALPtJxbML8vdxmgZy` and `dpl_ESi6VGbNipjf614xvABLHoTnR7tP`. State that `Dockerfile.vercel` auto-created/found repository `dockerfile`, authentication succeeded, but Vercel's own `buildah push` was denied. Do not create a Sandbox or upgrade unless the user independently chooses that change after Vercel explains the plan boundary. Resume only after Vercel confirms the authorization issue is fixed; then run one deployment and verify the no-key state. The user remains responsible for entering `DEEPSEEK_API_KEY` later.
