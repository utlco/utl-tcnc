
import pathlib

from tcnc import tcnc

import conftest

FILE_T1000 = 'files/t1000.svg'

LOG_FILE = './tmp/tcnc.log'

ARGS = [
    '--a-feed-match=false',
    '--a-feed=360.00',
    '--a-offset=0.00',
    '--active-tab=output',
    '--append-suffix=false',
    '--biarc-max-depth=4',
    '--biarc-tolerance=0.0010',
    '--blend-tolerance=0.0000',
    '--brush-landing=0.0000',
    '--brush-takeoff=0.0000',
    '--brush-reload-angle=0',
    '--brush-reload-dwell=0.0',
    '--brush-reload-enable=false',
    '--brush-reload-max-paths=1',
    '--brush-reload-rotate=false',
    '--brush-soft-landing=false',
    '--create-debug-layer=true',
    '--enable-tangent=true',
    '--gcode-target=linuxcnc',
    '--gcode-units=doc',
    '--id=path2751',
    '--line-flatness=0.0010',
    '--min-arc-radius=0.0010',
    '--path-close-overlap=0.0000',
    '--path-close-polygons=false',
    '--path-preserve-g1=false',
    '--path-smooth-fillet=false',
    '--path-smooth-radius=0.0000',
    '--path-split-cusps=false',
    '--path-tool-fillet=true',
    '--path-tool-offset=true',
    '--preview-scale=small',
    '--preview-toolmarks-outline=true',
    '--preview-toolmarks=true',
    '--separate-layers=false',
    '--spindle-clockwise=true',
    '--spindle-mode=path',
    '--spindle-speed=0',
    '--spindle-wait-on=0.0000',
    '--tolerance=0.00010',
    '--tool-trail-offset=0.3000',
    '--tool-width=1.0000',
    '--write-settings=true',
    '--x-subpath-layer=subpaths_tcnc',
    '--x-subpath-offset=0.0000',
    '--x-subpath-render=false',
    '--x-subpath-smoothness=0.50',
    '--xy-feed=400.00',
    '--z-depth=-0.2500',
    '--z-feed=400.00',
    '--z-safe=1.0000',
    '--z-step=-0.2500',
]


def test_t1000():
    """Verify no errors with test input SVG."""
    tcnc.Tcnc().run(argv=ARGS + conftest.BASE_ARGS + [FILE_T1000], output=conftest.SVG_FILE)


