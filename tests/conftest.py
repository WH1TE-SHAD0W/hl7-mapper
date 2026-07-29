from pathlib import Path

import pytest

from sickcert.parser import parse_file
from sickcert.store import Dataset

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample_oru_r01.xml"


@pytest.fixture
def sample_path() -> Path:
    return SAMPLE


@pytest.fixture
def sample_rows():
    return parse_file(SAMPLE)


@pytest.fixture
def dataset(sample_rows) -> Dataset:
    data = Dataset()
    data.extend(sample_rows)
    return data
