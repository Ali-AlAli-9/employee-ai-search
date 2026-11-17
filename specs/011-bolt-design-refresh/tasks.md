---
description: "Task list for Bolt Design Refresh (spec 011)"
---

# Tasks: Bolt Design Refresh

**Input**: [`spec.md`](./spec.md) · [`plan.md`](./plan.md)

**Prerequisites**: plan.md (required), spec.md (required)

## Phase 1: Specification

- [X] T001 Write `spec.md` and `plan.md`

## Phase 2: User Story 1 - Workspace shell (Priority: P1) 🎯 MVP

**Goal**: responsive sidebar/topbar with real auth, language, theme and key status.

**Independent Test**: `npm.cmd run type-check` and a manual RTL/admin/guest render.

### Tests first (must fail before implementation)

- [X] T002 [US1] Add `frontend/lib/format.test.ts` for `formatBytes` (0, 999,
      KB/MB/GB, negative/invalid) and `timeAgo` (now/minutes/hours/days and invalid
      input) in both locales.

### Implementation

- [X] T003 [US1] Add pure `frontend/lib/format.ts` with typed `formatBytes` and
      `timeAgo` helpers; run the focused test green.
- [X] T004 [US1] Replace `frontend/app/globals.css` tokens with the Bolt-inspired
      blue/emerald/neutral system, utility classes, scrollbars and keyframes while
      keeping `.card`, `.btn`, `.btn-primary` and `.chip` names for compatibility.
- [X] T005 [US1] Extend `frontend/tailwind.config.ts` with `primary`, `neutral`,
      `success`, `warning`, `error` palettes and the new animations; keep existing
      themed colour names so legacy components still compile.
- [X] T006 [US1] Update `frontend/app/layout.tsx` to load Inter and Noto Naskh Arabic
      through `next/font/google` and apply the pre-paint theme **and** language
      attributes without layout shift.
- [X] T007 [US1] Add `frontend/components/AppShell.tsx` with desktop sidebar,
      mobile drawer, topbar, view title/subtitle, nav guard for admins, language/
      theme toggles, key-mode badge, account menu and sign-out entry point.
- [X] T008 [US1] Add shell/nav/status copy to `frontend/lib/copy.ts` in en and ar.

## Phase 3: User Story 2 - Full views (Priority: P1)

**Goal**: library, admin and settings as full pages backed by the real API.

**Independent Test**: `npm.cmd test` (the 34 existing cases stay green).

- [X] T009 [US2] Add `frontend/components/Modal.tsx` shared accessible confirm
      dialog with localized buttons.
- [X] T010 [US2] Add `frontend/components/views/LibraryView.tsx`: real
      `listDocuments`/`uploadDocument`/`getDocument` polling/`deleteDocument`,
      drop zone, stats, search, status badges, duplicate-replace confirmation and
      upload gating from `canUpload`/`canDelete`.
- [X] T011 [US2] Add `frontend/components/views/UsersView.tsx`: real
      `listUsers`/`updateUser`/`deleteUser`/`resetPassword`/`syncUsers`, stats,
      search, guests filter, pagination, self-row guard and confirm modals.
- [X] T012 [US2] Add `frontend/components/views/SettingsView.tsx`: appearance
      cards (theme/language), real BYOK form reusing `verifyLlmKey` and
      sessionStorage-only helpers, masked key display, privacy notes, account card.
- [X] T013 [US2] Refactor `ChatInterface` to pass health/user data into the views
      and keep the existing pre-send 402 guard bitwise-identical.

## Phase 4: User Story 3 - Chat and account surfaces (Priority: P2)

**Goal**: chat, citations and account view use the same design system.

- [X] T014 [US3] Add `frontend/components/views/ChatView.tsx` restyling
      `EmptyState`, `MessageList`, `CitationCard` and `MessageInput` with the new
      tokens while preserving all props, sample questions and page-label logic.
- [X] T015 [US3] Add `frontend/components/views/AuthView.tsx` split-screen auth,
      reusing `login`/`register`/`getMe`/`logout` and demo-guest entry from the
      existing `AuthPanel`; no "any password works" mock claim.
- [X] T016 [US3] Keep `EmptyState.test.tsx` green; assert localized samples still
      render and call `onPick`.

## Phase 5: Verification and release (Priority: P3)

- [X] T017 Remove or leave unreferenced legacy panels only after imports are gone;
      no mock-data file from the Bolt folder is present in the repo.
- [X] T018 Run `npm.cmd test`, `npm.cmd run type-check`, `npm.cmd run lint`,
      `npm.cmd run build` from `frontend/`.
- [X] T019 Run `py -3 -m pytest tests -q` from `backend/` as a regression check.
- [X] T020 Update `README.md` and `ARCHITECTURE.md` for the refreshed UI and the
      single-commit amend; no env/config/deployment value changes.
- [X] T021 Amend the single root commit locally (`git commit --amend --no-edit`),
      verify `git rev-list --count HEAD == 1`; the operator later authorised and
      performed the force-push explicitly.
- [ ] T022 Operator-only from spec 009 remains pending: consistency commands with
      the live API environment.

## Phase 6: Post-release fixes (same single commit)

- [X] T023 Remove the "answers are generated… / Built with Next.js and FastAPI"
      footer copy from `AppShell`, `MessageInput`, `AuthView`, `LibraryView` and
      their `copy.ts` keys; verified absent in both locales.
- [X] T024 Fix the account dropdown overlap: move the click-away layer out of the
      header so `fixed inset-0` covers the viewport (the header's `backdrop-filter`
      had made it header-sized), make the header opaque, and add a theme-aware
      `shadow-menu` token so the menu separates cleanly in light mode.
- [X] T025 Stop the theme effect from overwriting a returning visitor's stored
      light choice on first render.
- [X] T026 Fix modal readability: the BYOK dialog used `bg-white/[0.04]`, a
      near-transparent panel that let the dimmed page blur through the text.
      All dialog panels now use an opaque themed `bg-surface-elevated` with a
      `border-app` and a dedicated `shadow-modal`; overlays drop `backdrop-blur`
      for a clean `bg-black/70` scrim, and the BYOK panel uses the semantic
      `input`/`text-secondary` helpers. Verified in both themes with no console
      errors.
- [X] T027 Fix the document delete button: `LibraryView` passed
      `busy={deletingId !== null}`, which is always true while the confirmation
      dialog is open, so the confirm button stayed disabled and rendered "…".
      Added a dedicated `deleting` flag, close the dialog after a successful
      delete, and disable the close/cancel controls in `Modal` while busy.
      Verified end-to-end as an admin: upload → confirm → document removed,
      counters updated, no alert, no console errors.
- [X] T028 Fix the auth hero readability and drop the sample-data phrase. The
      hero gradient ended in near-black `#020617`, so the lower feature list was
      hard to read; it now ends in a brighter `#1d4ed8` and each remaining
      feature sits on a translucent white chip with a subtle ring. Removed
      `featureLocal` ("Local-first with sample data" / "يعمل محلياً ببيانات
      العيّنة") from `copy.ts`, the feature array and the footer footnote in
      `AuthView`, along with the now-unused `LockKeyhole` import. Verified in
      English/LTR and Arabic/RTL: both remaining lines are visible, the removed
      phrase is absent in both locales, and there are no console errors.
- [X] T029 Make the intro/hero panel appear at every viewport width instead of
      `hidden lg:flex`; it now stacks above the account card on small screens
      (`flex flex-col gap-8 p-8 lg:justify-between lg:gap-0 lg:p-10`), with a
      smaller heading on narrow screens. Removed the duplicated eyebrow from
      the card so the page is no longer visually scattered. Also fixed language
      persistence: the effect that mirrored `language` back to `localStorage`
      raced the initial read (noticeable under dev StrictMode) and reset Arabic
      to English on reload; the write now happens only in `toggleLanguage`.
      Verified at 795px in Arabic/RTL: hero, title and both feature lines are
      visible, the card has no duplicate header, and Arabic survives reload.
- [X] T030 Pin the intro hero copy to pure white. Tailwind's `white` token is
      remapped to `--white-rgb`, which is `237 240 245` in dark mode and
      `15 23 42` in light mode, so `text-white` could turn dark on the blue
      gradient. Replaced the hero's `text-white`, `bg-white/*`, `ring-white/*`
      and `text-white/90` utilities with theme-independent `[#fff]` variants.
      Verified in both themes: heading and feature lines compute to
      `rgb(255, 255, 255)` and body to `rgba(255, 255, 255, 0.9)`.

**Independent test per story**: see the `Independent Test` line in each phase.
