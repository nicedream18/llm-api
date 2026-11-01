from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from app.application.errors import ApplicationError
from app.application.services.platform_service import PlatformService
from app.infrastructure.database.migrations import execute_migration
from app.infrastructure.repositories.platform_repo import PlatformRepository
from app.types.platform import PromptTemplateInput


def test_prompt_cache_and_atomic_config_write(tmp_path):
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        execute_migration(db, Path("docs/migrations/015_platform_features.sql"))
    service = PlatformService(PlatformRepository(engine), tmp_path)
    prompt = service.create_prompt(PromptTemplateInput(name="welcome", template="Hello {{name}}"))
    assert service.render_prompt(prompt["id"], {"name": "Ada"})["content"] == "Hello Ada"
    with pytest.raises(ApplicationError, match="missing"):
        service.render_prompt(prompt["id"], {})
    service.cache_put("gpt", {"prompt": "hi"}, {"text": "hello"}, "key-scope", 300)
    assert service.cache_get("gpt", {"prompt": "hi"}, "key-scope") == {"text": "hello"}
    assert service.cache_get("other", {"prompt": "hi"}, "key-scope") is None
    result = service.write_config("codex", {"base_url": "http://localhost"})
    assert Path(result["path"]).read_text(encoding="utf-8").find("base_url") >= 0
    assert {"prompt_templates", "semantic_cache"} <= set(inspect(engine).get_table_names())


def test_config_target_rejects_path_traversal(tmp_path):
    service = PlatformService(type("Repo", (), {})(), tmp_path)
    with pytest.raises(ApplicationError):
        service.preview_config("../secret", {})
