"""Configuration loading for the RAG toolkit."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_KNOWLEDGE_GLOBS: tuple[str, ...] = (
    "README.md",
    "readme.md",
    "docs/**/*.md",
    ".devdoc/**/*.md",
    "documentation/**/*.md",
)

DEFAULT_CODE_GLOBS: tuple[str, ...] = (
    "src/**/*.ts",
    "src/**/*.js",
    "src/**/*.py",
    "apps/**/*.ts",
    "apps/**/*.js",
    "apps/**/*.py",
)

DEFAULT_DOCUMENTATION_PREFIXES: tuple[str, ...] = (
    ".devdoc/",
    "docs/",
    "documentation/",
)

DEFAULT_IGNORE_DIRS: tuple[str, ...] = (
    "node_modules",
    "dist",
    "coverage",
    "build",
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".turbo",
    ".next",
    "qdrant_data",
)

DEFAULT_MCP_INSTRUCTIONS = (
    "You have access to a private RAG index for this workspace. "
    "ALWAYS call search_knowledge for architecture/docs questions and "
    "search_code for implementation questions before answering from memory. "
    "When an app filter is configured, pass app=<name> to narrow search_code. "
    "Cite returned file paths in your answer. "
    "If a tool returns a Qdrant lock error, tell the user to stop indexing "
    "or switch qdrant.mode to server."
)


@dataclass
class EmbeddingConfig:
    # openai → POST {base}/v1/embeddings ; ollama → POST {base}/api/embeddings
    provider: str = "openai"
    base_url: str = "http://localhost:1234/v1"
    api_key: str = "local"
    model: str = "text-embedding-nomic-embed-text-v1.5"
    document_prefix: str = ""
    query_prefix: str = ""
    timeout_ms: int = 60000
    batch_size: int = 32
    # Soft cap before calling the embedding API (chars). 0 disables.
    max_input_chars: int = 6000
    # Parallel HTTP embedding requests (useful for Ollama /api/embeddings)
    concurrency: int = 4


@dataclass
class QdrantConfig:
    mode: str = "local"  # local | memory | server
    local_path: str = "./qdrant_data"
    url: str = "http://localhost:6333"
    collection: str = "workspace_rag"
    # Retries when local storage is briefly locked (Cursor reconnect / overlapping start)
    connect_retries: int = 10
    connect_retry_delay_ms: int = 500


@dataclass(frozen=True)
class AppRule:
    """Map a repo-relative path prefix to an app label for search_code filtering."""

    prefix: str
    name: str


@dataclass
class McpConfig:
    name: str = "workspace-rag"
    instructions: str = DEFAULT_MCP_INSTRUCTIONS


@dataclass
class IndexConfig:
    repo_root: str = ".."
    sources: str = "all"  # knowledge | code | all
    chunk_size: int = 1200
    chunk_overlap: int = 150
    status_file: str = "./index_status.json"
    knowledge: list[str] = field(default_factory=lambda: list(DEFAULT_KNOWLEDGE_GLOBS))
    code: list[str] = field(default_factory=lambda: list(DEFAULT_CODE_GLOBS))
    apps: list[AppRule] = field(default_factory=list)
    documentation_prefixes: list[str] = field(
        default_factory=lambda: list(DEFAULT_DOCUMENTATION_PREFIXES)
    )
    ignore_dirs: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_DIRS))


@dataclass
class SearchConfig:
    top_k: int = 8
    score_threshold: float = 0.2


@dataclass
class Config:
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    mcp: McpConfig = field(default_factory=McpConfig)
    log_level: str = "INFO"

    @property
    def package_root(self) -> Path:
        return PACKAGE_ROOT

    @property
    def repo_root_path(self) -> Path:
        root = Path(self.index.repo_root)
        if not root.is_absolute():
            root = (PACKAGE_ROOT / root).resolve()
        return root

    @property
    def qdrant_local_path(self) -> Path:
        path = Path(self.qdrant.local_path)
        if not path.is_absolute():
            path = (PACKAGE_ROOT / path).resolve()
        return path

    @property
    def status_file_path(self) -> Path:
        path = Path(self.index.status_file)
        if not path.is_absolute():
            path = (PACKAGE_ROOT / path).resolve()
        return path

    @property
    def app_names(self) -> set[str]:
        return {rule.name.strip().lower() for rule in self.index.apps if rule.name}


def _merge_dataclass(cls: type, data: dict[str, Any] | None) -> Any:
    if not data:
        return cls()
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in valid})


def _merge_index_config(data: dict[str, Any] | None) -> IndexConfig:
    if not data:
        return IndexConfig()

    apps_raw = data.get("apps")
    apps: list[AppRule] = []
    if isinstance(apps_raw, list):
        for item in apps_raw:
            if not isinstance(item, dict):
                continue
            prefix = str(item.get("prefix", "")).strip()
            name = str(item.get("name", "")).strip()
            if prefix and name:
                # Normalize prefix to use forward slashes and trailing slash when folder-like
                prefix = prefix.replace("\\", "/")
                apps.append(AppRule(prefix=prefix, name=name))

    kwargs: dict[str, Any] = {}
    for key in (
        "repo_root",
        "sources",
        "chunk_size",
        "chunk_overlap",
        "status_file",
    ):
        if key in data:
            kwargs[key] = data[key]

    for list_key in ("knowledge", "code", "documentation_prefixes", "ignore_dirs"):
        if list_key in data and data[list_key] is not None:
            kwargs[list_key] = [str(x) for x in data[list_key]]

    if "apps" in data:
        kwargs["apps"] = apps

    return IndexConfig(**kwargs)


def _merge_mcp_config(data: dict[str, Any] | None) -> McpConfig:
    if not data:
        return McpConfig()
    defaults = McpConfig()
    name = str(data.get("name", defaults.name)).strip() or defaults.name
    instructions = data.get("instructions")
    if instructions is None:
        instructions = DEFAULT_MCP_INSTRUCTIONS
    else:
        instructions = str(instructions).strip() or DEFAULT_MCP_INSTRUCTIONS
    return McpConfig(name=name, instructions=instructions)


def _overlay_env(config: Config) -> Config:
    """Apply RAG_* environment overrides."""
    env_map = {
        "RAG_EMBEDDING_PROVIDER": ("embedding", "provider", str),
        "RAG_EMBEDDING_BASE_URL": ("embedding", "base_url", str),
        "RAG_EMBEDDING_API_KEY": ("embedding", "api_key", str),
        "RAG_EMBEDDING_MODEL": ("embedding", "model", str),
        "RAG_EMBEDDING_DOCUMENT_PREFIX": ("embedding", "document_prefix", str),
        "RAG_EMBEDDING_QUERY_PREFIX": ("embedding", "query_prefix", str),
        "RAG_EMBEDDING_TIMEOUT_MS": ("embedding", "timeout_ms", int),
        "RAG_EMBEDDING_BATCH_SIZE": ("embedding", "batch_size", int),
        "RAG_EMBEDDING_MAX_INPUT_CHARS": ("embedding", "max_input_chars", int),
        "RAG_EMBEDDING_CONCURRENCY": ("embedding", "concurrency", int),
        "RAG_QDRANT_MODE": ("qdrant", "mode", str),
        "RAG_QDRANT_LOCAL_PATH": ("qdrant", "local_path", str),
        "RAG_QDRANT_URL": ("qdrant", "url", str),
        "RAG_QDRANT_COLLECTION": ("qdrant", "collection", str),
        "RAG_QDRANT_CONNECT_RETRIES": ("qdrant", "connect_retries", int),
        "RAG_QDRANT_CONNECT_RETRY_DELAY_MS": ("qdrant", "connect_retry_delay_ms", int),
        "RAG_INDEX_REPO_ROOT": ("index", "repo_root", str),
        "RAG_INDEX_SOURCES": ("index", "sources", str),
        "RAG_INDEX_CHUNK_SIZE": ("index", "chunk_size", int),
        "RAG_INDEX_CHUNK_OVERLAP": ("index", "chunk_overlap", int),
        "RAG_INDEX_STATUS_FILE": ("index", "status_file", str),
        "RAG_SEARCH_TOP_K": ("search", "top_k", int),
        "RAG_SEARCH_SCORE_THRESHOLD": ("search", "score_threshold", float),
        "RAG_MCP_NAME": ("mcp", "name", str),
        "RAG_LOG_LEVEL": ("log_level", None, str),
    }

    for env_key, (section, field_name, cast) in env_map.items():
        raw = os.environ.get(env_key)
        if raw is None:
            continue
        value = cast(raw)
        if field_name is None:
            setattr(config, section, value)
        else:
            setattr(getattr(config, section), field_name, value)
    return config


def load_config(path: str | Path | None = None) -> Config:
    """Load config from YAML, then overlay RAG_* env vars."""
    config_path = Path(path) if path else Path(os.environ.get("RAG_CONFIG", "config.yaml"))
    if not config_path.is_absolute():
        config_path = (PACKAGE_ROOT / config_path).resolve()

    data: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

    config = Config(
        embedding=_merge_dataclass(EmbeddingConfig, data.get("embedding")),
        qdrant=_merge_dataclass(QdrantConfig, data.get("qdrant")),
        index=_merge_index_config(data.get("index")),
        search=_merge_dataclass(SearchConfig, data.get("search")),
        mcp=_merge_mcp_config(data.get("mcp")),
        log_level=str(data.get("log_level", "INFO")),
    )
    return _overlay_env(config)
