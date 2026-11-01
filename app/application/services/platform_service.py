"""Prompt templates, semantic cache and safe client configuration service."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.application.errors import ApplicationError


class PlatformService:
    def __init__(self, repository, config_dir=None):
        self.repo = repository
        self.config_dir = Path(config_dir or (Path.cwd() / "data" / "client-config"))

    def _decode(self, row):
        if row is None:
            return None
        result = dict(row)
        for key in ("request", "response"):
            if key in result and isinstance(result[key], str):
                try:
                    result[key] = json.loads(result[key])
                except (TypeError, ValueError, json.JSONDecodeError):
                    result[key] = {}
        return result

    def list_prompts(self):
        return self.repo.list_prompts()

    def create_prompt(self, dto):
        return self.repo.create_prompt(dto.model_dump())

    def update_prompt(self, prompt_id, dto):
        return self.repo.update_prompt(prompt_id, dto.model_dump(exclude_unset=True))

    def delete_prompt(self, prompt_id):
        return self.repo.delete_prompt(prompt_id)

    def render_prompt(self, prompt_id, variables):
        row = self.repo.get_prompt(prompt_id)
        if not row or not row.get("enabled"):
            raise ApplicationError("Prompt template is unavailable", 404, "not_found")
        rendered = str(row["template"])
        for name, value in variables.items():
            rendered = rendered.replace("{{" + name + "}}", str(value))
        if "{{" in rendered:
            raise ApplicationError("Prompt variable is missing", 422, "missing_prompt_variable")
        return {"id": prompt_id, "version": row["version"], "content": rendered}

    @staticmethod
    def cache_key(model, request, scope):
        payload = json.dumps({"model": model, "scope": scope, "request": request}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def cache_get(self, model, request, scope):
        row = self.repo.get_cache(self.cache_key(model, request, scope))
        if not row:
            return None
        try:
            if datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
                return None
        except (TypeError, ValueError):
            return None
        return self._decode(row).get("response")

    def cache_put(self, model, request, response, scope, ttl_seconds):
        return self.repo.put_cache({
            "cache_key": self.cache_key(model, request, scope), "model": model, "scope": scope,
            "request": json.dumps(request, ensure_ascii=False), "response": json.dumps(response, ensure_ascii=False),
            "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat(),
        })

    def clear_cache(self):
        return self.repo.clear_cache()

    def preview_config(self, target, values):
        self._validate_target(target)
        return {"target": target, "path": str(self.config_dir / f"{target}.json"), "values": values}

    def write_config(self, target, values):
        self._validate_target(target)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        target_path = self.config_dir / f"{target}.json"
        fd, temp_name = tempfile.mkstemp(prefix=f".{target}-", suffix=".tmp", dir=self.config_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(values, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return {"target": target, "path": str(target_path)}

    @staticmethod
    def _validate_target(target):
        if not target or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in target):
            raise ApplicationError("Invalid configuration target", 422, "invalid_target")
