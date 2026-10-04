from rag.config import EmbeddingConfig
from rag.embeddings import EmbeddingClient, normalize_embeddings_url


def test_normalize_adds_v1_embeddings():
    assert normalize_embeddings_url("http://localhost:1234") == "http://localhost:1234/v1/embeddings"


def test_normalize_with_v1_suffix():
    assert (
        normalize_embeddings_url("http://localhost:1234/v1")
        == "http://localhost:1234/v1/embeddings"
    )


def test_normalize_already_embeddings():
    assert (
        normalize_embeddings_url("http://localhost:1234/v1/embeddings")
        == "http://localhost:1234/v1/embeddings"
    )


def test_normalize_strips_trailing_slash():
    assert (
        normalize_embeddings_url("http://localhost:1234/v1/")
        == "http://localhost:1234/v1/embeddings"
    )


def test_normalize_ollama_api_embeddings():
    assert (
        normalize_embeddings_url("http://localhost:11434", provider="ollama")
        == "http://localhost:11434/api/embeddings"
    )


def test_normalize_ollama_strips_v1_suffix():
    assert (
        normalize_embeddings_url("http://localhost:11434/v1", provider="ollama")
        == "http://localhost:11434/api/embeddings"
    )


def test_normalize_ollama_keeps_api_embed():
    assert (
        normalize_embeddings_url("http://localhost:11434/api/embed", provider="ollama")
        == "http://localhost:11434/api/embed"
    )


def test_client_uses_ollama_url():
    client = EmbeddingClient(
        EmbeddingConfig(
            provider="ollama",
            base_url="http://localhost:11434",
            model="nomic-embed-text:v1.5",
        )
    )
    assert client.url == "http://localhost:11434/api/embeddings"
    assert client.provider == "ollama"
