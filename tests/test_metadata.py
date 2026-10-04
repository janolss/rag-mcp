from rag.config import AppRule, IndexConfig
from rag.indexer.metadata import metadata_from_path


def _index() -> IndexConfig:
    return IndexConfig(
        documentation_prefixes=[".devdoc/", "docs/", "documentation/"],
        apps=[
            AppRule(prefix="apps/web/", name="web"),
            AppRule(prefix="apps/taskscheduler/", name="taskscheduler"),
        ],
    )


def test_devdoc_is_global_documentation():
    meta = metadata_from_path(".devdoc/architecture/multi-tenancy.md", _index())
    assert meta["type"] == "documentation"
    assert meta["app"] == "global"
    assert meta["language"] == "markdown"


def test_readme_is_global_documentation():
    meta = metadata_from_path("readme.md", _index())
    assert meta["type"] == "documentation"
    assert meta["app"] == "global"


def test_web_service_is_code():
    meta = metadata_from_path("apps/web/services/BookingService.ts", _index())
    assert meta == {
        "type": "code",
        "app": "web",
        "language": "typescript",
        "file": "apps/web/services/BookingService.ts",
    }


def test_web_test_is_test():
    meta = metadata_from_path("apps/web/tests/services/BookingService.test.js", _index())
    assert meta["type"] == "test"
    assert meta["app"] == "web"
    assert meta["language"] == "javascript"


def test_taskscheduler_source_is_code():
    meta = metadata_from_path("apps/taskscheduler/src/jobs/foo.ts", _index())
    assert meta["type"] == "code"
    assert meta["app"] == "taskscheduler"


def test_taskscheduler_test_is_test():
    meta = metadata_from_path("apps/taskscheduler/tests/tenant-runtime.test.ts", _index())
    assert meta["type"] == "test"
    assert meta["app"] == "taskscheduler"


def test_unmatched_code_is_global():
    meta = metadata_from_path("src/utils/helpers.py", _index())
    assert meta["type"] == "code"
    assert meta["app"] == "global"
    assert meta["language"] == "python"
