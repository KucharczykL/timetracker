"""Container-build invariants."""

from pathlib import Path

from django.conf import settings


def test_codegen_uses_the_locked_python_environment():
    dockerfile = (Path(settings.BASE_DIR) / "Dockerfile").read_text()

    assert "RUN uv run --frozen python manage.py gen_element_types" in dockerfile


def test_windows_lan_detection_uses_the_default_route():
    makefile = (Path(settings.BASE_DIR) / "Makefile").read_text()

    assert "Find-NetRoute -RemoteIPAddress 1.1.1.1" in makefile
