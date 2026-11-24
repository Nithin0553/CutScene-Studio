# CutScene Studio — Living Development Context

Last updated: 2026-11-24. This is the canonical handoff for the **new standalone repository**, not the earlier AI-agent research Studio.

## 1. Start here in every new chat

1. Read this file and root [AGENTS.md](AGENTS.md) before proposing or making changes.
2. Verify the current GitHub repository, branch HEAD, working-tree status (when a local checkout is available), open PR and most recent CI results. Do not assume this document is newer than Git.
3. Read the relevant implementation and regression tests; continue from the first unresolved item below unless the owner requests a different task.
4. Update this file in the same commit or PR as every code, configuration, documentation, test, or workflow change. Record native test observations and decisions here as they occur, even when no implementation changes are required.
5. Push requested changes to the active branch, verify the resulting commit, and report actual test results, blockers and local steps. Do not claim an engine test was run remotely when it was not.

Resume prompt: "Read context.md and AGENTS.md from Nithin0553/CutScene-Studio on feature/deterministic-studio-v1. Verify the latest repository state, then continue from the last unresolved step."

## 2. Repository and release state

- Repository: https://github.com/Nithin0553/CutScene-Studio (public; no declared open-source license).
- Active integration branch: `feature/deterministic-studio-v1`. Default branch `main` still contains only the initial README as of this handoff; do not tell users to clone main for the working Studio.
- Draft PR [#1](https://github.com/Nithin0553/CutScene-Studio/pull/1), targeting main. Do not merge or publish a certified release without owner approval and the acceptance evidence below.
- Original repository: `Nithin0553/CutsceneAI`; historical only. Do not change it while working on the standalone Studio.
- Exact pre-agent baseline in original repository: `3b3ef7071e4e23efefa4d1ac6c7dee3c26738153`. Selected deterministic improvements also sourced from original main snapshot `28c63e5c1eb65f499f21508b9491d7f0e9b88a5b`.
- Latest code baseline before this handoff: `9245e5b1ca467a44c03a23c28329a1fe7669a53e`. Git HEAD, not a hardcoded hash in this file, is the authoritative current revision.

## 3. Product direction and constraints

Build a simple, solid, local Unity Timeline to Unreal Level Sequence transfer Studio. Keep the default transfer deterministic: no AI agents, LangGraph, LLMs, API keys, cloud calls, or learning/dataset collection in the critical path. Historic standalone research tools and evidence are retained but are not part of the default workflow. Do not revive the old AI-agent architecture without explicit owner direction.

First release is scoped to the cinematic elements of Benchmark 001 and 002. Avoid benchmark-name-specific logic, assumptions about scene names, or fixed private paths. Use the source as authoritative. Keep the UI clean, minimal and responsive with meaningful progress animation. Do not emit unnecessary files, commit generated artifacts, overwrite existing target sequences, or restart engines repeatedly. Explicit editor approval, source asset-copy rights, backed-up target projects and guarded native execution remain required.

## 4. Architecture and implementation map

```text
Unity Timeline + PlayableDirector
  -> Unity extractor / source component census (read-only source)
  -> CSIR + source evidence
  -> deterministic CED retrieval / feature dispatch / mapping / transfer plan
  -> immutable prepared candidate + destination preflight
  -> explicit guarded Unreal worker job
  -> asset import / actor setup / Level Sequence generation
  -> native readback + CineTwin comparison / evidence / diagnostics
```

| Area | Main location |
| --- | --- |
| Windows setup and launch | tools/install_studio.ps1, tools/start_studio.ps1 |
| Local API, discovery, approval, job queue | tools/studio_local_bridge.py |
| Primary UI | apps/studio-web/index.html, cinematic.js, cinematic.css |
| Legacy advanced UI | apps/studio-web/app.js; ?advanced=1 |
| Unity package | integrations/unity/com.cutsceneai.extractor/ |
| Deterministic planning | packages/studio/ (transfer_backend.py, prepared_transfer.py, feature_dispatch.py, ced_discovery_registry.py, source_surface_gap.py) |
| Source asset inspection | tools/studio_auto_assets.py, studio_source_identity.py, studio_source_materials.py |
| Unreal editor integration | integrations/unreal/studio_local_editor_worker.py, studio_planner_sync.py, studio_destination_preflight.py, studio_auto_scene.py, studio_generation_readback.py |
| Verification | packages/cinetwin/, packages/validation/, Unreal native readback and persistence audits |
| Regression and hygiene | tests/, .github/workflows/ci.yml, tools/repo_check.py |

Studio uses a localhost HTTP server at port 8765 by default. The Unreal worker uses a file queue and Slate editor tick callback, not arbitrary remote code execution. The worker protocol is currently studio-editor-v0.6; host validates checkout and worker source hash. Local run evidence is under `~/.cutscene-studio/runs`. Source exports are inside the Unity project; generated assets are in Unreal. None belong in Git. Unity uses an explicit Export for Studio action, not a live heartbeat bridge in this version.

## 5. Installation and usage

Windows prerequisites: Git, Python 3.11+ with Tkinter, Unity 6 (package declares 6000.0 and Timeline 1.8.10), compatible Unreal Editor (UE 5.8 used in the owner's current test), and user-provided engine projects. Other engine/OS combinations are not certified.

```powershell
git clone --branch feature/deterministic-studio-v1 https://github.com/Nithin0553/CutScene-Studio.git
cd CutScene-Studio
powershell -ExecutionPolicy Bypass -File .\tools\install_studio.ps1
powershell -ExecutionPolicy Bypass -File .\tools\start_studio.ps1
```

Open http://127.0.0.1:8765. In Unity Package Manager, add from disk `integrations/unity/com.cutsceneai.extractor/package.json`. Save scene/Timeline, select PlayableDirector in Edit Mode, then Tools > CutsceneAI > Export for Studio. In Unreal enable Python Editor Script Plugin and Editor Scripting Utilities (initial activation may require restart). Use a saved backed-up destination level. In Studio choose both project roots and copy the connection command into Unreal Output Log in Python mode. Select cutscene, level, asset rights, Connect Projects, matching Source details, Start Transfer. Keep Allow partial transfer off for strict benchmarks.

Use the generated command rather than copying any old project-specific paths. The current command binds to the exact checkout and workspace. To update: stop the localhost server, pull the active branch, restart server and hard-refresh browser. Reinstall dependencies only when necessary. If Git reports dubious ownership on a trusted filesystem, add only the specific repository to safe.directory; never disable ownership checks globally.

### Unreal automatic startup and previous blocker

Confirmed in owner's native session: an old `Content/Python/init_unreal.py` in the destination project automatically loaded the older repository from a different drive and the legacy `~/.cutsceneai-studio/runs` workspace. Restart alone failed until that startup script was backed up and updated to load the new checkout and `~/.cutscene-studio/runs`. After fully closing Unreal and reopening, the user reported the new module path, new workspace and a registered delegate handle. A project-local bootstrap is optional for new users; preserve unrelated startup content and do not automatically overwrite existing scripts. Automatic installation from Studio is not implemented.

For connection troubleshooting, in Unreal's Python Console inspect:
```python
import studio_local_editor_worker as w; print(w.__file__); print(w.WORKSPACE); print(w.HANDLE)
```
Use the correct checkout, workspace, target project and level. If an old module is cached, stop it only when no job is active, save, fix conflicting project startup settings, completely close Unreal, and reopen once. Never reload or purge arbitrary engine modules during a running job.

## 6. Evidence and current status

| Area | Evidence / state |
| --- | --- |
| Deterministic standalone integration | Implemented on active branch; prior historical benchmark passes are not new certification |
| Windows install and localhost UI | Automated checks pass; owner launched and used UI locally |
| Unity source export | One menu action writes unique CSIR and matching census; owner selected Benchmark 001 in UI |
| Unreal connection | Owner confirmed correct new module, workspace and registered handle after fixing startup script |
| Native sequence generation | Owner screenshot shows generated Level Sequence open in Unreal AI_Test04 with tracks and Benchmark_Event_01 marker; no complete run receipt or fidelity report supplied |
| Native visual result | Screenshot showed dark/black viewport; cause not established. Could be empty/unlit environment, camera/framing, asset setup, or visibility issue. Inspect before changing source-equivalent scene |
| Benchmark 001 | New native full acceptance not yet verified |
| Benchmark 002 | New native full acceptance not yet verified |
| Automated tests | Verified at handoff HEAD 3702f93: [push CI 45452676096](https://github.com/Nithin0553/CutScene-Studio/actions/runs/45452676096) and [PR CI 45452697076](https://github.com/Nithin0553/CutScene-Studio/actions/runs/45452697076) succeeded; push jobs on Windows and Ubuntu passed Python compilation, pytest, JS syntax and UI regression, Ruff and repository hygiene. Last implementation baseline 9245e5b also passed. |
| Public stable release | Not merged; no declared license; release candidate only |

Known UI limitations: project folder checkmarks/toast are not proof of a live editor connection; transfer screen now reflects actual target editor validity, but project screen still has folder-validation indicators. Multiple valid matching source records require manual selection; auto-select exists only for a single valid match. Source details may include partially captured components (collision/URP/signal behavior not Unreal-verified). Keep those limitations explicit. No blanket partial-transfer override to hide errors.

## 7. Benchmark acceptance

Authoritative references: [Benchmark 001](docs/benchmarks/BENCHMARK_001.md), [Benchmark 002](docs/benchmarks/BENCHMARK_002.md), benchmark source/target freeze and pipeline correction docs. Treat historical docs as evidence from the original system, not current branch/CI status.

- B001: one humanoid and skeletal clip, root/keyed motion, moving prop, two cameras and cut, animated camera transform, FOV/lens, audio, event and static environment. Verify structural, timing, spatial, animation and audio/event fidelity in native engines.
- B002: 12 seconds, 24 fps, two independently animated characters (overlapping clips and root motion), moving and parented props, three cameras with cuts at 4 and 8 seconds, animated lens/light, overlapping audio with fades, three events including payload. Material/environment fidelity must be inspected where authored. Do not hardcode names or timing into general conversion.
- Inspect generated actors/assets, hierarchy, root trajectories and orientations, camera identities/cuts/framing/lens, timing, blend/section behavior, light/material/audio/event behavior. Report unsupported features and quantization explicitly. Save/reopen Unreal level and sequence and verify persistence. Preserve original source and targets.
- Generated sequence alone does not equal verified cinematic fidelity; require source-bound readback and measured acceptance evidence. Arbitrary skeleton retargeting, scripts/shaders, VFX, physics/gameplay and broad unsupported combinations are outside the first-release promise.

## 8. Next work (ordered by current state)

1. Continue the owner's native Benchmark 001 test from the generated sequence. Collect Studio Results, run/job ID, native receipts/readback, output log and Unity/Unreal comparisons. Inspect actors and camera view in the dark level; distinguish missing environment light from failed transfer before modifying anything. A Basic/Open World map may be useful for separate visual testing, not as unreported benchmark evidence.
2. Diagnose any actual fidelity gaps, implement general deterministic fixes with regression tests, push and re-test native B001 including save/reopen.
3. Run B002 in a fresh backed-up target, verify all its requirements and persistence; record unresolved scope honestly.
4. Improve onboarding: clear distinction between valid folder vs live editor; safely resolve matching source details without manual selection when unambiguous; project-local companion installation/repair with explicit approval, backups and conflict detection. Avoid repeated engine restarts.
5. Review the draft PR, confirm clean checkout install and current CI, document license/release decision with owner, and merge/tag only after explicit approval and acceptance.

### Resume checkpoint: collect B001 evidence before changing conversion

- On the existing local run, open Studio > Results (or View Previous Transfer Report) > View Report. Capture the sequence name, asset/binding counts, job status, native structure, persistence, CineTwin and visual status. The Results UI deliberately does not equate generation success with fidelity. A screenshot of the report and both engine views at matching timeline positions is useful.
- Preserve the existing candidate and saved output. In PowerShell, read the active job pointer and corresponding job JSON without changing anything:

```powershell
$root = Join-Path $HOME '.cutscene-studio\runs'
$active = Get-Content -Raw (Join-Path $root 'active-job.json') | ConvertFrom-Json
$job = Get-Content -Raw (Join-Path $root ('jobs\' + $active.job_id + '.json')) | ConvertFrom-Json
$job | Select-Object job_id,candidate_id,status,generation_status,generated_sequence,sequence_path,assets_imported_count,bindings_created_count,fidelity_verified,visual_audit_status,closed_loop_status,error | Format-List
Get-ChildItem -LiteralPath (Join-Path $root ('candidates\' + $job.candidate_id)) -File | Select-Object Name,Length
```

- The active pointer may refer to a newer run: confirm the job and generated sequence match B001 before relying on them. Retain the exact job's receipt, generation readback, hierarchy audit, diagnostic and closed-loop report when available. Missing evidence is not a passing result. Review all local logs, file paths and reports for sensitive information before sharing; never commit them. Do not share `/api/status` output because it contains a local token.
- In Unreal, inspect the saved destination level in a free Perspective viewport with Sequencer camera lock disabled, frame an existing generated actor, and compare Lit and Unlit view modes. Scrub the same timeline frame with camera lock enabled and compare with Unity. If the actor is visible in Unlit but not Lit, lighting is a candidate cause; if the camera view alone is black, inspect camera binding, transform and cut before altering the environment. Do not add lights, move actors, replace cameras or regenerate the candidate as a first diagnostic step. A different map is a separate test, not evidence for the existing run.
- Once the scene is saved and the initial evidence is captured, a controlled reopen in a new Unreal process is needed for independent persistence verification; this is an acceptance test, not a recurring connection requirement.

Implementation inspected at 3702f93: `apps/studio-web/cinematic.js` Results and View Report, `tools/studio_local_bridge.py` job/diagnostic/verification endpoints and `integrations/unreal/studio_generation_readback.py`. No implementation change is justified until native evidence identifies the gap. Local working-tree status and native engine results cannot be verified from the GitHub connection alone.

## 9. Verification commands

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_studio.ps1 -Dev
.\.venv-studio\Scripts\python.exe -m pytest -q
.\.venv-studio\Scripts\python.exe -m ruff check tests
node --check apps/studio-web/app.js
node --check apps/studio-web/cinematic.js
node tests/studio/test_cinematic_ui.cjs
.\.venv-studio\Scripts\python.exe tools/repo_check.py
```

Node.js is only needed for UI tests. CI checks compileall, Python regressions, JS syntax/UI tests, Ruff and hygiene on Windows and Ubuntu. Actual Unity compilation and Unreal native execution must be verified separately; use local evidence supplied by the owner when the engines are not accessible.

## 10. Change log and maintenance

Keep this concise and newest-first. For every change add date, summary, affected paths, tests/evidence, remaining blockers, and next action. Refresh sections above when facts change. Do not include credentials, private absolute paths, personal details or generated logs in this public handoff. If older entries grow too long, archive them with provenance rather than losing unresolved work.

| Date | Change / evidence |
| --- | --- |
| 2026-11-24 | Resumed from 3702f93; verified draft PR #1 remains open targeting unchanged main and both push/PR CI passed. Inspected Results/job/readback implementation; documented read-only B001 evidence collection and black-viewport isolation in section 8. Documentation only; no new local or native tests run. Next: owner supplies matching B001 run evidence before conversion changes. |
| 2026-11-24 | Created living context and AGENTS.md, linked from README, corrected clone command and obsolete contribution instructions. Documentation-only; no engine code changed. |
| 2026-11-24 | Owner corrected legacy project startup script, verified new Unreal worker and workspace; generated B001 sequence visible in screenshot. Black viewport/full native fidelity remain open. |
| 2026-11-24 | 9245e5b: exact checkout/workspace, immediate heartbeat, repeated-start diagnostic, target level mismatch display and transfer-screen connection indicators. Windows/Ubuntu CI passed. |
| 2026-11-24 | 74f1de1: connection command exposed before transfer, missing Unity export guidance; CI passed. |
| 2026-11-24 | f9df6ec: one-click Unity export and remove default learning/suggestion side effects. CI passed. |
| 2026-11-24 | ea524a6 / 96b5227: integrate deterministic adapter improvements, minimal UI, isolated Windows setup, cross-platform regression and startup smoke; CI passed after syntax/fixture corrections. |
| 2026-11-24 | b2bd596: import exact pre-agent baseline into independent repository; draft PR #1 created later. |
