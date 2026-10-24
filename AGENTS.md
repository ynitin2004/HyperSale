# HyperSale session protocol

For sales-platform work, follow `sales-platform/CLAUDE.md`, starting with
`sales-platform/docs/MEMORY.md` and the document owning the affected area.
Application code lives at the repository root in `services/`, `apps/`, and `spikes/`.

After every completed task, update `sales-platform/docs/PHASES.md` with progress,
verification evidence, and remaining acceptance gates. Do not mark a phase complete
from code presence alone. Update `sales-platform/docs/MEMORY.md` last each session.
Update DECISIONS.md for new decisions and FLOW.md for changed execution paths.
Preserve the existing major-change quiz rule in CLAUDE.md.

User clarification (2026-10-16): report discovered issues and the proposed repair
before proceeding; wait for explicit permission to repair them. Continue authorized
diagnostics independently. Do not interpret broad project access as approval for repairs.
Do not push either Git remote, deploy/publish, or apply hosted database changes without
the user's explicit permission. Keep setup and proposed repairs local for review.

Keep GitHub and GitLab CI definitions aligned when changing CI. Claude's local
history records GitLab as an intentional fallback. Do not expose `.env` secrets.
