"""Shared test helpers.

All tests run offline: the API responses under tests/fixtures are captures of
real O'Reilly responses (public endpoints only, no cookies involved). Book
body text in the captures is replaced by placeholders.
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

# Make `import safaribooks` work when pytest is launched from anywhere.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def fixtures_dir() -> pathlib.Path:
    return FIXTURES


@pytest.fixture(scope="session")
def load_fixture():
    """Return a loader: text for anything, parsed object for *.json."""

    def _load(name: str):
        path = FIXTURES / name
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if path.suffix == ".json" else text

    return _load
