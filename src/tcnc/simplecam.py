"""Simple G code generation from basic 2D geometry."""

from __future__ import annotations

import dataclasses
import logging
import math
import os
from typing import TYPE_CHECKING

import geom2d

from . import fillet, gcode, offset, toolpath

DEBUG = bool(os.environ.get('DEBUG'))

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from typing_extensions import Self

if DEBUG or TYPE_CHECKING:
    import geom2d.plotpath  # pylint: disable=ungrouped-imports


logger = logging.getLogger(__name__)


class CAMError(Exception):
    """CAM Error."""


@dataclasses.dataclass
class CAMOptions:
    """CAM options set by user."""

    # Home the XYA axes when all done
    home_when_done: bool = False
    # Sort strategy
    path_sort_method: str | None = None
    # Maximum feed depth per pass
    z_step: float = 0
    # Final feed depth
    z_depth: float = 0
    # Tangential tool width in machine units
    tool_width: float = 0
    # Tool trail offset in machine units
    tool_trail_offset: float = 0
    # Biarc approximation tolerance
    biarc_tolerance: float = 0.001
    # Maximum bezier curve subdivision recursion for biarcs
    biarc_max_depth: int = 4
    # Flatness of curve to convert to line
    line_flatness: float = 0.001
    # Ignore path segment start tangent angle when rotating about A
    # ignore_segment_angle = False
    # Allow tool reversal at sharp corners
    # allow_tool_reversal: bool = False
    # Enable tangent rotation. Default is True.
    enable_tangent: bool = True
    # Fillet paths to compensate for tool width
    path_tool_fillet: bool = False
    # Offset paths to compensate for tool trail offset
    path_tool_offset: bool = False
    # Preserve G1 continuity for offset arcs
    path_preserve_g1: bool = False
    # Split cam at points that are not G1 or C1 continuous
    path_split_cusps: bool = False
    # Closed polygon overlap distance
    path_close_overlap: float = 0
    # Fillet paths to smooth tool travel
    path_smooth_fillet: bool = False
    # Smoothing fillet radius
    path_smooth_radius: float = 0
    # Number of paths to skip over before processing
    skip_path_count: int = 0
    # Start outputting G code when path count reaches this
    # Useful if the job has to be stopped and restarted later.
    path_count_start: int = 1

    def __post_init__(self) -> None:
        """Perform any post-init processing."""
        if self.z_depth > 0:
            self.z_step = 0
        else:
            self.z_step = min(abs(self.z_depth), abs(self.z_step))

    @classmethod
    def from_options(cls, options: object) -> Self:  # noqa: ANN102
        """Transfer options from, say argparse.Namespace, to CAMOptions."""
        # This might break since __dataclass_fields__ is undocumented
        fields = set(
            cls.__dataclass_fields__.keys()  # pylint: disable=no-member
        )
        logging.debug('fields: %s', fields)
        cam_options = {
            name: getattr(options, name)
            for name in fields
            if name in options.__dict__
        }
        logging.debug('cam options: %s', cam_options)
        return cls(**cam_options)


class SimpleCAM:
    """Simple 2D CAM library.

    Converts line/arc path geometry into G code
    suitable for a straightforward 2.5 axis machine with an optional
    fourth angular axis (A) that rotates about the Z axis. The fourth axis
    position is always tangential to the movement along the X and Y axes.
    This is usually called a tangential tool (ie a knife or a brush).

    Since the path geometry is two dimensional the Z and A axes are
    calculated automatically.
    By default the Z axis value is determined by the current plunge depth
    and the A axis value is the tangent normal of the current segment.

    These defaults can be overridden by assigning extra attributes
    to the segment.

    Segment attributes:

        * `inline_end_z`: The Z axis value at the end of the segment.
        * `inline_start_a`: The A axis value at the start of the segment.
        * `inline_end_a`: The A axis value at the start of the segment.
        * `inline_ignore_a`: Boolean. True if the A axis is not to be
           rotated for the length of the segment.

    """

    # Current angle of A axis
    # TODO: Probably should use GCode.A property
    current_angle: float = 0.0

    # Tiny movement accumulator
    _tinyseg_accumulation: float = 0.0
    # Keep track of tool flip state
    _tool_flip_toggle: int = -1

    options: CAMOptions
    gc: gcode.GCodeGenerator

    def __init__(
        self, gc: gcode.GCodeGenerator, options: CAMOptions | None = None
    ) -> None:
        """Constructor.

        Args:
            gc: A GCodeGenerator instance
            options: CAM options
        """
        self.gc = gc
        self.options = options if options else CAMOptions()

    def generate_gcode(
        self,
        path_list: Iterable[
            Sequence[geom2d.Line | geom2d.Arc | geom2d.CubicBezier]
        ],
    ) -> None:
        """Generate G code from tool paths.

        :param path_list: A list of drawing paths.
            Where a drawing path is a sequential collection of
            geom2d.CubicBezier, geom2d.Line, or geom2d.Arc segments.
            Other shape types will be silently ignored...
        """
        # TODO: range check various properties
        # if geom2d.is_zero(self.options.z_step):
        #    # If the step value is zero then just use the final depth.
        #    self.options.z_step = abs(self.options.z_depth)

        toolpaths = self.generate_toolpaths(path_list)

        toolpaths = self.postprocess_toolpaths(toolpaths)

        # Sort paths to optimize rapid moves
        if self.options.path_sort_method is not None:
            toolpaths = sort_paths(toolpaths, self.options.path_sort_method)

        # G code header - mostly boilerplate plus some info.
        logger.debug('Generate header...')
        self.generate_header(toolpaths)

        # Make sure the tool at the safe height
        self.gc.tool_up()

        # Generate G code from paths. If the Z step is less than
        # the final tool depth then do several passes until final
        # depth is reached.
        # If the final tool depth is > 0 then just ignore the step
        # value since the tool won't reach the work surface anyway.
        if self.options.z_depth < 0 < self.options.z_step:
            tool_depth = -self.options.z_step
        else:
            tool_depth = self.options.z_depth

        zpass_count = 1

        while tool_depth >= self.options.z_depth:
            logger.debug('pass: %d, tool_depth: %f', zpass_count, tool_depth)
            for path_count, path in enumerate(toolpaths, 1):
                # Skip empty paths...
                if not path:
                    continue

                if path_count >= self.options.path_count_start:
                    self.gc.comment()
                    actual_depth = tool_depth * self.gc.unit_scale
                    self.gc.comment(
                        f'Path: {path_count}, pass: {zpass_count}, '
                        f'depth: {actual_depth:.05f}{self.gc.gc_unit}'
                    )
                    # Rapidly move to the beginning of the tool path
                    self.generate_rapid_move(path)
                    # Plunge the tool to current cutting depth
                    self.plunge(tool_depth, path)
                    # Create G-code for each segment of the path
                    self.gc.comment('Start tool path')
                    for segment in path:
                        self._generate_segment_gcode(segment, tool_depth)
                    # Bring the tool back up to the safe height
                    self.retract(tool_depth, path)
                    # Do a fast unwind if angle is > 360deg.
                    # Useful if the A axis gets wound up after spirals.
                    # if abs(self.current_angle) > (math.pi * 2):
                    #    self.gc.rehome_rotational_axis()
                    #    self.current_angle = 0.0
            if (
                self.options.z_depth > 0
                or self.options.z_step < self.gc.tolerance
                or abs(self.options.z_depth - tool_depth) < self.gc.tolerance
            ):
                break
            tool_depth = max(
                self.options.z_depth, tool_depth - self.options.z_step
            )
            zpass_count += 1
        self.gc.tool_up()
        # Do a rapid move back to the home position if specified
        if self.options.home_when_done:
            self.gc.rapid_move(x=0, y=0, a=0)
        # G code footer boilerplate
        self.gc.footer()

    def generate_toolpaths(
        self,
        path_list: Iterable[
            Sequence[geom2d.Line | geom2d.Arc | geom2d.CubicBezier]
        ],
    ) -> list[toolpath.Toolpath]:
        """Generate tool paths.

        Sort order will be maintained.

        Args:
            path_list: A list of drawing paths.
                Where a drawing path is a sequential collection of
                geom2d.CubicBezier, geom2d.Line, or geom2d.Arc objects.

        Returns:
            A new list of tool paths.
        """
        # #DEBUG
        # for path in path_list:
        #     prev_seg = path[0]
        #     for seg in path[1:]:
        #         if not geom2d.segments_are_g1(prev_seg, seg):
        #             geom2d.debug.draw_point(prev_seg.p2, color='#00ffff')
        #         prev_seg = seg
        #     if (path[-1].p2 == path[0].p1
        #             and not geom2d.segments_are_g1(path[-1], path[0])):
        #         geom2d.debug.draw_point(path[-1].p2, color='#00ffff')
        # #DEBUG
        # if self.options.path_tool_offset and self.options.tool_trail_offset > 0:
        #     for path in path_list:
        #         new_path = cam.offset_path(path, self.options.tool_trail_offset,
        #                                     preserve_g1=self.options.path_preserve_g1)
        #         new_path_list.append(new_path)
        #         #if self.debug_svg is not None:
        #         #    logger.debug('pre offset layer')
        #         #    geom2d.debug.plot_path(new_path, '#cc3333', offset_layer)

        # First pass is converting Bezier curves to circular arcs
        # using biarc approximation then adding corner fillets for
        # tool width turn compensation. Paths will also be split
        # at non-G1 vertices if required.
        toolpaths: list[toolpath.Toolpath] = []
        for path in path_list:
            # Create a ToolPath.
            # Converts Beziers to biarcs and adds hinting
            tool_path = toolpath.Toolpath.toolpath(
                path,
                biarc_tolerance=self.options.biarc_tolerance,
                biarc_max_depth=self.options.biarc_max_depth,
                biarc_line_flatness=self.options.line_flatness,
            )
            if DEBUG:
                geom2d.plotpath.draw_path(tool_path)

            # Option: Split path at cusps (non-G1 vertices).
            if self.options.enable_tangent and self.options.path_split_cusps:
                toolpaths.extend(split_toolpath_g1(tool_path))
            else:
                toolpaths.append(tool_path)

        # DEBUG
        # logger.debug('a1=%f, a2=%f, a3=%f, a4=%f' % (
        #    cam.seg_start_angle(path[0]),
        #    cam.seg_end_angle(path[0]),
        #    cam.seg_start_angle(path[-1]),
        #    cam.seg_end_angle(path[-1])))
        # for path in path_list:
        #     prev_seg = path[0]
        #     for seg in path[1:]:
        #         if not util.segments_are_g1(prev_seg, seg):
        #             prev_seg.svg_plot(color='#00ffff')
        #         prev_seg = seg
        #         if not util.segments_are_g1(prev_seg, seg):
        #             seg.svg_plot(color='#00ffff')
        # DEBUG
        return toolpaths

    def postprocess_toolpaths(
        self, toolpaths: list[toolpath.Toolpath]
    ) -> list[toolpath.Toolpath]:
        """Allow subclasses to post process the generated tool paths."""
        logging.debug('postprocessing...')
        new_toolpaths = []
        for path in toolpaths:
            new_path = path
            # Option: create fillets to compensate for tool width
            if (
                self.options.enable_tangent
                and self.options.path_tool_fillet
                and self.options.tool_width > 0
            ):
                new_path = fillet.fillet_toolpath(
                    new_path,
                    self.options.tool_width / 2,
                    fillet_close=True,
                    mark_fillet=True,
                )
                # if DEBUG:
                #    geom2d.plotpath.plot_path(path, color='#33cc33')
            # Option: Add overlap segment to closed polygons.
            if path.is_closed() and self.options.path_close_overlap > 0:
                # Add overlap
                add_path_overlap(new_path, self.options.path_close_overlap)
            # Option: Add tool trail compensation offsets
            if (
                self.options.enable_tangent
                and self.options.path_tool_offset
                and self.options.tool_trail_offset > 0
            ):
                new_path = self.offset_toolpath(new_path)
                # Option: Add smoothing fillets to offset toolpath.
                if (
                    self.options.path_preserve_g1
                    and self.options.path_smooth_radius > 0
                ):
                    new_path = fillet.fillet_toolpath(
                        new_path,
                        self.options.path_smooth_radius,
                        fillet_close=True,
                        adjust_rotation=True,
                    )
            new_toolpaths.append(new_path)

        return new_toolpaths

    def offset_toolpath(self, path: toolpath.Toolpath) -> toolpath.Toolpath:
        """Offset tool path to compensate for tool trail."""
        path = offset.offset_path(
            path, self.options.tool_trail_offset, self.options.line_flatness
        )
        if self.options.path_preserve_g1:
            # Rebuild paths to fix broken G1 continuity caused by
            # path offsetting.
            path = offset.fix_g1_path(
                path, self.options.biarc_tolerance, self.options.line_flatness
            )
        return path

    def generate_header(self, path_list: list[toolpath.Toolpath]) -> None:
        """Output header boilerplate and comments."""
        self.gc.header(comment=f'Path count: {len(path_list)}')

    def plunge(self, depth: float, path: toolpath.Toolpath) -> None:
        """Bring the tool down to the current working depth.

        This can be subclassed to generate custom plunge profiles.
        """
        # When the first segment has an inline Z axis hint
        # it means that there is a soft landing, in which case
        # the tool is just brought to the work surface.
        if hasattr(path[0], 'inline_z'):
            depth = 0
        # Bring the tool down to the plunge depth.
        self.gc.tool_down(depth)

    def retract(
        self,
        depth: float,  # noqa: ARG002 # pylint: disable=unused-argument
        path: toolpath.Toolpath,  # noqa: ARG002 # pylint: disable=unused-argument
    ) -> None:
        """Lift the tool from the current working depth.

        This can be subclassed to generate custom retraction profiles.
        """
        # Lift the tool up to safe height.
        self.gc.tool_up()

    def generate_rapid_move(self, path: toolpath.Toolpath) -> None:
        """Generate G code for a rapid move to the beginning of the tool path."""
        # TODO: Unwind large rotations
        first_segment = path[0]
        segment_start_angle = toolpath.seg_start_angle(first_segment)
        if self.options.enable_tangent:
            rotation = geom2d.calc_rotation(
                self.current_angle, segment_start_angle
            )
            self.current_angle += rotation
        self.gc.rapid_move(
            first_segment.p1.x, first_segment.p1.y, a=self.current_angle
        )

    def _generate_segment_gcode(
        self, segment: toolpath.ToolpathSegment, depth: float
    ) -> None:
        """Generate G code for Line and Arc path segments."""
        # Amount of Z axis movement along this segment
        depth = getattr(segment, 'inline_z', depth)

        # Ignore the a axis tangent rotation for this segment if True
        inline_ignore_a = getattr(segment, 'inline_ignore_a', False)

        rotation: float = 0
        if inline_ignore_a or not self.options.enable_tangent:
            start_angle = self.current_angle
            end_angle = self.current_angle
        else:
            start_angle = toolpath.seg_start_angle(segment)
            end_angle = toolpath.seg_end_angle(segment)
            # Rotate A axis to segment start angle
            rotation = geom2d.calc_rotation(self.current_angle, start_angle)
            if not geom2d.is_zero(rotation):
                self.current_angle += rotation
                self.gc.feed(a=self.current_angle)
            # Amount of A axis rotation needed to get to end_angle.
            # The sign of the angle will determine the direction of rotation.
            rotation = geom2d.calc_rotation(self.current_angle, end_angle)
            # The final angle at the end of this segment
            end_angle = self.current_angle + rotation
        # logger.debug('current angle=%f' % self.current_angle)
        # logger.debug('start_angle=%f' % start_angle)
        # logger.debug('end_angle=%f' % end_angle)
        # logger.debug('rotation=%f' % rotation)
        if isinstance(segment, geom2d.Line):
            self.gc.feed(segment.p2.x, segment.p2.y, a=end_angle, z=depth)
        elif isinstance(segment, geom2d.Arc):
            pos = self.gc.get_current_position_xy()
            r = segment.center.distance(pos)
            if not geom2d.float_eq(r, segment.radius):
                logger.debug(
                    'degenerate arc: r1=%f, r2=%f, %s',
                    r,
                    segment.radius,
                    str(segment),
                )
                # geom2d.debug.draw_arc(segment, color='#ffff00', width='1px')
                # For now just treat the f*cked up arc as a line...
                self.gc.feed(segment.p2.x, segment.p2.y, a=end_angle, z=depth)
            else:
                arcv = segment.center - segment.p1
                self.gc.feed_arc(
                    segment.is_clockwise(),
                    segment.p2.x,
                    segment.p2.y,
                    arcv.x,
                    arcv.y,
                    a=end_angle,
                    z=depth,
                )
        self.current_angle = end_angle

    def flip_tool(self) -> None:
        """Offset tangential tool rotation by 180deg.

        This useful for brush-type or double sided tools to even out wear.
        """
        # Toggle rotation direction
        self._tool_flip_toggle *= -1  # Toggle -1 and 1
        self.gc.axis_offset['A'] += self._tool_flip_toggle * math.pi


def add_path_overlap(path: toolpath.Toolpath, overlap: float) -> None:
    """Extend closed paths with an overlap segment."""
    if len(path) < 3 or path[0].p1 != path[-1].p2:  # noqa: PLR2004
        return
    oseg: toolpath.ToolpathSegment | None = None
    if isinstance(path[0], geom2d.Line):
        endp = path[0].p1 + geom2d.P.from_polar(overlap, path[0].angle())
        oseg = toolpath.ToolpathLine(path[0].p1, endp)
    elif isinstance(path[0], geom2d.Arc):
        arcseg = path[0]
        arclen = arcseg.length()
        overlap = min(arclen, overlap)
        endp = arcseg.point_at(overlap / arclen)
        oseg = toolpath.ToolpathArc(
            *geom2d.Arc.from_two_points_and_center(
                arcseg.p1, endp, arcseg.center
            )
        )
    if oseg:
        path.append(oseg)


def flip_paths(path_list: list[toolpath.Toolpath]) -> None:
    """Flip path directions.

    Preserve original path order but flip path directions
    if necessary to minimize rapid travel.
    The first path in the path list determines the flip order.
    """
    endp = path_list[0][-1].p2
    for path in path_list:
        d1 = endp.distance(path[0].p1)
        d2 = endp.distance(path[-1].p2)
        if d2 < d1:
            path.path_reversed()
        endp = path[-1].p2


def split_toolpath_g1(
    path: toolpath.Toolpath,
) -> list[toolpath.Toolpath]:
    """Split the path at path vertices that connect non-tangential segments.

    Args:
        path: The path to split.

    Returns:
        A list of one or more paths.
    """
    path_list: list[toolpath.Toolpath] = []
    new_path = toolpath.Toolpath()
    seg1 = path[0]
    for seg2 in path[1:]:
        new_path.append(seg1)
        if (
            not geom2d.float_eq(
                seg1.end_tangent_angle(), seg2.start_tangent_angle()
            )
            or hasattr(seg1, 'inline_ignore_g1')
            or hasattr(seg2, 'inline_ignore_g1')
        ):
            path_list.append(new_path)
            new_path = toolpath.Toolpath()
        seg1 = seg2
    new_path.append(seg1)
    path_list.append(new_path)
    return path_list


def sort_paths(
    path_list: list[toolpath.Toolpath],
    sort_method: str = 'optimize',
) -> list[toolpath.Toolpath]:
    """Sort the tool paths to minimize tool movements.

    This will try to sort the tool paths to minimize tool travel
    between the end of one path and the start of the next path.

    Args:
        path_list: A list of tool paths.
        sort_method: Sorting strategy.

    Returns:
        A sorted list of paths.
    """
    if sort_method == 'flip':
        # Preserve original path order but flip path directions to
        # minimize rapid travel.
        flip_paths(path_list)
    elif sort_method == 'optimize':
        # TODO: implement this...
        # Just sort the paths from bottom to top, left to right.
        # Only the first point of the path is used as a sort key...
        # path_list.sort(key=lambda cp: (cp[0].p1.y, cp[0].p1.x))
        path_list = _sort_segment_paths_1(path_list)
    elif sort_method == 'y+':
        # Sort by Y axis then X axis, ascending
        path_list.sort(key=lambda cp: (cp[0].p1.y, cp[0].p1.x))
    elif sort_method == 'y-':
        # Sort by Y axis then X axis, descending
        path_list.sort(key=lambda cp: (cp[0].p1.y, cp[0].p1.x), reverse=True)
    elif sort_method == 'x+':
        # Sort by X axis then Y axis, ascending
        path_list.sort(key=lambda cp: cp[0].p1)
    elif sort_method == 'x-':
        # Sort by X axis then Y axis, descending
        path_list.sort(key=lambda cp: cp[0].p1, reverse=True)
    elif sort_method == 'cw_out':
        # TODO
        # Sort by geometric center moving clockwise outwards
        pass
    else:
        # do nothing for unknown sort methods...
        pass

    return path_list


def _sort_segment_paths_1(
    path_list: list[toolpath.Toolpath],
) -> list[toolpath.Toolpath]:
    """Sort paths.

    This is a specialized sort for single segment paths that
    are all more or less the same length.
    """
    new_path_list: list[toolpath.Toolpath] = []
    # Use the length of the first path to determine band height
    band_height = path_list[0][0].length() * 1.5
    band_ceiling = band_height
    # First sort by Y axis then X axis, ascending
    path_list.sort(key=lambda cp: (cp[0].p1.y, cp[0].p1.x))
    bands: list[list[toolpath.Toolpath]] = [
        [],
    ]

    # Divide the surface into bands and sort
    for path in path_list:
        if path[0].p1.y <= band_ceiling and path[0].p2.y <= band_ceiling:
            bands[-1].append(path)
        else:
            band_ceiling += band_height
            bands.append([
                path,
            ])
    for i, band in enumerate(bands):
        band.sort(key=lambda cp: cp[0][0][0], reverse=bool(i % 2 != 0))
        new_path_list.extend(band)

    flip_paths(new_path_list)

    return new_path_list
