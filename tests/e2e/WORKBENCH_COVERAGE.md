# Current workbench browser gate

`npm run test:e2e:work` covers the active IDE, PDF, persistent composer and global
Library on desktop Chromium, touch WebKit tablet and mobile Chromium. It no
longer navigates to a removed “Работа” button. The old suite is retained unchanged
under `npm run test:e2e:work:legacy`; it is historical evidence, not a passing gate.

| Contract previously exercised in Work | Current evidence |
| --- | --- |
| Cold Work/Library chunks; navigation remains usable | `ide-studio.spec.js`, `workbench-library.spec.js` |
| Library pagination, failed page, explicit keyboard retry and native download | `workbench-library.spec.js` |
| Upload/copy destination, shared Library ownership and unknown copy ACK | `ide-studio.spec.js`, `pdf-studio.spec.js` |
| Explicit activation on first Work visit | Superseded by approved automatic IDE/PDF preparation; slow/failure/expiry/one-intent tests in both studio suites |
| Ready editor layout, dirty navigation, save conflicts, late lease and draft recovery | `ide-studio.spec.js`, `pdf-studio.spec.js`; editor, lease and navigation unit suites |
| File create/edit/move and isolated clone | `ide-studio.spec.js` |
| Sidebar/input geometry, breakpoints, narrow viewport and reflow | Studio suites and `composer.spec.js` |
| One build status and checks; no premature success | `pdf-studio.spec.js` |
| Preview read failure and explicit retry | `pdf-delivery.spec.js` |
| Publication read failure/deadline; no repeated POST; local draft survives | `pdf-delivery.spec.js` |
| Guarded Library vendor-kit installation | `pdf-delivery.spec.js` |
| Model/persona/mode keyboard, touch help, focus, drafts and accessibility | `composer.spec.js` |
| Passive agent details, immediate Escape/reopen and exact focus return | `workbench-help.spec.js` |
| Cancelled/unknown upload, retained selection and same-intent explicit retry | `library-upload.spec.js` |
| Changed-file conflict and explicit reselection with a fresh intent | `library-upload.spec.js` |
| Short/narrow Library feedback does not cover download/copy or their keyboard focus | `library-upload.spec.js` |

The shared `helpers/pdfApi.js` owns the unchanged PDF API/WS fixture used by the
studio and delivery tests. It intercepts all API/agent traffic; no pass here proves
real inference, billing, authenticated persistence, Docker isolation or Git push.

This is not a claim of one-for-one replacement of every historical assertion.
The old Work issue-board creation/refresh drafts no longer have a visible owner
in the approved IDE surface; their hook/component unit tests remain. Historical
Library-only outcomes supersede the legacy upload-and-workspace partial outcome;
the latter's hook/component unit coverage remains. Cancellation, retained selection,
same-intent retry, changed-file reselection and notification/action clearance now
also run against the current global Library. Drawer close/reopen is the current
equivalent of the retired source-panel replacement. The clearance test requires
an 8px gap in any nonoverlapping direction and real click/focus reachability rather
than hard-coding the old Work page's above-card placement. The old assertions stay
intact; this does not certify every historical partial-workspace outcome. Native/live
suites stay opt-in. No broad skipped suite or green native claim replaces them.
