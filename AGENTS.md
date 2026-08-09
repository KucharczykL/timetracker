# Agent guidance

## Windows parallel test runs

Keep the Makefile's default `PYTEST_WORKERS`; do not set it to `0` for normal
verification.

On Windows Codex desktop, run `make check` and test targets through a managed,
hidden process and wait for that process's final log and exit status. Foreground
capture can lose the Make -> uv -> pytest-xdist process tree. Serial mode is
only for CI, debugging, or an explicit request.
