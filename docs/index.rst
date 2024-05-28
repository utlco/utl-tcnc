
====
TCNC
====

.. toctree::
   :name: toptoc
   :hidden:
   :maxdepth: 3

   usage_tcnc

* Documentation: https://utlco.github.io/utl-tcnc/
* Repository: https://github.com/utlco/utl-tcnc
* Free software: LGPL v3 license


Introduction
------------
TCNC is an Inkscape extension that generates G-code targeted for a four (or 3.5)
axis CNC machine controlled by LinuxCNC v2.4+. The fourth axis (A) is angular
and is assumed to rotate about a vertical Z axis. The tool path is calculated
so that the A axis is kept tangent to movement along the X and Y axis. This is
designed to move a tangential tool
such as a brush, scraper, or knife centered along the path.

TCNC will calculate tool paths to compensate for a trailing tool offset (such as
a flexible brush whose contact with the surface trails behind the Z axis
center) and can also perform automatic filleting to compensate for distortions
caused by tool width. See :ref:`trail-offset` and :ref:`tool-width`.

Bezier curves are converted to circular arcs using a biarc approximation method.
Compared to using line segment approximation this results in much smaller G
code files (by orders of magnitude) and faster machine operation. Accuracy is
very good.

TCNC is currently used to produce G code for a painting apparatus based on a
modified Fletcher 6100 CNC mat cutter controlled by LinuxCNC. A stepper
controlled Z axis was added. The original pneumatic tool pusher was left on and
is triggered by **spindle_on**. This allows for fast brush lifts along with
very fine Z axis control. I haven't tested this with anything else so YMMV.

TCNC does not perform tool path buffering to compensate for kerf created by
cutting tools such as router bits, lasers, plasma cutters, or water jets. If
kerf is not an issue or the user is willing to manually compensate for it by
adjusting the input paths then this might work just fine for these applications.

**TCNC** is an ongoing project that is mainly designed for my personal use and
some of the features may seem weirdly specific.

There is absolutely no warranty for any purpose whatsoever. Use at your own risk.


Installing TCNC
---------------

Requirements
............

TCNC requires Python 3.9 or greater.

Installation requires a terminal window and shell.


Installation steps
..................

These shell commands should work on Linux and MacOS.
For Windows/WSL/Cygwin YMMV.

1. Create a temporary working directory and virtualenv::

    mkdir tcnc
    cd tcnc
    python -m venv venv
    . venv/bin/activate

2. Install the Inkscape extension installer::

    pip install https://github.com/utlco/utl-inkext/archive/refs/heads/main.zip

3. Install TCNC using the **inkstall** command::

    inkstall https://github.com/utlco/utl-tcnc/archive/refs/heads/main.zip

4. Restart Inkscape and verify the extension is installed:
   **Extensions->UTLCo->TCNC...**

At this point you can remove the temporary working directory or use it
to install other UTLCo extensions.


Related Source Code
...................

https://github.com/utlco/utl-inkext

https://github.com/utlco/utl-geom2d

