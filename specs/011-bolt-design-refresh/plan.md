# Implementation Plan: Bolt Design Refresh

**Branch**: `011-bolt-design-refresh` | **Date**: 2026-11-20 |
**Spec**: [`spec.md`](./spec.md)

**Input**: [`spec.md`](./spec.md)

## Summary

Port the visual language and information architecture of the local Bolt prototype
into the existing Next.js 14 client. The prototype supplies colours, typography,
spacing, shell and view layouts only. Every data path, permission check, BYOK rule,
streaming handler and localized string remains backed by the real project code.
The work is a single-amend frontend change: no backend, env or deployment edits.

## Technical Context

**Language/Version**: TypeScript 5 strict, React 18, Next.js 14 App Router,
Tailwind CSS 3.4, Vitest + Testing Library

**Primary Dependencies**: existing only — `lucide-react`, Tailwind, Next, Vitest.
No new package.

**Storage**: unchanged. Theme/language keep `localStorage`; the BYOK key keeps
`sessionStorage`; all documents, users and messages continue to come from the API.

**Testing**: `npm.cmd test`, `npm.cmd run type-check`, `npm.cmd run lint`,
`npm.cmd run build`; backend `py -3 -m pytest tests -q` as a regression gate.

**Target Platform**: one Linux container on Render free tier (512 MB).

**Project Type**: web service + React client.

**Performance Goals**: no new network call, no heavy animation loop; CSS-only
entrances and a memoized shell.

**Constraints**: free/offline default, no hosted embedding quota, no model download,
single API service, manual Render Web Service, exact `LLM_KEY_REQUIRED_DETAIL`,
friendly errors only, request-scoped BYOK, demo login enabled, sample-data-only
screenshots, one commit.

**Scale/Scope**: design tokens, one shell, five views, one pure format helper,
localized copy, two docs.

## Constitution Check

*Gates from `specs/001-employee-ai-search-platform/constitution.md`.*

| Principle | Status | Note |
|---|---|---|
| Test-Driven Development | PASS | Pure format helpers get failing tests before implementation; all existing tests remain the regression gate |
| Code Quality / type hints | PASS | Strict TS props for shell/views; no `any`; lint and type-check unchanged |
| Security by default | PASS | All mutations still use the existing API with server-side RBAC; no mock data or client-only guard is trusted |
| Observability & reliability | PASS | Health flags continue to drive BYOK/auth visibility; no new hidden state |
| Documentation as code | PASS | README + ARCHITECTURE updated in the same amend |
| Free-tier budget | PASS | No new dependency, service, provider, model or hosted quota |
| One-commit history | PASS | Work is amended into the existing root commit; no force-push by the agent |

No violation, so no complexity exception is required.

## Project Structure

```text
frontend/app/
├── globals.css                 # Bolt-inspired tokens, utilities, animations
├── layout.tsx                  # Inter + Noto Naskh Arabic fonts, pre-paint theme/lang
└── page.tsx                    # renders ChatInterface (now the workspace controller)
frontend/components/
├── AppShell.tsx                # sidebar + topbar + mobile drawer (new)
├── ChatInterface.tsx           # stateful controller, renders the five views
├── views/
│   ├── ChatView.tsx            # presentational chat + citations (new)
│   ├── LibraryView.tsx         # real upload/list/delete, from DocumentPanel logic
│   ├── UsersView.tsx           # real admin API, from AdminUsersPanel logic
│   ├── SettingsView.tsx        # appearance + real BYOK, from LlmKeyPanel logic
│   └── AuthView.tsx            # real auth, from AuthPanel logic
├── Modal.tsx                   # shared confirm dialog (new)
└── ...legacy panels retained until swaps are complete
frontend/lib/
├── format.ts                   # formatBytes + timeAgo (new, pure)
├── format.test.ts              # tests first (new)
└── copy.ts                     # added en/ar shell and view labels
README.md · ARCHITECTURE.md
specs/011-bolt-design-refresh/{spec,plan,tasks}.md
```

## Design decisions

1. **Reference, not copy**: Bolt's mock data, fake auth, fake streaming and
   `localStorage` key storage are explicitly rejected. Only CSS/class vocabulary,
   layout composition and icon usage are adapted.
2. **Single controller**: `ChatInterface` keeps the existing health/demo-login/BYOK/
   streaming orchestration so no security-sensitive logic is duplicated. Views are
   presentational and receive callbacks.
3. **No route explosion**: the prototype's view switch is mirrored in client state
   inside the existing single page. Next routes and the API proxy stay untouched.
4. **RTL-first tokens**: logical Tailwind utilities (`ps/pe/ms/me/start/end`) and
   `dir` are retained; Arabic uses Noto Naskh Arabic, English uses Inter.
5. **Theme compatibility**: the existing `data-theme` attribute and `lib/theme.ts`
   remain the source of truth; CSS variables are remapped, not renamed in callers.
6. **Page labels unchanged**: citations continue to print only `page_label` or
   `page_number` from the server.

## Risks and mitigations

- **Risk**: duplicating panel logic drifts from the API contract.
  **Mitigation**: copy only the API-call sequences from the original panels; keep
  the same helpers (`friendlyError`, `DuplicateDocumentError`, `UNAUTHORISED_DETAIL`).
- **Risk**: className churn breaks the existing `EmptyState` test.
  **Mitigation**: keep `SAMPLES` and the sample-button accessible names stable.
- **Risk**: font loading harms the free-tier cold start.
  **Mitigation**: use `next/font/google` with `display: swap` and two weights only.
- **Risk**: stale video screenshots after the redesign.
  **Mitigation**: recorded as a follow-up in the spec; no re-capture in this change.
