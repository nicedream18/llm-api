from types import SimpleNamespace

import pytest

from app.application.errors import ApplicationError
from app.application.services.kb_service import KbService
from app.types.models import UploadDocDTO


class Repo:
    def __init__(self, exists=True):
        self.exists = exists

    def find_kb_by_id(self, _kb_id):
        return object() if self.exists else None

    def find_doc_by_id(self, _doc_id):
        return SimpleNamespace(kb_id="kb-1")

    def find_source_by_id(self, _source_id):
        return {"id": "source-1", "kb_id": "kb-1"}

    def delete_doc_by_id(self, doc_id):
        self.deleted_doc = doc_id

    def delete_source(self, source_id):
        self.deleted_source = source_id


def service(repo):
    return KbService(repo, None, None, None)


def test_upload_rejects_missing_kb_and_path_traversal():
    with pytest.raises(ApplicationError, match="not found"):
        service(Repo(False)).upload_doc("missing", UploadDocDTO(filename="a.txt", content="hello"))
    with pytest.raises(ApplicationError, match="filename"):
        service(Repo()).upload_doc("kb", UploadDocDTO(filename="../secret.txt", content="hello"))


def test_upload_rejects_unsupported_type_before_persisting():
    with pytest.raises(ApplicationError, match="Unsupported"):
        service(Repo()).upload_doc("kb", UploadDocDTO(filename="archive.exe", content="hello", file_type="exe"))


def test_document_and_source_deletes_are_scoped_to_the_knowledge_base():
    repo = Repo()
    kb = service(repo)
    assert kb.delete_doc("other-kb", "doc-1") is False
    assert kb.delete_source("other-kb", "source-1") is False
    assert not hasattr(repo, "deleted_doc")
    assert not hasattr(repo, "deleted_source")

    assert kb.delete_doc("kb-1", "doc-1") is True
    assert kb.delete_source("kb-1", "source-1") is True
    assert repo.deleted_doc == "doc-1"
    assert repo.deleted_source == "source-1"


def test_source_import_rejects_missing_knowledge_base():
    with pytest.raises(ApplicationError, match="not found"):
        service(Repo(False)).create_source("missing", {"source_type": "url"})
