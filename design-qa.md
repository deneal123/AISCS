# IDE agent rail — implementation checkpoint, 2026-10-17

## 2026-10-19 — new-project form and uncertain create recovery

The form now describes a separate project instead of falsely claiming the chat
has no repositories. Name receives initial focus and inline invalid-name focus;
copy reflects automatic preparation rather than an extra manual Start step.
An uncertain create keeps its frozen name/ID across a mounted surface hide/reopen.
Only the explicit retry dispatches it; old visit callbacks and late replies are
retired. Scope changes do not expose the old name. No full-reload durability claim.

11 unit tests passed (setup6/form5), source ESLint and build main.d98a5d1a.js.
Three compiled browser cases passed: lost create ACK/surface switch/same-ID retry,
expired empty-history/new form and saved-history/expiry/restore. New 320px screenshot
inspected at `.work/ide-create-recovery`; axe serious/critical0. Strict static audit0
and canonical UI contract passed. APIs are fixtures; no native registration,
provider call, migration, restart, production change or broad-suite green claim.

## 2026-10-18 — expired IDE project recovery

Expiry now has contextual guidance in the existing file pane, rather than a
permanent information row. Saved/unfinished versions lead to the same History
dialog; confirmed empty history leads to the existing separate-project form.
Loading/read failure/disabled capability do not falsely claim an empty history.
Entry performs no restore, allocation or agent message. Cached source and drafts
remain intact; the recovery section disappears after a confirmed restoration.

23 focused unit tests passed (8 recovery, 15 existing IdeStudio; existing act
warning remains). Source ESLint and production build main.d8e62843.js passed.
Strict audit0 and canonical UI contract passed. Three compiled browser cases
passed: expiry/history/restore, preserved copyable draft, empty history/new form
without allocation. Recovery-region axe serious/critical0. Inspected desktop
and320 screenshots in `.work/ide-expiry-recovery`; these use API fixtures, not
another native storage/expiry run. No broad regression-green claim, service
restart, migration, global left-divider change or production operation.

## 2026-10-18 — revoke an unknown pending Save

The existing History modal now offers a compact cancel action for pending uploads
that cannot yet be physically discarded. Confirmation initially focuses Cancel;
it distinguishes publication revocation from stopping a writer or freeing space.
No extra toolbar row, palette or overlay owner. A confirmed terminal record clears
only its matching Save intent. Unknown acknowledgement keeps it pending; a
publication race prevents dispatch. Capacity remains server-owned and charged.

18 hook tests and four compiled browser scenarios passed, including320px,
Escape/focus return, busy state, fresh-ID Save after revoke and held quota.
Inspected `.work/ide-abandon/ide-studio-revoking-an-unk-1cd51-t-deletion-or-quota-release-chromium/ide-abandon-320.png`.
Build main.25f0c1b5.js, changed-source ESLint, strict audit0 and UI contract passed.
143 focused backend tests, PostgreSQL17 groups and targeted MyPy passed. Native
dev API/storage acceptance also passed: revoked writer resumed after a new Save,
could not publish, and its copy was collected without changing the new README or
HEAD. Earlier transient storage failures remain documented in PROJECT_TODO;
their cause is unproven. Browser scenarios above still use API fixtures.
The previous broad-suite red is not superseded by these focused checks.

## Six-hour UI/backend correction slice, 2026-10-18 (in progress)

Latest continuation, 19:56 MSK: lost-create-ACK recovery was exercised against
native dev (one accepted create response dropped, zero repeated content writes,
zero agent messages). The source-only project opened and its explicit content
initialization action became available after stable reading. Creation/Formatting
now share a retired-thread-safe mutation owner and coalesce duplicate admission.
Format-catalog failure has explicit retry, not an unexplained disabled New button.
62 targeted PDF units passed; isolated WorkHub/IdeStudio33 passed with one act
warning. Two catalog browser cases passed at1440/393 before touch-target refinement.
The refinement's final replay passed three cases; mobile initially measured the
44px close target during scale animation (43.56px). Its assertion now polls the
actual geometry without lowering44; the single failed case then passed.
Final source build main.fd66311f compiled; ESLint (zero warnings) and canonical UI
contract passed. This is not a replacement full 432-case/143-suite green.
IDE desktop one-row and320px two-row/no-overflow toolbar: two focused browser
cases passed after compacting New project by its container width. Screenshot
inspected. No pending background test/worker process remains in this checkpoint.

Latest focused checkpoint, 19:34 MSK: compact persona/model pickers and exclusive
tooltip ownership, one IDE toolbar/create owner, inline Formatting selects and
New document modal implemented. 48 focused composer/formatting unit tests, 25
new-document/hook unit tests and four targeted dev browser cases passed. Native
authenticated dev preparation returned ready200; a separate presentation opened
with editable slide content. Mobile entry at 393px has no horizontal overflow.
Formatting language persisted after full page reload and reopening. Inspected
native screenshots; no agent messages, compilation or paid provider calls.
Final focused-source build `main.59a5d523.js` compiled; ESLint and the root
canonical UI contract passed. No full browser matrix was repeated for this build.
Dev upgrade038 was authorized; backend startup also automatically applied039
through its existing `upgrade heads` entrypoint. Reported immediately; journal
was empty, health200, no destructive downgrade. Runtime freshness for the full
native restore/capture scenario remains unaccepted.

The subsequent full 432-case replay was cancelled to prioritize feature work;
it is not a green gate. The latest full unit run had 141 passed /2 failed suites,
944 passed /7 failed tests (WorkHub/IdeStudio timeouts under concurrent load).
No timeout/baseline relaxation. Earlier broad evidence below is historical and
must not be applied to later UI changes.

Earlier checkpoint, 18:39 MSK (not full product acceptance): production build
`main.d38ae295.js` / workspace `6029.15216780.chunk.js` compiled; 142 frontend
suites /949 tests /one snapshot, ESLint, root UI contract, strict audit (zero
findings), 23 root gate/continuity tests and eight compiled accessibility checks
pass. The source remained unchanged throughout the 423-case production browser
matrix: 421 passed /two desktop-only split cases skipped, no failures (39.2m),
across Chromium, mobile Chromium and tablet WebKit. Earlier diagnostic matrix
failures below remain historical evidence, not the current build's result.
Actual compiled IDE result, mobile Markdown local-anchor focus and passive-help
screenshots were inspected. Authenticated native Library inspection is separate
from intercepted API/agent fixtures. No migration/restart/deploy/paid model call
was performed; dev is still on migration037. Human-question, durable Save/history
and full native IDE/PDF acceptance remain open.

- Existing RU dark workbench and shared Chakra controls/tokens retained. Compact
  mode popup follows composer density, uses 44px option targets, keyboard/hover
  help and a touch-accessible detail toggle; no permanent description canvas.
- IDE runtime facts moved into the project toolbar with passive detail; idle agent
  uses short fill-only suggestions and one visible credit disclosure. No divider
  coupling, provider/model request, script or Git send was added by these actions.
- PDF build activity has one owner in preview header / mobile pane navigation.
  Semantic Save owns dirty/pending/acknowledged labels without a duplicate status.
  Materials keeps sources visible, technical/build files behind named counted
  disclosures, one scroll owner and original dirty-navigation/editor guards.
- Reviewed fresh desktop/mobile screenshots of Materials, mode popup, idle IDE
  agent and PDF after preparation. Browser tests cover 320/393/1440 widths,
  keyboard disclosures/focus, draft retention, explicit Library-only upload and
  source selection. Fixture drift in the Library upload endpoint was repaired;
  upload does not silently insert a working copy.
- Latest frontend full run: 138 suites / 935 tests / 1 snapshot passed. Latest
  source refinement (normalized production preparation error) is included in the
  new hook suite. Lint/build and root UI contract passed earlier in this slice;
  final build and 8 compiled accessibility checks passed. Configured legacy Work
  replay stopped at its first retired “Работа” selector (1 failed, 95 not run);
  current IDE/PDF/composer matrix and coverage migration remain separate work.
  Strict premium audit: 0 findings. Official DESIGN lint: 0 errors, 7 existing
  token-reference warnings; no baseline relaxation.
- PDF first-entry now has a durable server-owned allocation claim and stable
  scaffold path, not a POST to the old unconditional activation on mount. Existing
  projects survive; uncertain/expired state is not replaced with a blank runtime.
  New backend focused tests: 34 passed; isolated PostgreSQL test: 6 internal groups
  including 16 concurrent claims, ownership, expiry and migration round-trip;
  disposable database removed. Browser mocked API matrix: 14 passed, plus 2
  missing-endpoint 404 cases preserving the original chat rather than looping.
- Boundary: no deployment or operational DB migration applied. These browser
  checks intercept API/WS and are not authenticated end-to-end runtime proof.
  Fresh acknowledged scaffolds now initialize semantic content through the existing
  deterministic renderer, guarded by revision, source digest and project lease;
  existing or unconfirmed scaffolds cannot enter that write. Failure leaves the
  usable source-only project. Focused backend tests: 44 passed; deterministic
  agent editor: 9 passed, including initial-to-editable round trip, with no model.
  Backend full run after scaffold dispatch journaling: 3719 passed /130 skipped,
  coverage 79.93%. Unknown scaffold ACK cannot replay a write; only an explicit
  confirmed-conflict retry can rearm it. Focused tests: 48 passed; PostgreSQL
  probe now covers 7 internal groups. Full MyPy: 471 files passed after narrowing the
  existing IDE context once and passing its empty chat-file list explicitly;
  25 focused worker/context regressions passed, no runtime behavior change.
  Dev DB read-only inspection: head 037, new preparation table absent. Application
  of additive 038 and backend reload on dev requested separately; not performed.
  IDE durable Save/restore/history and overall six-hour acceptance remain open.
- Recovery slice: a compiled red test demonstrated that workspace failure
  unmounted the unsaved PDF editor. Confirmed project facts now survive failed,
  expired and subsequently absent reads within the same owner scope. Publication
  is fenced, including late lease acquisition; text stays editable and explicitly
  downloadable as JSON/raw text, without pretending to include project assets.
  One desktop compiled recovery case passed; the next four-case dev replay found
  a narrow tooltip overflow after the download. That geometry fix and full replay
  are still being verified. No implicit workspace replacement or write was added.
- Broad current-surface replay was diagnostic: 324 passed, 5 failed, 2 skipped,
  35 not run. Three retired Work labels were repaired; tablet hidden-popup and
  drawer focus bugs are under verification. New shared Library/cold-entry checks:
  18 passed. The configured legacy Work gate has not yet been migrated or hidden.
- Next full frontend run: 140 suites /941 tests /1 snapshot passed. The frozen
  production matrix completed 393 cases: 388 passed, 3 failed, 2 skipped. Tablet
  revealed retained hidden popup descendants, immediate Escape before initial
  focus, and missing explicit return target after cancelling PDF content reset.
  Popup roots now mount only while open; runtime help establishes initial focus
  before paint; the PDF reset dialog names its final focus target. Each repaired
  case passed 3 dev repetitions. New production build/recheck is in progress;
  neither the preceding build nor the dev pass counts as final browser acceptance.
- Next current-surface matrix: 401 passed /2 failed /2 skipped (405 cases).
  Tablet cold-Library and Materials workflows exhausted the total 30s deadline;
  their focused repeats passed 9 and 3 cases respectively. Serial replay remains
  diagnostic: it exposed a real 320px provider-status reopening failure in the old
  build. The provider panel now uses the same immediate conditional-root lifecycle
  as the repaired compact picker/runtime help. Six unit checks pass; 24 dev browser
  repetitions and the next compiled build are still being checked.
- Authenticated dev read-only Library screenshots at 1440/393px were inspected:
  no document overflow, zero blocked mutation attempts, no agent socket or workspace
  creation. Test session refresh had zero balance adjustment. No auth state, trace
  or browser profile was written with the screenshots. This verifies live Library
  presentation only, not the unprovisioned native IDE/PDF runtime.
- Additional source refinements (require a new compiled replay): provider reopening
  passed 24 dev repetitions across desktop/mobile/tablet, with six unit checks.
  Account Library replaces duplicate static prose/boxed guidance with one short
  explicit upload/copy line; redundant origin/ready badges are absent only in its
  document presentation. Exceptional statuses, copy feedback, accessible names,
  native downloads and 34px actions remain. Actual dev screenshots were inspected;
  23 focused unit tests and 12 dev browser workflows pass. Long MIME values wrap.
- Markdown local table-of-contents fragments now focus their own heading without
  changing the Chat URL, opening another file or requesting a resource. Scoped IDs,
  Unicode/duplicate slugs and a monotonic collision counter are covered by six unit
  checks. Existing GFM, inert HTML and no-auto-image-fetch behavior remains. Browser
  focus/scroll verification and the new build are still pending.
- Subsequent refinements: passive IDE help uses the same immediate initial-close
  focus, conditional content root and native return-focus owner as runtime help.
  Twelve dev repetitions pass. Current Library cancellation/retry/reselection and
  short-viewport feedback workflows are now a dedicated gate, not retired Work
  assertions. A keyboard-cancel red test found replacement of the focused Cancel
  node with a new Retry node; one stable control now changes action without replay
  or lost focus. Focused unit and nine refined dev cases pass; the compiled 423-case
  matrix includes these workflows and local Markdown heading focus.

## Isolated clone on nonempty projects, 2026-10-17

- The explicit Clone action now redirects a definite nonempty/conflicting target
  to one separate project, without an additional manual Create step. Existing
  source files and metadata are not cleared. Canonical Chakra modal/Workbench
  controls and existing theme tokens were retained; global divider unchanged.
- Migration 036 persists immutable request digest, one destination and one Git
  dispatch claim. Allocation never rearms quota/expired/unknown work. GET status
  never provisions, fetches or writes Git. Lost reply/commit ACK is read back;
  uncertain dispatch cannot be replayed. Reserved startup uses explicit same-intent
  recovery; entry into its destination does not insert .git ahead of the clone.
- Native PostgreSQL disposable-database probe passed: existing 14 descriptor,
  9 runtime and 9 onboarding cases plus 8 clone identity/ownership/concurrent
  reservation/dispatch/terminal-replay cases. The disposable database was removed.
- Full backend after final dispatch hardening: 3627 passed, 129 skipped,
  coverage 79.61%; changed-file Ruff/format and focused MyPy passed. Full frontend:
  132 suites / 851 tests / 1 snapshot passed. Build, lint, strict audit and root
  UI contract passed; DESIGN lint has 0 errors and 7 existing warnings.
- Initial compiled browser run: 36 passed / 6 failed because lowercase IDE detail
  codes were replaced by Axios codes. A regression and mapper repair fixed that
  boundary. Actual dev then exposed the production HTTP envelope converting the
  string reason into http_error; routes now emit structured closed codes. API
  tests and browser fixture use that real envelope, not only FastAPI's default.
- Compiled IDE suite subsequently passed 42/42 desktop/tablet/mobile cases.
  Final dialog close-label/duplicate-submit checks passed the 6 clone cases.
  A combined accessibility replay was 29 passed / 1 failed: initial refresh became
  enabled before preparation disabled it, losing programmatic focus. Source now
  keeps refresh disabled through initial validation and the test waits for Ready.
  After the last focus fix: 15 affected unit tests passed, production build passed,
  and final combined IDE/accessibility suite passed 66/66 desktop/tablet/mobile
  cases in `.work/ide-isolated-clone-final-all/`. No timeout/assertion was relaxed.
- Final hardening binds isolated Git dispatch to its private, currently claimed
  journal intent. The public Git DTO cannot supply it; direct/old/foreign/complete
  claims stop before download or Git. This also prevents inspection of an unknown
  destination from bypassing the one-dispatch invariant via the legacy Git action.
  Focused and real PostgreSQL permission checks passed, including live/foreign/
  wrong/complete intent fences. Full backend passed as recorded above. The final
  native replay after this hardening passed again, with a settled branch read and
  enabled controls before capture; both fixture sandboxes and rows were removed.
- Native dev after migration/API/frontend refresh passed the actual GitHub clone
  from a changed project: original file written and read back byte-for-byte,
  2 distinct repository descriptors and separate runtimes, one isolated clone,
  no LLM requests. Both exact fixture sandboxes and thread were removed. Earlier
  native attempts failed before the clone because the harness had not returned
  from Code to Files on mobile; later error-envelope failures are retained above.
  Final native screenshots are in `.work/ide-design-20261017/`.
- The durable journal survives a page reload, but its interactive recovery is not
  yet reattached after a full browser reload. It is an explicit open acceptance
  item, not replaced by memory-only same-page retry. Private Git hosts/credentials,
  long-running clone jobs, human-question, script execution, Graphify, archive,
  diff/commit/push, real-provider task acceptance and legacy Work gate stay open.

## Automatic entry and deferred Git completion, 2026-10-17

- IDE entry now prepares the owned project/runtime and initializes Git without
  manual Create/Start actions. Registry loading/failure is not treated as absence.
  Existing projects/config/files are preserved; quota/expiry/unknown states do
  not silently allocate replacements. PDF onboarding is a separate open item.
- Native concurrent first entry reproduced two pending prepare responses with
  neither tab completing Git init. The UI now observes the same runtime with
  bounded GETs, then finishes setup once using the accepted repository ID.
  Git reads, mutations and agent admission wait for that continuation. A red
  regression also caught navigation leaving busy latched after cancellation;
  retirement now clears busy and return revalidates the same repository.
- Backend lookup contention keeps the strict observation/generation fence:
  discard superseded private binding, resolve afresh at most once. It never
  retries a mutation/allocation or carries the first binding into an operation.
- Current focused frontend set: 65 passed across entry/reads/scene, WorkHub and
  PDF review. Backend preparation/runtime/routes: 37 passed with --no-cov
  (focused behavior check, not a new whole-backend coverage claim).
  Production build, ESLint, strict premium audit and root UI contract
  passed. DESIGN lint: 0 errors, 7 existing warnings. Theme tokens, global sidebar
  divider and the canonical Chat/PDF composer owners were not changed.
- Compiled browser suite: 36/36 passed across desktop, tablet and mobile;
  `.work/ide-entry-ready-continuation/`. Covers pending-to-Ready, cancellation and
  return, lost acknowledgement recovery, file edit/move, scoped agent result,
  keyboard/select, compact controls and reduced-motion/reflow. Accessibility:
  8/8 passed in `.work/ide-entry-ready-a11y/`.
- Native dev replay passed twice with simultaneous first entry, Chat/IDE return,
  reload, later second tab and actual public GitHub clone over pristine seed:
  2 default requests, 6 prepare calls including same-repo completion/reconciliation,
  1 repository, 1 clone, no LLM requests. Each exact fixture was removed.
  Latest screenshots: `.work/ide-design-20261017/dev-ide-auto-entry-desktop.png`
  and `dev-ide-auto-entry-mobile.png`; desktop agent rail and narrow single-pane
  controls inspected. The clone uses networked public Git, not mocked files.
- The first full frontend run was not green: 833 passed, 6 failed in WorkHub,
  PDF review and IDE scene timing. The IDE fixture now flushes resolved startup
  through act before asserting admission, without increasing timeouts or weakening
  assertions. Focused rerun passed; final whole-suite rerun: 131/131 suites,
  839/839 tests and 1 snapshot passed. This later pass does not erase the initial
  timing failures or establish that the wider suite is free of flakiness.
- Legacy Work browser scenarios still target the retired peer and need migration;
  this checkpoint does not waive that gate. Clone-to-new for modified projects,
  human questions, script execution/console, repository Graphify, archive,
  diff/commit/push and real-provider task acceptance remain open roadmap work.

## Mini-report follow-up, 2026-10-17

- Requested change: IDE renders only the bounded plain-text `ide_finish_task`
  report (280 code points), never the complete Chat reply or its code. Confirmed
  write counts and uncertain acknowledgements remain independent. No separate
  summarizer request or surcharge; omitted tool calls get receipt-only fallback.
- Agent/tool/schema/context checks: 73 passed. Backend persistence: 14 passed;
  changed-file Ruff/format and backend message-metadata MyPy passed.
- Final component regression set (result, persistent composer, submit, WorkHub):
  29 passed. Full frontend set: 825 passed, 2 failed in WorkHub after a 5s timeout;
  isolated WorkHub rerun passed. This does not make the full run green.
- Compiled browser result/Chat/IDE round-trip: 3/3 passed on desktop, tablet and
  mobile; screenshots in `.work/ide-mini-summary-compiled-final/`. Actual dev
  frontend replay: 1/1 passed after idle-checked service restart. The initial dev
  replay before restart failed to resolve the current scene; no tests were relaxed.
- Accessibility/reduced-motion contract: 8/8 passed. Build and ESLint passed;
  strict premium audit and root UI contract passed. DESIGN lint: 0 errors,
  7 existing warnings. Existing user runtime containers were not restarted.
- Legacy Work browser gate remains blocked: it still looks for the retired
  “Работа” peer; 1 failed, 95 not run with max-failures=1. Whole-IDE mock parity,
  real-provider task acceptance and remaining roadmap items are still open.

Mini-report slice verified; full-goal result remains blocked on open roadmap/gates,
not a claim that the whole IDE is finished.

Scope: repair the missing agent pane and reuse the approved Chat/PDF input and
trace owner. This checkpoint is not acceptance of the entire IDE mockup.

## Current comparison

- Approved reference: `.work/ide-design-20261017/11-ide-input-v3.png`, 1665×945.
- Browser: `tmp_e2e/playwright-report/ide-studio-agent-rail-owns-92340-and-scoped-repository-reply-chromium/ide-agent-input.png`
  and `ide-agent-result.png`, 1665×945 CSS/device pixels, DPR 1.
- Combined comparison: `.work/ide-design-20261017/ide-agent-reference-comparison.png`.
  Both images retain their original size; the stacked comparison adds labels only.
- Native dev: `.work/ide-design-20261017/dev-ide-agent-desktop.png` (1440×900)
  and `dev-ide-agent-mobile.png` (393×851). These use an isolated test account and
  repository, not user source. The first desktop native capture caught Git status
  loading; that oversized loader was subsequently replaced by inline toolbar text.
- State difference is explicit: the reference contains an edited TypeScript
  project, diff and console. The synthetic capture uses Python, an initial agent
  task and a deterministic reply. It cannot certify a real LLM-generated diff.

## Findings and iterations

- Resolved P1: no agent rail/input at all. The shared persistent DOM host now
  moves into IDE; the same input, voice, attachments, selectors and Stop remain
  owned by Chat. The new rail stays visible on desktop, and Agent is an explicit
  panel below 1100px. Switching panels/surfaces retains the uncontrolled draft.
- Resolved P2: a full-page-style Git status loader displaced the workbench.
  Git preparation now uses quiet inline status in the existing toolbar.
- Resolved P2 in source: the tablet's single-pane layout hid both Move controls.
  Code toolbar now uses the actual single-pane mode, not the old 768px breakpoint.
  The original browser run was 26/27; rerun evidence is recorded below.
- Open P1, whole-mock scope: actual diff/Changes review, bounded script console,
  repository Graphify and chosen-branch publication remain unfinished roadmap
  items. They are not replaced by fake controls or fabricated terminal output.
- Open P1, whole-mock scope: the shared human-question contract remains CONT-01.
  An arbitrary model question is not represented as a working decision panel.

## Fidelity surfaces

- Typography: existing Inter UI / JetBrains Mono code owners retained. Native
  dev captures exercise real font delivery; synthetic fixtures differ in content.
- Layout: three real scroll owners with vertical rules; tree 208px, agent
  340/380px and flexible source editor. This is the compact token-based adaptation,
  not a pixel-perfect claim for the generated reference's larger tree/agent widths.
- Colors/tokens: existing page/card/foreground/brand tokens and Workbench button
  variants; no new palette, gradients, panel shadows or boxed toolbar groups.
- Assets: existing icon library; no screenshot-as-UI, generated substitute
  terminal, CSS art, new raster asset or decorative placeholder.
- Copy: repository-scoped cost notice and operational empty state; suggestions
  only fill input. Only confirmed server receipts produce a write count. Unknown
  write outcomes never become a claim that no files changed.

## Verification checkpoint

- Native no-LLM proof: folder/create/read/CAS-edit/readback in an isolated runtime;
  owned target preparation, stale-generation refusal and immediate UI lease after
  agent write. Every exact fixture runtime/thread removed after the probe.
- Focused UI tests: 36 passed, including shared owner continuity, IDE submit
  preparation/cancellation, and the PDF vendor test that failed in the full run.
- Full frontend run: 819 passed / 1 failed, 128/129 suites. The separate existing
  PDF vendor-activation test failed under the complete run and passed separately.
  Do not describe that full run as green or silently weaken its assertions.
- Agents full run: 2832 passed / 23 skipped; later two read/unknown-ack regression
  tests passed with the focused IDE/schema suite (26 tests).
- Backend full run: 3566 passed / 129 skipped; subsequent REST confirmation
  fail-closed regression passed in the focused 15-test run.
- Workspace full run: 1114 passed / 132 skipped. Build, ESLint, changed-file Ruff,
  focused MyPy, strict premium audit and root UI contract passed. DESIGN lint:
  zero errors, seven existing token-documentation warnings.
- Global accessibility command: eight Chromium cases passed; responsive IDE
  rerun: six cases passed across desktop/mobile/tablet. Final IDE matrix: 27/27
  passed, including the repaired tablet move action. The later preparation-cancel
  affordance and zero-confirmed-write message have focused unit coverage; the
  subsequent three-viewport agent rerun passed 3/3, including cancelling a delayed
  target preparation without losing input or dispatching its late response.
  Final source build, ESLint, strict audit, UI contract and diff checks passed.
  Native proof repeated after the final service restart; exact fixture cleanup
  succeeded and the two pre-existing user runtimes retained the same container IDs.

final result: blocked

Blocker: full approved IDE visual/functional scope is still incomplete. The
missing-agent-panel repair is implemented and verified, but this report does
not certify whole-page parity or a paid real-model coding task.

---

# PDF Studio — visual and interaction QA, 2026-10-15

## Comparison target and evidence

- Source visual: `C:/Users/denea/.codex/generated_images/01a03caa-cef6-7c30-81dc-b9a4a1ee7694/exec-23471812-186b-4a0e-9dfa-00708213b17f.png`.
- Source: 1485×1059 bitmap; implementation: 1440×1024 CSS/device pixels at DPR 1.
  Full-view comparison opened both images in the same tool input; no pixel-perfect
  claim is made across the different application shell widths or document states.
- Browser implementation: `.work/pdf-studio-1440.png`, `.work/pdf-studio-320.png`,
  `.work/pdf-assistant-running-1440.png`, `.work/pdf-assistant-running-393.png`.
  These ignored captures are local evidence, not published user material.
- Target is the approved third layout, amended by subsequent explicit decisions:
  no conversation canvas/persona onboarding or permanent assistant/scope header;
  input is replaced by the existing trace during a run/decision.
- The reference shows a compiled article and three full introductory paragraphs.
  Current automated captures use a synthetic semantic draft and empty preview.
  They verify layout and interaction, not compiled-preview fidelity or final
  authenticated acceptance. Missing same-state preview capture prevents sign-off.

## Comparison history

1. Earlier capture had bordered form cards, 90px empty section bodies, clipped
   mobile editor actions, a three-row project toolbar and non-descriptive project
   path labels. These were P1/P2 UX differences from the reference.
2. Current capture uses a multiline document title, typographic headings,
   auto-growing prose, quiet block selection, explicit optional section bodies,
   structure navigation and source-preserving save. The project selector names the
   document; the mobile toolbar has two rows. Save/build actions use token-owned
   Workbench button variants rather than marketing gradient/pill variants.
3. Browser testing caught outline navigation focusing the block checkbox. The
   corrected target excludes checkbox inputs and uses Chakra final-focus ownership.
   The post-fix 18-scenario suite passed, including navigation and retained draft.
4. Visual inspection at 320px found build-label crowding despite no page overflow.
   Mobile primary actions now retain full text without decorative icons; the
   regression checks each button's content width, not just document overflow.

## Required fidelity surfaces

- Typography: existing self-hosted Inter/product stack retained; explicit normal
  prose weight, 21px headings and 22/26px multiline title. No font dependency added.
- Spacing/layout: equal initial editor/preview columns, compact natural-height
  assistant dock, aligned sidebar/action boundary, protected mobile text gutters.
  Authoring and preview scroll independently; long prose has bounded inner scroll.
- Tokens: runtime theme owns blue.500 action, neutral surfaces and 6px control
  geometry. Existing landing/admin button variants are unchanged. Strict premium
  audit has no findings; DESIGN lint has zero errors and seven pre-existing
  schema/orphan-token warnings.
- Assets: no new bitmap assets are required. Existing brand/icon assets retained;
  no mock PDF page or fake PDF toolbar was substituted for a compiled artifact.
- Copy/content: factual technical/visual/delivery statuses, no implicit publication
  success, no presentation mode in Chat; unsupported new citations remain explicit.

## Materials follow-up

- The former tree-only drawer now exposes project files, shared thread materials,
  Library, upload and refresh. It reuses the Work upload/copy/pagination owners;
  loading the drawer alone neither provisions Workspace nor starts an agent.
- A selected source opens in the actual fenced editor. Content/LaTeX round trips
  retain it; same-file selection cannot bypass a semantic dirty-draft confirmation.
  Failed reads leave the content surface available with a bounded recovery message.
- Materials do not imply automatic document insertion. Binary assets are not opened
  as text; Library-only partial uploads remain available and explicitly partial.
- File actions initially had 44px mobile hit areas; the later explicit compact
  PDF contract now uses aligned 34px Workbench download/copy actions. The open-drawer axe check found two
  low-contrast shared helper labels (4.38:1); both now use the existing brighter
  foreground token instead of changing the palette or suppressing the rule.
- Ignored captures: `.work/pdf-materials-library-1440.png` and
  `.work/pdf-materials-library-393.png`. These use synthetic API responses, not
  authenticated upload/delivery acceptance or evidence of asset/citation insertion.

## User-feedback follow-up

- Toolbar density is now a theme-owned `workbench` size: 34px desktop/mobile,
  12.5px labels and 14px icons. Project selection is capped at 320px;
  block selection at 200px. A presentation selects Slide, not an empty placeholder.
  Narrow editor panels use accessible structure/save icons rather than pushing
  Save onto a detached row. No landing/admin size recipe was changed.
- PDF trace actions (Stop, Stages and Open in Chat) use that same 34px Workbench
  recipe rather than falling back to large generic Chat controls.
- The existing build owner is projected in an always-visible strip: admission,
  queue and compiler/audit state. Open PDF lives in the main toolbar alongside
  Build Draft and Check Final; mobile uses a labelled compact preview icon.
  An opened PDF changes that read action
  to Refresh PDF. It does not compile/publish; an older preview is labelled during
  a new build and cannot pretend to refresh an artifact that does not exist yet.
- The project selector has no duplicate profile subtitle; its top and height
  match Materials/Formatting. Build buttons never add a second progress spinner.
- Account navigation exposes Chat/Work/PDF, preserves the thread and uses the
  existing dirty-router guard. Rows are 34px, the panel is opaque and scrolls
  within a short viewport. Immediate Escape/reopen no longer inherits a delayed
  exit-visibility animation. Axe caught and fixed an exposed decorative avatar
  and low-contrast blue text in this touched owner.
- Startup distinguishes unknown, loading, confirmed absence and read failure for
  both Workspace and project. Delayed reads never expose creation controls; errors
  offer read retry. Previous-thread projects and retired replies are masked.
  This fixes the false empty-state sequence; real authenticated ~30s server
  latency is not measured or claimed resolved by mocked timing.
- Workspace invalidation and assistant completion re-read project facts and
  changed semantic versions. Local dirty text retains its original edit base.
  Genuine source-only projects are distinguished from failed/loading structure.
- Starting new content over source-only LaTeX has explicit replacement consent,
  initial Cancel focus and no write/lease before confirmation. This is not tool
  billing consent and is not described as reverse-converting a PDF.
- PDF tool consent is backend-derived only after ownership/revision validation,
  then carried through private execution context. Normal Chat retains its gate;
  credit reservation, provider/admin policy and legacy decline remain effective.
  REST now retains the same project anchor as WebSocket. An unidentified PDF
  target cannot silently become an ordinary Chat request.
- Backend, agents and the agents worker were scoped-restarted after both workers
  reported zero active/reserved/scheduled tasks. Later the dev frontend was found
  exited (255, not OOM); it was started separately and internal/host HTTP returned
  200. No reason for its earlier exit is asserted. No paid model acceptance was run.

## Remaining P1/P2 work

- P1: Registered-source selection is implemented below; qualify the bibliography
  lifecycle against a real authenticated project and research handoff. Project image
  intake/insertion is now implemented separately from generic Workspace copying;
  its authenticated compiler/delivery acceptance remains part of the P2 flow below.
- P2: Capture the actual compiled PDF, dirty/older-preview state and delivery through
  an authenticated dev flow, without paid model calls; compare the same document,
  viewport and state with the reference. Current mock-driven passes do not prove it.
- P2: Extend long-document acceptance beyond the proposal review: full editor,
  native mobile keyboard and authenticated artifact states still need inspection.
- P1: Profile the reported ~30s authenticated startup with the existing private
  Work timing collector. Unknown/failed reads are now safe, but mocked delayed
  reads do not identify or improve the real server/network bottleneck.
- P1-UI-FONT20261015 remains tracked in `../docs/PROJECT_TODO.md`: the original
  late font swap was addressed with local optional fonts, but deliberately stalled
  font requests still need separate WebKit/Safari qualification. The bounded
  expected-failure fixture is not cross-browser font acceptance.
  Current rerun: Chromium/Firefox four passes; WebKit two reproduced expected
  failures (`.work/fonts-review-current.json`). Playwright's aggregate green exit
  includes those expected failures; it must not be reported as six font passes.

## Verified engineering evidence

- Agents unchanged: earlier 2765 passed, 23 skipped. Backend latest: 3218 passed,
  126 skipped. Workspace latest: 957 passed, 102 skipped, plus ten isolated native
  import checks passed (the opt-in native suite is separate from the default run).
- Frontend latest full run: 725 tests / 115 suites / one snapshot passed, including
  Auth and WorkHub. Prior loaded runs had timing failures; timeouts were not raised.
  Header follow-up: six tests passed after the immediate menu-visibility fix.
  Lint, production build, strict premium audit and root UI contract passed.
- Dev Chromium: delayed three-stage startup passed without any creation/write;
  visible build/Open-to-Refresh cases passed at 1440/393/320px. Header navigation
  passed at 1440/393/320px, including open-menu axe serious/critical, immediate
  Escape/reopen and dirty-editor guard. Ignored reports: `.work/pdf-account-menu-final.json`,
  `.work/pdf-header-startup-verified.json` (the latter also records the now-fixed
  fast-reopen timing failure; the former is its passing follow-up).
- Compiled PDF/UI browser verification after proposal and read-race changes:
  50 scenarios passed in `.work/pdf-review-compiled-verified.json`, including the full
  PDF matrix and Chat/Work/admin/404 axe checks with no serious/critical violations.
  Final focused unit follow-up after compact trace actions: 45 passed, including
  malformed response handling, ambiguous-save recovery and coalesced reads.
  No authenticated compiled-preview/delivery acceptance is inferred from it.
- Final full Work matrix: 85 passed, eight existing project-specific skips across
  Chromium, tablet and mobile in `.work/work-assets-final-browser.json` (6.6 minutes).
  Prior checkpoints are `.work/work-review-final.json` and `.work/work-polish-verified.json`. Earlier runs
  expected the deliberately removed project subtitle and reset Preview on a
  breakpoint; those assertions now match the approved UI. Overflow checks await
  settled overlay/breakpoint geometry with the same zero-overflow threshold and
  existing assertion timeout. No acceptance threshold or timeout was relaxed.
- An earlier Picodex review settled without its requested artifact; none of those
  worker claims were integrated. The later bounded asset/source inventory completed
  with settled/zero-exit/final-text evidence. Its findings were checked against
  agents draft/editor/renderer and backend proposal/source publication contracts.
  Workspace paths are workspace-relative, not automatically project-owned; source
  publication does not import figure binaries. Existing bibliography keys constrain
  accepted citation IDs. No image/citation insertion is claimed from this inventory.
- No paid calls, production deployment or publication commits performed.

## Proposal-review follow-up

- Review shows Before/Proposed columns (stacked on phones), meaningful table cells,
  figure paths, citation IDs, formulas and heading levels. Unchanged blocks are
  omitted; malformed, foreign or unreviewable mutations cannot enable Apply.
- Close cancels a pending read and restores focus. Chakra owns the modal; the
  comparison region has visible keyboard focus and PageDown scrolling. Actions
  remain reachable at 320×568. Axe found the missing focusable scroll region in
  the first browser run; it was fixed, not excluded from the audit.
- Explicit apply pins revision/version/digest and uses the existing fenced lease.
  Acknowledged writes stay acknowledged if subsequent reads fail; recovery only
  re-reads. Conflicts require a new proposal. An ambiguous write requires fresh
  review before retry; dirty edits and retired targets cannot dispatch a write.
- Browser testing exposed automatic and post-save authoring reads aborting one
  another. The shared loader now coalesces the exact in-flight resource/generation;
  the independent unit regression and five focused browser scenarios pass.
- Focused development-browser coverage passed at 1440/900/393/320px with long
  paragraphs, table/figure/citation comparison, focus trapping, Escape/restoration,
  delayed-read cancellation, stale rejection and single-write/no-compile checks.
  Captures: `.work/pdf-review-1440.png`, `.work/pdf-review-320.png`; passing report:
  `.work/pdf-review-browser-coalesced.json`. These remain synthetic API fixtures,
  not proof of registered source/asset ownership or authenticated compilation.
  Latest unit report: `.work/pdf-review-full-unit.json` (705/114/one snapshot).
- After compacting trace actions, eight compiled browser regressions passed in
  `.work/pdf-trace-compact-final.json`, including measured 34px controls, stable
  sidebar navigation and compact toolbars from 320px to 1920px.
- One compiled browser run was interrupted when a local rebuild replaced files
  being served to that run. Its server failure is not counted as a product pass.
  The subsequent immutable-build run above passed all 50 scenarios.

## Project-image intake and insertion follow-up

- PDF Library images use one clearly scoped “В PDF-проект” copy action, not a
  competing generic root-copy action plus another import button. Other materials
  retain the existing Work intake. Download/copy controls use the shared 34px
  Workbench size on mobile and desktop.
- The existing public Library-copy contract accepts an optional validated project
  path. Server ownership resolution still supplies the source URL privately;
  the project revision and project lease are required. The destination derives
  from the owned Library UUID under project `figures/`, with PNG/JPEG/PDF only.
  The existing staging/import/revision path is reused. Original files win on retry.
  Aggregate import counts without a matching target-file receipt cannot advertise
  an image as available; an older backend's root-copy response also fails closed.
- Image and slide blocks use the shared AppSelect over exact project descendants.
  Known original Library names replace UUID labels; only project-relative paths
  enter the draft. A missing reference stays visible and unchanged. Choosing an
  image and caption neither saves nor compiles; explicit Save remains required.
- Import acknowledgement and read refresh are separate. The authoring read follows
  an acknowledged project revision change even when the semantic version is the
  same, so a clean editor can use the new edit base. Dirty text keeps its old base.
- Browser testing found native disabling of a pending copy button stranded focus
  outside its drawer. The shared Library button now retains focus with aria-busy/
  aria-disabled and a guarded handler. Explicit Add Block also scrolls/focuses the
  new content field. JSDOM's absent scrollIntoView is mocked only in its unit test;
  browser behavior is verified separately, not inferred from that mock.
- The hover-state axe check found copy text at 4.4:1 on its selected card. The
  shared copy action now uses the existing blue.100 token rather than changing the
  palette or excluding the contrast check. No assertion timeout was increased.
- Backend full run after this API change: 3218 passed, 126 skipped; coverage 79.03%
  clears the unchanged 67% gate. A preliminary focused run had 46 passing tests but
  failed the repository-wide coverage threshold; it is not counted as a green gate.
  Ruff and MyPy (421 source files) pass. Frontend intermediate full run: 722/115,
  one snapshot; the post-focus owning follow-up has 51 passing tests.
- The bibliography Picodex inventory completed with settled/zero-exit/final-text
  evidence. Canonical ExistingCitations, source-key creation and owned file reads
  were independently inspected. Numeric IDs alone do not provide a usable source
  picker; duplicate-ID ambiguity remains a prerequisite for that separate work.
  No bibliography registration or citation insertion is claimed here.
- After both local workers reported zero active/reserved/scheduled jobs, only the
  dev backend was restarted. It is healthy and its in-container request model
  exposes document_path. The public OpenAPI URL is disabled (404); no authenticated
  import/compile/delivery acceptance is inferred from the restart or schema check.
- Nested destination review exposed an existing importer gap: lexical safe_path
  alone did not reject a `figures` ancestor symlink. Staging/publication now reject
  aliases; cleanup skips an aliased staging parent instead of following it.
  Destinations that are symlinks/directories are not reported as existing assets.
  This remains the existing operation-guarded importer, not a new binary writer.
- Workspace checks: 957 passed, 102 existing/opt-in skips; Ruff and format pass.
  Offline native Docker import suite: ten passed, including the five original
  atomicity/cancellation scenarios and project/figures/destination/staging alias
  rejection plus successful nested binary copying. Only uniquely named isolated
  fixture containers were removed. An initial structural cleanup-command assertion
  was updated to count the same single cleanup after its new safety prefix.
  These filesystem tests do not prove authenticated Library/compiled-PDF delivery.
- Final frontend evidence: `.work/pdf-assets-final-unit.json` (725/115/one snapshot)
  and `.work/pdf-assets-final-browser.json` (54 passed). Browser cases cover image
  copy/kept/conflict, exact project selection, dirty-base save, keyboard focus,
  open selector, no assistant/build dispatch and axe at 1440/393/320px. Captures
  `.work/pdf-image-insert-1440.png` and `.work/pdf-image-insert-393.png` were visually
  inspected; they use synthetic API responses and an empty preview, not a fake
  compiled figure. The entire Work matrix also passes after the shared copy changes.
- Only the dev Workspace image/service was subsequently rebuilt/recreated after
  live health reported zero active workspaces, document jobs and source publications.
  Health is green and the in-container importer exposes the new symlink guard.
  Other services and production were not rebuilt or deployed.

## 2026-10-16: single sidebar Library

- Library now opens beside Memory/Graph/Settings on all three surfaces. Work's
  source rail/mobile tabs and PDF Materials no longer embed Library lists. The
  ordinary Workspace file-intake action remains an explicit Workspace operation;
  PDF Materials now only inspects project/shared source files.
- The global drawer reuses Work Hub's read model, upload selection/intent,
  pagination, per-file outcomes and protected download/copy operations. Workspace
  is the default copy destination; the loaded PDF project is an explicit choice.
  Unsupported figure types explain the restriction instead of falling back to a
  different destination. Dirty drafts block mutations, not owned downloads.
- Sidebar rows remain 34px including Library. Mobile navigation closes before
  Library opens; returning focus and the extra action-shelf row are regression
  cases. The destination list stays inside the modal focus/stacking owner through
  the shared AppSelect inline variant. A body portal below the drawer and a fixed
  portal displaced by the drawer transform were reproduced and corrected, not
  bypassed with forced test clicks.
- A cold lazy bundle now exposes a dismissible Library loading drawer even when
  Work is hidden behind Chat. Same-URL thread hydration cannot dismiss a just-opened
  Library; changing routes retires captured open/close handlers. Disabled shared
  intake also guards the hidden input and retry, not only the visible drop target.
- Separate startup work overlaps Library DB and Workspace discovery after owner
  verification and awaits cancellation of the owned background read. Backend:
  3224 passed /126 skipped, coverage 78.89% (unchanged 67% gate), Ruff/format and
  MyPy (421 source files) pass. Source-digest publication guards now reject a
  renderer-time race inside the existing Workspace operation lock; Workspace:
  960 passed /102 skipped, Ruff/format pass. These code checks are not authenticated
  dev compiler/delivery acceptance or evidence that the reported 30 seconds is fixed.
- The user confirmed latency both on reload and returning Chat→PDF, locally.
  Three repeated returns retain the same editor DOM and perform no additional
  discovery reads in the mocked desktop/393/320 browser checks. The real private
  latency diagnosis remains open; no paid inference or authenticated acceptance
  was attempted, and no production deployment/commit/push occurred.
- The full Work browser matrix passed: 88 passed /8 intentional project-specific
  skips (`.work/global-library-verified-work.json`). Cold lazy Library loading,
  dismiss/reopen and focus passed independently at desktop/mobile/tablet. The
  pre-final PDF/UI matrix had 59 passed /1 failure: semantic loading could remain
  pending after overlapping project refreshes. A deterministic unit reproduced
  retirement of that read even when project revision/version stayed unchanged.
  Accepted project-read generations now restart the semantic read, and a late
  retired response cannot replace it. This is a separate content-loading race,
  not evidence that real local discovery latency is fixed.
- After that fix, all 732 tests /116 suites /1 snapshot pass
  (`.work/global-library-source-fence-unit.json`), ESLint and production build
  pass (`main.4f099b6c.js`). Root UI contract and strict premium audit pass with
  zero findings; DESIGN lint has zero errors and seven existing custom/orphan
  token warnings. Final compiled PDF/UI checks passed: 60/60
  (`.work/global-library-verified-pdf.json`). Focused post-fix Work Library checks
  passed on desktop/mobile/tablet: 25 passed /2 intentional vendor-layout skips
  (`.work/global-library-post-generation-work.json`). No retries, forced pointer
  clicks, longer test timeouts or weakened accessibility assertions were added.
  Intermediate HMR runs, old navigation/row assertions and hidden spinner-text
  assertions are not green acceptance evidence. The remaining feature work above
  is still open.

## 2026-10-16: registered citation picker

- Citation blocks now select project-registered sources by actual title/year,
  with supplied author/DOI/URL only. Adding a new citation requires a selected
  registered source and explicit Save. Existing missing references remain visible
  and unchanged; source failure/retry never discards dirty prose or its edit base.
  The new-citation picker scrolls inside the editor, preserving scarce reading
  space rather than adding another fixed mobile toolbar row. Shared AppSelect,
  Workbench controls, colors and type are reused; no new visual language.
- The lazy protected read uses the existing thread ownership check and reads only
  the owned project's fixed bibliography path. Project revision/source digest are
  checked again after projection. A private non-metered agents RPC shares its
  bounded reader with ExistingCitations; no separate source-ID trust path or
  compiler/model/write is introduced. Duplicate IDs are ambiguous, not last-wins;
  nested/comment pseudo-entries cannot register citations. The renderer rejects
  unknown IDs and preserves exact bibliography bytes on a valid semantic edit.
- Real CitationRegistry output round-trips through the reader, including escaped
  punctuation and DOI. Raw percent-encoded URLs in literal values work. Unknown
  TeX is not evaluated or converted into invented metadata; oversized metadata is
  omitted, not truncated into a different URL. Unsafe/credential-bearing URLs are
  omitted and the UI renders supplied locator text inertly, never as raw markup.
- The parser respects the existing 750,000-byte source-file cap. Workspace's
  ordinary read boundary is still 256 KiB: a truncated read is unavailable, never
  a supposedly complete partial source list. Large bibliography qualification and
  authenticated document/compiler/delivery acceptance remain open.
- Current source checks: backend 3240 passed /126 skipped, 78.91% coverage with
  the unchanged 67% floor, Ruff/format and configured MyPy (422 files) pass.
  Agents 2783 passed /23 skipped; Ruff and formatting of touched files pass.
  A broad agents format check still finds the previously dirty
  tools/workspace_client.py, which was not silently reformatted. Local-only
  `.work/.gitignore` now keeps generated worker/probe artifacts outside product
  lint/discovery, without changing canonical rules, thresholds or source coverage.
  Frontend: 742 passed /118 suites /1 snapshot, ESLint and production build pass
  (`main.4c3fe55d.js`). Strict UI audit and root composition gate pass; DESIGN lint
  retains seven pre-existing token warnings and no errors. Consolidated compiled
  PDF/UI browser checks pass: 64 in `.work/pdf-citations-final-browser.json`, plus
  the final long-bibliography case in `.work/pdf-citations-long-bibliography.json`.
  The latter checks local filtering, dismissed-query non-commit, popup/control
  width and left alignment within 1px, selection and focus, with no write/model.
  The full Work regression matrix passes: 88 passed /8 intentional skips in
  `.work/pdf-citations-work-regression.json`. No timeout/retry or assertion waivers.
- The non-autoreloading dev backend and agents alone were restarted after both
  workers reported zero active/reserved/scheduled tasks and the Redis agents queue
  had zero messages across priorities. Both services are healthy, frontend HTTP is
  200, live `/api/openapi.json` contains the source route, and an unauthenticated
  source request is 401. A real backend→agents private RPC on synthetic bibliography
  returned id/title/year/DOI without a model or compiler. This verifies private RPC
  wiring, not access to the user's real owned bibliography or full delivery.
- The bounded Pi review wrote a useful snapshot but did not settle; the owned job
  was cancelled after further worker work was unnecessary. Its gaps were reproduced
  independently in canonical tests; its artifact is not a completion receipt.
  No paid acceptance, commit/bump/push or production deployment occurred.

## 2026-10-16: compact document controls and material hierarchy

- Explicit user feedback supersedes the previous 34px-on-mobile PDF recipe.
  Shared `documentControls` now drives Chakra's `document` Button size and
  AppSelect: 30px/12px mobile, 34px/12.5px desktop. Pane choices use their content
  width. Sidebar rows stay 34px, composer targets 44px and mobile editable text
  16px. This is a document-control variant, not a global scale/font reduction.
- WorkspaceTree is now the same collapsible hierarchy in Work and PDF Materials:
  directories before files, project-relative names, visible indentation and
  exact-path selection. Folder disclosure is local/read-only and stays usable
  during processing. Only selected ancestors open automatically; a background
  snapshot does not undo deliberate collapse. Full names wrap and full paths
  remain available through focus/selection readout and accessible labels.
- PDF Materials has one content scroller. Empty `documents` shells and foreign
  projects are excluded from shared files. Binary materials remain non-editable;
  opening text still uses the existing dirty-navigation/read/lease owner.
  Live ZIP scenarios now reveal ancestors before selecting nested sources;
  only syntax checks were run on these authenticated opt-in scenarios.
- Full frontend run: 746 tests /119 suites /one snapshot pass, followed by five
  focused hierarchy tests including project-switch isolation. An earlier loaded
  run hit the existing 5s WorkHub cursor test timeout; both the focused owning
  suite and the full rerun passed without timeout/assertion changes.
  ESLint, production build (`main.5a8d7466.js`), root UI gate and strict premium
  audit pass; DESIGN lint has zero errors and seven existing token warnings.
- PDF/UI Chromium: 68 passed; desktop WebKit hierarchy at 1440px: one passed.
  Touch emulation: 13 passed, one mobile-Safari-at-1440px click/stability timeout;
  isolated rerun reproduced that wide-phone failure while 320px and 393px passed.
  No force-click, larger timeout, retry or expected-failure waiver was added.
  The isolated failure's three font requests completed with HTTP 200 in under
  20ms each: it is not evidence that the separate stalled-font issue caused it.
  Its wide phone-emulation qualification remains open, not a platform-wide pass.
- Browser reports: `.work/pdf-tree-density-browser.json`,
  `.work/pdf-tree-touch-browser.json`, `.work/pdf-tree-safari-isolated.json`,
  `.work/pdf-tree-webkit-wide.json`. New captures use CSS-pixel scale and
  project-qualified names, avoiding inflated DPR previews and cross-project
  overwrites. Authenticated startup latency/native devices/compiler/delivery
  remain open; no backend change or paid acceptance occurred in this iteration.
- Work desktop/mobile/tablet regression against the same frozen build: 88 passed,
  eight existing project-specific skips, no unexpected failures
  (`.work/pdf-tree-work-browser.json`). No authenticated live acceptance was run.
- Picodex completed the bounded read-only density review with agent_settled,
  exit 0 and final text. Findings were rechecked against current code; concurrent
  snapshot findings are not treated as current defects without verification.

## 2026-10-16: startup invalidation, PDF tracking and unused Chat decoration

- Initial snapshot discovery no longer treats an accumulated invalidation version
  as a new event. A genuine invalidation during the pending first read keeps
  loading rather than offering to create an already existing workspace/project.
  The new unit regression failed before the fix; the delayed HTTP/WS browser
  scenario passed in the 69-case PDF/UI Chromium run.
- Work/PDF no longer mount ChatBackdrop. Bounded WebKit probes isolated the unused
  animated blurred bloom as the main wide/high-DPR rendering cost; disabling all
  shared backdrop filters alone did not resolve it. Chat retains its decoration.
  The formerly failing 1440px phone-Safari hierarchy case passed unchanged, and
  the subsequent 14-case mobile Chrome/Safari hierarchy/density matrix passed
  (`.work/pdf-build-tracking-touch.json`). This supersedes the earlier wide-phone
  failure above, not the separate unresolved optional-font/native-device checks.
- The user's apparently endless build was checked against local containers:
  the two latest workspace job manifests were preview_ready, no failure code,
  no retained compiler and two artifacts each. Recent backend logs contained an
  HTTP 409 without endpoint attribution; it is not proof of a compiler error.
  A disposable synthetic project, using the real isolated Docker pipeline,
  measured admission at 2.014/1.918s and completed drafts at 7.468/7.191s.
  Its owned workspace was removed; no account source, model or paid call was used.
  These are diagnostic timings, not a benchmark of the user's document.
- Reviewed the 393px phone-Safari Materials capture and 320px phone-Chrome
  document-controls capture at CSS-pixel scale. Nested names/indentation, wrapping
  of long source filenames, compact two-row toolbar and the preserved composer
  controls are visible; no extra Chat backdrop or onboarding cards are present.
- Reproduced the UI defect: a lease invalidation refreshed the project, advanced
  the shared read generation, retired build polling and prevented busy cleanup.
  Build tracking now has its own abortable lifetime; refreshed/stale project
  snapshots cannot replace its result. Accepted status is shown before lease
  release completes. Thread/project changes still ignore retired responses.
  Four deterministic regressions cover admission invalidation, release delay,
  retired admission and a project read arriving after a newer completed build.
  The owning hook's 21 tests pass; build/profile/billing/isolation policy is unchanged.
- Compiled PDF/UI Chromium checks passed all 71 cases, including both new desktop
  and phone admission-invalidation scenarios. The later stale-read epoch guard
  also passed the owning hook suite. In the concurrent full unit run 750/753
  passed; three WorkHub failures included a 5s timeout and immediate async-state
  assertions. All 18 WorkHub cases then passed unchanged in an isolated recheck.
  These receipts are separate; the earlier mixed full run is not a clean full-suite
  acceptance (`.work/pdf-build-tracking-unit.json`,
  `.work/pdf-build-tracking-workhub-recheck.json`). No test timeout/assertion was relaxed.
- The final serial full unit rerun passed all 753 tests /119 suites /one snapshot
  in 109.862s (`.work/pdf-build-tracking-unit-serial.json`). Final production build
  compiled without warnings: `main.2c25708e.js`, document chunk `6057.2084256c`.
  ESLint, syntax and touched diff whitespace checks pass. The mixed-run failures
  above remain recorded rather than being erased or hidden by a waiver.
- Final-build browser recheck: all five admission-invalidation and visible
  build/Open/Refresh scenarios pass at desktop and narrow widths
  (`.work/pdf-build-tracking-final-browser.json`). No paid/authenticated end-to-end
  acceptance or production deployment is claimed by these mocked browser cases.
- DESIGN records the shared async lifetime rule; no new visual token or one-off
  progress indicator was added. Strict premium audit and root composition gate
  pass; DESIGN lint retains seven existing warnings and zero errors.
- Picodex's bounded read-only build audit settled with exit 0. Its ranking was
  hypothetical; canonical code and the live synthetic timings were checked
  independently. No proposed removal of integrity checks, source freshness,
  container isolation or compiler passes was applied.

## Result

final result: progress

## IDE clone recovery after full reload — 17.10.2026

- The owned clone journal now retains canonical public GitHub URL/ref (migration
  037), checked against the immutable request digest. Discovery is a private,
  no-store GET scoped to the thread owner and either source or destination repo.
  It does not provision, dispatch Git, probe health or call a model. Legacy rows
  without valid parameters remain inspection-only. Explicit matching POST may
  backfill missing parameters, but never replaces existing ones.
- Reload restores a compact recovery row using the existing PDF/document-size
  controls. Continue opens pinned read-only fields and reuses the same intent.
  Running observation is GET-only with a 90-second budget and manual Check after
  expiry. A read failure is not authoritative absence or permission to create.
  Completion announcements are intent-scoped; changing attempts cannot inherit
  a previous completion. Late reads/callbacks and local editor drafts stay fenced.
- Native authenticated dev: two simultaneous first-entry tabs shared one default
  project; a changed source file was saved, then an owned reserved clone attempt
  was seeded as a loss-before-dispatch precondition. Full mobile reload restored
  its URL/ref without a clone POST. Explicit Continue completed one real GitHub
  clone using the original intent. A second reload did not replay it. Exact API
  readback preserved the source file; two distinct project runtimes and the exact
  test thread were removed. No user project, Library, PDF binding or LLM run was
  changed. This is not a process-kill-during-Git recovery acceptance test.
- Backend focused recovery/HTTP/disposable-PostgreSQL corpus: 26 passed. Schema
  037 is installed on dev. Focused Ruff/format and MyPy (three source files)
  passed. Frontend full unit/integration run: 868 passed /133 suites /one snapshot;
  React act/Router future warnings remain visible. ESLint, production build,
  strict premium audit (zero findings), root UI contract and scoped diff checks
  passed. DESIGN lint: zero errors /seven existing warnings. No visual tokens or
  global sidebar divider changed; DESIGN.md records the intentional recovery
  behavior evolution, not a palette/layout redesign.
- Earlier failures are retained: the previous full unit run had one 5-second
  WorkHub late-snapshot timeout (857 passed); the unchanged test passed in the
  final full run. An added recovery-contract fixture omitted the required
  repository state; the fixture was corrected, not the validator weakened.
  Two combined browser runs were 71 passed /one tablet total-test timeout in a
  long agent scenario. Its trace reached the final return-to-IDE checks after
  combining suggestion/draft/cancel/run/result/Chat behavior in one 30-second
  test. It is split into two independent scenarios with all assertions retained;
  neither test timeout nor retry budget was increased.
- Final frozen compiled browser verification after that split: 75 passed across
  Chromium desktop, tablet and mobile Chrome (51 IDE cases plus 24 accessibility
  contract cases). The split tablet flows took 20.7s and 15.2s under the same
  unchanged 30-second limit. Artifacts are ignored under
  `.work/ide-clone-recovery-verified`; native mobile recovery was visually
  inspected separately. These mocked browser cases do not replace the native
  Git acceptance or establish a real-provider LLM coding result.
- The manifest's legacy Work E2E command was rechecked with one-failure cutoff:
  one failed /95 not run, still waiting for the obsolete “Работа” button. This
  gate is not green or replaced by a claim about the new IDE browser corpus.
  Private credentials/other hosts, long clone jobs, real LLM coding acceptance,
  human-question, scripts/Stop/output, Graphify, archive and Git publication
  remain open in the ordered product plan.

final result: progress

## IDE writable setup and file move — 17.10.2026

- The user-reported write failure was a dev deployment mismatch: hot-reloaded
  controls preceded backend routes and the rebuilt workspace image. Both services
  now run the mutation handlers; existing user runtime containers were preserved
  across sidecar updates. No user repository was initialized, cloned, moved or
  deleted by acceptance checks.
- Native authenticated UI fixtures confirmed file/folder creation, editing,
  runtime write, explicit server readback, Git init, public GitHub clone and
  file move with tree/tab retargeting plus a second server readback. Fixtures
  used the isolated acceptance account and exact owner cleanup, not user data.
  Clone is Git pack/history/origin, not archive import; public GitHub only, 20 MiB
  object limit, networkless execution environment, no hooks/scripts/submodules.
- Mobile 393px and desktop screenshots were inspected. Move reuses AppSelect,
  existing modal ownership and compact document controls (30/34px). Files and
  Git actions are separate quiet groups; no palette/global sidebar change.
  Move has a keyboard/touch destination picker, not a drag-only interaction.
  A stale cached destination is retired only after a confirmed no-clobber move.
- Shared WorkspaceEditor has a business-named IDE variant: memory-only drafts,
  explicit path lease/digest-CAS write, temporary-storage wording, no automatic
  Git commit. Dirty-navigation lifecycle owners compose across retained PDF/IDE.
- Backend full suite: 3558 passed /129 skipped, coverage 79.45% against unchanged
  67% floor. Workspace full suite: 1112 passed /132 skipped. Separate exact-source
  networkless Docker acceptance: 6 passed (write/Git/move), with test resources
  removed. Changed-file Ruff/format/MyPy and diff checks passed.
- Frontend full suite: 818 passed, 128 suites, one snapshot. Production build,
  ESLint, root UI contract and strict premium audit (zero findings) passed.
  DESIGN lint has zero errors /seven existing warnings. Post-final-cache-fix
  focused hooks: 39 passed. Compiled IDE browser: 24 passed across desktop,
  mobile and tablet, including move failure/retry/axe. After the final cache fix,
  the compiled create/edit/move browser flow passed again on all three viewports
  (3 passed); the earlier compiled run alone was not treated as proof of that edit.
- Accessibility matrix: 24 passed on an isolated rerun without rebuilding assets
  beneath its server. The initial concurrent run was 17 passed /7 failed with
  server-unreachable/navigation failures, not a green accessibility gate.
- Legacy Work E2E remains red: its first test still asks for the removed “Работа”
  navigation label (one failed /95 not run under fail-fast). It was not weakened,
  skipped or relabelled as a green full gate. Its migration remains separate from
  the passing repository-owned IDE corpus.
- Drift: the read-only contract was intentionally extended to verified explicit
  mutations using existing tokens/owners. Durable saves, execution/agent,
  Graphify, archive and user commit/push remain open; this is not full IDE sign-off.

final result: progress


This is a progress checkpoint, not a production/design completion claim. The
overall page-polish goal remains active until remaining workflows and same-state
visual evidence are completed. No source/profile/billing contract is waived.

## IDE read-scene checkpoint, 2026-10-17

- Implemented the first repository-owned scene at the compatible `surface=work`
  URL; header, account menu and title now say IDE. It uses the dedicated registry,
  runtime/tree/file API, not a renamed legacy/PDF workspace. Reads are scoped and
  retired by thread/repository/generation/path. Missing data never fabricates an
  empty registry or provisions a sandbox. Source state remains memory-only.
- Source rail is 240/280px; the central code surface owns overflow. Mobile uses
  Files/Code panels and the existing 30px document controls; desktop uses 34px.
  The selector stays capped, filenames wrap, and partial folders are not called
  empty. A successful file choice moves focus into Code; failure is visible even
  from mobile Files and retains previously read text. Binary/partial files are
  labelled. No editing/Git/Graphify capability is advertised as already working.
- The existing Library/PDF owner mounts on first use, never on IDE entry. A
  deterministic component test and browser counter verify zero legacy snapshot
  reads from a fresh IDE visit. Attachments open Library; saved-document recovery
  opens PDF through the same navigation guard. Profile-query consumption moved
  to the existing URL owner to keep the container under its unchanged size gate.
- Visual review opened desktop and DPR-scaled phone captures from
  `tmp_e2e/ide-acceptance/*/ide-read-scene.png`. Physical screenshot pixels are not
  CSS control dimensions. Browser geometry verified actual 30/34px heights and
  the opened selector popup's width/alignment. The shared WorkspaceTree file-size
  foreground changed from fg.4 to fg.3 after axe measured 4.4:1 on its raised
  selected row; no new palette or exception was introduced. The source/editor
  separator now uses border width/style separately so responsive shorthand does
  not accidentally turn it white. The global sidebar divider is untouched.
- Final functional unit corpus: 787 passed /124 suites /1 snapshot. IDE browser
  corpus: 15 passed across desktop/tablet/mobile; accessibility corpus: 8 passed;
  complete compiled PDF corpus: 67 passed; retained Library corpus: 15 passed.
  They use bounded synthetic APIs and do not certify installed backend migrations,
  paid agents, real repository credentials, native mobile devices or push.
  The 640px reflow case is a proxy, not proof of native browser 200% zoom.
- A final copy-only publication-warning correction points to Library in the
  sidebar rather than Work/IDE. Its owning DocumentForgePanel suite passed all
  30 cases after the edit. Production build and ESLint passed. Root UI composition
  and strict premium audit passed; DESIGN lint keeps seven existing warnings and
  zero errors. No baseline/threshold, test timeout or behavioral assertion was
  relaxed. The earlier 701-line container failure was fixed structurally.
- Earlier verification attempts are not silently called passes: concurrent
  Playwright invocations shared an artifact directory and produced ENOENT cleanup
  errors; rebuilding the served build interrupted a PDF server. Corrected runs
  used separate output directories/ports and a frozen build. Library upload tests
  now open the actual sidebar drawer before selecting a file; old peer selectors
  were migrated to IDE while retaining geometry, focus, dirty and no-mutation
  assertions. The full legacy Work gate still stops on its obsolete Work-screen
  selector (1 failed /95 not run). Only its 15 retained Library flows are claimed
  green; its remaining editing/context scenarios must migrate with the new IDE.
- This is progress, not IDE or overall design sign-off. New backend/sidecar code
  is not deployed by these browser checks. Durable sources/recovery, editor and
  leases, creation/clone, assistant tools, script runs, Graphify, export and Git
  remain tracked in PROJECT_TODO. The complete future three-part layout is
  documented in DESIGN rather than exposed as inactive placeholder controls.

## IDE approved-mobile implementation slice, 2026-10-17

- User approved the mobile Code / Files / Agent / Graphify direction and asked
  for implementation. The design pause is lifted in DESIGN and the root plan.
  This checkpoint implements only the file-reading part, not the full IDE.
- IdeCodePane now owns compact open-file navigation, close and explicit refresh,
  a readable full path, optional source highlighting/line numbers and a factual
  read-only status. Files and Code retain one mobile content area. The existing
  document controls remain 30px mobile /34px desktop; no global sidebar or its
  divider was changed. Navigation uses native labelled buttons, not an incomplete
  ARIA tab widget. Closing with keyboard restores focus into the source region.
- The read hook retains at most eight validated files in memory within the
  current thread/repository/runtime generation. Tab selection does not reread;
  refresh does. Failed refresh preserves source; removed paths/new generations
  retire their cache. Captured obsolete actions and late superseded reads cannot
  revive tabs. This is neither an editable draft nor durable source storage.
- Chat and IDE share one curated PrismLight grammar owner, using the installed
  dependency. Unknown languages and source above 64Ki characters stay literal;
  optional chunk/render failure also leaves readable source. Actual grammar,
  literal HTML safety, Chat's existing code/copy UI and failed enhancement are
  tested. Jest 27's resolver mirrors refractor 5's actual package export paths;
  no mocked grammar replaces the integration test or production dependency.
- Inspected the approved phone image against actual phone and desktop code
  captures in ignored `.work/ide-implementation-20261017/compiled-ide/` (and
  dev captures under `browser-final/`). Hierarchy, bounded tabs, breadcrumb,
  source area and neutral dividers are the implemented subset. The screenshot
  fixture contains a long line/long folder to exercise internal overflow, not
  user repository content. Physical DPR pixels are not CSS control dimensions.
- Full unit run: 799 passed /125 suites /1 snapshot. Later final focused tests:
  28 passed /4 suites, including the new enhancement-failure case and the Chat
  code-block regression. Final ESLint and production build passed. Strict premium
  audit and root composition gate passed; official DESIGN lint has zero errors
  and seven existing warnings. Frozen compiled IDE browser corpus: 18 passed
  across desktop/tablet/mobile; general accessibility corpus: eight passed.
  PDF editor/assistant/layout regression: four passed at 1440/900/393/320px.
- Earlier failed checks are retained as evidence: initial Jest integration found
  its unsupported ESM export resolution and one stale callback dependency, both
  fixed and rechecked. The first dev browser run was 15 passed /3 failed because
  a new test clicked React Select's hidden dummy input; targeting its visible
  control preserved the pointer assertion. The next dev run was 16 passed /2
  failed before IDE mounted. Hot updates/concurrent local load may contribute,
  but this is not a proven root cause or a solved dev startup claim. The final
  frozen run used a separate owned server/output, no raised timeout or retry.
- Full IDE acceptance remains blocked: durable capture/restore and file writes,
  creation/clone, scoped agent/tools/questions, run/terminal, Graphify, export
  and user-owned Git publication still need implementation and integration.
  The right assistant rail and four mobile panes are not falsely represented by
  inactive controls. No new DB migration was applied and no backend/sidecar was
  deployed. The pre-existing full legacy Work gate remains red/unmigrated.

final result: progress

## IDE entry recovery and explicit project setup — 17.10.2026

- Reported black scene reproduced as a real registry 404 for a new Chat UUID
  with no persisted thread. A saved test thread returned 200; current dev DB
  was already schema 034, not the historical 031 audit. No migration was run.
- Passive draft list is empty without writing; existing foreign threads still
  return 404. Explicit Create atomically saves an owned thread and repository
  descriptor, reusing an immutable intent after ambiguous acknowledgement.
  The form retains its submitted name; Start environment remains a separate
  explicit operation, not an automatic side effect of navigation or creation.
- Failure without cached rows now has a centered recovery scene, not a black
  canvas. Retry renders loading until resolved. Cached rows/files remain readable.
  Existing AppSelect, Chakra form controls, AppLoading, document-size buttons,
  colours and scrollbar owners are reused. Mobile button height is 30px;
  the form owns its internal vertical scroller.
- The backend was restarted to load mounted sources. Workspace's old image
  lacked allocation protocol. Its image was rebuilt/recreated only after a
  zero-managed-container check and exact environment-value comparison; workers
  and user configuration were untouched. Both services are healthy afterward.
- Native authenticated dev browser, isolated existing test actor: new Chat →
  editable form → one confirmed registration → persisted list → explicit Start →
  ready runtime/tree. Desktop 1440px and phone 393px screenshots were inspected.
  No model call, PDF retarget, Library write or source modification occurred.
  Exact test container was removed through its authenticated owner binding, then
  exact synthetic thread rows were removed; final managed-container count is zero.
- Backend full suite: 3543 passed /129 skipped, coverage 79.59% with unchanged
  67% threshold. Focused IDE 37 passed; disposable PostgreSQL concurrency/ownership
  proof passed (14 descriptor +9 runtime cases, fixture DB removed). Changed-file
  Ruff/format and MyPy passed. Workspace full suite: 1103 passed /129 skipped.
- IDE focused frontend corpus: 34 passed. ESLint, production build, strict premium
  audit (zero findings), root UI contract and diff checks passed. DESIGN lint:
  zero errors /seven existing warnings. Compiled IDE browser: 21 passed across
  desktop/tablet/mobile, including form validation and axe on the invalid form.
  Accessibility corpus: 24 passed across the same three projects after updating
  its obsolete heading and waiting for the enabled refresh action before focus.
- Earlier failures are not hidden: the initial mixed browser run was 41 passed /
  four readiness failures, not axe violations (three obsolete heading selectors,
  one attempt to focus refresh before loading finished). No timeout was raised.
  Full frontend corpus was 807 passed /one legacy WorkHub timeout; unchanged
  WorkHub then passed separately (18 tests). That does not certify a green full
  frontend run or the still-unmigrated legacy Work E2E gate.
- Drift: established compact controls/colours/layout are unchanged. The formerly
  passive-only IDE scene now has explicit registration/runtime activation;
  DESIGN.md records this approved functional evolution. Clone, writable source
  editor/durable Save, scripts, agent/questions, Graphify, archive and push remain
  open in the ordered plan. This is not completion of the full IDE roadmap.

final result: progress

## IDE mini report verification — 17.10.2026

- Approved behavior: IDE displays a plain-text one- or two-sentence report from
  `ide_finish_task`, bounded to 280 Unicode code points. Full reply/code remains
  available in Chat. Confirmed file receipts and uncertain writes are separate
  from model prose; the report never counts as a file write or Git commit.
- The existing persistent Chat/PDF composer, bounded trace, result panel, tokens
  and scrollbar owners are retained. No sidebar divider or control size changed.
- Progressive disclosure now retains this local report tool from the already
  authorized candidates, including subsequent rounds. It cannot resurrect a
  capability denied by context, model support or configuration. Two red cases
  reproduced removal before the fix; all four authorized/absent-stage cases pass.
- Focused agents finish/tools/disclosure: 51 passed; grounding/runner: seven
  passed. Full agents: 2861 passed /23 skipped. Full backend: 3645 passed /
  129 skipped, coverage 79.70%. A preceding focused backend run passed its 14
  assertions but failed the global coverage threshold; the full run clears it.
- Compiled browser agent-result workflow: three passed across desktop, tablet
  and mobile, including axe, restored composer, hidden full reply, Chat navigation
  and return to the same mini report. Screenshots visually inspected at desktop
  and mobile. Separate accessibility command: eight passed. Build, ESLint,
  project UI contract and strict static audit pass (zero audit findings).
- Full frontend corpus on this source: 134 suites /884 tests /one snapshot pass.
- The manifest's legacy Work E2E command is still red: one failed /95 not run,
  because its first test searches for the retired "Работа" button instead of IDE.
  No timeout or accessibility rule was relaxed to hide this migration debt.
- After authoritative worker/document idle checks, only the mounted-source agents
  container was restarted. It is healthy and its runtime registers the unbilled
  finish tool. No paid real-model request was run; model compliance is not claimed
  from scripted browser frames. Full IDE-05 acceptance remains open.

final result: mini report verified; full IDE roadmap remains in progress

## IDE draft conflict and lost-ack recovery — 17.10.2026

- IDE-03 extends the canonical WorkspaceEditor conflict owner: immutable base,
  memory-only local draft and generation-pinned environment read. Explicit
  Edit/reacquire reads under the owned lease before enabling edits; a changed
  base does not silently rebase the draft. A Save without a current edit fence
  is refused. Captured recovery/discard actions and late reads cannot affect a
  different repository. Generation replacement retains copyable text.
- Read-only comparison never repeats a write. Matching content after a lost ACK
  is a current observation, not an invented write receipt. Reviewed full text
  loads only on an explicit action and updates the existing read cache; partial,
  binary, mismatched or unavailable reads leave replacement disabled. Cache
  consumer failure cannot downgrade an acknowledged write. Recovery controls
  stay busy until failed-write lease cleanup completes.
- No token, sidebar divider, global shell or PDF behavior changed. The existing
  compact button/textarea/conflict owners are reused. Mobile removes duplicate
  read-only warnings, puts actions before the bounded comparison and preserves
  at least an 80px selectable draft; the editor owns short-height overflow.
- Six red unit cases reproduced the missing/unsafe recovery before the fix.
  Initial browser check: eight passed /one tablet contrast failure (2.97:1 during
  disabled-to-enabled transition). Recovery uses the canonical neutral action
  and excludes opacity/text-colour transitions, without an axe exemption.
  A subsequent UI iteration temporarily removed the reacquire button: 93 passed /
  three missing-action failures. The action was restored inside the same panel;
  no timeout or selector was weakened to hide it. Final checks follow below.
- Native authenticated dev: isolated owned project/file; a second actor writes
  another version through real lease/CAS APIs. The first editor keeps its draft,
  rejects stale Save and adopts the reviewed version only explicitly. Then a real
  successful write response is deliberately dropped; readback proves exact text
  and no duplicate write. Desktop/mobile screenshots inspected. No model request,
  Git commit, Library upload or user-project mutation. Fixture runtime/thread
  removed; managed-container list is empty afterward.
- The first native attempt stopped on a helper-only missing `.cjs` extension and
  removed its fixture in finally; corrected helper rerun passed. No orphan fixture
  or success claim from that failed attempt remains.

- Final current-source checks: 135 frontend suites /898 tests /one snapshot pass;
  compiled IDE + accessibility matrix 96 passed across desktop, tablet and mobile
  with no retries. Production build, ESLint, root UI contract, strict audit
  (zero findings) and diff checks pass. DESIGN lint: zero errors /seven unchanged
  warnings. Final audit artifact: `.work/ide-editor-recovery-audit.json`.
- The configured legacy Work E2E command remains red on the retired "Работа"
  selector (one failed /95 not run). This is not a green full repository gate.
  Actual runtime expiry/replacement with a draft and the full ordered IDE
  acceptance remain open; no durable browser draft storage is introduced.

final result: draft conflict/lost-ack recovery verified; full IDE remains in progress

## IDE runtime loss and non-destructive Refresh — 17.10.2026

- Refresh while the editor owns a source copy observes runtime/tree without
  discarding that text or changing registry selection. Pending/failed runtime
  verification immediately revokes write permission. Copy remains available;
  acquiring a new fence waits for old-fence cleanup. Replacement-generation
  source requires an explicit compare/adopt step, not silent rebasing or replay.
- Losing a real dev allocation preserved both a dirty draft and a previously
  clean editor snapshot. Save/reacquire were disabled, no replacement allocation
  or write was dispatched, and cancelling the shared navigation guard retained
  the text. Exact fixture runtimes/threads were removed. A removed allocation is
  unknown, not guessed TTL expiry. Generation replacement is fixture-based,
  not a forced rewrite of a user allocation. Desktop/mobile screenshots inspected.
- No global sidebar/divider, tokens or PDF flow changed. This is memory-only
  rescue of one open source copy, not durable storage of the repository. The
  existing private capsule/storage foundation still needs lifecycle integration,
  retention/quota/cleanup and restore acceptance before claiming durable Save.
- The first full frontend run in this checkpoint was 904 passed /one failure:
  the replacement-source scenario observed a disabled initial Refresh before
  preparation settled. The test helper now awaits the actual React preparation,
  open and edit actions with act; no timeout or assertion was relaxed. The
  corrected IdeStudio/editor corpus passes all 31 cases. Later complete results
  are recorded below; this failed run is not presented as green.
- Current compiled IDE/accessibility matrix: 105 passed across desktop, tablet
  and mobile, no retries. Current native dev dirty-copy retirement passed with
  exactly one preparation, no replay/replacement, and acknowledged fixture
  removal; the managed-container list is empty afterward. ESLint, project UI
  contract, strict audit (zero findings) and scoped diff checks pass.
- Final full frontend rerun: 135 suites /905 tests /one snapshot passed. React
  act and Router future warnings still appear; none were suppressed. The
  configured legacy Work E2E migration debt described above is unchanged, so
  this is not a green full-repository quality-gate claim.
- Production build rerun compiled successfully after the final checks.

final result: runtime-loss rescue verified; durable project restoration remains open

## IDE completion, panel sizing and Markdown — 17.10.2026

- The final report is semantic rather than receipt boilerplate. A model ending
  in prose without `ide_finish_task` gets at most one bounded, metered repair
  round through the existing provider session, offering only the already
  authorized finish tool. Other calls are discarded; no workspace write replay.
  Existing reports, cancellation, prompt budget and deadline suppress repair.
  Full Chat text remains unchanged. No-write receipts are not repeated below
  the mini-report; legacy generic fallback is not presented as semantic content.
- IDE uses PDF's split owner with independent keys for tree/code and code/agent.
  Assistant starts at half the available width, like PDF; pointer and keyboard
  resize preserve input. Mobile retains one explicit area. Sidebar untouched.
- Completed trace expansion now has one owner. Collapsing the inner trace also
  releases the reserved height and changes the outer action back to “Этапы”.
  Running and explicitly expanded traces remain bounded/scrollable.
- User confirmed account switching while retaining the previous Chat URL.
  Native read-only probe: an unpersisted UUID returns 200 for both IDE registry
  and PDF work snapshot. Only an owned-read 404 triggers a fresh UUID on the
  same surface; 503/network errors do not create projects. Ownership checks
  remain unchanged. Browser fixtures verify both IDE and PDF transitions.
- Markdown sources now switch Code/Preview without writes. The public Chat
  renderer/prose owner is reused with a repository variant that does not strip
  model-only tags or repair file syntax. GFM headings/lists/tables and code are
  supported. HTML is inert, images are not auto-fetched; relative links use the
  guarded file navigation and external links do not retain opener/referrer.
- Checks: 136 frontend suites /913 tests /one snapshot pass; agents 2871 pass,
  23 skip. Compiled IDE matrix: 91 pass, two intentionally desktop-only sizing
  cases skip on mobile/tablet. Project accessibility command: eight pass.
  PDF denied-scope regression: three viewports pass. ESLint, production build,
  UI contract, offline wire parity, scoped diff checks and strict audit pass
  (zero findings); DESIGN lint has zero errors/seven unchanged warnings.
  Actual screenshots of report, resized panels and Markdown were inspected.
- Early red runs found missing terminal-event classification (removed needless
  new event), old Jest ESM/export resolution gaps (mapped actual package exports,
  not renderer mocks), and an unscoped synthetic reply in the browser fixture
  (fixed repository metadata). Final assertions were not relaxed.
- Native agents service was restarted after Celery inspection reported zero
  active tasks. Health/engine and local final-tool recording pass in-container;
  no paid model request was made, so real-model phrasing is not live acceptance.
- Configured legacy Work E2E remains red on the retired “Работа” selector:
  one failed /95 not run. No green full-repository claim. Full ordered IDE and
  durable snapshot/history integration remain open.

final result: completion/layout/Markdown changes verified; full IDE remains in progress

## 2026-10-18 — public IDE Save/history/restore continuation

- Two compact toolbar icons, no additional toolbar row. File write and durable
  project Save retain distinct labels. History uses the existing token palette,
  Chakra Modal, bounded body scrolling, stable close/focus behavior, explicit
  restore confirmation (Cancel initially focused), and accurate B/KB/MB/GB labels.
- Unknown acknowledgement retains only a frozen opaque intent in session storage;
  reopening/reload never dispatches a mutation. Same-intent retry/reconciliation
  is explicit. A late historical publication never claims current files changed.
- 23 focused unit tests passed (8 new hook cases +15 IdeStudio). Existing read
  scenario still emits an act warning. Changed-source ESLint passed; production
  build passed. Strict premium audit:0 findings; UI contract passed. DESIGN lint:
  0 errors/7 unchanged warnings. Full suite was not rerun and its prior red result
  remains a separate gate, not erased by this focused pass.
- Compiled browser Save/history/expiry-restore/confirmation/focus/320 scenario
  passed. Native authenticated dev browser Save created a second durable version
  in a labelled QA scope, history passed at1440/320, no horizontal overflow,
  unexpected writes0, agent messages0. Native screenshots were inspected; an
  initial generic modal background, zero-MB rounding and duplicate success
  message were corrected through existing tokens/feedback ownership.
- Backend native proof independently exercised actual35-second runtime expiry,
  restore into a new generation and exact UTF-8 file contents. The browser proof
  is native Save/history; its restore confirmation coverage is mocked, not claimed
  as a second native UI-expiry run. Protected credentials/storage locators are
  neither captured to browser traces nor included in output.
- Evidence: `.work/save-restore-native/ide-history-desktop.png`,
  `.work/save-restore-native/ide-history-320.png`, compiled browser artefacts in
  `.work/save-restore-browser/` (ignored). Pending-upload discard UI and recovery
  from lost uploader settlement remain open; the full IDE is not complete.

## 2026-10-18 — safe cleanup of unfinished IDE snapshots

- History now includes terminal uncollected records as cleanup tasks, never as
  restore options. Deletion is offered only after server settlement evidence and
  requires confirmation with Cancel initially focused. Current status is re-read
  immediately before dispatch; published/HEAD snapshots remain protected server-side.
- Unknown delete replies retain the previous intent and quota until collected
  proof. Checking an acknowledged deletion does not issue another delete or Save.
  An unrelated pending operation remains intact. The existing modal/feedback
  owners were extended; no new toolbar row, raw colors or overlay stack added.
- 15 hook tests passed, including double activation, publication race, malformed
  status, unknown writer, lost ACK, retained quota and active-visit retirement.
  Three compiled browser cases passed: ordinary Save/history/restore, cleanup at
  320px with waiting state/Cancel/focus, and lost cleanup ACK. Initial browser run
  found a real stale-DOM focus bug; actions now register by immutable ID. The
  assertion was preserved. Empty history no longer advertises unavailable restore.
- Native configured-storage cleanup passed: a real QA-capsule copy is protected
  before writer settlement, discoverable after retire commit, deleted by public
  API with exact1747-byte logical capacity release and idempotent replay.
  Published original and UTF-8 README remain intact. This is not a crash/writer
  quiescence test; settlement follows actual storage put completion.
- Backend route tests now install production exception handling and verify
  structured domain codes/private headers instead of only bare FastAPI detail.
  46 focused backend tests and the 17-group PostgreSQL probe passed; targeted
  MyPy/Ruff passed. Strict audit0 and UI contract passed; ESLint/build passed.
  No full-suite green claim: prior broad red result remains separate.
- Process-crash recovery without a settlement receipt and periodic orphan sweep
  remain open. No production, remote Git, provider run or global left divider change.
