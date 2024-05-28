====
TCNC
====

* Documentation: https://utlco.github.io/utl-tcnc/
* Repository: https://github.com/utlco/utl-tcnc
* Free software: LGPL v3 license

**Note:** This is a re-write/re-factor of the original `tcnc` package which
hasn't been maintained for several years. It has been updated to
use Python 3.9+ and the geometry package has been split out into
its own repository (https://github.com/utlco/utl-geom2d).

TCNC is an Inkscape (version 1.2+) extension that generates
G-code suitable for a
3.5 axis CNC machine controlled by LinuxCNC v2.4+.
The rotational axis (A) is assumed to rotate about
the Z axis and is kept tangent to movement along the X and Y axes.

It is currently used to produce output for a painting apparatus based on
a modified Fletcher 6100 CNC mat cutter controlled by LinuxCNC. A stepper
controlled Z axis was added. The original pneumatic tool pusher was left on
and is triggered by **spindle_on**. This allows for fast brush lifts along
with very fine Z axis control.
I haven't tested this with anything else so YMMV.

TCNC uses biarc approximation to convert Bezier curves
into circular arc segments.
This produces smaller G code files and is very accurate.


Install
-------

See: https://utlco.github.io/utl-tcnc/index.html#installing-tcnc


Notes
-----

This extension does not depend at all on the extension libraries supplied
with Inkscape. In fact, you can run this extension as a standalone
command line tool without having to install Inkscape at all. It will
work on most SVG files.

TCNC is an ongoing project that is mainly designed for my own use
and some of the features may seem weirdly specific or not relevant
to most people's needs.

