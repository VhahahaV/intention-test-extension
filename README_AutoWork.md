# README_AutoWork

This document describes the minimal automation workflows added to this repo and how to use/extend them.

## Overview
- Node CI: `.github/workflows/ci.yml`
  - Triggers: `push`/`pull_request` to `main`，以及手动 `workflow_dispatch`。
  - Concurrency: 防抖分组 `ci-${{ github.ref }}`，自动取消同分支上旧运行。
  - Steps: checkout → Node 20 → `npm install` → `npm run lint|compile|test`（存在才跑）→ 如有 `out/` 则上传为 `out-${sha}` artifact。
  - Purpose: 快速反馈 TS 编译/ESLint/单测结果，保留编译产物便于定位问题。

- Python CI: `.github/workflows/python-ci.yml`
  - Triggers: `push`/`pull_request` to `main`，以及手动 `workflow_dispatch`。
  - Concurrency: 防抖分组 `python-ci-${{ github.ref }}`。
  - Steps: checkout → Python 3.10 → `python -m compileall backend`。
  - Notes: 先不装沉重依赖（torch/transformers），保证稳定和速度；后续可按需开启 `pip install -r`、Ruff/pytest。

- CodeQL: `.github/workflows/codeql.yml`
  - Triggers: `push`/`pull_request` to `main`、每周定时与手动 `workflow_dispatch`。
  - Matrix: `javascript-typescript`, `python`。
  - Concurrency: `codeql-${{ github.ref }}-${{ matrix.language }}`，避免同分支重复分析。
  - Steps: checkout → CodeQL init → autobuild → analyze（自动上传 SARIF 到 Code scanning）。

- VSIX Package & Publish: `.github/workflows/vsix.yml`
  - Trigger: `push` tags `v*` 与手动 `workflow_dispatch`。
  - Concurrency: `vsix-${{ github.ref }}`。
  - Steps: checkout → Node 20 → install → compile → `vsce package` → 读取 `package.json` 的 `name/version` → 以 `vsix-<name>-<version>` 命名上传 artifact。
  - Optional publish: 若配置 `VSCE_PAT` 且 `package.json` 有 `publisher`，则 `vsce publish`；标签名含 `rc|beta|pre` 时用 `--pre-release`。

## Required secrets (GitHub → Settings → Secrets and variables → Actions)
- `VSCE_PAT` (optional): Azure DevOps PAT with Marketplace Manage/Publish scopes, for `vsce publish`.
  - Also ensure `package.json` includes a valid `publisher` (Marketplace publisher name), for example:
    ```json
    {
      "publisher": "your-publisher"
    }
    ```
  - Without `publisher`, the workflow will only package and upload the VSIX artifact (no publish).

## Branches & triggers
- `ci.yml`（Node）与 `python-ci.yml`：`push`/`pull_request` 到 `main`，并支持手动 `workflow_dispatch`。
- `codeql.yml`：`push`/`pull_request` 到 `main`、每周定时、手动 `workflow_dispatch`。
- `vsix.yml`：tags `v*` 或手动 `workflow_dispatch`。
  - Stable publish: tags like `v0.2.3`.
  - Pre-release publish: tags containing `rc`, `beta`, or `pre` (e.g. `v0.3.0-rc.1`) use `--pre-release`.

## Local verification
- Node CI: on your machine run `npm install`, `npm run lint`, `npm run compile`, `npm test`.
- Python CI: run `python -m compileall -q backend`.
- VSIX: `npx @vscode/vsce package` (requires `publisher` in `package.json` for publish; not required for package).

## Extending the workflows (recommended next)
- Python tests: add `pytest`, `ruff` and a `pyproject.toml`, then install deps in CI and run `pytest`/`ruff`.
- Backend smoke test: run a stub backend or add a mock OpenAI URL to test HTTP endpoints without hitting real APIs.
- E2E (optional on main/schedule): clone `perwendel/spark` and run a minimal generation flow; cache Maven/CodeQL assets.
- Add Docker workflow: build and push images on tag (SemVer tags) and `edge`+`sha-<7>` on `main`.

## Notes
- The repository currently lacks `publisher` in `package.json`. Publishing to Marketplace requires adding it.
- Heavy Python deps (torch/transformers) are omitted by default to keep CI fast and stable.
- CodeQL autobuild is safe for JS/TS/Python; no compilation is required.
