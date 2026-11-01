import pytest
from pydantic import ValidationError

from app.types.models import KbAskRequestDTO, KbSearchRequestDTO


def test_knowledge_request_contracts_bound_retrieval_parameters():
    assert KbSearchRequestDTO(query="q", top_k=100, search_mode="vector").top_k == 100
    assert KbAskRequestDTO(question="q", max_rounds=10).max_rounds == 10

    with pytest.raises(ValidationError):
        KbSearchRequestDTO(query="q", top_k=0)
    with pytest.raises(ValidationError):
        KbSearchRequestDTO(query="q", search_mode="unknown")
    with pytest.raises(ValidationError):
        KbAskRequestDTO(question="q", vector_weight=1.1)
