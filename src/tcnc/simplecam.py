"""Simple G code generation from basic 2D geometry."""

from __future__ import annotations

import logging
import math
import os
from typing import TYPE_CHECKING

import geom2d

from . import fillet, gcode, offset, toolpath

DEBUG = bool(os.environ.get('DEBUG'))

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

if DEBUG or TYPE_CHECKING:
    import geom2d.plotpath


logger = logging.getLogger(__name__)


class CAMError(Exception):
    """CAM Error."""


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

    # Home the XYA axes when all done
    home_when_done = False
    # Sort strategy
    path_sort_method = None
    # Maximum feed depth per pass
    z_step = 0.0
    # Final feed depth
    z_depth = 0.0
    # Tangential tool width in machine units
    tool_width = 0.0
    # Tool trail offset in machine units
    tool_trail_offset = 0.0
    # Biarc approximation tolerance
    biarc_tolerance = 0.01
    # Maximum bezier curve subdivision recursion for biarcs
    biarc_max_depth = 4
    # Flatness of curve to convert to line
    line_flatness = 0.001
    # Ignore path segment start tangent angle when rotating about A
    # ignore_segment_angle = False
    # Allow tool reversal at sharp corners
    allow_tool_reversal = False
    # Enable tangent rotation. Default is True.
    enable_tangent = True
    # Fillet paths to compensate for tool width
    path_tool_fillet = False
    # Offset paths to compensate for tool trail offset
    path_tool_offset = False
    # Preserve G1 continuity for offset arcs
    path_preserve_g1 = False
    # Split cam at points that are not G1 or C1 continuous
    path_split_cusps = False
    # Close polygons with overlap
    path_close_polygon = False
    path_close_overlap = 0
    # Fillet paths to smooth tool travel
    path_smooth_fillet = False
    # Smoothing fillet radius
    path_smooth_radius = 0.0
    # Number of paths to skip over before processing
    skip_path_count = 0
    # Start outputting G code when path count reaches this
    # Useful if the job has to be stopped and restarted later.
    path_count_start = 1

    # Cumulative tool feed distance
    feed_distance = 0.0
    # Current angle of A axis
    # TODO: get rid of this and use GCode.A property
    current_angle = 0.0
    # Tiny movement accumulator
    _tinyseg_accumulation = 0.0
    # Keep track of tool flip state
    _tool_flip_toggle = -1

    gc: gcode.GCodeGenerator

    def __init__(self, gc: gcode.GCodeGenerator) -> None:
        """Constructor.

        Args:
            gc: a GCodeGenerator instance
        """
        self.gc = gc
        # Properties will be set by user.

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
        # if geom2d.is_zero(self.z_step):
        #    # If the step value is zero then just use the final depth.
        #    self.z_step = abs(self.z_depth)

        logger.debug('Generating tool paths...')
        toolpath_list = self.generate_toolpaths(path_list)

        toolpath_list = self.postprocess_toolpaths(toolpath_list)

        # Sort paths to optimize rapid moves
        if self.path_sort_method is not None:
            toolpath_list = sort_paths(path_list, self.path_sort_method)

        # G code header - mostly boilerplate plus some info.
        logger.debug('Generate header...')
        self.generate_header(toolpath_list)

        # Make sure the tool at the safe height
        self.gc.tool_up()

        # Generate G code from paths. If the Z step is less than
        # the final tool depth then do several passes until final
        # depth is reached.
        # If the final tool depth is > 0 then just ignore the step
        # value since the tool won't reach the work surface anyway.
        if self.z_depth > 0:
            self.z_step = 0
            tool_depth = self.z_depth
        else:
            self.z_step = min(self.z_step, abs(self.z_depth))
            tool_depth = -self.z_step
        depth_pass = 1
        logger.debug('Generating g code...')
        while tool_depth >= self.z_depth:
            for path_count, path in enumerate(toolpath_list, 1):
                if not path:
                    # Skip empty paths...
                    logger.debug('Empty path...')
                    continue
                if path_count >= self.path_count_start:
                    self.gc.comment()
                    actual_depth = tool_depth * self.gc.unit_scale
                    self.gc.comment(
                        f'Path: {path_count}, pass: {depth_pass}, '
                        f'depth: {actual_depth:.05f}{self.gc.gc_unit}'
                    )
                    # Rapidly move to the beginning of the tool path
                    self.generate_rapid_move(path)
                    # Plunge the tool to current cutting depth
                    self.plunge(tool_depth, path)
                    # Create G-code for each segment of the path
                    self.gc.comment('Start tool path')
                    logger.debug('Starting tool path...')
                    for segment in path:
                        self._generate_segment_gcode(segment, tool_depth)
                    # Bring the tool back up to the safe height
                    # self.retract(tool_depth, path)
                    # Do a fast unwind if angle is > 360deg.
                    # Useful if the A axis gets wound up after spirals.
                    # if abs(self.current_angle) > (math.pi * 2):
                    #    self.gc.rehome_rotational_axis()
                    #    self.current_angle = 0.0
            if (
                self.z_depth > 0
                or self.z_step < self.gc.tolerance
                or abs(self.z_depth - tool_depth) < self.gc.tolerance
            ):
                break
            tool_depth = max(self.z_depth, tool_depth - self.z_step)
            #             # remaining z distance
            #             rdist = abs(self.z_depth - tool_depth)
            #             if rdist > self.gc.tolerance and rdist < self.z_step:
            #                 tool_depth = self.z_depth
            #             else:
            #                 tool_depth -= self.z_step
            depth_pass += 1
            logger.debug('pass: %d, tool_depth: %f', depth_pass, tool_depth)
        self.gc.tool_up()
        # Do a rapid move back to the home position if specified
        if self.home_when_done:
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
        # if self.path_tool_offset and self.tool_trail_offset > 0:
        #     for path in path_list:
        #         new_path = cam.offset_path(path, self.tool_trail_offset,
        #                                     preserve_g1=self.path_preserve_g1)
        #         new_path_list.append(new_path)
        #         #if self.debug_svg is not None:
        #         #    logger.debug('pre offset layer')
        #         #    geom2d.debug.plot_path(new_path, '#cc3333', offset_layer)

        # First pass is converting Bezier curves to circular arcs
        # using biarc approximation then adding corner fillets for
        # tool width turn compensation. Paths will also be split
        # at non-G1 vertices if required.
        toolpath_list: list[toolpath.Toolpath] = []
        for path in path_list:
            tool_path = toolpath.Toolpath.toolpath(
                path,
                biarc_tolerance=self.biarc_tolerance,
                biarc_max_depth=self.biarc_max_depth,
                biarc_line_flatness=self.line_flatness,
            )
            if DEBUG:
                geom2d.plotpath.draw_path(tool_path)

            # if self.debug_svg is not None:
            #    geom2d.debug.draw_path(path, '#33cc33', biarc_layer)
            # First, create fillets to compensate for tool width
            if self.path_tool_fillet and self.tool_width > 0:
                tool_path = fillet.fillet_toolpath(
                    tool_path,
                    self.tool_width / 2,
                    fillet_close=True,
                    mark_fillet=True,
                )
                # if DEBUG:
                #    geom2d.plotpath.plot_path(path, color='#33cc33')

            # Split path at cusps. This may add more than one path.
            if self.path_split_cusps:
                paths = split_toolpath_g1(tool_path)
                toolpath_list.extend(paths)
            else:
                toolpath_list.append(tool_path)

        # These passes need to be done after cusps are split since
        # the path list may have been extended.
        new_path_list = []
        for path in toolpath_list:
            new_path = path
            if self.tool_trail_offset > 0:
                new_path = self.offset_toolpath(new_path)
            if self.path_smooth_radius > 0:
                new_path = fillet.fillet_toolpath(
                    new_path,
                    self.path_smooth_radius,
                    fillet_close=True,
                    adjust_rotation=True,
                )
            new_path_list.append(new_path)

        toolpath_list = new_path_list

        if self.path_close_polygon and self.path_close_overlap > 0:
            # Add overlap
            for path in toolpath_list:
                add_path_overlap(path, self.path_close_overlap)

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
        return toolpath_list

    def postprocess_toolpaths(  # noqa: PLR6301
        self, path_list: list[toolpath.Toolpath]
    ) -> list[toolpath.Toolpath]:
        """Allow subclasses to post process the generated tool path."""
        return path_list

    def offset_toolpath(self, path: toolpath.Toolpath) -> toolpath.Toolpath:
        """Offset tool path to compensate for tool trail."""
        path = offset.offset_path(
            path, self.tool_trail_offset, self.line_flatness
        )
        if self.path_preserve_g1:
            # Rebuild paths to fix broken G1 continuity caused by
            # path offsetting.
            path = offset.fix_g1_path(
                path, self.biarc_tolerance, self.line_flatness
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

    #     def retract(self, depth, path):
    #         """Lift the tool from the current working depth.
    #
    #         This can be subclassed to generate custom retraction profiles.
    #         """
    #         # If the last segment has an inline Z axis hint then the
    #         # Z axis movement will be determined by that segment.
    #         if not hasattr(path[-1], 'inline_z'):
    #             self.gc.feed(z=0)
    #         # Lift the tool up to safe height.
    #         self.gc.tool_up()

    def generate_rapid_move(self, path: toolpath.Toolpath) -> None:
        """Generate G code for a rapid move to the beginning of the tool path."""
        # TODO: Unwind large rotations
        first_segment = path[0]
        segment_start_angle = toolpath.seg_start_angle(first_segment)
        if self.enable_tangent:
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
        # Keep track of total tool travel during feeds
        self.feed_distance += segment.length()
        # Amount of Z axis movement along this segment
        depth = getattr(segment, 'inline_z', depth)
        # Ignore the a axis tangent rotation for this segment if True
        inline_ignore_a = getattr(segment, 'inline_ignore_a', False)
        rotation: float = 0
        if inline_ignore_a or not self.enable_tangent:
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
