"""LLM Provider abstraction layer.

Supports multiple LLM backends:
- NVIDIA NIM API (default, existing)
- Amazon Bedrock (Claude via Converse API, for hackathon)

Usage:
    from services.llm_providers import get_llm_provider, get_embedding_provider

    provider = get_llm_provider()  # Returns provider based on settings.llm_provider
"""

from config import get_settings
from services.llm_providers.base import BaseEmbeddingProvider, BaseLLMProvider


def get_llm_provider() -> BaseLLMProvider:
    """Factory: return the configured LLM provider."""
    settings = get_settings()
    provider_name = getattr(settings, "llm_provider", "nvidia")

    if provider_name == "bedrock":
        from services.llm_providers.bedrock import BedrockLLMProvider

        return BedrockLLMProvider()
    else:
        from services.llm_providers.nvidia import NvidiaLLMProvider

        return NvidiaLLMProvider()


def get_embedding_provider() -> BaseEmbeddingProvider:
    """Factory: return the configured embedding provider.

    Note: For the hackathon, we keep NVIDIA embeddings even when using Bedrock for LLM.
    This avoids re-indexing existing Neo4j vector data (dimension mismatch: NVIDIA=2048, Titan=1024).
    """
    settings = get_settings()
    embedding_provider = getattr(settings, "embedding_provider", "nvidia")

    if embedding_provider == "bedrock":
        from services.llm_providers.bedrock import BedrockEmbeddingProvider

        return BedrockEmbeddingProvider()
    else:
        from services.llm_providers.nvidia import NvidiaEmbeddingProvider

        return NvidiaEmbeddingProvider()


__all__ = [
    "BaseLLMProvider",
    "BaseEmbeddingProvider",
    "get_llm_provider",
    "get_embedding_provider",
]
