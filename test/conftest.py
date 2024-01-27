
import pytest

import geom2d

@pytest.fixture(scope='module', autouse=True)
def _initialize():
    geom2d.set_epsilon(1e-7)


