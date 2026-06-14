import os
import shutil
import pytest

# Playwright runs an async event loop in the background, which triggers
# Django's async safety checks when running synchronous tests. This allows
# synchronous operations inside the async context safely.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # Try to find a system-installed Google Chrome or Chromium to bypass Nix/NixOS shared library issues
    for browser_name in ["google-chrome-stable", "google-chrome", "chromium", "chrome"]:
        path = shutil.which(browser_name)
        if path:
            return {
                **browser_type_launch_args,
                "executable_path": path,
            }
    # Fallback to default Playwright behavior
    return browser_type_launch_args
