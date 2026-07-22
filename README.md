# Timetracker

A simple game catalogue and play session tracker.

# Development

The project uses `uv` to manage Python versions and dependencies.
Simply run:

```
make init
```

This installs the correct Python version, syncs all dependencies, and installs npm packages.
Afterwards, you can start the development server using `make dev` or `make server`
(without the Tailwind watcher). Both targets accept `DEV_HOST` and `DEV_PORT`, for
example `make dev DEV_HOST=0.0.0.0 DEV_PORT=9999`.
