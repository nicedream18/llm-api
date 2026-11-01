import pytest

from app.application.errors import ApplicationError
from app.application.services.kb_service import KbService
from app.types.models import UploadDocDTO


class Repo:
    def __init__(self, exists=True):
        self.exists = exists

    def find_kb_by_id(self, _kb_id):
        return object() if self.exists else None


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
