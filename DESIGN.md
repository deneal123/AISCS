---
version: alpha
colors:
  page: "#000000"
  surface: "#0A0C12"
  surfaceRaised: "#0E1119"
  primary: "#2D5BFF"
  textPrimary: "#FFFFFF"
  textSecondary: "#8A90A2"
typography:
  product:
    fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
  code:
    fontFamily: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
rounded:
  control: "6px"
  panel: "10px"
spacing:
  compact: "8px"
  normal: "12px"
  section: "20px"
components:
  workHub:
    density: "compact"
    sourceLabels: "required"
  workspaceEditor:
    conflictRecovery: "reload-before-overwrite"
---

# GPTHub product UI

## Simulator profile (27 October 2026)

The current default is the registered MaleCNS whole-CNS preset when its dataset
is installed. All 166,700 neurons are drawn; only display connections use LOD.
The source graph and event journal own activity, never stimulus sliders. Raw EM
coordinates, the view-only body embedding and schematic peripheral routes remain
distinct. Peripheral paths follow the rest-pose FlyBody limbs and its conditional
display pose. The old local preset remains independently replayable.

`connectomeData` owns typed-buffer validation and `useConnectomeData` owns the
authenticated, run-scoped read, cancellation and retry. A missing or corrupt
buffer has an explicit error; it never becomes a fake local fallback. Saved
spike events drive the point cloud and graph-delay transmission cues. Idle
scenes stay still and rewind clears the event clock. The whole-CNS preset starts
with transparent body, a closed local aperture and a compact recording strip.
Input-region picking and local E1/REF placement are mutually exclusive modes.
Preset and input selection use the canonical AppSelect, with no screen-local
dropdown. Unsupported abdominal input remains disabled with an explicit reason.
The local classifier's accuracy is never shown as whole-CNS accuracy.

`/simulator` reuses the product header, graphic mark, tokens, Chakra controls,
shared `useAppToast`, authenticated API client and file downloads. The wordmark
is hidden in this profile. The left list owns experiments, with experiment
icons; it does not create chat threads. The main surface is one large 3D scene,
with a compact E1−REF recording below and an on-demand parameter/electrode panel.
No screen-local select/toast/modal system or permanent dashboard card grid is added.

`features/simulator/SimulatorPage` owns draft vs saved configuration, selection,
request cancellation and playback. Accepted runs remain immutable. Escape
restores the electrode draft and returns focus. Invalid physical coordinates
disable Apply and Run with a textual reason. Placement must be explicitly applied
or cancelled before Run; a valid but uncommitted position cannot start a calculation.
Snapshot versions and selection
identity prevent late HTTP/WebSocket results replacing another experiment.

The scene uses the independently licensed FlyBody model used by SIM-003;
`public/assets/simulator/flybody` owns provenance, checksums and Apache-2.0.
Old registered FlyGym scenes remain replayable. The registered source surface,
author-defined neural geometry and visual pose are distinct. Body materials
retain source normals/colors; one global scene time drives neural highlighting,
recording cursor and a clearly labelled conditional leg reaction. Heat maps,
external stimulating contacts and free locomotion must not appear as calculated
results before their numerical adapters exist. E1/REF are recording contacts.

The local window is a view-only aperture with a faint thorax outline; it does
not remove tissue from the operator or change the registered picking mesh.
The local-focus and reset-camera controls work in both single and paired views.
Paused unchanged scenes do not redraw the GPU; files/record-only views release
the 3D renderer. Native OrbitControls keyboard navigation is documented beside
the canvas: arrows pan and Shift+arrows rotate. Contact coordinates also remain
editable without dragging.

Comparison is a separate tab, never the default layout. A is an explicitly
pinned completed record; B is the selected completed record. Camera and model
time are shared. The two signals use one physical amplitude range, never
independently normalized ranges. `features/simulator/theme.js` owns the trace
palette (`SIMULATION_TRACES`): pinned A is amber and selected B is blue; labels
repeat these identities. Auxiliary input/spike/motion tracks belong to B.
Each pane shows its saved parameters, contacts and prediction, including errors.
Model, units, actual time axes, engine/runtime/operator versions and registered
coordinate frame must be compatible. Missing provenance does not imply equality.
Incompatible records have a reason instead of a fabricated aligned scene.
The URL restores `run`, `compare` and `view=comparison`; a missing/forbidden A
preserves accessible B as a single record with a recovery notice. View changes
and reload never submit another calculation. New experiment clears the pair.

The recording strip can expand into one shared-clock view of scheduled ExpSyn
conductance increments (µS), six-cell spike events, conditional leg-root angle
(degrees) and E1−REF (µV). Orange denotes input, mint denotes actual threshold
events. Missing historical input journals are labelled missing, never plotted
as observed zero input. Trace geometry is cached; playback redraws the cursor.
Changing any draft parameter labels the displayed signal as the saved run's
record until another calculation completes. Animation and the event journal
are excluded from classifier features.

Presentation mode uses the browser fullscreen API on the simulator workspace,
leaving the global platform header outside it. It temporarily hides history and
auxiliary tracks, while retaining run/stop, replay state, time and the recording.
Exit restores the prior layout; API refusal keeps the windowed application usable.
View/settings/fullscreen transitions cancel uncommitted placement; repeated
Electrodes clicks never rebase its cancellation snapshot. Applied positions stay
as the next draft and do not change a saved trace.

History uses explicit server-backed “Ещё опыты” paging, retaining visible records
on read failure and retrying the failed page. Refresh cancels an old pending page.
Artifact lists are owned by selected run and files view: late reads are aborted
and cannot populate another run. Failed reads have an inline read-only retry.
Shared HTTP GET retries remain in force. WebGL loss leaves files and recording
available; an explicit 3D retry recreates only the renderer, without submitting work.
Region hover distinguishes the nearest registered source surface from view-only
anatomy; it is a selection aid, not an activation or temperature measurement.

OS reduced-motion disables autoplay, including after reload; explicit playback
remains available. Graphics failure preserves access to records and files.
Canonical live scene evidence is `tests/simulator`, opt-in with a disposable
authenticated account at 1366×768 and 1920×1080; it is distinct from mocked
GPTHub tests and from scientific validation.

## Overview

The authenticated product is a compact dark control surface for an agent-assisted
conversation. It should feel like a dependable workbench: information-dense,
calm and explicit about what is temporary, what is persistent, and what is
still in progress. It is not a neon dashboard or a document-office clone.

## Colors

Runtime ownership is `src/theme/tokens.js`. `ink` supplies structural depth,
`blue.500` is the single primary action color, and success/warning/error remain
semantic-only. Work Hub uses the same tokens through
`features/workspace-room/model/theme.js`; it must not introduce raw colour
literals or a second theme.
The `colors.bg.menu` semantic role is opaque `#0A0C12`, matching the existing
surface/ink.900 role. Shared AppSelect and ChoicePanel consume it so page text
cannot bleed through a choice list; there is no screen-local background patch.
The canonical Tooltip recipe uses that same opaque role through `bg`, never a
translucent `background` shorthand that can override a component's backgroundColor.
Its surface and enter state must not allow underlying option text to show through.

## Typography

Use the product sans stack for navigation, state and actions. File content is
the only code-style surface and uses the documented monospace stack. Russian
labels are concise, sentence-case and name the user-visible consequence.

Inter and JetBrains Mono Latin/Cyrillic variable subsets are self-hosted under
`public/static/fonts/fontsource-5.3.0/`, with original OFL licenses and SHA-256
manifest. HTML подключает CSS синхронно; браузер загружает только наборы символов,
нужные отображаемому тексту, без обязательного preload обоих наборов Inter.
`font-display: optional` prohibits a late swap: a cold,
slow or unavailable font may retain the readable system fallback for that visit.
There is no external font request or JavaScript font-ready rendering gate.
Published font paths are immutable; updates require a new versioned directory.
Chat uses the canonical product stack; Chakra's mono role uses the code stack.

## Layout

Chat, IDE and PDF are peer URL-backed surfaces of the selected thread. IDE retains
`surface=work` for URL compatibility; its repository scope is separate from the
legacy thread Workspace used by PDF and Library copying. Legacy Work components
and their editor/context contracts below remain supporting implementation during
the staged IDE migration, not a second exposed Work destination.
The legacy workbench is three-part on wide screens: source navigation, editor, and context.
On narrow screens those sections become explicit tabs. Persistent Library and
temporary Workspace are always labelled as different sources. Opening Work is
read-only in the legacy Library controller; an explicit create/upload action
provisions its sandbox. IDE entry prepares its separate owned environment
automatically, per the 17.10.2026 product decision. PDF entry now prepares its first
project too, per the 18.10.2026 correction. Preparation uses an authenticated POST
with a server-owned durable first-entry claim, stable project path, and existing
workspace revision/lease guards. Snapshot GETs, Library reading and Chat entry
remain passive. Existing projects are reused. Failed/unknown/truncated discovery
cannot authorize another blank environment; expired identities are not replaced.
Lost replies expose bounded recovery, not automatic POST replay or a second name.
During initial preparation the creation form never flashes beneath the loader.
The PDF toolbar always retains an explicit New document action after preparation.
Its modal owns local profile/language choices and one stable unique destination;
creating a presentation never changes the open document's profile or sources.
Fresh acknowledged scaffolds initialize their semantic draft under the same
project lease and acknowledged revision. Unconfirmed creation never retries an
initial source write. Source-only creation has one warning, not a warning plus
an unconditional success notification. Formatting uses inline select menus
inside its Drawer focus owner, one explicit Apply action and a collapsed
publisher-template disclosure; repeated profile/path cards are omitted.
Lost create replies reconcile only the modal's exact destination and selected
profile/mode/language by passive reads; they never repeat scaffold/content writes.
Creation and Formatting share one thread-bound mutation owner: duplicate clicks
coalesce and late replies cannot select a project or leave a busy state in a
different chat. The modal owns unconfirmed-create errors inline, without a
duplicate toast. A failed format catalog retains an explicit retry in the modal
and Formatting; it never silently disables New document with no recovery.
Catalog recovery selects the normal default only when no format was chosen.
The New document modal uses a flex-column form with a bounded, independently
scrollable body and fixed header/footer. Its select menus portal into the modal's
own DOM/focus boundary outside the body's clipping frame; react-select's measured
available menu height wins over the ordinary280px ceiling. Wheel, keyboard and
pointer selection must work with a long format catalog at a360px viewport height.
New-document/modal and document-drawer close controls reuse the shared 44px
mobile target recipe; desktop chrome remains compact.
A Work upload keeps its source in Library and atomically adds a separate copy
to Workspace without starting the agent. That remains the legacy inline intake
variant. The global Library drawer uploads only to Library; adding a working
copy to the explicitly named Workspace/PDF/IDE destination is a separate action.
Workspace, Library and room status are
independent: one unavailable facet must not replace the other two with a page-
level error. Background refresh keeps the current editor mounted and stable.
Realtime frames are validated before they reach chat or Work state. An invalid
frame becomes a local, generic protocol notice; it must not enter persisted
history, expose transport payloads, or terminate an otherwise healthy socket.

## Elevation & Depth

Static work panels use bordered ink surfaces, not decorative shadows. The
selected file and primary operation use blue soft fill. Warnings are visible in
text and never represented by colour alone.

## Shapes

Controls use the shared compact radius. Panels use the documented panel radius;
the editor body remains square to preserve a clear document boundary.

## Components

Reuse Chakra controls and shared tokens. Every async mutation keeps its button
geometry while busy, gives an explicit recovery path for conflict/unavailable
states, and never exposes container identifiers, URLs, commands, capabilities
or streamed file content.
Панель долговременной памяти использует непрозрачную поверхность и компактное
состояние без фактов, без большого центрированного блока и повторного CTA.
«Добавить факт» раскрывает отдельную подписанную многострочную форму; черновик
сохраняется при отмене и ошибке, после подтверждения форма закрывается с возвратом
фокуса. Поиск отделён от формы. Удаление видно без наведения и имеет цель 44 px;
длинные ключи и значения переносятся, заголовок не пересекается с закрытием.
Секция MemOS действительно скрывает и раскрывает записи даже при одной записи.
Внутри — не более пяти карточек на странице, длинный текст показан превью в четыре
строки. Полный текст раскрывается отдельно в ограниченной прокручиваемой области.
Корректные JSON-фрагменты диалога отображаются репликами; неизвестный формат
остаётся исходным текстом. Это только представление, сохранённая память не меняется.

The editor is writable only while the current path lease is held. Lease
collision or loss switches it to an explicit read-only state while retaining
the local draft. Revision conflicts use an inline recovery panel: copy the
local text or deliberately load the current server version after reviewing the
bounded diff. Neither invalidation nor Chat/Work navigation may erase a dirty
draft.

Work intake is two-stage. `imported` and `kept` mean the durable Library source
and temporary Workspace step were both resolved. `library_saved` is partial
success: the source is safe and visible in Library even though the workspace
copy is deferred. A cancelled or ambiguous request reconciles the snapshot
before a retry, and the retry reuses its opaque upload intent.
The Library-only variant returns `library_uploaded`: complete persistence, not
a failed/deferred Workspace import. Its separate endpoint fails closed on an
older deployment and never falls back to activation, transcription or import.
The selected File pins both intent and intake mode across presentation changes.
Глобальная Библиотека использует серверные страницы по 10 файлов, без накопления
предыдущих страниц. Поиск по имени выполняется по всей библиотеке владельца,
не зависит от открытой страницы и сбрасывает её на первую. Задержка ввода — 300 мс;
IME завершается до запроса, очистка применяется сразу. Устаревшие чтения отменяются.
Поиск остаётся сверху, общий Pager — под прокручиваемым списком; ошибка новой
страницы сохраняет предыдущую и даёт явный повтор чтения. Имена переносятся,
карточки и кнопки действий разделены отступами; на мобильных действия имеют высоту 44 px.

The Work header includes one restrained provenance rail: file source, workspace
state, revision and edit ownership. It is structural information, not
decoration. On medium screens Context becomes an explicit overlay; on mobile
the same three sections remain reachable as tabs. One panel owns each scroll
axis, and sticky actions reserve the device safe area.
The Work tabs root is an explicit flex column. Ready panels fill the shell's
remaining height; editor actions stay at its bottom, rather than ending at the
intrinsic height of a short file. This does not add viewport sizing to other pages.

Navigation that looks like a button remains a semantic link through the shared
`ActionLink`. Product-owned selects use the shared authored listbox so popup
geometry, focus and collision behavior do not change between Chat and admin.
The global theme owns scrollbars and overlay layers; features may request stable
gutter geometry but must not restyle the scrollbar palette locally.
IDE transient diagnostics have one permanent34px toolbar slot, “Состояние IDE”.
Registry/runtime/file/Git/clone recovery notices, their retry actions and Git
progress live in its viewport-bounded popover, never additional workbench rows.
Warnings do not auto-open it or resize/reposition the tree, code, console or agent
panels. Initial fatal loading/errors still occupy the existing scene body.
Log/trace output owns internal bounded scrolling; growing text must never select
a responsive layout, alter split ratios or move the surrounding workbench.

PDF Studio is a dedicated third thread surface (`surface=pdf`), not a hidden
Work context tab. Opening it is passive. At 1100px and above, two initially equal
columns place the editor above a compact document-assistant dock on the left and
a full-height PDF preview on the right. The keyboard-operable column separator
persists only non-sensitive geometry. Below 1100px, Editor/Preview buttons
preserve mounted drafts; the assistant dock stays available under either pane.
Work/PDF use the static workbench substrate, not Chat's decorative ambient mesh
and animated blurred bloom. The Chat-only backdrop unmounts on these peer surfaces;
it never owns the composer, document state or navigation. This avoids rasterizing
a hidden conversation decoration behind document panels, especially at high DPR.
The content editor changes semantic blocks through the trusted renderer and
atomic source publisher; LaTeX remains available for arbitrary source projects.
Its content surface is document-like, not a stack of bordered form cards: multiline
title, typographic headings and auto-growing prose with one subtle focused baseline.
Empty section-body fields are omitted; signatures edit renderer-owned party items.
Block selection stays explicit and source IDs/citations are never inferred.
Structure navigation focuses the existing block without altering content/selection.
Explicitly adding a block scrolls it into the editor's visible region and focuses
its first content field, not the selection checkbox. Background reads never invoke
this one-shot focus intent or move the user's caret.
The edit base pins revision/version/digest until acknowledgement or explicit discard;
background project refresh cannot rebase a dirty draft onto an unseen version.
`Button` owns `workbenchPrimary`/`workbenchSecondary`: token blue.500 or neutral
ink, control radius, no marketing sheen, gradient, pill or hover translation. PDF
actions consume these variants and the shared `document` size: 34px desktop,
30px below 768px, with 12.5px/12px utility labels and 14px icons. This mobile
density follows explicit feedback to reduce oversized buttons, not page scaling.
`theme/tokens.js:documentControls` owns these values; Chakra Button and AppSelect
adapt the same token. PDF project/block selectors share that control height.
Editable mobile text remains 16px; composer touch targets remain 44px and sidebar
rows remain 34px. Pane choices are content-width, not full-width bars. Controls
remain at least 24px with visible focus and gaps. Existing generic
button sizes and landing/admin recipes are not restyled globally. Project selection
is capped at 320px on desktop; block type selection at 200px. Toolbars wrap their
action groups when space is tight, never stretch a lone selector across the page.
The project selector has no duplicate subtitle: profile/language/preparation are
available in Formatting. Its control aligns with Materials and Formatting.
Narrow editor containers use labelled structure/save icons; the save control owns
its state name without a duplicate status line. This follows available panel width,
not only viewport width.
Unmanaged source edits or stale versions block semantic publication, never
trigger refetch-and-overwrite. Compilation and delivery never replace the editor.
The assistant reuses one persistent composer owner across Chat/PDF, including
voice, attachments, mode/persona/model and context. PDF never displays the Chat
message viewport or reserves empty conversation space. While sending/running or
awaiting a live anchored offer, the composer is hidden, not unmounted, and the
existing Chat trace appears in its place with explicit Stop. It
uses the shared workbench trace layout: a closed bounded card, fixed header/activity,
and one keyboard-accessible internal scroller for steps and any pending offer. The
outer dock/card do not scroll away their bottom border or header as steps arrive.
Workbench disclosure has no height animation; ordinary Chat keeps its natural-height
trace. Completion restores input. Explicitly opening completed details temporarily
reuses the input area without unmounting the composer; closing details returns the
same draft and focus. In an extremely short idle dock, summary/input may scroll
inside their existing surface instead of shrinking the summary to an overlapping row.
Sending from PDF Studio
grants tool consent for that owned, server-validated project run; a persistent dock
notice explains automatic tools, credit use and unchanged account limits before send.
Backend revalidates project/revision before reserving credits; consent never bypasses
balance, provider/admin policy, compiler restrictions or review/apply of edits.
Ordinary Chat keeps its confirmation gate. Historical anchored offers remain explicit:
opening/reloading a page neither accepts them nor launches a continuation.
Completion, cancellation, failure or offer expiry restores the composer. A compact
outcome and optional completed trace remain available; full replies stay in Chat.
No layout transition admits/retries a job or accepts an offer. The dock has no
permanent assistant/scope header; a selected-block count with
explicit clear action and proposal review appear only when applicable. Narrow composer
containers use the existing compact icon presentation regardless of viewport.
The idle dock contains input/settings and the concise cost notice, not Chat persona onboarding or an
empty conversation canvas. Persona selection remains in the shared composer. Project
creation lives only in the empty editor. Formatting becomes available after
project creation and contains profile/language/preparation settings and publisher
formats, not a second creation form, authoring outline, build controls or preview.
The single account Library opens from the sidebar beside Memory, Graph and Settings,
without changing Chat/Work/PDF surface. Its modal drawer reuses the persistent
Work Hub's snapshot, upload intent, copy owner and cursor pagination; no second
data/controller owner is mounted. Work and PDF do not embed Library tabs or lists.
Materials provides only project sources and shared thread files. The shared
WorkspaceTree renders sorted, collapsible folders before files, with short names
and indentation; project Materials omits the repeated project-root prefix.
Folders are collapsed initially, with only the selected file's ancestors opened.
Explicit collapse survives background snapshot updates. Folder disclosure is
passive and remains available while file selection is busy/blocked. Native buttons
and nested lists own Tab/Enter/Space, not a partial ARIA tree keyboard model.
Full paths remain in accessible names/tooltips and a wrapping focus/selection
readout; filenames wrap rather than hide their extension. Materials owns one
vertical scroller, not a competing scroll frame per group. The empty documents
container and other PDF projects do not appear as shared thread materials.
Primary project sources remain visible; build artifacts and service/configuration
files live in named, counted Accordion disclosures, with an empty shared-files
section reduced to one disabled row. Disclosure state follows stable section keys,
not list indices, and selected ancillary files reveal their section. Reduce-motion
disclosures avoid delaying repeated navigation. Detailed intake/editability guidance
lives behind an explicit information control, not two permanent paragraphs.
Replacing a
panel does not replace the upload session. Material intake is explicit and never
starts the assistant or silently inserts an illustration/citation. Partial intake
remains labelled as Library-only. Dirty drafts and active processing block material
mutations, not Library reading/download. Source selection changes the editor only
after the shared dirty-navigation guard and a successful read; LaTeX retains the
chosen source instead of reopening main.tex. Binary materials are listed but never
interpreted as editable text. Other projects stay behind the project selector.
The Library explicitly selects a copy destination: the current chat's Workspace,
loaded PDF project or current IDE repository. Outside IDE it defaults to Workspace;
inside IDE it defaults to the named current repo, or an unresolved IDE destination
while preparation is pending, never a legacy creation action. A missing/retired project
requires a new destination choice, never a silent retarget. PNG/JPEG/PDF use
“В PDF-проект” only for an explicitly selected project; incompatible files remain
downloadable and explain the restriction. The existing copy owner sends only the owned
file ID, selected project, expected revision and project lease. The backend derives
the immutable Library-ID-based name under that project's `figures/`; no client URL
or arbitrary destination is accepted. A target-file receipt is required, not just
aggregate import counts. Existing files win, so deliberate retries do not overwrite
or start generation. Ordinary Work copying retains its original destination.
The existing importer rejects symlink ancestors during staging/publication and
does not follow an aliased staging parent during cleanup. A symlink or directory
at the requested file destination is not a confirmed existing asset. These checks
run inside the existing serialized Workspace import operation; no new writer or
compiler policy bypass is introduced.
IDE copying uses a named inline destination form within the same drawer, not a
second Library or nested modal. The relative path is editable before submit;
the existing parent must exist. Opaque files up to 20 MiB are copied create-only,
without unpacking, executable permission, Git commit or LLM work. The exact
thread/repository/generation and path lease are pinned, with backend/runtime
admission and size/SHA-256 receipt checks. A definite name conflict permits a new
path; an unknown write acknowledgement freezes the submitted path and offers
inspection, never an automatic POST retry. Late acquisitions release only their
original lease. Completion refreshes clean IDE views, never another repo or draft.
Image/slide blocks select existing project-relative figure paths with AppSelect;
known Library names are displayed when available. Only exact project descendants
compatible with the trusted renderer are offered. Missing references remain visible
and unchanged, never silently cleared by a partial snapshot. Choosing a file and
caption only edits the local draft; explicit Save still owns source publication.
Project imports re-read the authoring base after their acknowledged revision change.
Citation blocks choose registered sources by title/year through AppSelect; author,
DOI and URL are shown only when supplied by the project's bibliography. Missing
metadata is not inferred. Unknown existing references remain visible and unchanged.
Adding a citation requires an explicit registered choice and only changes the local
draft; Save owns publication and preserves the exact bibliography bytes. The extra
new-citation picker scrolls with document content, rather than consuming another
fixed toolbar row on short mobile viewports.
The protected source-inventory read is lazy, project/revision/source-digest scoped,
non-metered and non-mutating. Late/retired reads cannot change another project.
Read failure has an inline retry that revalidates project facts without a write;
dirty content and its original edit base remain intact. Unknown or duplicate source
IDs cannot be selected or accepted by the trusted renderer. Its shared bounded
BibTeX reader ignores comments/nested pseudo-entries, never evaluates TeX, projects
only supplied plain metadata, omits rather than truncates long values, and does not
expose unsafe or credential-bearing URLs. It is not an arbitrary BibTeX interpreter.
Truncated or oversized bibliography reads are unavailable, never a partial list
presented as complete. Source records stay in protected REST, not WS/snapshot,
browser persistence, telemetry or model prompts.
Library copy actions preserve focused button DOM while busy, expose aria-busy and
aria-disabled, and reject repeat activation. Native disabling must not strand focus
on the page body and break the enclosing drawer's Escape behavior. Shared Library
download/copy actions use the shared 34px Workbench size on desktop and mobile.
Preview checks use a compact disclosure and three factual technical/visual/Library
statuses, not a permanently expanded pipeline table. Details retain diagnostics,
publication and recovery. Build admission, queue and actual compilation/audit stages
are visible outside that disclosure, even from the mobile editor. Open/Refresh PDF
lives alongside Build Draft and Check Final in the main toolbar, never on a separate
action row or inside Checks. Mobile uses a labelled 30px preview icon beside those
actions. Opening it selects Preview without a new build; read failures remain visible
with the same retry action.
Build progress has one owner: in the desktop preview header, or beside the mobile
Editor/Preview choices while either pane is active. There is no extra full-width
build-status strip and no second copy of the completed status. Preview errors stay
inline in that same owner. Only this compact status animates build progress. Toolbar build/final/cancel
buttons retain their labels and geometry, expose busy/disabled semantics and never
add another build spinner.
An opened preview changes that action to Refresh PDF, still a read of the current
build artifact, never compilation or publication.
No spinner implies completed delivery, and a failed compiler artifact is not a ready PDF.
Assistant completion and Workspace invalidation re-read project facts and changed
semantic versions; they do not overwrite a dirty edit base or cancel compilation.
Build tracking owns a separate abortable lifetime from project/semantic reads.
Lease acquire/release invalidations cannot retire its status polling, replace an
in-flight status with an older project snapshot or leave admission busy forever.
Show the accepted build before best-effort lease release finishes. Changing
thread/project retires that lifetime and ignores late admission/status responses.
Loading/unavailable structure is distinguished from a genuine source-only project;
PDF compilation never promises reverse conversion from arbitrary LaTeX.
Starting new semantic content in a source-only project explicitly warns that its
LaTeX will be replaced. Cancel is initially focused; no lease or write precedes consent.
This short safety dialog has no entrance/exit animation; its close and focus return
are immediate, including reduced-motion and slow-device use.
The sidebar footer has no top divider and never measures or constrains the composer.
Input/process shelves size naturally to their own content, voice and attachments,
without sidebar-driven minimum height or synchronization. Sidebar controls remain
fixed 34px rows with stable typography and gaps, independently bottom-anchored.
Private document context is server-validated and restored from confirmation
anchors. Only opaque project/proposal IDs enter message metadata. Project
content and proposed block text are fetched through protected REST, never WS.
Model proposals do not write source: explicit review/apply checks source revision,
draft version and digest. A dirty local editor blocks proposal application.
Review presents only changed blocks as Before/Proposed columns, stacking on narrow
screens. Heading level, list order, table cells, asset path and citation ID are
reviewable, not silently reduced to paragraph text. Старый формат предложения v1
сохраняет порядок и число блоков: вставка и перестановка в нём недоступны.
Согласованный сервером вариант v2 явно показывает вставку, удаление и изменение
относительного порядка. Новые блоки имеют временные new_* ID, пока доверенный
renderer не назначит окончательные. Тип существующего ID неизменен. Вставка и
удаление показывают отсутствие второй стороны одной короткой строкой и используют
полную ширину для содержания, без пустой колонки. Перемещение называет прежнюю и
новую позиции и показывает содержание один раз. Вставка/удаление не создают ложных
перемещений неизменённых соседей. Неизвестные версии, повтор ID, неожиданные поля и
смена типа существующего блока запрещены. Оба формата остаются предложениями:
прежние Apply, version/digest/CAS и запрет при грязном редакторе сохраняются.
Chakra owns modal focus trapping, Escape and restoration. A pending read is
cancellable; the comparison region is keyboard-scrollable and the compact footer
stays reachable in short viewports. Close is initially focused; applying is explicit.
An acknowledged save is distinct from refreshing the editor. Refresh failure keeps
the saved outcome and offers read-only recovery, never another implicit write.
Ambiguous saves require a fresh review; revision conflicts cannot auto-overwrite.
The semantic PDF editor has one save control/state owner: Save when dirty, Saving
while awaiting acknowledgement, Saved after confirmation. It does not place a
duplicate saved label beside a disabled Save action; narrow layouts retain the
same accessible state name when the visible label yields to its icon.
Concurrent authoring reads for the exact thread/project/generation share their
in-flight request, so background and post-save refresh cannot abort each other.
Changing target or generation retires the previous read; it is not a freshness cache.
Presentation is a Beamer project profile, not a selectable chat mode. Historical
route/billing names remain readable; changing layout never starts paid work.
Project-local vendor kits are selected from Library ZIP files. The UI names
their isolated, untrusted scope and never exposes their download URL, digest,
compiler path or container boundary.
Installed vendor v2 formats are activated only by cloning to an explicitly
named new project. The original project remains selectable. The context panel
shows the trusted base profile separately from the project-local format and
reports whether semantic content was copied or needs migration.

The structured authoring panel is a projection of workspace-owned state: safe
brief fields, outline, evidence coverage and unresolved requirements. It does
not replace the text editor and does not store draft content in browser
persistence. Authoring, compilation, deterministic audit, visual audit and
Library delivery are displayed as independent stages.

## Do's and Don'ts

Mobile defect correction (21.10.2026): `shared/hooks/useVisualViewportCss` owns
visual-viewport height/offset CSS variables; Chakra Modal/Drawer geometry adapts
them through `theme/overlays`, without another focus manager. The viewport meta
uses `viewport-fit=cover`, never scale restrictions. `--app-safe-bottom` maps to
the native bottom inset; composer, console, Files/Graphify and overlay actions
reserve it once at their bottom edge. Clone uses one scrollable body and fixed
header/actions. Library names wrap, rows do not flex-shrink, and action groups
have an explicit8px gap with wrapping. Thread peers share document-control
geometry on desktop; mobile navigation lives in the account menu and availability
joins the composer settings row (24.10.2026 product decision).
Persona onboarding is immediately visible, with no scroll-reveal dependency.
Mobile composer reserves44px send/voice targets but removes the idle send fill
and reduces the text gutters; settings sit4px below the input. Empty states give
navigation/focus actions only, never fabricated Graphify availability or implicit
paid work. These are corrections to the existing workbench, not a new visual identity.
Browser keyboard/safe-area injection is regression evidence, not native iOS proof.

- Do retain the current file text until the user chooses discard or reload.
- Do fetch file contents and diffs through REST after a bounded invalidation.
- Do keep Library usable while Workspace or room coordination is unavailable.
- Do let a read-only editor explicitly reacquire its lease without replacing
  the current draft.
- Do not create a legacy Library/PDF sandbox implicitly, run a shell command, or
  invoke the agent from Work. IDE entry prepares only its owned repository runtime.
- Do keep legacy workspace creation behind labelled actions. IDE first entry uses
  the server-owned prepare contract; refresh/Library shortcuts never provision it.
- Do not visually imply that the temporary workspace is permanent account
  storage.
- Do keep blocking conflict and lease recovery inline; transient toasts only
  acknowledge completed or deferred operations and never duplicate one action.

## UX contract

This section is the canonical behavior contract, consolidated from the former
`UX-CONTRACT.md` by explicit product decision on 09.10.2026. The standalone file
is not required or restored. `premium-ui.json` points its `canonicalMap` here;
the root UI gate and premium audit must validate the same map. This migration
changes contract ownership, not runtime behavior, policy or acceptance thresholds.

### Product context and business sources

- Audience: authenticated users working with chats, durable account files and
  temporary thread sandboxes. Primary jobs are asking the agent, using owned
  attachments and editing/reviewing Workspace without losing local work.
- Locale: Russian (`ru-RU`); bounded service codes use closed Russian dictionaries,
  never raw codes. Accessibility target: WCAG 2.2 AA and 200% zoom.
- Chat and Work HTTP/WS contracts own authorization and lifecycle; this document
  owns their observable UI consequences, not storage or billing rules.
- Sources: `../docs/PDF_DOCUMENT_PLATFORM.md`, `../docs/PROJECT_TODO.md`,
  `../docs/VIDEO_SUMMARY_ACCEPTANCE.md`; runtime boundaries are backend Chat/Work
  routers and the frontend shared API/WS adapters. Static tests are evidence,
  not substitutes for authenticated browser acceptance.
- Runtime tokens remain owned by `src/theme/tokens.js`, consumed by Chakra and
  feature theme adapters. No palette, font, spacing or breakpoint changes occur
  as part of contract consolidation.

### Canonical UI map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | `shared/controls/AppSelect` | `react-select` keyboard model | single, clearable, portalled | keyboard and popup E2E |
| Form | shared form-control contract | Chakra FormControl and shared inputs | labelled field, help, inline error | unit and axe E2E |
| Form textarea | `shared/controls/AppTextarea` | Chakra textarea | editable or read-only; resize disabled | unit and static audit |
| Navigation CTA | `shared/controls/ActionLink` | router/link semantics | router or external link | semantic-role unit test |
| Scrollbar | global Chakra theme | `theme/tokens.js` | geometry-only local exception | computed-style E2E |
| Toast | `shared/hooks/useAppToast` | Chakra toast portal | success, info, warning, error | live-region and dedup unit tests |
| UI loading | `shared/controls/AppLoading` | Chakra Spinner and polite status | route or peer-surface label; parent owns geometry | suspended-surface unit and browser checks |
| Dialog | Chakra dialog/alert-dialog | Chakra focus manager | destructive or dirty-navigation | focus/recovery E2E |
| Library dataset navigation | useLibraryBrowser + общий Pager | Account work-library, limit/offset/q | Серверные страницы по 10 файлов; поиск по всей библиотеке | Work Hub unit + Library E2E |
| CRUD | Work Hub / repository-owned IDE feature services | Work snapshot v2; IDE generation and path leases | WorkspaceEditor workspace/ide; create, edit, move, conflict recovery | mocked and live Work/IDE E2E |
| Repository reads | `useIdeRepositories` / `useIdeRepositoryReads` | protected IDE REST and exact generation | list/load-more, runtime, tree, file | IDE hook/component and browser tests |
| File hierarchy | `WorkspaceTree` | existing snapshot or validated IDE projection | project-relative base, bounded incomplete folders | native keyboard and browser tests |

### Composer and choice panels

- На стартовом экране до768px личности показаны сеткой3колонки с иконками
  в целях56px и промежутками12px, без постоянных подписей/описаний карточек.
  Доступные названия и подсказки сохраняются; отметки1/2 показывают порядок выбора.
  Десктоп сохраняет именованные карточки. Вводный абзац «Выберите специализацию»
  отсутствует на всех размерах. Ограничение двух личностей не меняется.

- Панель этапов отделяется от запроса и следующей реплики отступом16px,
  даже если обе реплики принадлежат пользователю. Ошибка разрывает визуальную
  серию, но не меняет историю или состояние задания. Заголовок и пояснение ошибки
  переносятся без обрезки; все маркеры используют общую ось. Счётчик этапов
  использует русские формы «шаг / шага / шагов».

- `ChatMessagesArea` owns the mobile reading gutter for messages, traces and
  overlaid status feedback: at least the existing 16px spacing token on each
  side, expanded by the corresponding safe-area inset when needed. Numeric
  spacing `3` is only 6px in this theme and is not a reading gutter. Desktop
  spacing and the bounded content column are preserved; wide code/tables scroll
  inside the message, never by removing page padding or widening the viewport.

- Global `theme/mobileInteraction` owns mobile input/gesture behavior, including
  nested scrollers and portalled controls. Text-editing fields use the existing
  16px type token on narrow/coarse-pointer screens, winning compact SDK styles;
  checkbox/radio/file/range/button sizing is not changed by that rule.
  Coarse-pointer surfaces request `pan-x pan-y` to suppress accidental pinch while
  retaining panning. Desktop keyboard/browser-menu zoom is not intercepted, and
  viewport scale limits/user-scalable restrictions are not added.
  Native iPhone/Android pinch, keyboard autofocus and one-finger scroll acceptance
  remain open in `../docs/PROJECT_TODO.md` P1-UI-TOUCH20261015. Computed styles,
  CDP page-scale admission and emulated focus do not prove those native behaviors
  or waive the 200%/system-accessibility acceptance requirement.

- Below 768px composer mode/persona/model triggers are 30px icon-only circles
  centered in transparent, non-overlapping 44px touch targets,
  with no chevron or truncated label. Mode uses its current mode icon, persona
  uses the user icon and model uses the CPU icon. Accessible names and titles
  retain the category and full selection; sheets expose the actual selection.
  This is an explicit composer variant: profile/admin/Work controls keep labels.
  Context gauge has a
  fixed 44px touch / 34px desktop target. The mobile ring and choice circles all
  have the same 30px visible diameter, never a ring inside a second outline. Its slot never
  grows with model controls. All five controls share one centered mobile row in
  a baseline-free flex chain; the context slot and button do not introduce an
  inline line-box gap. Model trigger and ring share one vertical center on desktop
  as well as mobile, without compensating negative margins or translations.
  DOM/tab order: mode, persona, model, context, AI availability, with equal
  6px gaps between 44px hit targets, without stretched pills or wrapping.
  Settings remain separate from the input.
  Choice glyphs use the shared 24-viewBox outline set at 16px, centered in the
  mobile target. Context uses the same neutral surface, border and blue focus
  treatment; its readable numeric percentage stays within the ring (the percent
  unit is included in its accessible name/title). Zero usage has no amber dot.
  Activation dismisses the context hint and invalidates a pending enter-delay;
  completion never reopens it over a sidebar. A fresh hover/keyboard focus can
  show it again, while compaction keeps it disabled.
  Hover/press changes color, never the target's size or alignment. Selected and
  open choices use the existing restrained blue treatment rather than new badges.
  Selected picker text/checks and attachment navigation use the existing
  `blue.100` foreground; the palette has no `blue.200` entry. Literal numeric
  palette references in composer/shared picker owners are unit-checked against
  the runtime registry so missing tokens cannot silently inherit white text.
- Composer text and its settings remain separate surfaces. Desktop uses a left
  mode/persona group and a right model/context group; mobile uses the compact
  icon row rather than a second settings row. Choice triggers share 34px desktop / 44px touch geometry,
  the existing compact typography and token-owned neutral/selected states.
- `shared/controls/ChoicePanel` owns responsive overlays: a portalled desktop
  Popover (320px mode/persona, 384px model, viewport bounded) or a modal bottom
  Drawer. Rich panels intentionally exceed their compact trigger width; ordinary
  form `AppSelect` retains its width-matching single-select contract.
  Mode/persona align to their trigger's left edge; model aligns right. Collision
  handling remains library-owned. Panels clear the input rather than masking it.
- Compact persona/model triggers use240px/256px desktop panels. Named
  44px rows retain identity and selection; descriptions are opt-in through the
  header info action, expanding to320px. Model rows show the name and inline
  metadata icons, never a second cost/capability text line. Known cost tiers keep
  semantic color and distinct arrows; modality/tool/context icons have accessible
  labels. One shared row hint explains supplied metadata on hover/keyboard focus;
  Info exposes descriptions on touch. Unknown metadata produces no invented icon.
  Long model names remain in accessible option names, row hints and a title.
  The mobile `model-palette` sheet is centered at280px for the compact composer
  (320px with Info descriptions or the labelled profile picker), with the shared
  24px viewport bound. It does not stretch sparse names and metadata across the
  screen. Single selection closes it immediately; the duplicate full-width Close
  shelf is omitted, retaining the44px header Close, backdrop and Escape. The last
  body owns the bottom safe area. Search, provider groups, bounded list scrolling
  and explicit batch expansion remain; desktop widths are unchanged.
  Persona selection count and an enabled-only clear action share one row;
  neither picker repeats its selected value beneath the title.
  Mobile personas use the shared `composer-persona-icons` ordered-multi listbox:
  three columns of44px icon targets with8px gaps, without checkbox squares or
  permanent row labels. `features/chat/constants/personaIcons` maps the existing
  product-owned outline glyphs for both onboarding and the picker; unknown admin
  IDs get the neutral user glyph. Accessible option names remain complete. Selected
  icons show their1/2 order; the first personality remains the leading one. Header
  Info reveals named descriptions on touch without changing selection; Done and
  explicit clearing remain. Desktop keeps its named rows. The mobile
  `persona-palette` sheet is280px wide (320px with descriptions), viewport bounded
  like the mode palette, while retaining its multi-select action shelf.
  `ChoiceHints` owns one transient hint per panel. Hover/focus changes its owner;
  blur, pointer exit, click and Escape dismiss it. No independent checkbox hints
  can remain stacked. Wheel, captured scroll and resize dismiss an active hint;
  a scrolled-away row cannot pin its tooltip to another part of the interface.
  Fresh hover/keyboard focus can reveal it again. The shared `layers.tooltip` token is 760, above drawer
  (720) and below command/toast (820/920), including on mobile sheets.
- Compact mode triggers use a matching compact mode picker (18.10.2026 user
  decision): an88px vertical desktop icon column or content-height mobile sheet.
  Desktop strategies stack below the modes; its title is visually hidden but
  still names the dialog. Header Info/Close remain visible. Explicit descriptions
  expand it to280px. Mobile uses the shared `ChoicePanel` mode-palette variant:
  a centered280px content-height sheet (320px with descriptions, bounded by24px
  viewport gutters). It has no redundant Close action shelf: the named44px header
  Close control, backdrop dismissal and Escape remain available. The last body
  owns the bottom safe area. Mode targets stay44px wide rather than stretching
  into empty columns; strategy targets form one centered group with8px gaps.
  AppSelect's
  named `composer-icons` presentation keeps react-select's listbox/keyboard owner,
  44px icon targets, selected check and visible keyboard-focused outline. Pointer
  hover is transient; react-select's retained active option must not leave a second
  blue ring or hover fill after pointer exit, selection or reopening. Only the focused
  or hovered mode has a tooltip explanation; no permanent help region, secondary
  heading or blank description canvas occupies the picker. Auto strategies share
  one compact group and expose explanations on focus/hover. In icon-only mode,
  each strategy is a44px icon toggle (`aria-pressed`); no redundant checkbox
  square. Selected state uses the shared blue surface and inset outline.
  The expanded descriptive presentation retains labelled checkboxes.
  A labelled description toggle reveals the detailed list without selecting or
  sending anything, including on touch. Wide labelled mode controls retain the
  rich list. Compactness follows the existing composer-container owner, not only
  the viewport. Persona/model identities and searchable model names are not
  replaced with indistinguishable generic icons by this mode-specific change.
  The description toggle lives in the existing header next to Close, not in a
  second full-width toolbar. The compact desktop picker stays below450px tall
  with the current five modes and two Auto strategy controls; touch explanations
  remain explicitly expandable rather than depending on hover.
  Desktop popup roots mount only while open and appear immediately, without an
  exit/scale visibility phase. This prevents touch WebKit from retaining hidden
  ancestor styles on the listbox input and option glyphs; rapid Escape/reopen
  must still expose all options and restore the trigger. Mobile keeps the
  library-owned modal Drawer. Passive IDE runtime help initially focuses its
  named Close control synchronously so an immediate Escape after touch opening
  reaches the surface, not the composer. Its focus restoration remains native.
  Геометрия `ChoicePanel` вычисляется в layout commit до первого paint, включая
  первое холодное открытие; последующие viewport/resize-события сохраняют общего
  владельца наблюдения. Установившаяся геометрия не заменяет проверку первых кадров.
  Панели mode/persona/model также не используют slide/fade при открытии/закрытии
  на мобильных: выбор немедленный, без выходящего focus-trap на пути следующего
  действия. Chakra сохраняет владение modal focus, Escape и возвратом к trigger.
  Остальные Drawer-процессы сохраняют свои правила анимации.
- `AppSelect` owns rich/grouped options and ordered multi-selection through
  react-select. Panels use its composer presentation, localized announcements
  and library keyboard semantics, never a custom ARIA menu/focus-repair loop.
  Подсказка описывает сам `role=option`: ARIA, ref и обработчики Tooltip объединяются
  с library-owned option, без generic `aria-describedby`-обёртки внутри listbox.
  Non-searchable mode/persona panels visually hide only the redundant input
  chrome; the library's focusable combobox remains available to keyboard and
  assistive technology. Searchable model panels retain their visible search.
  Mobile sheets use opaque `ink.900` and the shared drawer scrim, with a bordered
  action shelf and the shared secondary button recipe. Persona indicators use
  `borderRadius.control` (6px), not the 10px legacy compact-panel radius.
- Only one composer picker opens at a time. Mode/model commit and close; persona
  choices and Auto strategy controls commit immediately and remain open until
  closed. Closing is not a rollback. At two personas, unselected choices are
  disabled; the selected pair retains its original leading-persona order.
- Mobile sheets retain their title/close/action regions and safe area; their
  height follows 80% of the visual viewport, including keyboard changes. Search
  and footer remain above its bottom edge: the sheet tracks both visual viewport
  resize and scroll/offset changes, not only its height. Library motion is retained.
  Search and selected values survive responsive presentation changes. Focus returns to
  the trigger; Escape closes a picker before it can stop a streaming response.
- Layout-changing ResizeObserver consumers use `shared/utils/observeResizeFrame`:
  coalesce measurements into the next animation frame and cancel on close/unmount.
  Auto-growing `AppTextarea` responds to outer-width changes, not to its own height
  or inner scrollbar; observer callbacks never synchronously refit the observed node.
- Moving the persistent composer between Chat/IDE/PDF synchronizes destination
  content width in the host's layout commit, before paint, through its existing
  imperative handle. Hidden/zero-width hosts never replace the last valid size;
  deferred observer work reads current geometry, not an old host's entry.
  Button theme transitions cover visual feedback only (colour and shadow),
  never transform/width/height/padding/font size. The same rule applies
  to send/stop buttons; route changes must not animate control geometry.
  Прозрачность disabled/enabled меняется сразу: уже доступная кнопка должна иметь
  читаемый контраст с первого enabled commit, не после завершения fade.
- Shared glass-card hover recipes (`theme/glass.js`) also keep their hit targets
  stationary, including persona choices, billing cards and profile rows. Hover
  changes the border, surface, shadow and pointer-inert decoration, never the
  target's position or scale: a pointer at its edge must not toggle hover in a loop.
- Базовая высота общего поля ввода рассчитана на одну строку (`rows=1`): фокус,
  первый символ и доступность отправки не меняют геометрию. Высота растёт только
  при переносе текста, ограничена существующим максимумом и уменьшается обратно
  после удаления лишних строк; длинный текст прокручивается внутри поля.
- Composer Enter is IME-safe; Shift+Enter keeps its multiline behavior. Switching
  choices or Chat/Work never clears text, attachments or the voice preview.
  Result delivery never clears a newer draft, including a late result after Stop;
  only explicit submission consumes the submitted composer text.
  Mobile uses the short placeholder “Сообщение…” so the empty input fits between
  attachment and voice/send actions at 320px without a clipped second line.
  Microphone, recording/elapsed stop control and transcription status share a
  fixed 44px slot; voice state changes never widen the action shelf over text.
  `ComposerActionControl` owns attachment, microphone and send/Stop presentation,
  using the same44px hit target with a smaller32px inner surface and16px glyph
  from `theme/tokens.composerActionControl`. Voice recording, permission waiting,
  transcription and attachment upload retain this geometry; their fill, border,
  spinner and focus outline belong to the inner surface, never the whole target.
  The outer target stays transparent; no external glow enlarges the blue surface.
  Hover/press/focus style the inner surface without moving or resizing either slot.
  The timer stays visible without live-announcing every second. Transcription
  exposes a localized status, not an actionable or unlabelled loading control.
  Voice preview edit/discard actions also retain 44px targets and never dispatch
  a message: appending recognized text and discarding it remain explicit actions.
  Microphone permission, recording and transcription have one private thread-bound
  owner. Duplicate admission/Stop cannot create another capture/upload. Changing
  thread or unmount retires callbacks before stopping tracks, aborts observation
  and ignores late permission/transcript/error; cleanup never starts STT. Empty
  captures do not upload. This does not imply cancellation/refund of a server
  operation already accepted. Chat/Work switching retains the same owner.
- Model search has an explicit clear action. Catalog rows are grouped by provider,
  initially bounded to 60, with explicit expansion. Context/cost/capability labels
  come only from supplied metadata; estimates remain labelled. Manual selection
  never silently becomes Auto on refresh. A confirmed unavailable choice blocks
  sending with an inline correction; failed discovery preserves selection and
  cached rows, with an explicit generation-guarded retry.
  Локальная LFM2.5 располагается перед Авто и облачными группами, но только когда
  она есть в полученном каталоге. Метка «Бесплатно» основана на серверном `is_free`,
  а не на имени/нулевом cost tier; она относится к токенам, не к платным инструментам.
  Её непринятый option использует общую золотую грань как приглашение внутри панели.
  Выбор и активный option гасят приглашение без смены геометрии. Это именованное
  исключение для открытого picker: фоновые подсказки за модалкой остаются выключены.
  Reduced motion и forced colors используют общие правила. Провайдер отображается
  той же панелью доступности, без самостоятельного платного health-запроса.
- Research model settings use the same catalog's positive `tools` metadata, never
  a frontend name heuristic. Backend applies the runtime tool-support policy,
  including its evidenced GigaChat profiles. Rich-catalog loading/failure is
  separate from a usable legacy chat-model list: settings expose retry, retain
  saved selection and last-known metadata for still-listed models, and never
  disguise failed discovery as an authoritative empty research list. Selection
  is independent of the chat model, persists locally and travels as `ldr_model`
  in the WebSocket research request.
  Settings keep select portals inside Chakra's dialog focus owner; the drawer's
  identity slide transform is removed at rest so fixed menus retain viewport
  coordinates on desktop as well as mobile. Actual enter/exit transforms remain
  library-owned; no offset arithmetic or replacement focus manager is added.
- Mode copy describes actual behavior: presentations are PDF, legacy route IDs
  remain compatible, beta labels remain honest. Required hints are visible text,
  not hover-only tooltips. Picker changes introduce no paid model calls.

Verification: `tests/unit/components/ComposerChoices.test.jsx`, capability/cache
regressions and `tests/e2e/composer.spec.js`; shared form selectors, Work and admin
remain part of the regression matrix. Screenshots and browser traces are ignored.

### Chat/Work/PDF navigation and responsive state

- Рабочая оболочка Chat/IDE/PDF ограничена общим visual viewport в `ProtectedLayout`:
  высота и смещение приходят из `useVisualViewportCss`. Брендовая шапка не сжимается,
  main занимает остаток, без сохраняющегося transform от анимации страницы.
  Второй документный скролл не прячет заголовок треда под шапку. Остальные страницы
  аккаунта сохраняют естественную высоту и обычную прокрутку.
- На коротком мобильном экране PDF-превью само ограничивает переполнение: его
  заголовок, содержимое и проверки не рисуются поверх dock. В обычном вводе
  остаётся прокручиваемая область документа, а настройки ввода достижимы прокруткой
  внутри dock. Вопрос/стоимость/трейс сохраняют прежний полный бюджет высоты,
  не уступая место превью за счёт безопасности Stop и подтверждений.
  Состояние расширенного dock передаёт `PersistentChatSurface` через общий shell;
  геометрия не выводится из DOM/тестовых селекторов дочернего портала.
  Home/End сфокусированной области этапов прокручивают именно её, не страницу;
  клавиши интерактивных потомков не перехватываются.

- Подсказка следующего действия имеет единого владельца: `motion.css` и атрибут
  `data-action-hint="idle|hover"`. Используется существующая золотая грань, без
  новых цветов, размеров, заливки или движения самого элемента. Это приглашение,
  не обозначение выбора или выполнения. Фокус внутри, нажатие, открытое/выбранное,
  отключённое или занятое состояние немедленно убирают грань. Открытая модалка
  гасит фоновые подсказки; `ChatPageSurfaceShell` приостанавливает их на время
  подготовки, отправки, очереди, исполнения, загрузки и голосового ввода.
- `ComposerShell` приглашает к доступному вводу только без фокуса. Каретка,
  открытый выбор настроек, запись/распознавание голоса и сжатие контекста гасят
  свечение. Во время набора не светятся и соседние приглашения. Завершение,
  отмена или отказ возвращают подсказку лишь для доступного неактивного ввода.
  Фокус обозначается статичной рамкой без внешнего свечения. Таймеров и новых
  владельцев состояния задачи нет; общий композер действует одинаково в Chat/IDE/PDF.
- `ChatHeaderBar` обозначает текущий раздел статичной рамкой и `aria-pressed`,
  без постоянной анимации и сплошной заливки. Другой раздел приглашает при
  наведении; переход немедленно убирает приглашение. Невыбранные доступные
  личности используют такой же вариант, выбранные не светятся.
- Контекстные приглашения: открыть файлы из пустого готового IDE-редактора;
  открыть только что собранный PDF с совпадающим digest источников и без грязных
  правок; перейти к сохранённому PDF из последнего завершённого ответа. Открытое
  превью, старый артефакт и недоступные действия не рекомендуются. Публикация,
  трата денег и разрушительные действия не получают автоматических подсказок.
- Reduced motion оставляет неподвижную грань только там, где ещё нужна подсказка;
  forced colors убирает декоративный слой и сохраняет системную рамку выбора.
  Клавиатурный фокус независим от подсказки. Hover/focus/выбор не меняют геометрию.
- `?surface=chat|work|pdf` is the only peer navigation; the thread stays in the path,
  reload restores the surface and no sidebar duplicate is introduced.
- The visible `work` peer is named IDE in the thread header, account menu and
  document title. No repository is migrated or provisioned by that rename.
- Attachment shortcuts open the existing global Library overlay without changing
  surface or copying files. Saved-document recovery opens PDF through the same
  dirty-navigation owner, never the IDE repository selector. Their labels name
  those actual destinations; the old ambiguous “Open Work” callback is retired.
- The account menu exposes Chat, Work and PDF as semantic router links. Inside
  Chat they preserve the current thread and unrelated query state; only one peer
  is current. Outside Chat they enter `/chat` with the chosen surface. Navigation
  remains passive and uses the existing dirty-editor router guard. Account-menu
  rows are compact 34px targets on desktop and mobile, with viewport-bounded scroll
  on an opaque ink surface. Opening/closing is immediate: rapid Escape/reopen must
  not inherit a delayed exit-visibility animation. Chakra still owns keyboard/focus.
- Legacy Work/Library reads remain passive. IDE entry prepares its owned project
  and runtime after authoritative registry evidence; it never provisions the
  thread's legacy sandbox. Chat remains mounted; surface changes cannot erase
  the composer, streaming result or dirty Workspace draft.
- PDF startup distinguishes an unresolved workspace read, unresolved project
  read, confirmed absence and read failure. Neither an initial render nor a slow
  request may advertise workspace/project creation. Failures expose read retry,
  never creation as a substitute. Thread changes mask previous-thread facts before
  effects complete; late aborted responses cannot replace the current project.
  Proven expiry is distinct from an unknown read: the existing toolbar's New
  document action remains enabled when the draft/build guards allow it. Its
  dialog lets the user choose document/presentation before allocating anything,
  explicitly warns that this creates a fresh environment, and allocates only on
  submission. Creation uses the acknowledged fresh workspace revision. A dead
  runtime is not offered a reload button that cannot recover it. The format
  catalog is a passive owner-checked read independent of workspace readiness.
  Existing same-project drafts stay mounted during background revalidation.
  Once a workspace/project has been confirmed in this scope, unavailable or
  expired reads retain its editor and local draft. A subsequent absent read is
  not permission to prepare a blank replacement; expiry remains terminal for
  that runtime. New owner/thread scope still clears all retained facts. Save,
  including a late lease response and raw-source writes, requires current ready
  facts. The exceptional recovery row offers explicit retry and local JSON/raw
  export, clearly excluding assets; no remote write or hidden durable-save claim.
  Recovery help stays viewport-bounded. Closing Materials/Formatting restores
  the exact toolbar trigger, including touch browsers that do not focus buttons
  on pointer activation; opening a source instead targets its editor.
  A nonzero invalidation counter at mount/thread entry is not a new event and
  cannot cancel/downgrade the initial snapshot into a background refresh. A real
  invalidation during that read may supersede it, but initial loading stays
  unresolved until the accepted current response, never a transient create offer.
- Lazy route/Work loading announces a bounded localized status through the shared
  loading primitive instead of an empty panel. It never implies sandbox creation,
  model processing, measurable percentage or successful subsystem availability.
  Header Chat navigation remains usable; parent layout keeps its scroll ownership.
- Route titles reflect the active surface without message/filename content.
- Route render/lazy-load failures use an eager app-owned child error surface,
  keeping the enclosing layout and navigation where that layout remains healthy.
  Parent failures retain a safe home link. The title is “Ошибка страницы”; raw
  exception/stack text is not shown or sent to app-owned boundary callbacks.
  Chunk failures offer explicit reload (with an unsaved-edit warning) and home,
  not automatic reload or a reset that cannot retry a cached rejected lazy import.
  No recovery action dispatches a chat/model request. React/dev-tool diagnostics
  are separate from app-owned feedback and are not certified by this contract.
  Route loaders replace private import exceptions with AppRouteLoadError. Dev
  tooling leaves that one app-owned failure to the eager recovery surface;
  unrelated ChunkLoadError/runtime failures and compiler diagnostics stay enabled.
- Library, Workspace and Room availability are independent; a failed facet is
  contained inside its panel. At >=1200px source/editor/context scroll
  independently; 768–1199px uses source/editor and a Context overlay; <768px uses
  Files/Context tabs. Library is the same sidebar drawer at every breakpoint.
  Actions account for safe-area and visual keyboard.
- No horizontal overflow at 393px or 200% zoom. Truncated filenames retain an
  accessible label/title. Internal transport keys, capabilities and container
  identifiers are not rendered or persisted in browser state.

### IDE repository scene — staged read integration, 17.10.2026

Business source: `../docs/IDE_WORKSPACE_ARCHITECTURE.md` and IDE-01/02/03 in
`../docs/PROJECT_TODO.md`. One repository owns one separate runtime. The thread's
legacy/PDF binding must never be substituted when an IDE read fails or is empty.

- A fresh Chat URL is a draft, not a registry outage: listing it does not persist
  a thread. After an authoritative registry read, `useIdeEntry` calls protected
  `ide/prepare` for the selected repo or the server-owned default. First entry
  shows the shared loading treatment, never a Create/Start form flash. The
  server serializes identity/allocation across reloads and tabs, initializes Git
  without staging/commits/README and preserves existing Git/config/source bytes.
  No AI, execution, indexing or PDF build starts. Quota rejection is not retried
  automatically; expired/unknown work is not replaced with an empty environment.
  Preparation failure offers explicit recovery, not another client creation
  intent. Registry failures remain read retries, not preparation as a substitute.
  A bounded memory-only per-thread cache avoids preparing a visited repo again
  on peer switches; reload still reconciles through the server owner. Additional
  named projects retain the form and immutable creation intent, then prepare
  automatically without a second Start action.
  When preparation initially reports pending, observe that same runtime with
  bounded GETs. After Ready, finish setup once through prepare with the accepted
  repository ID; never issue another default creation or rearm quota rejection.
  Dependent Git reads, file mutations and agent sends wait for this continuation.
  Leaving retires the request and clears busy state. Returning first re-observes
  that repository before continuing; a cancelled request is not cached as done.

- `shared/api/ide` owns protected repository reads; `useIdeRepositories` owns
  bounded server pagination and selected descriptor; `useIdeRepositoryReads`
  owns runtime/tree/file reads for the exact thread/repository/generation/path.
  Read errors retain valid same-resource content, never manufacture empty state.
  Selection and source content remain memory-only because this is transient
  private work context, not a shareable dataset query. No source or path enters
  telemetry, browser persistence or route titles. Source paths stay in REST bodies.
  Current-visit validation precedes dependent Git reads, including the first frame
  after peer re-entry. The server's observation/generation fence is not relaxed
  to hide competing UI readers. Cached Git data and confirmed outcomes survive
  background validation; mutation controls wait for the current read. Pending
  startup receives bounded read-only observation, then explicit read recovery.
  Refresh stays disabled through the unvalidated initial visit rather than briefly
  accepting focus before startup disables it. A failed read still permits recovery.
- Subject and visual signature: a code workbench whose identity comes from the
  selected repository and short, hierarchical filenames, not a decorative banner.
  Reuse Inter/product and JetBrains Mono/code roles, existing page/surface/primary
  tokens and Workbench button variants. No new palette or token values. The
  project selector is capped at 320px, with one quiet refresh utility. There is no
  duplicate subtitle under it and no enclosing box around each action group.
- At 1100px and above, a 208px source rail, flexible code panel and 340px agent
  rail (380px at 2xl) use quiet vertical rules, never enclosing cards. Each owns
  its scroll; long code lines scroll inside the code panel, never the page.
  Below 1100px Files/Code/Agent/Graphify pressed buttons choose one full-width
  panel. Repository mutation tools stay under Files on narrow screens, leaving
  room for the agent. Graphify explicitly reports its not-yet-integrated state.
  Successful deliberate file selection opens Code;
  responsive changes and refresh do not erase the current read. Buttons/select
  consume the existing `document` size (34px desktop, 30px mobile), not enlarged
  mobile controls. The global sidebar/divider is unchanged.
- Reuse WorkspaceTree, its native disclosure keyboard semantics and short names.
  An `incomplete` folder with no returned children says its contents are partial,
  never empty. The overall bounded-tree warning stays visible. Binary and
  truncated file reads are explicitly labelled; no partial text is editable.
- Registry loading, confirmed empty, failure, unavailable runtime and expired
  runtime are different states. Initial/unavailable reads never offer creation
  as a substitute. List/runtime reads have explicit timeouts, never allocate,
  abort on retirement and reject captured obsolete callbacks. Only observed
  pending/dispatching startup is polled; error/unknown/expiry is not a retry loop.
  Source reads require the generation received with the tree. Refresh keeps a
  same-generation file visible; a changed/expired generation retires it.
- A ready repository offers compact file/folder creation and Git setup groups.
  On desktop these actions share the project-selector toolbar, separated into
  quiet groups, rather than occupying a second full-width strip. File/folder
  actions compact to named icons as their toolbar narrows. The empty editor
  points to this single creation owner instead of repeating Create file.
  New project likewise becomes a named icon below 680px of toolbar-container
  width; its label returns above that width. At320px, selector/status and actions
  fit two compact rows rather than pushing refresh onto a third row.
  The existing WorkspaceEditor uses its named `ide` variant: explicit edit lease,
  digest-checked write and Ctrl/Cmd+S write only to the temporary environment,
  never an automatic Git commit or an assertion of durable storage. Creation
  refuses an existing target; missing parents are created explicitly. Failed
  writes retain the draft, expired leases make it read-only, generation changes
  cannot rebase a dirty draft silently. The shared navigation guard keeps separate
  IDE and PDF draft owners rather than overwriting the sibling lifecycle.
- Selecting a file exposes Move in the tree header (desktop) or code toolbar
  (mobile). Focusing a directory exposes the same header action for that folder.
  The header keeps the document-control height even before Move appears, so
  focus cannot shift a row between pointer down/up and consume the first click.
  IDE also enables native internal drag-and-drop for files and folders: onto a
  folder row, or free tree space for the repository root. Destination uses a
  token-owned focus outline; a transient instruction appears only during dragging.
  The same guarded move owner handles both paths; no external drag payload can
  supply a source, and passive PDF/Library trees do not gain mutation behavior.
  Self/descendant/no-op drops are rejected; busy/expired/unverified runtimes disable
  dragging. Tree feedback stays in its source pane, without a duplicate code notice.
  Confirmed folder moves retarget descendant tree paths and cached tabs, preserving
  contents; uncertain replies retain the old view and require inspection.
  The shared authored Select chooses an existing folder, including the
  repository root, with an optional filename change. The modal remains within
  the viewport; errors retain the destination and never overwrite another file.
  Folder choices exclude the source and its descendants. Only a confirmed atomic
  no-replace move retargets tree selection and open tabs. Dirty
  navigation applies before moving. This keyboard/touch path requires no drag.
- Git init creates metadata without a commit or staging user files. Clone
  accepts public HTTPS GitHub repository URLs and an optional branch, with a
  20 MiB fetched-object limit. It retains reachable branch history and origin,
  refuses user data in the target, and never runs scripts/hooks/submodules. A
  server-owned untouched Git-init seed may be replaced only after full staging
  and a second private byte/structure/mode check under the operation lock. The
  browser cannot request this exception. Modified/unknown projects are not
  cleared. A definite nonempty/conflicting destination redirects the same explicit
  Clone action to a new isolated project. The server journal pins one destination
  per immutable intent and claims Git dispatch once. Lost acknowledgements are
  reconciled with GET; running/uncertain Git is never automatically replayed.
  Retry of a reserved startup reuses that same intent; fields remain read-only.
  Confirmed completion selects the new repo while retaining the original in the
  selector. Failed/uncertain attempts offer inspection of the created project.
  Entry into any clone destination must not initialize Git before publication.
  After a full reload, a repository-owned GET discovers the latest attempt from
  either its source or destination. The journal persists only canonical public
  GitHub URL/ref, verified against the immutable request digest, never credentials
  or source. Reserved attempts expose an explicit Continue action with pinned
  read-only fields; discovery alone never allocates or dispatches. Legacy rows
  without parameters remain inspection-only, never guessed. Running observation
  is GET-only and bounded to 90 seconds; failure/timeout leaves manual Check.
  Completed announcements belong to one intent, not the next recovered attempt.
  Existing drafts and selection guards remain authoritative on late completion.
  Other hosts/private credentials are not presented as supported. Status/refresh
  does not initialize or clone. Unconfirmed mutations are not automatically
  retried. Files, source bytes and origin stay out of URL/WS/browser storage.
  Script execution, indexing, export and push remain ordered TODOs.
- The retained WorkHub remains the single Library/PDF data/controller owner.
  It mounts only on the first PDF/Library use, not on entry to IDE; opening a
  repository must not wait for or even request the legacy thread snapshot.
  IDE is lazily mounted only after its first visit and kept in memory on peer
  switches; no second Library or assistant is mounted inside the new scene.
  IDE-05 reuses that persistent composer/voice/attachment/settings owner through
  a permanent right-rail slot. Opening it does not start a model. Suggestions
  fill the existing input only. Its idle scene shows one short heading and three
  compact suggestion actions, not repeated onboarding paragraphs. The header
  keeps the credit cost visible in one short line; passive agent help contains
  detailed scope, tariff/limit and non-automatic execution/publication information.
  Repository identity already belongs to the project selector, not a duplicate
  agent subtitle. Only an actual blocker adds a warning; an expired environment
  is never described as merely needing Start. The runtime status sits beside the
  project selector with passive details, not two full-width information rows.
  A protected REST preparation pins an owned
  repository generation; WS carries only an opaque two-minute target ID. The
  worker revalidates before reservation and supplies private repository tools,
  never the Chat/PDF sandbox. No IDE-to-ordinary-Chat fallback on enqueue failure.
  IDE uses general code assistance, not PDF routing or extra paid-tool consent.
  Existing expensive-run decisions remain explicit and retain the IDE target.
  During execution the same bounded trace replaces, rather than remounts, input;
  Stop stays available. Completion restores input and a repository-scoped mini
  report, never the full reply. The local `ide_finish_task` tool supplies one or
  two plain-text sentences (at most 280 Unicode code points), without a separate
  summarizer service or tool surcharge. If a tool-capable model ends in prose
  without the report, one bounded, metered completion round offers only the
  authorized finish tool; mutations cannot be repeated. It preserves the last
  answer's outcome, blocker and next step rather than substituting receipt counts.
  If that fails, the UI explicitly labels the missing report;
  historical replies without this metadata refer to the full Chat
  answer, never silently display or truncate its source/code in the IDE rail.
  Only confirmed write receipts produce a count, never model prose. Unknown
  acknowledgement is labelled separately; zero receipts do not prove no writes.
  Zero-write boilerplate is not repeated below the semantic report. Completed
  trace disclosure has one expansion state, so collapsing it releases its height.
  Desktop IDE starts with the same 50/50 assistant width as PDF. Its code/agent
  and tree/code dividers reuse the pointer/keyboard split owner with independent
  geometry keys. Narrow layouts retain the existing single-area navigation.
  Markdown sources expose a compact Code/Preview switch. Preview reuses the
  canonical Chat Markdown renderer and prose tokens through its public feature
  API, with a repository variant that never strips thinking tags, repairs fences
  or rewrites the file. GFM tables/lists and fenced code are supported. Raw HTML
  is inert; images do not make automatic remote or authenticated-origin requests.
  Relative file links use the existing guarded repository navigation; external
  HTTP(S)/mail links open separately without opener/referrer access.
  Fragment links navigate/focus headings only inside the current preview, without
  changing the Chat URL or opening a repository file. Unicode and duplicate titles
  have stable local slugs; generated DOM IDs are scoped, not user-controlled global
  names. Numbering repeated headings must not restart a quadratic collision scan.
  A proven inaccessible thread (404 from owned repository/work snapshot reads)
  starts a fresh thread on the same surface; never create in or claim the old
  account's thread. Network errors remain errors, not permission to initialize.
  After completion, clean source views refresh; local editor drafts are retained.
  Existing-source writes require an observed digest and CAS; no automatic Git
  snapshots, execution, Library imports/exports or publication. File receipts
  acknowledge temporary environment storage, never a commit or durable backup.
  IDE draft recovery extends the existing WorkspaceEditor conflict panel, not a
  second editor or modal. On explicit Edit/reacquire the owned lease is followed
  by a bounded generation-pinned source read; a changed base remains read-only,
  preserving the original digest and local text. Recovery can copy the draft,
  compare base/local/environment text, or explicitly load the reviewed full-text
  version. A read matching the draft does not retroactively confirm a lost write.
  Partial, binary, unavailable and mismatched reads never enable replacement.
  Generation replacement preserves a dirty draft for copy/review, but acquiring
  edit permission requires explicitly adopting a reviewed current-generation
  source first. Source/draft/comparison bytes remain memory-only. Comparisons are
  bounded, visibly omit long content and are not presented as a Git diff/commit.
  Loading a reviewed version updates the existing source-read cache independently
  of write receipts. A failed tree/cache consumer cannot revoke a confirmed Save.
  Mobile recovery avoids a duplicate read-only banner, keeps primary recovery
  actions above the bounded comparison, and preserves a selectable draft area.
  The editor owns short-height overflow; shell/sidebar geometry is unchanged.
  Refresh while an editor owns a source copy is a read-only runtime/tree
  observation: it neither discards text nor refreshes registry selection behind
  the editor. Navigation and intentional replacement retain the shared guard.
  Pending/failed runtime verification immediately revokes writing, editing and
  adopting a comparison; copying local text stays available. A detached editor
  snapshot remains in memory even if it was clean before runtime loss, and is
  protected by the dirty-navigation guard until explicitly discarded/adopted.
  Reacquire waits for outstanding old-fence cleanup. A missing allocation is
  labelled unknown, not guessed expired and not replaced by a fresh workspace.

Evidence: `tests/unit/features/workspace-room/ideReadContracts.test.js`,
`useIdeReads.test.js`, `tests/unit/components/IdeStudio.test.jsx`, WorkspaceTree
regressions and `tests/e2e/ide-studio.spec.js`. Mocked browser reads are not proof
that migrations/current sidecar sources are installed in the local runtime.

The complete IDE direction is staged, not reduced to this read-only scene:
at wide workbench widths, source navigation stays on the left, Code/Graph/Changes
share the central working area, and the assistant occupies one right context
rail extending the existing Work context pattern. Its input reuses the same
persistent composer owner as Chat/PDF once the server-validated repository tool
context is implemented. The graph is the current repository's Graphify result,
not a copy of the global Knowledge Graph. By explicit user decision19.10.2026,
the developer console starts open below the central editor. It never changes
the full-height tree or agent rail. Its existing Workbench separator changes
height with pointer or keyboard; only non-sensitive geometry is persisted.
The toolbar toggle/collapse action can hide it and restores focus to its trigger.
Initial rendering does not take input focus, launch commands or allocate a runtime.
Commands run only on explicit submit, against the current owned ready generation,
from the repository root in separate non-interactive processes. This is not a PTY
and `cd`/environment changes do not carry over between commands. Output is plain
text with bounded stdout/stderr, exit code, timeout and truncation states. Dirty
editor text is not silently written/discarded by a command; the console says
that saved files are used. A completed command refreshes clean views only.
Manual command text/output stay in memory-only per-generation browser history (last30),
not URL, localStorage, Chat messages, model context or telemetry. Private server
receipts expire with the runtime; they hold a command digest and bounded output.
Stable execution IDs prevent duplicate dispatch; lost responses offer a status
read of that same ID, never automatic replay. An unknown result is not success,
failure or cancellation. There is no enabled Stop placeholder without native
process-cancellation support. Collapse/clear affects display, not the process.
Agent-command receipts additionally appear in this same fixed console through a
bounded, owner-checked read-only history. Process stage and criterion verification
are distinct labels; exit zero alone never means the task was verified. Unknown
cleanup keeps mutation controls blocked. Switching repository/generation retires
reads, ignores late responses and hides prior output. History errors remain inside
the console scroller with an explicit read retry; no outer banner or resize.
Task-owned receipts remain in the backend journal; their bounded diagnostics may
enter that agent's private working context, never public traces or browser storage.
Commands accepted by the task-bound harness use the existing server snapshot,
execution and Stop authority. This adds neither a user-command replay action nor
automatic dependency installation. Dirty buffers remain untouched.
At medium and narrow widths Files/Code/Agent/Graphify are explicit panels. Background changes
never remount the editor or recreate the composer. Controls require their owning
API and failure/dirty-state contract, never enabled placeholders. The console
now has the isolated exec boundary described above; graph/archive/push remain
separate staged capabilities. This direction alone is not evidence of delivery
of every IDE-03 through IDE-08 scenario.

### IDE approved design direction — 17.10.2026

The user explicitly approved the first desktop direction and the assistant's
three presentation modes, then explicitly approved the mobile mock and requested
implementation. This is an approved
interaction target, not a claim that the current read-only scene implements it.
The decision and image/reference evidence are in `../docs/IDE_DESIGN_REVIEW.md`.

- Repository tree on the left, the widest code working area in the centre and
  one assistant rail on the right. Exact rail widths remain responsive design
  details, not new normative tokens inferred from raster image dimensions.
- Reuse the persistent Chat/PDF composer, voice, attachments, mode/persona/model
  controls and conditional context-window gauge. Narrow desktop rails use the
  existing compact icon variant as PDF does; no separate miniature chat history,
  permanent assistant banner, repeated repo subtitle or unexplained `@` control.
- During an active run, its bounded internally scrollable trace replaces the
  normal input/settings without unmounting their owners. One progress indicator,
  explicit Stop and access to Chat remain available. Idle input does not reserve
  an empty trace canvas or depend on the global sidebar's height/divider.
- A genuine human question replaces trace/input with up to three choices and
  a free-text alternative. The shared `useHumanQuestion` / `HumanQuestionPanel`
  owner now renders this state in the persistent IDE/PDF dock, not another modal
  or composer. Choices are pressed buttons, not checkboxes. The body scrolls;
  answer/cancel/recovery actions stay in its footer. A failed acknowledgement
  retains a memory-only locked answer and checks the same owned question before
  an explicit same-intent retry. Reads/reload never submit an answer or start a
  second child. Fresh owned reads gate question content and actions after a
  thread/account switch; drafts never enter URLs, persistent storage or traces.
  Accepted questions restore the same child and existing Stop owner. Later
  persisted results take precedence over older retained live question messages.
  Server expiry/cancel/accept state is authoritative, not a client timer. The
  shared action-owner and intent utilities live under `shared`, with compatibility
  facades for existing Work callers. Their scope-aware busy state cannot block
  the next account/resource with an old operation, and captured reads are fenced
  after unmount as well as mutations.
  The answer and financial decision are separate facts. `useHumanQuestionCost`
  reads the owned same-child receipt before attaching the continuation to trace/
  Stop/task polling. Its business-named inline variant reuses this question frame,
  not the ordinary Chat paid-offer resend path or a second modal. It displays the
  server's estimate with explicit confirmation/decline; reads, reload, focus and
  local expiry never POST. Expired quotes refresh only on explicit action for
  the same child. Unknown completion requires GET; a still-pending retry retains
  the exact offer/decision and never silently changes it. A definitive stale
  project rejection still permits declining that pending continuation.
  When the cost GET is loading/unavailable or a decision ACK is unknown, the
  same footer exposes explicit same-child Stop instead of a disabled decline.
  `useQuestionContinuationStop` reuses owned Jobs cancel/status endpoints with
  automatic retry disabled, the canonical action owner, and account/thread/child
  fences. Stop intent invalidates stale price reads and blocks captured payment
  actions. Its ACK never claims terminal cancellation or a refund: an owned task
  GET must prove completion, including a result accepted before Stop. Unknown
  completion retains two fixed actions (explicit Stop retry and read-only Check),
  not another message/run/dialog. Focus only checks, and pending Stop intent stays
  memory-only. A stalled quote read must not prevent this safety action.
  Cost actions retain a 44px/two-line frame during loading/error/retry. Enter from
  the answer form cannot accept money; the initial cost focus is the safe decline
  action (or heading while loading). The estimate itself is the single first-line
  heading, pinned on an opaque workbench surface while details scroll. The details
  scroller remains keyboard-focusable even when it contains only status text. A short
  viewport must not clip the price behind the fixed footer. At viewport heights
  up to 400px, omit the nonessential static explanation, not price/actions/errors.
  Quotes, decisions and
  drafts stay memory-only.
  Backend threshold, expiry, permissions and pricing remain authoritative; the
  UI cannot create an approval, price or transcript. Native broker/worker/sidecar
  acceptance remains open, including the native Stop/first-execution race while
  the cost acknowledgement is unknown. Runtime human questions remain disabled
  until that rollout is verified.
- Static PDF tool/cost guidance lives in explicit toolbar help, not a permanent
  multi-line row above the input. Its full wording is retained. PDF and IDE reuse
  `WorkbenchInfoPopover`: opaque, click/keyboard-owned, bounded and internally
  scrollable, outside workbench clipping and with focus restored to its trigger.
  No question error or help disclosure adds an outer workbench banner.
- Completed work may show a concise owned result and changed-file/diff access,
  not a second full conversation. Local runtime saves, durable copies and Git
  publication remain distinct facts; permissions and cost rules stay server-owned.
- Keep the existing theme/control tokens and PDF input shell. These approved
  choices introduce no new palette, font or global control-size values.
- Approved mobile target: a single Files, Code, Agent or Graphify area, compact
  document-sized controls and a dedicated question panel. Code owns its file
  tabs, breadcrumb, scrolling source and factual status; it does not append a
  second composer. A short/keyboard viewport, loading/error/recovery and server
  operations still need actual browser/integration acceptance. Mock approval is
  not evidence of implementation or runtime readiness.
- Current implementation slice: bounded memory-only read tabs (eight files per
  current repo/generation), horizontal tab overflow, literal-source fallback and
  shared curated syntax grammars with Chat. Switching an already read tab is
  local; explicit Refresh rereads. Repo/generation changes retire the cache;
  removed paths are dropped after a confirmed tree read. Repository editing now
  has a separate memory-only draft owner; no durable save or Git publication is
  implied by a read or runtime write. Unknown/large source remains plain text rather
  than blocking the UI with tokenization. This does not close the IDE scope.

### Editing, leases and dirty navigation

- Opening a file attempts a lease. Occupied/lost lease opens it read-only with
  explicit reacquire. Background invalidation never remounts the editor or
  replaces dirty content. Save requires fence, current revision, writable file
  and actual changes; `Ctrl/Cmd+S` uses that same pessimistic save path.
- A captured file-open action from another thread, an inactive surface or an
  unmounted editor is rejected before changing the current draft or superseding
  its read. A superseded acquisition releases only its own lease and does not
  dispatch an obsolete file read.
- Save, explicit lease reacquisition and loading the reviewed server version also
  reject captured callbacks from an inactive surface, another thread or an
  unmounted owner before writing or releasing/acquiring a lease. A valid write
  already accepted by the server retains its existing acknowledgement semantics.
- Discard, draft copy and navigation cleanup are scoped to the current owner as
  well; reopening the same thread starts a new owner rather than reviving old
  callbacks. Late clipboard outcomes never notify another resource or repeat
  the copy. Explicit current-resource navigation cleanup may finish after Work
  becomes inactive, but a rejected cleanup cannot authorize the target action.
  The shared guard reads current dirty/blocker state, cancels obsolete pending
  actions and uses exact confirmation ownership across thread changes/unmount.
- `409`, `423`, `503` retain the draft and show inline recovery: copy local text
  or deliberately load the latest server version. No refetch-and-overwrite.
- Surface/thread/file changes, Back, new chat and active-chat deletion share one
  app-owned dirty guard. Initial focus: “Продолжить редактирование”. Confirming
  explicitly discards, releases lease best-effort and performs one target action;
  cancelling restores initiating-control/editor focus.
- Reload/tab close use only narrow `beforeunload`. Draft never enters persistent
  browser storage or telemetry. Selecting the open file only focuses it, without
  read, acquire or editor reset.

### Room summary, issues and Library

- Library is a sidebar action on Chat, Work and PDF, not a Work/PDF tab. Opening
  it mounts the existing read model lazily without navigating, provisioning or
  starting an assistant. Only Library mutations are enabled when Chat is active;
  hidden editor, collaboration, activation and history actions retain their own
  active-surface guards. An owned selected thread is required for Library upload;
  persistence alone never allocates a runtime. Account downloads do not require
  a thread. Legacy inline upload-and-copy retains its separate explicit behavior.
  Mobile closes its navigation drawer before presenting Library and restores
  focus to the Menu control; desktop restores focus to Library. Footer rows keep
  their 34px size and independent natural-height footer, including the fourth row.
  A cold lazy bundle presents a dismissible Library loading drawer even when the
  Work surface is hidden; unknown loading state never offers a creation action.
  The short destination select uses AppSelect's explicit inline menu variant
  inside the modal focus/stacking owner, avoiding a body portal below the drawer
  or fixed-position offsets inside its transformed content. Keyboard selection,
  pointer hits and the opened popup are covered together.
- Work snapshot v2 owns Workspace/Library/aggregate Room. Issue title/body/path
  content is fetched only through the protected issues endpoint, never snapshot
  or WS. Issues have idle/loading/ready/stale/unavailable states; refresh failure
  retains valid stale content without downgrading other facets.
- Issue/control mutation refreshes issues and snapshot independently. A failed
  refresh never undoes or misreports a confirmed mutation. Status/history/lease/
  intake labels use closed dictionaries with neutral unknown-value fallbacks.
- Issue creation/update and run controls use the shared thread-owned action
  lifecycle. Captured callbacks cannot dispatch from an inactive or obsolete
  thread. Duplicate actions are rejected while pending; late responses cannot
  refresh, notify, cancel the current run or clear another thread's busy state.
  Local cancellation callbacks and synchronous refresh failures do not revoke
  an already acknowledged server control operation.
- The issue form draft and its validation belong to the current thread/file's
  Work Hub, shared by responsive Context instances. Breakpoint changes retain
  entered fields and errors without browser persistence. Changing thread or file
  clears this single current-resource form; it is not a per-thread draft cache.
  Save acknowledgement clears only the exact submitted form, never newer input
  or another resource's form. Browser continuity acceptance remains tracked
  separately from component-state evidence in PROJECT_TODO.
- Upload states are idle → uploading → library_uploaded/imported/kept/library_saved/cancelled/error,
  visible beside the file. Cancellation/ambiguous failure reconciles snapshot
  before retry, reusing the upload intent. Existing Workspace files win.
- A cancelled or superseded upload cannot announce success or update another
  thread, including during snapshot reconciliation. A confirmed upload remains
  confirmed if an independent snapshot refresh fails. Cancellation copy never
  claims the Library was successfully refreshed without evidence.
- Confirmed Library-only intake remains labelled beside the matching file when
  the upload control is replaced; an explicit later copy outcome takes precedence.
- Per-file intake outcomes occupy their own wrapping line. Long recovery labels
  must not compete with file type/availability or clip inside the source rail.
- Selected upload File, status and retry intent belong to the current Work Hub,
  not its Files/Library upload control. Panel and breakpoint changes preserve
  them in memory; thread change/unmount clears them without browser persistence.
  Replacing a control neither resubmits nor cancels an in-flight request.
- Only imported/kept are confirmed copy outcomes. Unknown/missing/error outcomes
  retain the Library source and bounded per-file recovery, never false collision.
  `library_saved` keeps the source and retries deliberate copy without reupload.
- Explicit create/copy and history preview/revert share a thread-owned action
  lifecycle. Duplicate activation is rejected while that action is pending.
  Captured actions from another thread, an inactive surface or an unmounted owner
  cannot dispatch. Late responses cannot change the new thread's outcomes,
  notifications, revert dialog, editor or busy state. An obsolete acquisition
  releases its exact original lease and never proceeds to copy. Server-confirmed
  mutations remain confirmed if their independent snapshot refresh fails.
- Background snapshot merges cursor pages by file ID and preserves selection,
  scroll and editor. Durable files can outlive their source chat; a deleted chat
  is not evidence that a Library file is missing. No phantom file success.
- Initial Library loading is distinct from a confirmed empty list. Refresh keeps
  cached files actionable. Cursor-page failures remain inline beside a keyboard-
  accessible retry; retry uses the same cursor and does not hide existing files.
  This recovery is not a transient toast and never renders server error text.
- Available Library files expose a separate “Скачать” ActionLink through the
  authenticated owned-file backend route. Download requires neither a thread
  nor a sandbox/lease and stays available during unrelated workspace operations.
  A new tab preserves the editor, local draft and source selection. Unavailable
  files have a non-interactive label, never a storage-key/URL fallback. Copy is
  a distinct workspace mutation and is not triggered by downloading.

### Document Forge

- TeX/Bib/class/style files follow ordinary text lease/revision/dirty rules.
  Profiles lock geometry, engine and audit; prompts cannot weaken them.
- Build/poll/cancel/completion are independent of editing and Library access.
  Draft stays in Workspace; only explicit final publication or completed pdf_gen
  stores registered PDF/source artifacts in Library. A file card requires
  confirmed backend delivery, not model claims.
- Final publication uses the shared Work action owner for the exact thread/build/
  PDF. Duplicate or captured obsolete actions cannot dispatch. Workspace project
  snapshots do not own backend outbox state: recovered final artifacts reconcile
  it through the existing protected build-status read before a new publication.
  A queued acknowledgement survives unrelated snapshot/notification failure.
  Uncertain POST or polling failure stays inline with “Проверить сохранение”;
  this action only reads status and never re-enqueues or invokes a paid audit.
  No automatic POST replay. Another explicit publication is allowed only after
  a confirmed status read proves that no job exists. Pending, delivered and
  terminal jobs cannot be duplicated. Switching thread/build, leaving Work or
  unmounting aborts status requests and timers; late responses cannot affect
  another resource. Returning to a pending job resumes bounded reads only.
  Each observation has a five-minute wall-clock deadline, including an unresolved
  read; request timeouts and pauses are clamped to its remaining budget. Expiry
  releases local checking state and offers the same read-only recovery. It does
  not cancel the durable server job, re-enqueue it or trigger another paid audit.
  A late response cannot release or update a newly started observation.
  Publication recovery never replaces the editor or its dirty draft.
- Diagnostics are bounded Russian labels, never raw TeX logs, commands, absolute
  paths or exception text. PDF preview uses authenticated response and temporary
  in-memory object URL, revoked on replacement/unmount and never persisted.
  Preview reads belong to the exact thread/build/artifact and use the shared
  Work action owner: duplicate or captured inactive actions cannot dispatch,
  superseded responses cannot allocate a URL, and each allocated URL is revoked
  once on replacement, scope change or unmount. A read failure keeps an existing
  preview and offers inline recovery through the same explicit opening action.
  Only the visible responsive context's selected PDF tab mounts the viewer.
  Hidden tabs/rails, closed drawer and inactive Work surface do not mount an
  iframe. Toggling visibility reuses the owned object URL without downloading
  again; the surrounding context fields remain mounted during tab changes.
  Context tab selection is owned by the thread's WorkHub, shared by rail,
  drawer and mobile panels. Breakpoint changes, drawer close/reopen and background
  refresh retain it; changing thread resets it and closes the old drawer.
- Project modes share the selector's closed Russian dictionary; missing/unknown
  modes remain neutral rather than exposing raw values or assuming draft. Queued
  and preparing builds do not imply compilation or audit success. Technical
  audit success is shown only after a confirmed post-audit build state; failed,
  cancelled and unknown builds do not manufacture stage history.
- Vendor kits are owned Library ZIPs with vendor.toml, project lease/revision and
  isolated untrusted scope. No overwrite or weaker compiler isolation/engine.
  v2 activation requires a new target, probe and atomic clone; source stays intact.
  Copied/content-migration-required is explicit. Transport URL/hash/archive
  internals remain private, with safe package identity/version/trust displayed.
- Brief, semantic outline, evidence and unresolved fields use protected authoring
  content, not snapshot/WS/local storage/telemetry. Authoring, compilation,
  deterministic audit, visual audit and delivery have separate visible states.

### Feedback, overlays and async resilience

- IDE durable project Save and History are two icon actions in the existing
  toolbar, not an extra row or a duplicate file-save control. File writes still
  say “Записать в среду”; only a verified immutable snapshot earns “Проект
  сохранён”. The bounded history modal reuses Chakra Modal, shared document
  buttons, tokens and one body scroller. A historical publication does not claim
  to replace the current files. Restore is explicit, confirmed with initial
  focus on Cancel, and available only after the current runtime expires; live
  files and editor drafts are never silently overwritten. Server-confirmed
  active binding triggers a normal owned re-read, not client-side adoption.
  История явно возвращает фокус к фактической кнопке открытия (панель проекта либо
  блок восстановления). Если восстановление убрало прежнюю кнопку, фокус получает
  кнопка истории в панели. Pointer-click в WebKit не обязан менять activeElement,
  поэтому владелец открытия сохраняет currentTarget, а не полагается на автофокус.
  Unknown replies retain the exact opaque operation identity in tab-scoped
  session storage; reopening/reloading performs reads only. A user can check or
  explicitly retry the same intent. No code, credentials or storage locators
  are persisted in browser storage. The server owns retention (latest + ten
  previous, with active restore pins protected) and logical storage capacity.
  Uncollected retired/conflicted snapshots remain discoverable as cleanup tasks,
  not restorable versions. Only a settled unpublished snapshot offers deletion;
  an app-owned confirmation names its scope and initially focuses Cancel. The
  action re-reads current status before dispatch and the server rechecks under
  its owner lock. Publication winning the race prevents deletion. Unknown writer
  completion never becomes deletion permission by timeout. Space is freed in UI
  only after a server collected marker, not optimistically after a delete request.
  Lost delete acknowledgements recover via passive status; no new Save/delete
  happens on reload. Cancelling confirmation focuses the current row action
  (the prior DOM node was unmounted); completion focuses the modal close control.
  An unsettled pending row instead offers “Отменить попытку сохранения”. This
  revokes publication, not the background writer. The same confirmation explains
  that files stay intact and capacity remains charged until cleanup. Only a
  confirmed terminal response clears the matching local Save intent; lost replies
  require a check and never clear unrelated work. Server admission can still deny
  a fresh Save while unknown writers occupy capacity or concurrency slots.
  An expired runtime exposes contextual recovery inside the existing file pane,
  not another toolbar/banner row. It opens the same History owner; no restore or
  empty replacement is dispatched on entry. Pending operations remain reachable.
  Failed/unknown history reads never claim no versions exist. Confirmed empty
  history states only that no versions exist. New project remains available once,
  in the main toolbar; recovery does not repeat its button or explanatory copy.
  A disabled snapshot capability does not claim older versions are absent.
  Cached files/drafts stay intact. The guidance disappears after an acknowledged
  active restoration.
  The separate IDE-project form focuses its name and never claims an existing
  chat has no repositories. An uncertain create retains its immutable name/ID
  while the same mounted scope switches surfaces. The name is read-only and
  “Повторить создание” explicitly replays that identity; reopening does not POST.
  Retired visit callbacks cannot dispatch or adopt late results. Scope changes
  do not expose the previous name, and this in-memory recovery is not advertised
  as full-page-reload recovery.

- AI availability has one responsive control, distinct from the
  chat socket connection dot. Green means the enabled pool has fresh available
  catalog evidence; amber means partial availability, red means no enabled
  provider is available, and neutral means unknown/stale evidence. The count in
  the detail panel excludes disabled providers. Status never implies every model or generation
  will work. Hover/focus (desktop) and tap (mobile) reveal the same bounded
  provider list with text statuses and the primary provider. The Chakra popover
  owns placement, Escape and touch dismissal; no hover-only essential action.
  The controlled content root exists only while open and has immediate static
  visibility; a prior exit animation must not leave provider rows hidden on
  keyboard/touch reopening. Hover never moves focus out of the editor.
  Desktop uses the48×30px header trigger. Below768px the same component moves
  into the composer settings after context:44px target,30px circular glyph, no
  visible “ИИ” label. The accessible state name remains. Its284px viewport-bounded
  mobile panel reuses ChoicePanel's centered280px status-palette, backdrop,
  immediate opening, focus trap/return,44px close target and Escape dismissal.
  It shares the mode/persona/model group: opening a choice closes the other one.
  Status details scroll within the viewport-bounded body, without a duplicate footer.
  One responsive reader polls only cached gateway evidence every 30 seconds while
  visible; opening the popover never probes or invokes a paid model. Read failure
  keeps previous rows explicitly stale, never a misleading green indicator.
  The header groups identity, peer navigation, provider availability and account
  utilities explicitly. Desktop separates the last three with short, vertically
  centered rules, never enclosing boxes. Below768px the thread header is one56px
  row of identity/account controls. The extra navigation/status band is absent.
  Chat/IDE/PDF remain in the global account menu, preserving the thread URL and
  the existing dirty-navigation guard. Desktop peer navigation is unchanged.

- Blocking failures/conflicts stay inline; toast never holds the only recovery
  instruction. Toast dedup is two seconds by operation/bounded message, one on
  mobile and at most three on desktop; same operation updates in place.
  Сжатие контекста обновляет одно уведомление от запуска до результата, включая
  ответ за пределами окна дедупликации. Повторный клик до ответа не отправляет
  команду снова. Ошибка подготовки резюме не обозначается как пустая история;
  отсутствие подтверждения завершения показывается как неизвестный результат.
- Upload Cancel and explicit same-intent Retry share a stable DOM control so a
  keyboard cancellation does not strand focus on the document body. Cancelling
  is not proof of server rollback; reconciliation and user-triggered retry remain
  owned by the upload session, independent of Drawer visibility.
- Shared HTTP feedback uses only own dictionary entries and validated status/code
  types. Re-normalizing a DomainError preserves its code/private diagnostic origin;
  private details never become a new error code or public label. Technical detail
  traversal is cycle/depth/node/size bounded and never stringifies unknown objects.
  Unknown exceptions use the caller's safe fallback, not an assumed network cause.
- Chat socket errors carry a closed protocol code through transport and lifecycle.
  Trace, inline feedback and toast use the same safe dictionary; local socket
  failures use transport, unknown codes use internal. Exception messages are not
  parsed for permissions, copied to trace, or displayed. Unknown objects are not
  stringified; inherited JavaScript property names are not valid error codes.
- The shared toast owner measures visible Chat composer/Work editor/Library action
  shelves and the visual viewport. Its portal clears the highest visible shelf,
  including inline conflict-copy/reload and lease-reacquisition regions,
  including entrance motion and safe-area; fixed fallback offsets are not proof
  of clearance. Hidden panels are excluded. Resize, scroll and keyboard viewport
  changes reposition existing notifications without moving document content.
- Theme owns dropdown/popover/header/backdrop/dialog/drawer/palette/toast layers.
- Interactive admin tab panels render at full opacity without scroll-reveal
  wrappers. Decorative heading motion must not fade, delay or hide their controls.
- Admin section navigation uses the shared segmented control's wrapping variant:
  all destinations stay visible on narrow screens without a hidden scrollbar.
  Arrow/Home/End selection and focus remain owned by the same shared control;
  other segmented filters keep their existing non-wrapping layout.
- Admin setting save/reset failures use only the shared bounded error message,
  associated inline with the input. Raw server detail never renders; failed
  mutations retain local input and require an explicit retry.
  Saving/resetting one setting never remounts sibling controls or erases their
  dirty input. Refresh failure retains cached fields with an inline read retry;
  retrying that refresh does not repeat an acknowledged mutation. Only the
  explicitly saved/reset field adopts its confirmed value. Superseded reads and
  late completions after unmount cannot refresh another panel.
  Old thread/file responses are aborted or generation-guarded. Invalid WS frames
  produce a local generic protocol notice, not message history.
- No native browser dialogs, screen-local toast, clickable div, native product
  select, local scrollbar palette or Button-as-Link in migrated code. Forms use
  shared labelled controls, associated errors, preserved input and first-error
  focus; managed textareas do not resize manually.

### Video progress and costly decisions

- YouTube HTML only prepares a link; chip says “Ссылки на видео”, never proof of
  acquired video/transcript. Trace and activity share a lifecycle with actual
  probe/proxy/download/frames/transcript and measured authoring chunk counts.
  Heartbeats update freshness without duplicate steps or fabricated percentages.
- After 60 seconds without stage/event/operation heartbeat, progress is
  unconfirmed, not automatically failed/completed. Stop remains available;
  silence never resubmits a costly request. Stage payloads contain no URLs,
  transcript/frames, proxy credentials or integration bodies.
- Every costly offer parks answer generation. Both “Использовать” and “Продолжить
  без этого” exist; a whole-run offer uses “Не запускать”. Silence never consents.
  Owner/thread-bound offer ID restores original model/attachments/context once;
  replay cannot change a recorded decision or dispatch a second continuation.
- Stop withdraws unsent socket requests/consent even before a server task ID exists.
  A send/queue-flush failure reports a bounded terminal error and drops unsent
  work; reconnect never retries that failed request. Initially queued work still
  sends once on a healthy connection. Accepted server jobs retain their existing
  replay/job-id semantics; this rule does not infer that a server job was cancelled.
- Socket callbacks are scoped to the exact current socket and thread. Retired
  open/message/error/close events cannot forward content, clear a new queue or
  schedule its reconnect. Thread changes reset replay cursor and reconnect budget;
  reconnect within one thread retains its cursor. Retirement precedes close.
- Server policy close1008 terminates automatic reconnect and clears unsent work.
  An accepted WebSocket is not proof of thread ownership: the subsequent refusal
  must not reset the reconnect budget forever. The existing bounded access error
  owner supplies feedback, never the server's close reason. HTTP404 alone remains
  ambiguous because a new thread may not exist before its first message; the
  client never weakens the backend's owner-obscuring404 policy to distinguish it.
- Local connection loss preserves an acknowledged running job and Stop while
  reconnect/replay is possible; it never resubmits a message. Parked consent is
  not a connection failure. Provider/tool transport errors remain terminal.
  Agent-stage completion does not finish the job or fragment its streamed answer;
  agent_reply is the authoritative final content. Exhausted observation ends as
  unknown-result/error, never invented success. Idle connection errors cannot
  downgrade a received result. Constructor retries are bounded and contain no
  model/tool calls.
- Replayed job acknowledgements cannot reopen a completed answer, thaw a parked
  decision or replace newer work. Duplicate active acknowledgements may supply a
  missing cancellation task identifier without adding a queue step or resetting
  loading. The replay latch is bounded, private and never persisted.
- Tool availability is informational policy state, not a costly offer. Omitted
  tools requiring permission do not imply a pending decision or paused run;
  only an anchored confirmation offer may display that waiting state.
- A routing shortcut means only the mode was selected without a model call.
  It must not claim that the user's message or answer was processed without LLM;
  answer generation, its provider and usage remain independent stages.
- Cards stay actionable with collapsed/hidden trace. Accepted/declined survives
  reload; expiry says paid work did not start. Continuation resumes the anchored
  trace, no duplicate user message. Activity is below trace, above assistant.
- Manual scroll/keyboard reading/trace interaction suspends following. Idle time
  never drags the reader down; bottom/down action/new message restores following.
  This ownership persists between stream rounds and while a decision is parked.
  A manual gesture interrupts an outstanding smooth-scroll animation and its
  guard. A trace awaiting confirmation never auto-collapses on the terminal timer;
  the user may still explicitly expand or collapse it.

### Verification and migration

Серверный task_result v2 — отдельный итог задания, не признак завершения транспорта.
Существующие IDE/PDF-панели и terminal trace показывают закрытую русскую причину
partial/blocked/waiting_user/cancelled; legacy v1 читается. Неизвестный или неполный
результат не получает зелёное «проверено». Сообщение о неизвестном ACK/расходе не
предлагает новый запуск. Ни новое действие, ни новый владелец состояния не создаются;
текст переносится внутри прежних фиксированных областей, палитра/токены не меняются.

Shared owner adoption is scoped to Chat/Work, with admin/landing/404 touched only
when migrating those controls. Required evidence remains unit, lint/build,
strict audit, axe serious/critical checks, mocked desktop/tablet/mobile flows
and opt-in live Work. Canonical-source consolidation does not waive these gates
or declare untested behavior correct. Library downloads have their own component,
mocked and authenticated browser checks; unavailable retained Chat-card fixtures
remain a separate acceptance item in PROJECT_TODO.
Compiled mocked browser suites block service-worker registration so their network
handlers remain authoritative. External live suites preserve application service
workers; a mocked pass never certifies the production offline/cache lifecycle.
Composer and queue/reconnect fixtures explicitly exercise system-font fallback
by blocking font bytes. Their screenshots verify fallback geometry, not loaded
webfont typography. The dedicated native-font case permits real local font bytes;
Chromium CDP verifies actual Inter glyph use, not only computed font-family.
