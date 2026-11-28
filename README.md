# CutScene Studio

A local Unity Timeline → Unreal Level Sequence transfer tool with an optional single Ollama/LangGraph agent and deterministic engine adapters.

**Release candidate — native editor validation required.** Deterministic transfer works without an AI provider. The optional AI workflow uses local Ollama and LangGraph; it requires no cloud API key. Native execution remains deterministic and explicitly authorized. This independent repository derives from the original pre-agent Studio and retains selected deterministic integration fixes. Historical benchmark passes are not a certification of this new build.

## Development handoff

Read [context.md](context.md) and [AGENTS.md](AGENTS.md) before continuing development. The context file records current repository state, native evidence, known blockers and next steps; update it with every change.

## Quick start (Windows)

Install Git, Python 3.11+, a compatible Unity editor with Timeline, and Unreal Engine with Python Editor Script Plugin and Editor Scripting Utilities enabled. Use a backed-up target project.

```powershell
git clone --branch feature/deterministic-studio-v1 https://github.com/Nithin0553/CutScene-Studio.git
cd CutScene-Studio
powershell -ExecutionPolicy Bypass -File .\tools\install_studio.ps1
powershell -ExecutionPolicy Bypass -File .\tools\start_studio.ps1
```

Open http://127.0.0.1:8765. For the optional AI workflow, run the installer with `-Agent` (or `-Dev` for tests), install Ollama separately, and make the local `qwen2.5:7b-instruct` model available. The installer does not download or start an AI model. Select `-StorageRoot` for package caches and temporary files; the checkout and virtual environment remain where you placed them.

### Connect the editors

1. In Unity Package Manager, use **Add package from disk** and choose `integrations/unity/com.cutsceneai.extractor/package.json` in the cloned repository. Let Unity compile.
2. Open a saved cutscene scene and select its PlayableDirector. In Unity, choose **Tools > CutsceneAI > Export for Studio** (exports the cutscene and its source details together).
3. Open the intended saved destination level in Unreal. Enable Python Editor Script Plugin and Editor Scripting Utilities if not already enabled; the initial plugin activation may require an editor restart. Choose the project's folder in Studio and copy the connection command shown on the Projects screen (before connecting projects or starting transfer) into Unreal's Python Console.
4. Select the Unity and Unreal projects in Studio, choose the cutscene and target level, approve source asset-copy rights, and connect. If multiple matching source records exist, select the one from your latest export. Press **Start Transfer**. Inspect Results and the generated Level Sequence.

### Optional AI workflow

Enable AI Agent on the Projects screen and prepare the source-bound plan. Review withheld mappings and source limitations. Use the read-only target inspection, allow Ollama's resident model to expire, then explicitly authorize the exact candidate. No execution is queued during AI analysis.

After generation, the Results page can request one repair proposal. Only eligible source-backed skeletal-root motion corrections can currently become a fresh repair candidate. Select a separate saved empty staging map in the same backed-up project and inspect and authorize again. The original transfer is preserved; the comparison reports measured position-error changes, not full fidelity.

The worker stays connected while the editor runs. Use a fresh target and never overwrite an original cutscene. The engine editors are not started or stopped by Studio.

## First-release scope

Only the deterministic feature families authored in Benchmark 001 and 002 are in scope: transforms and hierarchy, character animation and root motion, static and moving props, cameras/cuts/lens, supported lights, audio sections/fades and event markers. Compatible source assets and native import support are prerequisites. No general retargeting, arbitrary scripts or shaders, VFX, physics or gameplay reconstruction.

See [Benchmark 001](docs/benchmarks/BENCHMARK_001.md) and [Benchmark 002](docs/benchmarks/BENCHMARK_002.md) for the source requirements. Generation is not proof of fidelity. Each feature must be independently validated in both engines and the saved result reopened before a release is certified.

## Tests

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_studio.ps1 -Dev
.\.venv-studio\Scripts\python.exe -c "import langgraph.graph, langsmith"
.\.venv-studio\Scripts\python.exe -m compileall -q packages tools integrations/unreal
.\.venv-studio\Scripts\python.exe -m pytest -q -rs
.\.venv-studio\Scripts\python.exe -m ruff check tests
node --check apps/studio-web/app.js
node --check apps/studio-web/cinematic.js
node tests/studio/test_cinematic_ui.cjs
.\.venv-studio\Scripts\python.exe tools/repo_check.py
```

Node.js is needed only for UI regression testing. Automated tests cover software contracts and a real localhost launch, not the installed native game engines. Keep editors and Ollama closed for the software-only suite. Review skip reasons; developer-local historical Stage 4 fixture skips are not native passes, and missing LangGraph must not be accepted as full AI regression coverage.

The Windows launcher stores new candidate plans and execution evidence in `runs` beside the repository (under the parent of the checkout). To select another existing storage root, use `-StorageRoot` with a local directory; use `-CheckOnly` to create/check the directories and Python prerequisites without starting the server. The launcher configures process-local package caches and temporary storage under the same root. The backend's direct CLI still accepts `--workspace`; use the connection command generated by the running Studio to bind Unreal to that exact workspace. Existing home-directory runs are not moved; preserve them and do not redirect an active editor worker while a job is running. Source exports live in the Unity project, and generated assets in the selected Unreal project. Keep all of these out of Git. No engine assets are included in this repository.

Historical benchmark evidence and standalone research utilities are retained; the default Studio transfer never invokes learning or dataset collection and does not generate suggestion files. This repository does not yet declare an open-source license.
