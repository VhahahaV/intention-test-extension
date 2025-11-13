# Workflow Guide (Plus)

This document explains the repository structure and the automation we added with GitHub Actions, including how to enable, run, customize, and troubleshoot the workflows.

> Tip: This complements the quick guide in `README_AutoWork.md` with deeper detail and examples.

---

## 1) Repository Structure Overview

```
.
├─ .devcontainer/           # Dev Containers settings for containerized dev
├─ .github/workflows/       # GitHub Actions workflow files (CI, CodeQL, VSIX)
├─ .vscode/                 # Editor settings (optional)
├─ backend/                 # Python backend (HTTP server, generation, core)
│  ├─ app/server.py         # HTTP server entry (Threaded)
│  ├─ server.py             # Backwards-compatible wrapper
│  ├─ main.py               # Generation entry (connects to ModelQuerySession)
│  ├─ core/                 # Session/messages/registry abstractions
│  ├─ requirements.txt      # Python dependencies (torch/transformers included)
│  └─ ...
├─ docker/                  # (Optional) extra docker helpers
├─ docs/                    # Documents (e.g., UI optimization)
├─ resources/               # Icons/fonts for extension
├─ setup/                   # Helper scripts for environment setup
├─ src/                     # VS Code extension TypeScript sources
│  ├─ extension.ts          # Activation, commands, orchestration
│  ├─ client.ts             # HTTP streaming client to backend
│  ├─ sidebarView.ts        # Webview provider
│  └─ ...
├─ web/                     # Webview static assets (HTML/CSS/JS)
├─ Dockerfile               # Backend container image
├─ package.json             # VS Code extension manifest + scripts
├─ tsconfig.json            # TS config
├─ README.md                # How to run locally / with Docker
├─ README_AutoWork.md       # Minimal automation overview
└─ README_Workflow_Plus.md  # This document
```

Key runtime paths:
- Extension connects to backend via HTTP (default `localhost:8080`). Port is configured by `intentionTest.port` in VS Code settings (see `package.json:configuration`).
- Backend reads `backend/config.ini` (`[openai] apikey/url`, `[tools] codeql`). In Docker, the image writes this automatically from env vars; locally you edit it.

---

## 2) What GitHub Actions Workflows We Added

All workflows live under `.github/workflows/`. They run automatically on `push`/`pull_request` to the `main` branch (and other triggers as noted), and can also be manually triggered via `workflow_dispatch`.

### 2.1 Node CI — Lint, Compile, Test
- File: `.github/workflows/ci.yml`
- Triggers: `push`/`pull_request` → `main`, and manual `workflow_dispatch`.
- Concurrency: `ci-${{ github.ref }}` with `cancel-in-progress: true` to avoid duplicate runs on the same branch.
- Permissions: read-only for code checkout.
- Steps:
  1) Checkout the repo.
  2) Setup Node.js 20 with npm cache.
  3) `npm install`.
  4) Conditionally run `npm run lint`, `npm run compile`, `npm test` if present.
  5) If an `out/` folder exists, upload it as an artifact named `out-${sha}` for debugging.
- Purpose: quickly catch TypeScript/ESLint/test regressions in the extension code.

### 2.2 Python CI — Syntax Compile Check
- File: `.github/workflows/python-ci.yml`
- Triggers: `push`/`pull_request` → `main`, manual `workflow_dispatch`.
- Concurrency: `python-ci-${{ github.ref }}`.
- Steps:
  1) Checkout the repo.
  2) Setup Python 3.10.
  3) `python -m compileall -q backend` to catch syntax errors quickly.
- Why no heavy deps: We intentionally skip installing `torch/transformers` to keep CI fast/stable. You can enable full installs later (see Section 4.1).

### 2.3 CodeQL — Security Scanning
- File: `.github/workflows/codeql.yml`
- Triggers: `push`/`pull_request` → `main`, weekly cron, manual `workflow_dispatch`.
- Concurrency: `codeql-${{ github.ref }}-${{ matrix.language }}`.
- Language matrix: `javascript-typescript`, `python`.
- Steps: `init` → `autobuild` → `analyze`. Results are uploaded to the repository’s “Code scanning alerts”.
- Purpose: detect common security issues in frontend (TS/JS) and backend (Python) code.

### 2.4 VSIX — Package & Optional Publish
- File: `.github/workflows/vsix.yml`
- Triggers: pushing tags `v*` (e.g., `v0.2.3`) and manual `workflow_dispatch`.
- Concurrency: `vsix-${{ github.ref }}`.
- Steps:
  1) Checkout, setup Node 20, install deps.
  2) `npm run compile` (if present).
  3) `npx @vscode/vsce package` to build a `.vsix` file.
  4) Read `package.json` to extract `name` and `version`; upload artifact as `vsix-<name>-<version>`.
  5) If secrets and metadata are in place, publish:
     - Stable: `vsce publish` for tags like `v0.2.3`.
     - Pre-release: `vsce publish --pre-release` for tags containing `rc|beta|pre` (e.g., `v0.3.0-rc.1`).
- Requirements for publish:
  - Add a `publisher` field to `package.json` (your Marketplace publisher name).
  - Configure a secret `VSCE_PAT` in GitHub (Azure DevOps PAT with Marketplace Manage/Publish scopes).
- Without these, the workflow still packages the VSIX and uploads it as an artifact (no publish).

---

## 3) How To Use These Workflows

### 3.1 Automatic Triggers
- Open a PR to `main` or push to `main` → Node CI, Python CI, CodeQL run automatically.
- Push a tag starting with `v` (e.g., `v0.2.3`) → VSIX packaging and optional publish.

### 3.2 Manual Triggers
- Go to GitHub → Actions → select a workflow → “Run workflow”. Useful to re-run CI quickly or test VSIX packaging without waiting for a tag.

### 3.3 Configure Secrets (for publish)
- Repository Settings → Secrets and variables → Actions → New repository secret:
  - `VSCE_PAT` (optional): Azure DevOps Personal Access Token for Marketplace publication.
- Add `publisher` to `package.json`:
  ```json
  {
    "publisher": "your-publisher-id"
  }
  ```
- After this, tagging will attempt to publish to the Marketplace automatically.

### 3.4 Reading Results
- Node/Python CI: Check the Actions run logs; download `out-<sha>` if present to inspect compiled output.
- CodeQL: Go to Security → Code scanning alerts; view results by language.
- VSIX: From the run page, download the `vsix-<name>-<version>` artifact. If published, check the Marketplace listing.

---

## 4) Customization & Extensions

### 4.1 Enable Full Python Checks (Optional)
Add installation and lint/test in `python-ci.yml`:
```yaml
    - name: Install backend dependencies
      run: pip install -r backend/requirements.txt

    - name: Lint (ruff)
      run: pip install ruff && ruff backend

    - name: Tests (pytest)
      run: pip install pytest && pytest -q
```
Add a `pyproject.toml` for Ruff/pytest configuration if needed.

### 4.2 Add a Backend Smoke Test (Optional)
- Start a lightweight backend mode (with mocked OpenAI URL) and call `/junitVersion` or `/session` endpoints to validate HTTP flow.
- Avoid hitting real OpenAI in PRs; reserve real calls for main/scheduled workflows.

### 4.3 Docker Workflow Blueprint (Not Yet Implemented)
When you’re ready to build/push images on tags:
```yaml
name: Docker
on:
  push:
    tags: [ 'v*' ]
  workflow_dispatch:

jobs:
  build-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write   # required for GHCR
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=raw,value=latest
      - uses: docker/build-push-action@v6
        with:
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```
Switch registry and credentials as needed (Docker Hub vs GHCR).

### 4.4 VSIX Release Notes (Optional)
- Generate a changelog per tag and attach it to a GitHub Release.
- Upload the built `.vsix` as a release asset.

---

## 5) Troubleshooting

- Node CI fails on `lint`/`compile`:
  - Check `tsconfig.json`, `eslint` versions, and ensure `npm install` finished without network errors.
- Python CI fails on `compileall`:
  - Fix Python syntax errors in `backend/`.
  - If you enable full dependency install and it fails, consider caching or pinning versions.
- CodeQL steps fail:
  - Ensure workflows have `security-events: write` permission (already set in the job).
  - Try re-running with `workflow_dispatch` to avoid queue spikes.
- VSIX publish skipped:
  - Add `publisher` to `package.json` and set `VSCE_PAT` secret.
  - For prereleases, include `rc`/`beta`/`pre` in the tag name (e.g., `v0.3.0-rc.1`).

---

## 6) What’s Not Done Yet

- Full Python lint/tests and heavy dependency setup are intentionally omitted by default to keep CI fast. See 4.1 to enable.
- Docker build/push workflows are not added yet; a blueprint is provided (4.3).
- E2E tests (e.g., cloning `perwendel/spark`) are not wired to CI by default; consider adding them on `main` or a nightly schedule.

---

## 7) Quick Reference (Paths)
- Node CI: `.github/workflows/ci.yml`
- Python CI: `.github/workflows/python-ci.yml`
- CodeQL: `.github/workflows/codeql.yml`
- VSIX: `.github/workflows/vsix.yml`
- Frontend: `src/`, `web/`
- Backend: `backend/`
- Docs: `README_AutoWork.md`, `README_Workflow_Plus.md`

If you want me to enable Docker workflow or add Python Ruff/pytest by default, say the word and I’ll wire them up.
