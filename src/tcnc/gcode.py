"""A G-code generator.

Suitable for a four axis (or 3.5 axis)
machine with X, Y, and Z axes along with an angular A
axis that rotates about the Z axis.

The generated G code is currently intended for a LinuxCNC
interpreter, but probably works fine for others as well.

====
"""

# ruff: noqa: PLR0904 PLR0912 PLR0913 PLR0917

from __future__ import annotations

import datetime
import gettext
import io
import logging
import math
from collections.abc import Iterable
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    import geom2d
    from typing_extensions import TypeAlias

_ = gettext.gettext

# Target-specific G codes
_TARGETS: dict[str, dict] = {
    'default': {
        'description': 'LinuxCNC 2.4+',
        'set_units_in': 'G20',
        'set_units_mm': 'G21',
        'reset_axis_offsets': 'G92.1',
        'spindle_on_cw': 'M3',
        'spindle_on_ccw': 'M4',
    },
    'linuxcnc': {},
    'rubens6k': {
        'description': 'Valiani CMC - Rubens 6K v1.3',
        'set_units_in': 'G70',
        'set_units_mm': 'G71',
        'reset_axis_offsets': 'G50',
        'disabled_axes': [
            'Z',
        ],
    },
}


TCoord: TypeAlias = tuple[float, float, float, float]


class GCodeError(Exception):
    """Exception raised by gcode generator."""


class PreviewPlotter:
    """GCode preview plotter interface.

    Base interface that can be implemented by users of the GCode
    class to provide a graphical preview of the G-code output.

    See :py:mod:`cam.gcodesvg` for an example of an SVG implementation.
    """

    # Set by GCodeGenerator.
    gc: GCodeGenerator | None = None

    def plot_move(self, endp: TCoord) -> None:
        """Plot G00 - rapid move from current tool location to to ``endp``.

        Args:
            endp: Endpoint of move as a 4-tuple (x, y, z, a).
        """

    def plot_feed(self, endp: TCoord) -> None:
        """Plot G01 - linear feed from current tool location to ``endp``.

        Args:
            endp: Endpoint of feed as a 4-tuple (x, y, z, a).
        """

    def plot_arc(
        self,
        center: geom2d.TPoint,
        endp: TCoord,
        clockwise: bool,
    ) -> None:
        """Plot G02/G03 - arc feed from current tool location to to ``endp``.

        Args:
            center: Center of arc as  a 2-tuple (x, y)
            endp: Endpoint of feed as a 4-tuple (x, y, z, a).
            clockwise: True if the arc moves in a clockwise direction.
        """

    def plot_tool_down(self) -> None:
        """Plot the beginning of a tool path."""

    def plot_tool_up(self) -> None:
        """Plot the end of a tool path."""


class GCodeGenerator:
    """GCode generator class.

    Describes a basic two axis (XY), three axis (XYZ),
    or four axis (XYZA) machine.
    The G code output is compatible with LinuxCNC.

    Angles are always specified in radians but output as degrees.

    Axis values are always specified in user/world coordinates and output
    as machine units (ie inches or millimeters) using ``GCode.unit_scale``
    as the scaling factor.
    """

    # Order in which G code parameters are specified in a line of G code
    _GCODE_ORDERED_PARAMS = 'XYZUVWABCIJKRDHLPQSF'
    # Non-modal G codes (LinuxCNC.)
    _GCODE_NONMODAL_GROUP = ('G04', 'G10', 'G28', 'G30', 'G53', 'G92')
    # G codes where a feed rate is required
    _GCODE_FEED = ('G01', 'G02', 'G03')
    # G codes that change the position of the tool
    _GCODE_MOTION = ('G00', 'G01', 'G02', 'G03')
    # G codes that are suppressed if the parameters remain unchanged
    _GCODE_MODAL_MOTION = ('G00', 'G01', 'G02', 'G03')
    # Default tolerance for floating point comparison
    _DEFAULT_TOLERANCE = 1e-8
    # Default tolerance for floating point comparison of angle values
    _DEFAULT_ANGLE_TOLERANCE = 1e-8
    # Default output precision
    _DEFAULT_PRECISION = 6
    # Default angular feed rate (deg/m)
    _DEFAULT_AFEED = 360

    _disabled_axes: set
    # Target machine.
    target: str
    # Feed rate along X and Y axes
    xyfeed: float
    # Z axis feed rate
    zfeed: float | None = None
    # Z axis safe height for rapid moves
    zsafe: float | None = None
    # Angular axis feed rate
    afeed: float | None = None
    # Current line number
    line_number: float = 0
    # The G code output stream
    output: TextIO
    # The current preview plotter
    preview_plotter: PreviewPlotter | None = None
    # User to machine unit scale
    unit_scale: float = 1.0
    # Tolerance for float comparisons
    tolerance: float = _DEFAULT_TOLERANCE
    # Tolerance for angle comparisons
    angle_tolerance: float = _DEFAULT_ANGLE_TOLERANCE
    # Number of digits precision for output
    precision: float = _DEFAULT_PRECISION
    # Delay time in millis for tool-down
    tool_wait_down: float = 0.0
    # Delay time in millis for tool-up
    tool_wait_up: float = 0.0
    # Alternate G code for Tool Up
    alt_tool_up: str | None = None
    # Alternate G code for Tool Down
    alt_tool_down: str | None = None
    # Default delay time in milliseconds after spindle is turned on.
    spindle_wait_on: float = 0.0
    # Default delay time in milliseconds after spindle is shut off.
    spindle_wait_off: float = 0.0
    # Spindle direction flag
    spindle_clockwise: bool = True
    # Default spindle speed
    spindle_speed: float = 0.0
    # Turn spindle on/off automatically on tool_up/tool_down
    spindle_auto: bool = False
    # Angles < 360 ?
    wrap_angles: bool = False
    # Show comments if True
    show_comments: bool = True
    # Show line numbers if True
    show_line_numbers: bool = False
    # Extra header comments
    header_comments: list[str | list[str]]
    # Blend mode. Can be None, 'blend', or 'exact'.
    # See <http://linuxcnc.org/docs/2.4/html/common_User_Concepts.html#r1_1_1>
    blend_mode: str | None = None
    # Blend tolerance. P value for G64 blend directive.
    blend_tolerance: float | None = None
    # Naive cam detector tolerance value. Q value for G64 blend directive.
    blend_qtolerance: float | None = None
    # Output code comments
    verbose: bool = False
    # GCode output units
    gc_unit: str = 'in'
    # precision = int(round(abs(math.log(self._DEFAULT_TOLERANCE, 10))))
    # set_output_precision(self.precision)
    # Axis scale factors
    axis_scale: dict[str, float]
    # Axis offsets
    axis_offset: dict[str, float]
    # Map canonical axis names to G code output names.
    # Values can be changed to accommodate machines that expect
    # different axis names (ie. using C instead of A or UVW instead of XYZ)
    axis_map: dict[str, str]
    # Last value for G code parameters
    # {'X': 0.0, 'Y': 0.0, 'Z': 0.0, 'A': 0.0, 'F': 0.0}
    _last_val: dict[str, float | None]
    # True if the tool is above the Z axis safe height for rapid moves
    _is_tool_up: bool = False
    # Flag set when the axis angle has been normalized
    _axis_offset_reset: float = False

    def __init__(
        self,
        xyfeed: float,
        zsafe: float | None = None,
        zfeed: float | None = None,
        afeed: float | None = None,
        output: TextIO | None = None,
        plotter: PreviewPlotter | None = None,
        target: str = 'linuxcnc',
    ) -> None:
        """GCodeGenerator constructor.

        Args:
            xyfeed: Default feed rate along X and Y axes,
                in machine units per minute.
            zsafe: The safe height of the Z axis for rapid XY moves.
            zfeed: Feed rate along Z axis
                in machine units per minute.
                (Defaults to the value of `xyfeed`.)
            afeed: Feed rate along A axis in degrees per minute.
            output: Output stream for generated G code.
                Must implement ``write()`` method.
                Defaults to a StringIO if None (default).
            plotter: Preview plotter. Should be a subclass of
                ``gcode.PreviewPlotter``.
            target: Target machine. Default is 'LinuxCNC'.
        """
        self.target = target.lower()
        self.xyfeed = xyfeed
        self.zsafe = zsafe
        self.zfeed = zfeed
        self.afeed = afeed
        self.output = output if output else io.StringIO()
        self.preview_plotter = plotter
        self.header_comments = []
        self.axis_scale = {}
        self.axis_offset = {}
        self.axis_map = {}
        self._disabled_axes = set()
        self._last_val = {param: None for param in self._GCODE_ORDERED_PARAMS}
        if self.preview_plotter:
            self.preview_plotter.gc = self

    @property
    def units(self) -> str:
        """GCode output units. Can be 'in' or 'mm'."""
        return self.gc_unit

    @units.setter
    def units(self, value: str) -> None:
        if value not in {'in', 'mm'}:
            raise ValueError('Units must be "in" or "mm".')
        self.gc_unit = value

    @property
    def X(self) -> float | None:  # noqa: N802 # pylint: disable=invalid-name
        """The current X axis value or none if unknown."""
        return self._last_val['X']

    @property
    def Y(self) -> float | None:  # noqa: N802 # pylint: disable=invalid-name
        """The current Y axis value or none if unknown."""
        return self._last_val['Y']

    @property
    def Z(self) -> float | None:  # noqa: N802 # pylint: disable=invalid-name
        """The current Z axis value or none if unknown."""
        return self._last_val['Z']

    @property
    def A(self) -> float | None:  # noqa: N802 # pylint: disable=invalid-name
        """The current A axis value or none if unknown."""
        return self._last_val['A']

    def disable_axis(self, axis: str) -> None:
        """Disable the specified axis and suppress output for that axis."""
        self._disabled_axes.add(axis.upper())

    def enable_axis(self, axis: str) -> None:
        """Disable the specified axis and suppress output for that axis."""
        self._disabled_axes.remove(axis.upper())

    def machine_attr(self, name: str, default: str | None = None) -> str | None:
        """Get the machine attribute or machine-specific G code."""
        if default is None:
            default = _TARGETS['default'].get(name)
        attr: str | None = _TARGETS.get(self.target, _TARGETS['default']).get(
            name, default
        )
        return attr

    def set_tolerance(
        self, tolerance: float, angle_tolerance: float | None = None
    ) -> None:
        """Set tolerance (epsilon) for floating point comparisons.

        Args:
            tolerance: The tolerance for scalar floating point comparisons
                except angular values.
            angle_tolerance: The tolerance for comparing angle values. Set to
                ``tolerance`` if None (default).
        """
        self.tolerance = tolerance
        if angle_tolerance is None:
            angle_tolerance = tolerance
        self.angle_tolerance = angle_tolerance

    def set_output_precision(self, precision: float) -> None:
        """Set numeric output precision.

        This determines the number of digits after the decimal point.

        This can be different from the precision implied
        by the `tolerance` value. The default is derived
        from the `tolerance` value.

        Args:
            precision: The number of digits after the decimal point.
        """
        self.precision = precision

    def fmt_float(self, x: float) -> str:
        """Format a float value to match current output precision."""
        return f'{x:.{self.precision + 1}g}'

    def set_units(self, units: str, unit_scale: float = 1.0) -> None:
        """Set G code units and unit scale factor.

        Note:
            Linear axis values are specified in user/world coordinates
            and output as machine units (ie inches or millimeters)
            using ``unit_scale`` as the scaling factor to scale from
            user/world units to G-code units.

        Args:
            units: Unit specifier. Must be `'in'` or `'mm'`.
            unit_scale: Scale factor to apply to linear axis values.
                Default is 1.0.
        """
        if units not in {'in', 'mm'}:
            raise ValueError(_('Units must be mm or in.'))
        self.units = units
        self.unit_scale = unit_scale

    def set_spindle_defaults(
        self,
        speed: float,
        clockwise: bool = True,
        wait_on: int = 0,
        wait_off: int = 0,
        auto: bool = False,
    ) -> None:
        """Set spindle parameter defaults.

        Args:
            speed: Spindle speed in RPM
            clockwise: Spindle direction. True if clockwise (default).
            wait_on: Number of milliseconds to wait for the spindle to reach
                full speed.
            wait_off: the number of milliseconds to wait for the spindle
                to stop.
            auto: Turn on/off spindle automatically on
                :py:meth:`tool_up()`/:py:meth:`tool_down()`.
                Default is False.
        """
        self.spindle_speed = speed
        self.spindle_clockwise = clockwise
        self.spindle_wait_on = wait_on
        self.spindle_wait_off = wait_off
        self.spindle_auto = auto

    def set_path_blending(
        self,
        mode: str,
        tolerance: float | None = None,
        qtolerance: float | None = None,
    ) -> None:
        """Set path trajectory blending mode and optional tolerance.

        Args:
            mode: Path blending mode. Can be 'exact' or 'blend'.
                Uses *G64* in 'blend' mode and *G61* in 'exact' mode.
            tolerance: Blending tolerance. Only used in 'blend' mode.
                This is the value for the G64 *P* parameter.
                Default is None.
            qtolerance: Naive cam detector tolerance value.
                This is the value for the G64 *Q* parameter.
                Default is None.
        """
        if mode.upper() == 'G61':
            mode = 'exact'
        elif mode.upper() == 'G64':
            mode = 'blend'
        if mode in {'exact', 'blend'}:
            self.blend_mode = mode
            self.blend_tolerance = tolerance
            self.blend_qtolerance = qtolerance
        # ignore anything else...

    def set_axis_offset(self, **kwargs: float) -> None:
        """Set the offset for the specified axes.

        Axis offsets are always specified in *machine units*.
        Angular offsets are always in *degrees*.

        This is a 'soft' offset, not a G92 offset. The offset
        value will be added to the current axis value when
        a move is performed.

        Example::

            gcode_gen = gcode.GCodeGenerator(...)
            gcode_gen.set_axis_offset(x=10, y=10)

        Args:
            kwargs: One or more axis offset values:
                * x: X axis offset value (optional)
                * y: Y axis offset value (optional)
                * z: Z axis offset value (optional)
                * a: A axis offset value (optional)
        """
        for axis, offset in kwargs.items():
            self.axis_offset[axis.upper()] = float(offset)

    def set_axis_scale(self, **kwargs: float) -> None:
        """Set the scaling factors for the specified axes.

        The scaling is applied before the world/machine unit scaling.

        Example::

            gcode_gen = gcode.GCodeGenerator(...)
            gcode_gen.set_axis_scale(x=10, y=10)

        Args:
            kwargs: One or more axis offset values:
                * x: X axis offset value (optional)
                * y: Y axis offset value (optional)
                * z: Z axis offset value (optional)
                * a: A axis offset value (optional)
        """
        for axis, scale in kwargs.items():
            self.axis_scale[str(axis).upper()] = float(scale)

    def map_axis(self, canonical_name: str, output_name: str) -> None:
        """Map canonical axis names to G code output names.

        Mapping can be used to accommodate machines that expect
        different axis names (ie. using C instead of A or UVW instead of XYZ).

        Args:
            canonical_name: Canonical axis name.
                (ie 'X', 'Y', 'Z', or 'A')
            output_name: Output name.
                (ie 'U', 'V', 'W', or 'C')
        """
        self.axis_map[canonical_name.upper()] = output_name.upper()

    def add_header_comment(self, comment: str | list[str]) -> None:
        """Append a comment to the header section.

        Args:
            comment: A comment or list of comments.
        """
        self.header_comments.append(comment)

    def comment(self, comment: Iterable[str] | str | None = None) -> None:
        """Write a G code comment line.

        Outputs a newline if the comment string is None (default).

        Args:
            comment: A comment string or an iterable of comment strings.
                In the case of multiple comments, each one will be
                on a separate line.
        """
        if self.show_comments:
            if isinstance(comment, str):
                self._write_line(comment=comment)
            elif isinstance(comment, Iterable):
                for comment_line in comment:
                    self._write_line(comment=comment_line)
            else:
                self._write('\n')

    def header(self, comment: str | None = None) -> None:
        """Output a pretty standard G code file header.

        Args:
            comment: A header comment or a list of comments (optional).
        """
        self._write('%\n')
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        today = now.astimezone().isoformat(' ')
        self.comment(f'Creation date: {today}')
        self.comment(f'Target machine: {self.machine_attr("description")}')
        self.comment(f'Output precision: {self.fmt_float(self.precision)}')
        self.comment(f'Units: {self.gc_unit}')
        self.comment(f'Unit scale: {self.fmt_float(self.unit_scale)}')
        if comment is not None:
            self.comment()
            self.comment(comment)
        if self.header_comments:
            self.comment()
            for hdr_comment in self.header_comments:
                self.comment(hdr_comment)
        self.comment()
        self._write_line('G17', _('Circular interpolation: XY plane'))
        if self.units == 'mm':
            gcode = self.machine_attr('set_units_mm')
            self._write_line(gcode, comment=_('Units are in millimeters'))
        else:
            gcode = self.machine_attr('set_units_in')
            self._write_line(gcode, comment=_('Units are in inches'))

        self._write_line('G90', _('Use absolute positioning'))
        if self.target == 'linuxcnc':
            self._write_line(
                'G40', comment=_('Cancel tool diameter compensation')
            )
            self._write_line(
                'G49', comment=_('Cancel tool length compensation')
            )
            if self.blend_mode == 'blend':
                if self.blend_tolerance is None:
                    self._write_line(
                        'G64', comment=_('Blend with highest speed')
                    )
                else:
                    p_value = self.fmt_float(self.blend_tolerance)
                    if self.blend_qtolerance is not None:
                        q_value = self.fmt_float(self.blend_qtolerance)
                        self._write_line(
                            f'G64 P{p_value} Q{q_value}',
                            comment=_('Blend with tolerances'),
                        )
                    else:
                        self._write_line(
                            f'G64 P{p_value}', comment=_('Blend with tolerance')
                        )
            elif self.blend_mode == 'exact':
                self._write_line('G61', comment=_('Exact path mode'))
        self.comment()
        self.comment(_('Default feed rate'))
        self.feed_rate(self.xyfeed)
        self.comment()

    def footer(self) -> None:
        """Output a generic G code file footer."""
        self._write('\n')
        if self._axis_offset_reset:
            gcode = self.machine_attr('reset_axis_offsets')
            if gcode:
                self.gcode_command(gcode, comment='Reset axis offsets to zero')
        self._write_line('M2', _('End program.'))
        self._write('%\n')

    def feed_rate(self, feed_rate: float) -> None:
        """Set the specified feed rate.

        Outputs the *F* G code directive if the feed rate
        has changed since the last feed value.

        Args:
            feed_rate: The feed rate in machine units per minute.
        """
        if self._last_val['F'] is None or not self.float_eq(
            feed_rate, self._last_val['F']
        ):
            self._write_line(f'F{self.fmt_float(feed_rate)}')
            self._last_val['F'] = feed_rate

    def pause(self, conditional: bool = False, comment: str = 'Pause') -> None:
        """Pause the G code interpreter.

        Outputs *M1* or *M0* G code.

        Note:
            Normally, pressing the start button in LinuxCNC/Axis
            will restart the interpreter after a pause.

        Args:
            conditional: use conditional stop if True.
            comment: Optional comment string.
        """
        mcode = 'M1' if conditional else 'M0'
        self.gcode_command(mcode, comment=comment)

    def dwell(self, seconds: float, comment: str | None = None) -> None:
        """Output a dwell command.

        Pauses the tool for the specified number of milliseconds.

        Args:
            seconds: Number of seconds to pause.
            comment: Optional comment string.
        """
        if seconds > 0:
            if comment is None:
                comment = f'Pause tool for {seconds:.3f} seconds'
            self._write_line(f'G04 P{seconds:.3f}', comment=comment)

    def tool_up(
        self,
        rapid: bool = True,
        wait: float | None = None,
        zsafe: float | None = None,
        comment: str | None = None,
    ) -> None:
        """Moves tool to a safe Z axis height.

        This should be called before performing a rapid move.

        The spindle will also be automatically shut off
        if ``Gcode.spindle_auto`` is True.

        Args:
            rapid: Use G0 to move Z axis, otherwise G1 at current feed rate.
                Default is True.
            wait: the number of milliseconds to wait for the tool to retract.
                Uses GCode.tool_wait_up value by default if None specified.
                This parameter is mainly useful for pneumatically
                controlled up/down axes where the actuator may take
                a few milliseconds to extend/retract.
            zsafe: The Z axis safe height. The default will be used if
                not specified.
            comment: Optional comment string.
        """
        if zsafe is None:
            zsafe = self.zsafe
        # Note: self._is_tool_up is purposely not checked here to insure
        # that the tool is forced to a safe height regardless of internal state
        if self.alt_tool_up:
            self.gcode_command(self.alt_tool_up)
        elif zsafe is not None:
            cmd = 'G00' if rapid else 'G01'
            self.gcode_command(cmd, Z=zsafe, force_value='Z', comment=comment)
        else:
            # This machine apparently has no Z axis, so bail
            raise GCodeError(
                'Z safe height not specified, cannot bring tool up'
            )
        if self.spindle_auto:
            self.spindle_off()
        if wait is None:
            wait = self.tool_wait_up
        if wait > 0:
            self.dwell(wait)
        self._is_tool_up = True
        if self.preview_plotter:
            self.preview_plotter.plot_tool_up()

    def tool_down(
        self,
        z: float,
        feed: float | None = None,
        wait: float | None = None,
        comment: str | None = None,
    ) -> None:
        """Moves tool on Z axis down to specified height.

        Outputs a *G1* move command using the current feed rate for the Z axis.

        The spindle will be automatically turned on first
        if ``Gcode.spindle_auto`` is True.

        Args:
            z: Height of Z axis to move to.
            feed: Feed rate (optional - default Z axis feed rate used if None.)
            wait: the number of milliseconds to wait for the tool to
                actually get to the specified depth.
                Uses `GCode.tool_wait_down` value by default if None specified.
                This parameter is mainly useful for pneumatically
                controlled up/down axes where the actuator may take
                a few milliseconds to extend/retract.
            comment: Optional comment string.
        """
        if feed is None:
            feed = self.zfeed
        if wait is None:
            wait = self.tool_wait_down
        if self.spindle_auto:
            self.spindle_on()
        if self.alt_tool_down is not None:
            self.gcode_command(self.alt_tool_down)
        else:
            self.gcode_command('G01', Z=z, F=feed, comment=comment)
        self._is_tool_up = False
        if wait > 0:
            self.dwell(wait)

        if self.preview_plotter:
            self.preview_plotter.plot_tool_down()

    def spindle_on(
        self,
        speed: float | None = None,
        clockwise: bool | None = None,
        wait: float | None = None,
        comment: str | None = None,
    ) -> None:
        """Turn on the spindle.

        Args:
            speed: Spindle speed in RPM.
                If None use default speed.
            clockwise: Spindle turns clockwise if True.
                If None use default value.
                This is probably machine dependant.
            wait: Number of milliseconds to wait for the spindle to reach
                full speed. Uses ``GCode.spindle_wait_on`` value by default.
            comment: Optional comment string.
        """
        if speed is None:
            speed = self.spindle_speed
        if clockwise is None:
            clockwise = self.spindle_clockwise
        if wait is None:
            wait = self.spindle_wait_on
        if comment is None:
            comment = 'Set spindle speed/direction'
        if self.target == 'linuxcnc':
            mcode = 'M3' if clockwise else 'M4'
            self._write_line(f'{mcode} S{int(speed)}', comment=comment)
        elif self.target == 'rubens6k':
            if speed > 0 and not clockwise:
                # bug in pylint
                # pylint: disable=invalid-unary-operand-type
                speed = -speed
                # pylint: enable=invalid-unary-operand-type
            self._write_line('S{speed:.2f}', comment=comment)
        if wait and wait > 0:
            self.dwell(wait)

    def spindle_off(
        self, wait: float | None = None, comment: str | None = None
    ) -> None:
        """Turn off the spindle.

        Args:
            wait: the number of milliseconds to wait for the spindle
                to stop. Uses ``GCode.spindle_wait_off`` value by default.
            comment: Optional comment string.
        """
        if self.target == 'linuxcnc':
            self._write_line('M5', comment=comment)
        elif self.target == 'rubens6k':
            self._write_line('S0', comment=comment)
        if wait is None:
            wait = self.spindle_wait_off
        elif wait > 0:
            self.dwell(wait)

    def normalize_axis_angle(self, axis: str = 'A') -> None:
        """Unwrap (normalize) a rotational axis.

        If the current angular position of the axis is > 360 this will
        reset the rotary axis origin so that 0 < angle < 360.

        Useful when cutting large spirals with a tangent knife to minimize
        long unwinding moves between paths.

        Args:
            axis: Name of axis to unwrap. Default is 'A'.
        """
        axis = axis.upper()
        if axis not in 'ABC':
            raise GCodeError(_('Can only normalize a rotational axis.'))
        angle = self._last_val[axis]
        if angle and abs(angle) > 2 * math.pi:
            # normalize the angle
            angle = angle - 2 * math.pi * math.floor(angle / 2 * math.pi)
            val = self.fmt_float(math.degrees(angle))
            self._write_line(
                f'G92 {axis}={val}', comment=_('Normalize axis angle')
            )
            self._last_val[axis] = angle
            self._axis_offset_reset = True

    def rapid_move(
        self,
        x: float,
        y: float,
        z: float | None = None,
        a: float | None = None,
        comment: str | None = None,
    ) -> None:
        """Perform a rapid *G0* move to the specified location.

        At least one axis should be specified.
        If the tool is below the safe 'Z' height it will be raised before
        the rapid move is performed.

        Args:
            x: X axis value (optional)
            y: Y axis value (optional)
            z: Z axis value (optional)
            a: A axis value (optional)
            comment: Optional comment string.
        """
        # Make sure the tool is at a safe height for a rapid move.
        z_position = self.position('Z')
        if (
            z_position is None
            or (self.zsafe is not None and z_position < self.zsafe)
            or self._is_tool_up
        ):
            self.tool_up()
        if z is not None and self.zsafe is not None:
            z = max(self.zsafe, z)

        self.gcode_command('G00', X=x, Y=y, Z=z, A=a, comment=comment)

        if self.preview_plotter:
            self.preview_plotter.plot_move(self._endp(x, y, z, a))

    def feed(
        self,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        a: float | None = None,
        feed: float | None = None,
        comment: str | None = None,
    ) -> None:
        """Perform a *G1* linear tool feed to the specified location.

        At least one axis should be specified.

        Args:
            x: X axis value (optional)
            y: Y axis value (optional)
            z: Z axis value (optional)
            a: A axis value (optional)
            feed: Feed rate (optional - default feed rate used if None)
            comment: Optional comment string.
        """
        # Determine default feed rate appropriate for the move
        if feed is None:
            if x is not None or y is not None:
                feed = self.xyfeed
            elif z is not None:
                feed = self.zfeed
            elif a is not None:
                feed = self.afeed

        if feed is not None:
            self.gcode_command(
                'G01', X=x, Y=y, Z=z, A=a, F=feed, comment=comment
            )
            if self.preview_plotter:
                self.preview_plotter.plot_feed(self._endp(x, y, z, a))

    def feed_arc(
        self,
        clockwise: bool,
        x: float,
        y: float,
        arc_x: float,
        arc_y: float,
        a: float | None = None,
        z: float | None = None,
        feed: float | None = None,
        comment: str | None = None,
    ) -> None:
        """Perform a *G2*/*G3* arc feed.

        This will raise a GCodeError if the beginning and ending arc radii
        do not match, ie if one of the end points does not lie on the arc.

        Args:
            clockwise: True if the arc moves in a clockwise direction.
            x: X value of arc end point
            y: Y value of arc end point
            arc_x: Center of arc relative to ``x``
            arc_y: Center of arc relative to ``y``
            a: A axis value at endpoint (in radians)
            z: Optional Z value of arc end point
            feed: Feed rate (optional - default feed rate used if None)
            comment: Optional comment string.
        """
        # Make sure that both the start and end points lie on the arc.
        current_x, current_y = self.get_current_position_xy()
        center_x = arc_x + current_x
        center_y = arc_y + current_y
        # Distance from center to current position
        start_radius = math.hypot(current_x - center_x, current_y - center_y)
        end_radius = math.hypot(arc_x, arc_y)
        if not self.float_eq(start_radius, end_radius):
            logger = logging.getLogger(__name__)
            logger.debug('Degenerate arc:')
            logger.debug(
                '  start point = (%f, %f), end point = (%f, %f)',
                current_x,
                current_y,
                x,
                y,
            )
            logger.debug(
                '  start radius = %f, end radius = %f', start_radius, end_radius
            )
            raise GCodeError('Mismatching arc radii.')
        gcode = 'G02' if clockwise else 'G03'
        self.gcode_command(
            gcode,
            X=x,
            Y=y,
            Z=z,
            I=arc_x,
            J=arc_y,
            A=a,
            F=(feed if feed is not None else self.xyfeed),
            force_value='IJ',
            comment=comment,
        )

        if self.preview_plotter:
            self.preview_plotter.plot_arc(
                (center_x, center_y), self._endp(x, y, z, a), clockwise
            )

    def get_current_position_xy(
        self,
    ) -> tuple[float, float]:
        """The last known tool position on the XY plane.

        Returns:
            A 2-tuple containing coordinates of X and Y axes
            of the form (X, Y). An axis value will be
            zero if the position is unknown.
        """
        x = self._last_val['X']
        y = self._last_val['Y']
        if x is None:
            x = 0
        if y is None:
            y = 0
        return x, y

    def get_current_position(self) -> tuple[float | None, ...]:
        """The last known tool position.

        Returns:
            A 4-tuple containing coordinates of all four axes
            of the form (X, Y, Z, A). An axis value will be
            None if the position is unknown.
        """
        return (
            self._last_val['X'],
            self._last_val['Y'],
            self._last_val['Z'],
            self._last_val['A'],
        )

    def position(self, axis: str) -> float | None:
        """The current position of the specified axis.

        Args:
            axis: The axis name - i.e. 'X', 'Y', 'Z', 'A', etc.

        Returns:
            The current position of the named axis as a float value,
            or None if unknown.
        """
        axis = axis.upper()
        if axis not in self._last_val:
            raise GCodeError(f'Undefined axis {axis}')
        return self._last_val[axis]

    def gcode_command(  # pylint: disable=too-many-branches
        self,
        command: str,
        params: str | None = None,
        force_value: str = '',
        comment: str | None = None,
        **kwargs: float | None,
    ) -> None:
        """Output a line of gcode.

        This is mainly for internal use and should be
        used with extreme caution.
        Use the higher level methods if at all possible.

        Args:
            command: G code command. Required.
            params: Parameter string that will be output as is.
                This `must not` be used with commands that
                that may change the position of the machine. Optional.
            force_value: A string containing the modal parameter names
                whose values will be output regardless of whether their
                values have changed.
                By default if the specified value of a modal parameter has not
                changed since its last value then it will not be output.
            comment: Optional inline comment string.
            kwargs: Axis values:
                * X: The X axis value. Optional.
                * Y: The Y axis value. Optional.
                * Z: The Z axis value. Optional.
                * I: Center (x) of arc relative to X,Y. Optional.
                * J: Center (y) of arc relative to X,Y. Optional.
                * R: Arc radius. Optional.
                * A: The A axis value in radians. Optional.

        Raises:
            GCodeError
        """
        if command is None or not command:
            return
        command = _canonical_cmd(command)
        base_cmd = command.split('.')[0]
        # Make sure motion can be tracked.
        if command in self._GCODE_MOTION and params:
            raise GCodeError('Motion command with opaque parameters.')
        pos_params = {}
        # Extract machine position parameters and update
        # internal position coordinates.
        for k in ('X', 'Y', 'Z', 'I', 'J', 'R', 'A', 'F'):
            value = kwargs.get(k, kwargs.get(k.lower()))
            if value is not None and k not in self._disabled_axes:
                if k in 'ABC':
                    # Use angle tolerance for comparing angle values
                    tolerance = self.angle_tolerance
                    if self.wrap_angles:
                        value = math.fmod(value, 2 * math.pi)
                else:
                    # Otherwise use float tolerance
                    tolerance = self.tolerance
                last_val = self._last_val[k]
                value_has_changed = (
                    last_val is None or abs(value - last_val) > tolerance
                )
                gcode_is_nonmodal = base_cmd in self._GCODE_NONMODAL_GROUP
                if k in force_value or value_has_changed or gcode_is_nonmodal:
                    self._last_val[k] = value
                    # Apply any axis transforms
                    value *= self.axis_scale.get(k, 1.0)
                    value += self.axis_offset.get(k, 0.0)
                    if k in 'ABC':
                        value = math.degrees(value)
                    elif k in 'XYZIJ':
                        # Tool height safety check
                        if (
                            k == 'Z'
                            and self._is_tool_up
                            and self.zsafe is not None
                            and value < self.zsafe
                        ):
                            self._is_tool_up = False
                        # Apply unit scale (user/world to machine units)
                        value *= self.unit_scale
                    pos_params[k] = value

        gcode_line = None
        if len(pos_params) > 0:
            # Suppress redundant feedrate-only lines
            if len(pos_params) > 1 or 'F' not in pos_params:
                line_parts = [
                    command,
                ]
                # Arrange the parameters in a readable order
                for k in self._GCODE_ORDERED_PARAMS:
                    value = pos_params.get(k)
                    if value is not None:
                        kk = self.axis_map.get(k, k)
                        line_parts.append(f'{kk}{self.fmt_float(value)}')
                gcode_line = ' '.join(line_parts)
        # Note: this check will suppress output of modal commands
        # with unchanged parameter values.
        elif base_cmd not in self._GCODE_MODAL_MOTION:
            gcode_line = command
            if params is not None and params:
                gcode_line += ' ' + params
        if gcode_line is not None:
            self._write_line(gcode_line, comment=comment)

    def _write_line(
        self, line: str | None = None, comment: str | None = None
    ) -> None:
        """Write a (optionally numbered) line to the G code output.

        A newline character is always appended, even if the string is empty.
        Empty lines and comment-only lines are not numbered.
        """
        if line:
            if self.show_line_numbers:
                self._write(f'N{self.line_number:06d} ')
                self.line_number += 1
            self._write(line)

        if self.show_comments and comment:
            sp = '  ' if line else ''
            self._write(f'{sp}; {comment}')

        self._write('\n')

    def _write(self, text: str) -> None:
        """Write the string to the gcode output stream."""
        self.output.write(text)

    def _endp(
        self, x: float | None, y: float | None, z: float | None, a: float | None
    ) -> TCoord:
        """Return the end point of the current trajectory.

        Used for preview plotting.
        """
        return (
            x if x is not None else self._last_val_checked('X'),
            y if y is not None else self._last_val_checked('Y'),
            z if z is not None else self._last_val_checked('Z'),
            a if a is not None else self._last_val_checked('A'),
        )

    def _last_val_checked(self, axis: str) -> float:
        v: float | None = self._last_val.get(axis)
        if v is None:
            raise ValueError(f'Undefined {axis} axis value.')
        return v

    def float_eq(self, a: float, b: float) -> float:
        """Compare two floats for approximate equality.

        Uses the tolerance specified for the GCodeGenerator class.
        """
        return abs(a - b) < self.tolerance


def _canonical_cmd(cmd: str) -> str:
    """Canonicalize a G code command.

    Converts to upper case...
    """
    # Converts to upper case and expands shorthand (ie. G1 to G01).
    # cmd = cmd.upper()
    # if len(cmd) == 2 and cmd[1].isdigit():
    #    cmd = cmd[0] + '0' + cmd[1]
    # return cmd
    return cmd.upper()
