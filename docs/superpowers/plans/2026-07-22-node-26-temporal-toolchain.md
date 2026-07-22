# Node 26 Temporal Toolchain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Node 26 the development, CI, and Docker assets runtime so the native Temporal API is available for the forthcoming client date/time formatter.

**Architecture:** Pin the Nix development shell, GitHub Actions job, and Docker assets stage to Node 26. Node 26 no longer bundles Corepack, so Docker and CI install the `packageManager`-pinned pnpm version explicitly. Pass `--no-experimental-webstorage` to Vitest workers with its cross-platform `--execArgv` option, preventing Node 26's experimental global `localStorage` from shadowing jsdom's implementation.

**Tech Stack:** Nix, Node 26, pnpm 10.33.0, Vitest 4, jsdom, GitHub Actions, Docker.

## Global Constraints

- Use Node 26 as the project minimum; set the local Nix shell, CI, and Docker assets stage to Node 26.
- Keep pnpm at the version declared in `package.json`: `pnpm@10.33.0`.
- Do not add a Temporal polyfill or modify date/time formatting code in this PR.
- Preserve `pnpm install --frozen-lockfile --ignore-scripts` in CI and Docker.
- Run every project command through `direnv exec .`.

---

### Task 1: Make the Vitest runner safe under Node 26

**Files:**
- Modify: `package.json`
- Modify: `Makefile`

**Interfaces:**
- Consumes: Node 26's `--no-experimental-webstorage` CLI flag.
- Produces: `pnpm test:ts`, the sole Vitest entry point used by `make test-ts`.

- [x] **Step 1: Demonstrate the Node 26 failure with the current runner**

Run:

```bash
direnv exec . env PATH="$(nix-build '<nixpkgs>' -A nodejs_26 --no-out-link)/bin:$(nix-build '<nixpkgs>' -A pnpm_10 --no-out-link)/bin:$PATH" make test-ts
```

Expected: Vitest fails in jsdom theme tests because Node 26's experimental `localStorage` global shadows jsdom's storage implementation.

- [x] **Step 2: Pass the Node flag to Vitest workers**

Change `package.json` to declare the supported runtime and pass the Node flag to every Vitest worker:

```json
"engines": { "node": ">=26" },
"scripts": {
  "test:ts": "vitest run --execArgv=--no-experimental-webstorage"
}
```

Change `Makefile`'s `test-ts` recipe from `pnpm exec vitest run` to:

```make
	pnpm test:ts
```

- [x] **Step 3: Verify Node 26 executes the full TypeScript test suite**

Run:

```bash
direnv exec . env PATH="$(nix-build '<nixpkgs>' -A nodejs_26 --no-out-link)/bin:$(nix-build '<nixpkgs>' -A pnpm_10 --no-out-link)/bin:$PATH" make test-ts
```

Expected: Vitest reports all test files and tests passing.

- [x] **Step 4: Commit the test-runner change**

```bash
git add package.json Makefile
git commit -m "test: run Vitest without Node web storage"
```

### Task 2: Align local, CI, and Docker toolchains on Node 26

**Files:**
- Modify: `shell.nix`
- Modify: `.github/workflows/build-docker.yml`
- Modify: `Dockerfile`
- Modify: `CLAUDE.md`
- Modify: `scripts/bootstrap-cloud-env.sh`

**Interfaces:**
- Consumes: `package.json`'s `packageManager` value `pnpm@10.33.0`.
- Produces: Node 26 and pnpm 10.33.0 in each supported execution environment.

- [x] **Step 1: Select pinned Nix packages**

Replace the generic Nix packages in `shell.nix`:

```nix
nodejs
pnpm
```

with:

```nix
nodejs_26
pnpm_10
```

- [x] **Step 2: Update GitHub Actions provisioning**

In `.github/workflows/build-docker.yml`, set the setup-node input to `"26"`. Replace Corepack activation with explicit pnpm provisioning, matching `package.json`:

```yaml
run: npm install --global pnpm@10.33.0 && pnpm install --frozen-lockfile --ignore-scripts
```

- [x] **Step 3: Update the Docker assets stage**

In `Dockerfile`, change the assets image to `node:26-bookworm-slim`. Replace the Corepack comment and command with an explanation that Node 26 has no bundled Corepack and:

```dockerfile
RUN npm install --global pnpm@10.33.0 \
    && pnpm install --frozen-lockfile --ignore-scripts
```

- [x] **Step 4: Update the cloud bootstrap helper and contributor documentation**

Update `scripts/bootstrap-cloud-env.sh` to prefer `/opt/node26/bin`, require Node 26 before installing dependencies, and install the exact `pnpm@10.33.0` version into `$HOME/.local`. Update `CLAUDE.md` so its package-manager guidance says Node 26 does not bundle Corepack, Nix supplies `pnpm_10`, and Docker/CI/bootstrap explicitly install the version pinned by `package.json`. Replace the conda Corepack setup advice with installation of `pnpm@10.33.0`.

- [x] **Step 5: Verify the local shell's effective versions and full checks**

Run:

```bash
direnv allow .
direnv exec . node --version
direnv exec . pnpm --version
direnv exec . make check
```

Expected: Node prints a `v26.` version, pnpm prints `10.33.0`, and `make check` exits 0.

- [x] **Step 6: Verify the Docker assets stage**

Run:

```bash
docker build --target assets .
```

Expected: dependency installation, Tailwind build, and TypeScript compilation complete with exit code 0.

- [ ] **Step 7: Commit the toolchain migration**

```bash
git add shell.nix .github/workflows/build-docker.yml Dockerfile CLAUDE.md scripts/bootstrap-cloud-env.sh
git commit -m "chore: align toolchain on Node 26"
```

### Task 3: Final verification and pull request

**Files:**
- Verify: working tree and complete diff

**Interfaces:**
- Consumes: both migration commits.
- Produces: a reviewable branch and pull request for CI validation.

- [ ] **Step 1: Check whitespace and review the diff**

Run:

```bash
git diff main...HEAD --check
git diff --stat main...HEAD
git status --short
```

Expected: no whitespace diagnostics and no uncommitted tracked changes.

- [ ] **Step 2: Push the branch and create the pull request**

Run:

```bash
git push -u origin chore/node-26-temporal-toolchain
tea pulls create --title "chore: align toolchain on Node 26" --head "chore/node-26-temporal-toolchain" --base main
```

Expected: a pull request URL, with GitHub Actions triggered by the push.
