
import pathlib
import pytest

import geom2d

# Location of tests
TEST_DIR = pathlib.Path(__file__).parent

# Location of test input SVG files
FILES_DIR = TEST_DIR / 'files'

# Location of test output
TMP_DIR = TEST_DIR / 'tmp'

LOG_FILE = TMP_DIR / 'tcnc.log'
NGC_FILE = TMP_DIR / 'output.ngc'
SVG_FILE = TMP_DIR / 'output.svg'

BASE_ARGS = [
    '--log-create=true',
    f'--log-filename=${LOG_FILE}',
    '--log-level=DEBUG',
    f'--output-path=${NGC_FILE}',
]


@pytest.fixture(scope='module', autouse=True)
def _initialize():
    geom2d.set_epsilon(1e-7)


