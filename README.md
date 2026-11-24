# CutScene Studio

A local, deterministic Unity Timeline → Unreal Level Sequence transfer tool.

**Release candidate — native editor validation required.** No AI services, LangGraph, API keys, or cloud calls are required for transfer. This independent repository derives from the original pre-agent Studio and retains selected deterministic integration fixes. Historical benchmark passes are not a certification of this new build.

## Quick start (Windows)

Install Git, Python 3.11+, a compatible Unity editor with Timeline, and Unreal Engine with Python Editor Script Plugin and Editor Scripting Utilities enabled. Use a backed-up target project.

```powershell
git clone https://github.com/Nithin0553/CutScene-Studio.git
cd CutScene-Studio
powershell -ExecutionPolicy Bypass -File .\tools\install_studio.ps1
powershell -ExecutionPolicy Bypass -File .\tools\start_studio.ps1
```

Open http://127.0.0.1:8765.

### Connect the editors

1. In Unity Package Manager, use **Add package from disk** and choose `integrations/unity/com.cutsceneai.extractor/package.json` in the cloned repository. Let Unity compile.
2. Open a saved cutscene scene and select its PlayableDirector. In Unity, choose **Tools > CutsceneAI > Export Selected Timeline**, then **Discover Installed Feature Surface**.
3. Open the intended saved destination level in Unreal. Enable Python Editor Script Plugin and Editor Scripting Utilities if not already enabled; the initial plugin activation may require an editor restart. Choose the project's folder in Studio and copy the connection command shown on the Transfer screen into Unreal's Python Console.
4. Select the Unity and Unreal projects in Studio, choose the cutscene and target level, approve source asset-copy rights, and connect. If multiple matching source records exist, select the matching one. Press **Start Transfer**. Inspect Results and the generated Level Sequence.

The worker stays connected while the editor runs. Use a fresh target and never overwrite an original cutscene. The engine editors are not started or stopped by Studio.

## First-release scope

Only the deterministic feature families authored in Benchmark 001 and 002 are in scope: transforms and hierarchy, character animation and root motion, static and moving props, cameras/cuts/lens, supported lights, audio sections/fades and event markers. Compatible source assets and native import support are prerequisites. No general retargeting, arbitrary scripts or shaders, VFX, physics or gameplay reconstruction.

See [Benchmark 001](docs/benchmarks/BENCHMARK_001.md) and [Benchmark 002](docs/benchmarks/BENCHMARK_002.md) for the source requirements. Generation is not proof of fidelity. Each feature must be independently validated in both engines and the saved result reopened before a release is certified.

## Tests

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_studio.ps1 -Dev
.\.venv-studio\Scripts\python.exe -m pytest -q
node tests/studio/test_cinematic_ui.cjs
.\.venv-studio\Scripts\python.exe tools/repo_check.py
```

Node.js is needed only for UI regression testing. Automated tests cover software contracts and a real localhost launch, not the installed native game engines.

Studio writes its required local candidate plans and execution evidence under `~/.cutscene-studio/runs`; source exports live in the Unity project, and generated assets in the selected Unreal project. Keep all of these out of Git. No engine assets are included in this repository.

Historical benchmark evidence is retained unchanged. This repository does not yet declare an open-source license.
