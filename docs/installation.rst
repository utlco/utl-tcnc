===============
Installing TCNC
===============

Requirements
------------

TCNC requires Python 3.9 or greater.

Installation requires a terminal window and shell.


Installation steps
------------------

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


Inkscape user extension location
................................

Inkscape extensions are usually installed in a hidden location
under the user's home directory.

See **Edit->Preferences->System->User extensions**.

Usual locations:

* Linux, MacOS:

   `~/.config/inkscape/extensions`, where **~** is your home
   directory (i.e. `/home/username` or `/Users/UserName`).

* Windows (this may be out of date - I don't use Windows):

   `C:\\Users\\YourUserName\\.Appdata\\Roaming\\inkscape\\extensions`

