"""SVG Preview plotter for Gcode generator."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, ClassVar

import geom2d
from geom2d import polygon

from . import gcode

if TYPE_CHECKING:
    from collections.abc import Sequence

    from inkext import inksvg
    from inkext.svg import TElement

logger = logging.getLogger(__name__)

_DEBUG = False

PATH_LAYER_NAME = 'tcnc preview: tool path'
TOOL_LAYER_NAME = 'tcnc preview: tangent tool'
OUTLINE_LAYER_NAME = 'tcnc preview: tangent tool outline'
SUBPATH_LAYER_NAME = 'tcnc subpaths'

_DEFAULT_TOOLMARK_INTERVAL_LINE = '10px'
_DEFAULT_TOOLMARK_INTERVAL_ANGLE = math.pi / 10


class SVGPreviewPlotter(gcode.PreviewPlotter):
    """Provides a graphical preview of the G-code output.

    Outputs SVG.

    Draws a line along the tool path as well as tool marks that
    show the current rotation of a tangential tool that rotates
    about the Z axis.
    """

    svg: inksvg.InkscapeSVGContext
    # Tangential tool offset.
    tool_offset: float = 0
    # Tangential tool width.
    tool_width: float = 0
    toolmark_line_interval: float = 0
    # Tool mark interval for in place rotation. In radians.
    toolmark_rotation_interval: float = _DEFAULT_TOOLMARK_INTERVAL_ANGLE
    show_toolmarks: bool = False
    show_tm_outline: bool = False
    incr_layer_suffix: bool = True
    flip_y_axis: bool = True

    # Experimental subpath options.
    # These aren't usually exposed publicly...
    x_subpath_render: bool = False
    x_subpath_layer_name: str = SUBPATH_LAYER_NAME
    x_subpath_offset: int = 0
    x_subpath_smoothness: float = 0.5
    x_subpath_maxdist: float = 0.005
    x_subpath_layer: TElement | None = None

    # Create layers that will contain the G code preview
    path_layer: TElement | None = None
    tool_layer: TElement | None = None
    outline_layer: TElement | None = None

    # Non-offset tangent lines - used to make offset lines
    toolmarks: list[geom2d.Line]
    # Toolpath segments associated with toolmarks
    toolmark_segments: list[geom2d.Line | geom2d.Arc]

    # Current XYZA location
    _current_xy = geom2d.P(0.0, 0.0)
    _current_z = 0.0
    _current_a = 0.0

    _styles: ClassVar[dict] = {
        'toolpath_end_marker': (
            'fill-rule:evenodd;fill:$feedline_stroke;'
            'stroke:none;marker-start:none'
        ),
        'movepath_end_marker': (
            'fill-rule:evenodd;fill:$moveline_stroke;'
            'stroke:none;marker-start:none'
        ),
        'feedline': (
            'fill:none;stroke:$feedline_stroke;'
            'stroke-width:$feedline_stroke_width'
            ';stroke-linecap:butt;stroke-linejoin:miter;stroke-miterlimit:4'
            ';stroke-opacity:1.0;marker-end:url(#PreviewLineEnd0)'
        ),
        'feedarc': (
            'fill:none;stroke:$feedline_stroke;'
            'stroke-width:$feedline_stroke_width'
            ';stroke-linecap:butt;stroke-linejoin:miter;stroke-miterlimit:4'
            ';stroke-opacity:1.0;marker-end:url(#PreviewLineEnd0)'
        ),
        'moveline': (
            'fill:none;stroke:$moveline_stroke;'
            'stroke-width:$moveline_stroke_width'
            ';marker-end:url(#PreviewLineEnd2)'
        ),
        'toolmark': (
            'fill:none;stroke:$toolmark_stroke;'
            'stroke-width:$toolmark_stroke_width;'
            'stroke-opacity:0.75'
        ),
        'toolmark_outline': (
            'fill:$tm_outline_fill;stroke:none'  # $tm_outline_stroke;'
            # 'stroke-width:$tm_outline_stroke_width;'
            'stroke-opacity:0.75;'
            'fill-opacity:0.75;'
        ),
        'tooloffset': (
            'fill:none;stroke:$tooloffset_stroke;'
            'stroke-width:$tooloffset_stroke_width;'
            'stroke-opacity:0.75'
        ),
        'subpath': (
            'fill:none;stroke:$subpath_stroke;'
            'stroke-width:$subpath_stroke_width;'
        ),
    }
    # Default style template mapping
    _style_defaults: ClassVar[dict] = {
        'feedline_stroke': '#ff3030',
        'moveline_stroke': '#10cc10',
        'toolmark_stroke': '#a6c3da',
        'tooloffset_stroke': '#429b9f',
        # 'tm_outline_stroke': 'none',  # '#c01010',
        # 'tm_outline_stroke_width': '1px',
        'tm_outline_fill': '#b5ebff',
        # 'tm_outline_fill_opacity': '0.1',
        'subpath_stroke': '#000000',
        'subpath_stroke_width': '1px',
    }
    _style_scale_defaults: ClassVar[dict] = {
        'small': {
            'feedline_stroke_width': '1.5px',
            'moveline_stroke_width': '1px',
            'toolmark_stroke_width': '1px',
            'tooloffset_stroke_width': '1px',
            'end_marker_scale': '0.3',
        },
        'medium': {
            'feedline_stroke_width': '3px',
            'moveline_stroke_width': '2px',
            'toolmark_stroke_width': '2px',
            'tooloffset_stroke_width': '1pt',
            'end_marker_scale': '0.38',
        },
        'large': {
            'feedline_stroke_width': '7px',
            'moveline_stroke_width': '5px',
            'toolmark_stroke_width': '5px',
            'tooloffset_stroke_width': '3px',
            'end_marker_scale': '0.38',
        },
    }
    _line_end_markers: ClassVar[tuple] = (
        (
            'PreviewLineEnd0',
            'M 5.77,0.0 L -2.88,5.0 L -2.88,-5.0 L 5.77,0.0 z',
            'toolpath_end_marker',
            'scale(%s) translate(-4.5,0)',
        ),
        (
            'PreviewLineEnd1',
            'M 5.77,0.0 L -2.88,5.0 L -2.88,-5.0 L 5.77,0.0 z',
            'toolpath_end_marker',
            'scale(-%s) translate(-4.5,0)',
        ),
        (
            'PreviewLineEnd2',
            'M 5.77,0.0 L -2.88,5.0 L -2.88,-5.0 L 5.77,0.0 z',
            'movepath_end_marker',
            'scale(%s) translate(-4.5,0)',
        ),
    )

    def __init__(
        self,
        svg_context: inksvg.InkscapeSVGContext,
        tool_offset: float = 0,
        tool_width: float = 0,
        toolmark_line_interval: float | None = None,
        toolmark_rotation_interval: float | None = None,
        style_scale: str = 'small',
        show_toolmarks: bool = False,
        show_tm_outline: bool = False,
        flip_y_axis: bool = True,
    ) -> None:
        """Constructor.

        Args:
            svg_context: An instance of svg.SVGContext to render output.
            tool_offset: Tangential tool offset. Optional, default is 0.
            tool_width: Tangential tool width. Optional, default is 0.
            toolmark_line_interval: Spacing of tool marks along straight lines.
                Specified in SVG user units.
            toolmark_rotation_interval: Spacing of tool marks along arcs.
                Specified in radians.
            style_scale: Scale of preview lines and glyphs. String.
                Can be 'small', 'medium', or 'large'. Default is 'medium'.
            show_toolmarks: Show a preview of the tangent tool if True.
            show_tm_outline: Show outline of tool mark path.
            flip_y_axis: Flip Y axis so that toolpath origin is at lower left.
        """
        self.svg = svg_context
        # Tangential tool offset.
        self.tool_offset = tool_offset
        # Tangential tool width.
        self.tool_width = tool_width
        # Tool mark interval along lines and arcs. In user units.
        if toolmark_line_interval is None:
            interval = self.svg.unit2uu(_DEFAULT_TOOLMARK_INTERVAL_LINE)
            self.toolmark_line_interval = interval
        else:
            self.toolmark_line_interval = toolmark_line_interval
        # Tool mark interval for in place rotation. In radians.
        if toolmark_rotation_interval is None:
            self.toolmark_rotation_interval = _DEFAULT_TOOLMARK_INTERVAL_ANGLE
        else:
            self.toolmark_rotation_interval = toolmark_rotation_interval

        nonzero_toolwidth = not geom2d.is_zero(self.tool_width)
        self.show_toolmarks = nonzero_toolwidth and show_toolmarks
        self.show_tm_outline = nonzero_toolwidth and show_tm_outline
        self.flip_y_axis = flip_y_axis

        # Initialize CSS styles used for rendering
        style_scale_values = self._style_scale_defaults[style_scale]
        self._style_defaults.update(style_scale_values)
        self._styles.update(
            self.svg.styles_from_templates(self._styles, self._style_defaults)
        )

        # Create layers that will contain the G code preview
        if self.show_tm_outline:
            # This layer goes underneath the others
            self.outline_layer = self.svg.create_layer(
                OUTLINE_LAYER_NAME,
                incr_suffix=self.incr_layer_suffix,
                flipy=self.flip_y_axis,
            )
        if self.show_toolmarks:
            self.tool_layer = self.svg.create_layer(
                TOOL_LAYER_NAME,
                incr_suffix=self.incr_layer_suffix,
                flipy=self.flip_y_axis,
            )
        self.path_layer = self.svg.create_layer(
            PATH_LAYER_NAME,
            incr_suffix=self.incr_layer_suffix,
            flipy=self.flip_y_axis,
        )
        svg_context.set_default_parent(self.path_layer)

        # Create Inkscape line end marker glyphs
        for marker in self._line_end_markers:
            transform = marker[3] % style_scale_values['end_marker_scale']
            self.svg.create_simple_marker(
                marker[0],
                marker[1],
                self._styles[marker[2]],
                transform,
                replace=True,
            )
        # Non-offset tangent lines - used to make offset lines
        self.toolmarks = []
        self.toolmark_segments = []

    def plot_move(self, endp: gcode.TCoord) -> None:
        """Plot G00 - rapid move from current position to :endp:(x,y,z,a)."""
        self.svg.create_line(self._current_xy, endp, self._styles['moveline'])
        self._update_location(endp)

    def plot_feed(self, endp: gcode.TCoord) -> None:
        """Plot G01 - linear feed from current position to :endp:(x,y,z,a)."""
        if self.show_toolmarks:
            self._draw_tool_marks(
                geom2d.Line(self._current_xy, endp),
                start_angle=self._current_a,
                end_angle=endp[3],
            )
        if self._current_xy.distance(endp) > geom2d.const.EPSILON:
            self.svg.create_line(
                self._current_xy, endp, self._styles['feedline']
            )
        self._update_location(endp)

    def plot_arc(
        self, center: geom2d.TPoint, endp: gcode.TCoord, clockwise: bool
    ) -> None:
        """Plot G02/G03 - arc feed from current position to :endp:(x,y,z,a)."""
        center = geom2d.P(center)
        radius = center.distance(self._current_xy)
        # assert(self.gc.float_eq(center.distance(endp), radius))
        assert self.gc
        if not self.gc.float_eq(center.distance(endp), radius):
            logging.getLogger(__name__).debug(
                'Degenerate arc: d1=%f, d2=%f', center.distance(endp), radius
            )

        # Draw the tool marks
        if self.show_toolmarks:
            angle = center.angle2(self._current_xy, endp)
            arc = geom2d.Arc(self._current_xy, endp, radius, angle, center)
            self._draw_tool_marks(arc, self._current_a, endp[3])

        # Draw the tool path
        sweep_flag = 0 if clockwise else 1
        style = self._styles['feedline']
        self.svg.create_circular_arc(
            self._current_xy, endp, radius, sweep_flag, style
        )
        self._update_location(endp)

    def plot_tool_down(self) -> None:
        """Plot the beginning of a tool path."""
        # This should signal the start of a tool path.
        #        logger.debug('tool down')
        #        geom2d.debug.draw_point(self._current_xy, color='#00ff00')
        self.toolmarks = []
        self.toolmark_segments = []

    def plot_tool_up(self) -> None:
        """Plot the end of a tool path."""
        # This should signal the end of a tool path.
        # logger.debug('tool up')
        # geom2d.debug.draw_point(self._current_xy, color='#ff0000')
        # Just finish up by drawing the approximate tool path outline.
        if self.show_tm_outline and self.tool_layer is not None:
            self._draw_toolmark_outline()
        if self.x_subpath_render:
            self._draw_subpaths()

    def _draw_tool_marks(
        self,
        segment: geom2d.Line | geom2d.Arc,
        start_angle: float,
        end_angle: float,
    ) -> None:
        """Draw marks showing the angle and travel of the tangential tool."""
        seglen = segment.length()
        rotation = end_angle - start_angle
        if seglen > 0:
            num_markers = int(seglen / self.toolmark_line_interval)
            num_markers = max(1, num_markers)
        else:
            num_markers = int(abs(rotation) / self.toolmark_rotation_interval)
            num_markers = max(1, num_markers)
        angle_incr = rotation / num_markers
        point_incr = 1.0 / num_markers
        angle = start_angle
        u = 0.0
        while u < (1.0 + geom2d.const.EPSILON):
            self._draw_tool_mark(segment, u, angle)
            angle += angle_incr
            u += point_incr

    def _draw_tool_mark(
        self, segment: geom2d.Line | geom2d.Arc, u: float, angle: float
    ) -> None:
        """Draw the tool mark as a simple T shape."""
        # This will be the midpoint of the tool mark line.
        p = segment.point_at(u)
        assert self.gc
        if not self.gc.float_eq(self.tool_offset, 0):
            # Calculate and draw the tool offset mark.
            px = p + geom2d.P.from_polar(self.tool_offset, angle - math.pi)
            if self.show_toolmarks:
                self.svg.create_line(
                    p, px, self._styles['tooloffset'], parent=self.tool_layer
                )
        else:
            # No tool offset
            px = p
        # Calculate the endpoints of the tool mark.
        r = self.tool_width / 2
        p1 = px + geom2d.P.from_polar(r, angle + math.pi / 2)
        p2 = px + geom2d.P.from_polar(r, angle - math.pi / 2)
        toolmark_line = geom2d.Line(p1, p2)
        # if not self.toolmarks or not toolmark_line.is_coincident(
        #    self.toolmarks[-1]
        # ):
        if self.show_toolmarks and (
            not self.toolmarks or toolmark_line != self.toolmarks[-1]
        ):
            self.svg.create_line(
                p1, p2, self._styles['toolmark'], parent=self.tool_layer
            )
        # Save toolmarks for toolpath outline and sub-path creation
        self.toolmarks.append(toolmark_line)
        self.toolmark_segments.append(segment)

    def _draw_toolmark_outline(self) -> None:
        """Draw an approximation of the tangent toolpath outline."""
        if len(self.toolmarks) < 2:  # noqa: PLR2004
            return

        if _DEBUG:
            # Find and show all the intersections of adjacent
            # toolmark line segments.
            # These generally mark tool edge reversals.
            prev_toolmark = self.toolmarks[0]
            for toolmark in self.toolmarks[1:]:
                p = prev_toolmark.intersection(toolmark, segment=True)
                if p:
                    geom2d.debug.draw_point(p, color='#ff0000')
                prev_toolmark = toolmark

        p1s, p2s = zip(*self.toolmarks)
        points_1 = list(p1s)
        points_2 = list(p2s)
        points_2.reverse()
        side_1 = _make_outline_path(points_1)
        side_2 = _make_outline_path(points_2)
        if not side_1 or not side_2:
            return

        # TODO: add non-g1 hints at natural outline cusps
        # to avoid over-smoothing
        # Smooth out the tool outlines
        # side_1 = geom2d.bezier.smooth_path(side_1)
        # side_2 = geom2d.bezier.smooth_path(side_2)

        outline = side_1
        # outline.extend(side_1)
        outline.append(geom2d.Line(side_1[-1].p2, side_2[0].p1))
        outline.extend(side_2)
        style = self._styles['toolmark_outline']
        self.svg.create_polypath(
            outline, close_path=True, style=style, parent=self.outline_layer
        )

    def _draw_subpaths(self) -> None:
        """Experimental: Create some offset paths."""
        if len(self.toolmarks) < 2:  # noqa: PLR2004
            return
        if self.x_subpath_layer is None:
            self.x_subpath_layer = self.svg.create_layer(
                self.x_subpath_layer_name,
                incr_suffix=self.incr_layer_suffix,
                flipy=self.flip_y_axis,
            )
        offset = self.x_subpath_offset
        # All toolmark lines are the same length, so use the first one
        length = self.toolmarks[0].length()
        while offset < length:
            offset_pts = []
            for line in self.toolmarks:
                p = line.point_at(offset / line.length())
                offset_pts.append(p)
            path = _make_outline_path(offset_pts)
            path = _simplify_path(path, self.x_subpath_maxdist)
            smooth_path = geom2d.bezier.smooth_path(
                path, smoothness=self.x_subpath_smoothness
            )
            self.svg.create_polypath(
                smooth_path,
                style=self._styles['subpath'],
                parent=self.x_subpath_layer,
            )
            offset += self.x_subpath_offset

    def _update_location(self, endp: gcode.TCoord) -> None:
        self._current_xy = geom2d.P(endp[0], endp[1])
        self._current_z = endp[2]
        self._current_a = endp[3]


def _make_outline_path(points: Sequence[geom2d.TPoint]) -> list[geom2d.Line]:
    path: list[geom2d.Line] = []
    prev_pt = points[0]
    for next_pt in points[1:]:
        if next_pt != prev_pt:
            # TODO: use toolmark_segments to determine line/arc
            # Simplify the outline by skipping inline nodes.
            if path and path[-1].which_side(next_pt, inline=True) == 0:
                prev_line = path.pop()
                next_line = geom2d.Line(prev_line.p1, next_pt)
            else:
                next_line = geom2d.Line(prev_pt, next_pt)
            path.append(next_line)
        prev_pt = next_pt
    # path = _fix_intersections(path)
    # path = _fix_reversals(path)
    return path


def _simplify_path(
    path: Sequence[geom2d.Line], tolerance: float
) -> list[geom2d.Line]:
    points1, points2 = (list(points) for points in zip(*path))
    # points1 = list(points1)
    # points2 = list(points2)
    points1.append(points2[-1])
    points = polygon.simplify_polyline_rdp(points1, tolerance)
    new_path = []
    prev_pt = points[0]
    for next_pt in points[1:]:
        next_line = geom2d.Line(prev_pt, next_pt)
        new_path.append(next_line)
        prev_pt = next_pt
    return new_path


def _fix_intersections(path: Sequence[geom2d.Line]) -> Sequence[geom2d.Line]:
    """Collapse self-intersecting loops."""
    # See: https://en.wikipedia.org/wiki/Bentley-Ottmann_algorithm
    # for a more efficient sweepline method O(Nlog(N)).
    # This is the bonehead way: O(n**2), but it's fine for
    # reasonable path lengths...
    # See: winding numbers. intersecting loops should match
    # underlying toolpath winding.
    fixed_path: list[geom2d.Line] = []
    skip_ahead = 0
    for i, line1 in enumerate(path):
        if i < skip_ahead:
            continue
        p = None
        for j, line2 in enumerate(path[(i + 2) :]):
            p = line1.intersection(line2, segment=True)
            if p is not None:
                geom2d.debug.draw_point(p, color='#ffc000')
                fixed_path.extend(
                    (geom2d.Line(line1.p1, p), geom2d.Line(p, line2.p2))
                )
                skip_ahead = i + j + 3
                break
        # fixed_path.append(line1)
        if p is None:
            fixed_path.append(line1)
    return fixed_path


def _fix_reversals(
    path: Sequence[geom2d.Line | geom2d.Arc],
) -> Sequence[geom2d.Line | geom2d.Arc]:
    """Collapse path reversals.

    This is when the next segment direction is more than 90deg from
    current segment direction...
    """
    # This works in O(n) time...
    skip_ahead = 0
    line1 = path[0]
    fixed_path = []
    for i, line2 in enumerate(path[1:]):
        if i < skip_ahead:
            continue
        skip_ahead = 0
        angle = line1.p2.angle2(line1.p1, line2.p2)
        next_line = line2
        if abs(angle) < math.pi / 2:
            if angle > 0:
                # Right turn - corner is poking outwards.
                # geom2d.debug.draw_point(line1.p2, color='#0000ff')
                # Move forward until next reversal
                for j, line3 in enumerate(path[(i + 1) :]):
                    angle = line1.p2.angle2(line1.p1, line3.p2)
                    if abs(angle) > math.pi / 2:
                        # geom2d.debug.draw_line(line2, color='#ff0000')
                        next_line = geom2d.Line(line1.p2, line3.p2)
                        skip_ahead = i + j + 1
                        break
                    next_line = line3
            else:
                # Left turn - corner is poking inwards.
                # geom2d.debug.draw_point(line1.p2, color='#ff0000')
                # Move forward until next reversal
                for j, line3 in enumerate(path[(i + 1) :]):
                    line1 = geom2d.Line(line1.p1, line3.p1)
                    angle = line1.p2.angle2(line1.p1, line3.p2)
                    if abs(angle) > math.pi / 2:
                        skip_ahead = i + j + 1
                        break
                    next_line = line3
        fixed_path.append(line1)
        line1 = next_line
    fixed_path.append(line1)
    return fixed_path
