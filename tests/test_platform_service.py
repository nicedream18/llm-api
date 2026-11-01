from pathlib import Path

import pytest

from app.application.services.platform_service import PlatformService


class Repo:
    def list_prompts(self):
        return []


def test_client_config_lifecycle_is_atomic_and_validates_target(tmp_path: Path):
    service = PlatformService(Repo(), tmp_path)

    assert service.list_configs() == []
    written = service.write_config("codex", {"base_url": "http://localhost"})
    assert Path(written["path"]).read_text(encoding="utf-8").find("base_url") >= 0
    assert service.list_configs()[0]["target"] == "codex"
    assert service.delete_config("codex") is True
    assert service.delete_config("codex") is False

    with pytest.raises(Exception, match="Invalid configuration target"):
        service.delete_config("../secrets")
