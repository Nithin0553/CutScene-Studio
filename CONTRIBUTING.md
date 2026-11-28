# Contributing to CutScene Studio

Read [context.md](context.md) and [AGENTS.md](AGENTS.md) before every change. This is the standalone deterministic Studio repository; the original research project's historical branch and PR instructions do not apply here.

## Workflow

1. Verify the current integration branch, HEAD, open PR and CI listed in the living context. As of initial release-candidate development, use `feature/deterministic-studio-v1` rather than the placeholder main branch. If a separate branch is needed, base it on the verified integration head.
2. Inspect the affected code, tests and engine boundary. Keep changes scoped, deterministic, and independent of benchmark names.
3. Add or update relevant regression tests and run the checks in context.md. Automated Python/JavaScript tests do not establish actual native editor compilation or fidelity.
4. Update context.md in the same commit or PR, including changed areas, test results, known limitations and next action.
5. Push the requested changes, verify CI, and report unresolved native checks. Do not merge to main or certify a release without owner approval.

## Review checklist

- Preserve source CSIR, benchmark freezes, Unity assets and existing Unreal targets.
- Require explicit asset rights, target identity, guarded execution and non-overwrite behavior.
- Avoid hardcoded private paths, generated evidence, exported media and secrets in Git.
- Preserve the optional single local Ollama/LangGraph agent, deterministic backend and explicit execution authorization. Do not introduce extra agents, unapproved learning or silently skip unsupported components.
- Keep the user-facing README current; mark historical documentation as historical where relevant.
- Record failures and incomplete measurements honestly; generation is not proof of fidelity.
- Do not delete branches or historical evidence without provenance review and explicit approval.
