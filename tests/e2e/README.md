Playwright E2E tests

Quick start:

- Install dependencies (from repo root):

  npm ci --prefix frontend

- Install Playwright browsers:

  npm --prefix frontend run e2e:install

- Run against a freshly built standalone frontend:

  npm --prefix frontend run build
  npm --prefix frontend run e2e:run

- Run against an already started dev stack:

  E2E_BASE_URL=http://localhost:3001 npm --prefix frontend run e2e:run

Notes:
- Without `E2E_BASE_URL`, Playwright starts an isolated SPA server. It does not reuse an arbitrary process on port 3000.
- Set `E2E_PORT=3012` if port 3000 is occupied; this changes both the server and test base URL.
- Use `workflow_dispatch` GH Action to run these on-demand in CI (there is a sample workflow under `.github/workflows/playwright-smoke.yml`).
