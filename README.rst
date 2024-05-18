
====
TCNC
====

* Documentation: https://tcnc.readthedocs.io (out of date)
* GitHub: https://github.com/utlco/utl-tcnc
* Free software: LGPL v3 license

**Note:** This is a re-write/re-factor of the original `tcnc` package which
hasn't been maintained for several years. It has been updated to
use Python 3.9+ and is fully typed. Some bugs have been fixed and
some new bugs have surely been introduced.

Tcnc is an Inkscape (version 1.2+) extension that generates
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

Tcnc uses biarc approximation to convert Bezier curves
into circular arc segments.
This produces smaller G code files and is very accurate.

Some G-code interpreters support a cubic Bezier spline command (G5)
that could follow Bezier curves directly, but it becomes difficult
(or impossible) to then maintain control over the tangency of the
rotational axis.


Machine-specific Behavior
-------------------------

You can specify a tool width in Tcnc to compensate for tool trail.
Tool trail is the distance between the center of rotation around the Z axis
and the tool contact point, and is a trait of flexible brushes and
drag knives.
Tool trail compensation mitigates trailing tool travel artifacts
(i.e. weird looking brush strokes)
during relatively sharp changes in direction and produces a better looking
and predictable tool path.

.. image:: docs/_images/example1.svg
   :width: 500
   :alt: Example drawing

Installing Tcnc
---------------

TCNC requires a system Python version 3.9 or greater.

The installer works on Linux, possibly MacOS,
but definitely not on Windows (yet).

Currently, installing utl-tcnc requires installing utl-inkext first
which provides an installer for Inkscape extensions.

I haven't had the time to publish to PyPI so this requires installing
directly from the GitHub repository.


Create a virtualenv and activate
++++++++++++++++++++++++++++++++

.. code-block::

    python -m venv venv
    . venv/bin/activate

Install utl-inkext package
++++++++++++++++++++++++++

.. code-block::

    pip install https://github.com/utlco/utl-inkext/archive/refs/heads/main.zip

This will also install a python program called **inkstall** which can be used to
install other UTLCo Inkscape extensions (such as TCNC).

Install utl-tcnc extension into Inkscape using **inkstall**.

.. code-block::

    inkstall https://github.com/utlco/utl-tcnc/archive/refs/heads/main.zip

Then restart inkscape and the extension should show up under the menu Extensions->UTLCo->Tcnc...


Usual location of user Inkscape extensions:

* MacOS, Linux:

    `~/.config/inkscape/extensions`

* Windows:

    `C:\\Users\\myname\\.Appdata\\Roaming\\inkscape\\extensions`

    This may or may not be correct. I don't know since I no longer use Windows...


Notes
-----

This extension does not depend at all on the extension libraries supplied
with Inkscape. In fact, you can run this extension as a standalone
command line tool without having to install Inkscape at all. It will
work on most SVG files.

If you only want to run utl-tcnc as a command line tool then just install the
**utl-tcnc** package::

    pip install https://github.com/utlco/utl-tcnc/archive/refs/heads/main.zip

To run::

    tcnc --help


Etc...
------

Tcnc is an ongoing project that is mainly designed for my own use
and some of the features may seem weirdly specific or not relevant
to most people's needs.

