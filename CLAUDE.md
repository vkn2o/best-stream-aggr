# CLAUDE.md

## Documentation workflow (mandatory, no reminders needed)

This project maintains a strict `docs/` folder that must be created and kept
up to date automatically while building — never wait to be asked.

- `docs/Architecture.md` — High-level map of the system: modules, services,
  and how data moves between them. Shape only, no deep implementation detail.
- `docs/Decisions.md` — Log of every meaningful decision made while changing
  code, with rationale (why a specific library, pattern, or tradeoff was
  chosen). Newest entries at the top.
- `docs/Flow.md` — How execution actually travels between files, functions,
  and modules.
- `docs/Handover.md` — Updated at the end of every session: what is done,
  what is in progress, what is broken, and what to avoid.
- `docs/Constraints.md` — Short, explicit list of what must never be done in
  this codebase.

Rules:
- Update these files continuously as code changes, not just when asked.
- `Handover.md` must be refreshed at the end of every session.
- Keep `Architecture.md` and `Flow.md` at the appropriate altitude (system
  shape / execution path) — don't let them drift into implementation detail.
- Every meaningful decision goes in `Decisions.md` with its rationale at the
  time it's made.
