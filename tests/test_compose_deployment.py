"""External PostgreSQL deployment contracts."""

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).parents[1]
DATABASE_URL_FILE = (
    "${TIMETRACKER_DATABASE_URL_FILE:?set TIMETRACKER_DATABASE_URL_FILE}"
)


@pytest.mark.parametrize(
    "filename", ["docker-compose.yml", "docker-compose.no-caddy.yml"]
)
def test_compose_uses_only_an_external_database_secret(filename):
    compose = yaml.safe_load((REPO / filename).read_text())

    assert set(compose["services"]) == {"timetracker"}
    service = compose["services"]["timetracker"]
    assert (
        "DATABASE_URL__FILE=/run/secrets/timetracker_database_url"
        in service["environment"]
    )
    assert service["secrets"] == [
        {
            "source": "timetracker_database_url",
            "target": "timetracker_database_url",
            "mode": 0o400,
        }
    ]
    assert compose["secrets"]["timetracker_database_url"] == {"file": DATABASE_URL_FILE}
    assert "postgres" not in compose["services"]
    assert "postgres" not in compose.get("volumes", {})
