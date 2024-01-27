
.. image:: https://readthedocs.org/projects/utlco_tcnc/badge/?version=latest
   :target: http://utlco_tcnc.readthedocs.io/en/latest/?badge=latest
   :alt: Documentation Status

====
TCNC
====

* Documentation: https://tcnc.readthedocs.io (possibly out of date)
* GitHub: https://github.com/utlco/utlco-tcnc
* Free software: LGPL v3 license

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
and the tool contact point. This is a property of flexible brushes.
This minimizes weird looking brush strokes
during relatively sharp changes in direction and produces a better looking
brush path.


Installing Tcnc
---------------

Note:
.....

TCNC requires Python 3.9 or greater.

I think Inkscape installs a version of python3 on
Windows if there is no default installation. Inkscape
documentation is vague on which python3 version it
installs and basically just says python3.6+ is required,
but that is already very old and 3.8 is getting stale,
so if you don't have a more recent vintage
I suggest installing a newer version.

The whole python version dependency mess is
really unfortunate and makes distributing plugins
kind of fraught. Mais c'est la vie...

1. `Download <https://github.com/utlco/tcnc/archive/master.zip>`_
   the latest version.

2. Unzip/extract the downloaded archive file (master.zip).

3. Copy or move the contents of the **tcnc/inkinx** folder
   to the user Inkscape extension folder.

4. Copy or move the entire **tcnc/tcnc** folder
   to the user Inkscape extension folder.

5. Restart Inkscape.

**Location of user Inkscape extension folder:**

* MacOS, Linux:

    `~/.config/inkscape/extensions`, where *~* is your home
    directory (i.e. /home/myname).

* Windows:

    `C:\\Users\\myname\\.Appdata\\Roaming\\inkscape\\extensions`

    This may or may not be correct. I don't know since I no longer use Windows...

Notes
-----

These extensions do not depend at all on the extension libraries supplied
with Inkscape. In fact, you can run these extensions as standalone
command line tools without having to install Inkscape at all.

Etc...
------
Tcnc is an ongoing project that is mainly designed for my own use
and some of the features may seem weirdly specific. Some of the code is in
a high state of flux due to rapid cycle experimentation.

