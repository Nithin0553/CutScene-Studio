# CutScene Studio — Project Context and Handoff

Last updated: 2026-11-26

## 1. Start here — mandatory development workflow

- The active repository is https://github.com/Nithin0553/CutScene-Studio.git. The older CutSceneAI repository is not the active development target.
- At the start of every new development chat or session, read this file from the latest relevant branch, inspect the repository state and recent commits, and resume from the recorded next steps. Verify claims against the code rather than relying on chat memory.
- Every development update, code change, bug fix, configuration change, architectural decision, experiment, test result, or meaningful project update must be reflected in this file before the work is considered complete. Include the context update in the same commit or pull request whenever practical.
- Keep the current-state sections accurate and maintain a concise dated change history. Preserve important decisions and unresolved issues. Record changed paths, validation commands and actual results, blockers, and the next actionable step. Reference commits or PRs where available; do not invent identifiers.
- Keep the Git workflow simple: use main as the stable baseline and short-lived feature branches/PRs when appropriate. Use descriptive, natural commit messages; avoid unnecessary branches, unrelated changes and destructive Git operations.
- Never claim an implementation or test passed without evidence. Distinguish planned, implemented, tested with mocks, and verified in real editors. Do not commit secrets, private assets, local model weights or machine-specific credentials.

## 2. Project goal

Build a reliable local AI-powered cross-engine cutscene transfer application, initially Unity Timeline to Unreal Engine Sequencer, with reverse direction as a future goal. The application should connect to both editors, inspect the source scene and timeline, transfer required assets, reconstruct the cutscene in the target, validate fidelity and attempt bounded repairs where supported.

## 3. Proposed architecture (not yet implemented in this repository)

- Studio UI: engine connections, transfer configuration, progress, diagnostics and validation report.
- Local backend: orchestration, schema validation, job state, deterministic transfer execution.
- Ollama: local LLM inference via a configurable local API (default http://localhost:11434). Model selection is pending hardware and capability checks.
- Single AI transfer agent: plans conversions, retrieves mapping knowledge, invokes allowlisted tools, interprets validation failures and proposes supported repairs. Consider LangGraph or a simpler state machine after reviewing requirements.
- Mapping knowledge: exact component/version matching first; optional semantic retrieval/RAG for relevant conversion knowledge. Reuse prior project mappings where appropriate after inspecting them.
- CSIR (engine-independent cutscene representation), source census, CED conversion knowledge/coverage, and CineTwin source-target comparison: concepts from the earlier research project to evaluate and port selectively, not existing features of this repository yet.
- Unity Editor Bridge: source scene, Timeline, assets, animation and capability inspection using editor APIs.
- Unreal Editor Worker: asset import, actor creation, Sequencer reconstruction and readback using editor APIs.
- Deterministic conversion and validation must remain outside LLM calculations. Validate tool arguments and transfer plans, retain provenance, bound repair attempts, and explicitly report unsupported or partial conversions. Avoid arbitrary generated code execution and unintended changes to source projects.

## 4. Current repository state

- Default branch: main.
- Baseline inspection on 2026-11-26 found only README.md at the root; its description is "The newer and solid version of the Studio."
- This context file establishes the development baseline and handoff workflow.
- User reports Ollama is already installed locally. Installed models, GPU, RAM, available storage, engine versions and local project paths have not yet been verified.
- No application code, integration tests, or real engine transfer results have been verified in this repository as of this entry.
- Prior research code and benchmarks must be reviewed explicitly before reuse. Do not assume prior implementations or results are present here.

## 5. Development roadmap

1. Verify local environment and Ollama model/API availability; review relevant prior implementation and decide what to reuse.
2. Establish project structure, configuration, shared contracts and reproducible tests.
3. Implement minimal Unity and Unreal editor connectivity and capability discovery.
4. Define source extraction, CSIR and mapping retrieval interfaces.
5. Implement deterministic asset and timeline reconstruction for a minimal benchmark.
6. Integrate the Ollama agent with typed tool calls and validated plans.
7. Add target readback, CineTwin validation, bounded repair and transparent coverage reporting.
8. Integrate Studio UI and run end-to-end real-engine benchmarks; expand supported features incrementally.
9. Evaluate reverse transfer separately after the initial direction is reliable.

## 6. Next actionable step

Verify the developer machine using PowerShell:

```powershell
ollama list
Invoke-RestMethod http://localhost:11434/api/tags
nvidia-smi
Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
```

If nvidia-smi is unavailable, check the installed GPU using Windows tools. Confirm Unity/Unreal versions and available disk space before selecting a model and starting implementation. Review the older research repository before deciding which modules to port. No model downloads or local editor actions have been performed by this session.

## 7. Change history

### 2026-11-26 — Project baseline and continuity

- Designated CutScene-Studio as the active repository.
- Established context.md as the required living handoff document.
- Recorded the proposed local Ollama single-agent architecture and deterministic engine execution approach.
- Verified the main branch root listing and README through GitHub; no application code was present in that listing.
- Documentation-only change; no software tests run.
- Next: verify local environment and review reusable research components.
