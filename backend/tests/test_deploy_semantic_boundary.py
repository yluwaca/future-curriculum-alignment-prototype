import pytest

from app.services import semantic_vector_service as module


def test_missing_offline_embedding_model_is_explicitly_unavailable(monkeypatch):
    module._SENTENCE_TRANSFORMER_MODEL = None

    def unavailable(_name):
        raise OSError("model is not bundled")

    monkeypatch.setattr(module, "SentenceTransformerCls", unavailable)
    with pytest.raises(module.PgvectorNotReadyError, match="not installed"):
        module.compute_embedding("data engineering")
