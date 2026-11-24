# Repository instructions

Applies to the entire CutScene-Studio repository.

- **Read [context.md](context.md) first** in every new development session. Verify current branch, HEAD, PR, CI and relevant implementation before continuing. It is the living handoff, not a substitute for source inspection.
- Work in this standalone repository; the active integration branch and scope are in context.md. Do not modify the original CutsceneAI repository or introduce AI agents/LangGraph into the default deterministic transfer.
- **Every project change must update context.md in the same commit or PR.** Record the change, affected areas, tests actually run, native evidence versus mocks, limitations and the next actionable step. Update current-state sections as needed. If a task only produces a test observation or decision, record it as a documentation change. Never claim unrun tests.
- Preserve source data, benchmark freezes and existing Unreal assets. Require explicit rights/approval and native preflight; do not bypass source identity, target identity, hashes, or non-overwrite checks.
- Do not commit generated run data, credentials, private paths or unnecessary artifacts. Use generic portable examples.
- Add appropriate regression tests; run the checks in context.md and verify CI when available. Native engine acceptance is distinct from automated checks.
- Push requested changes to the appropriate branch and report the verified commit and blockers. Do not merge to main or publish a certified release without owner approval.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution details.
