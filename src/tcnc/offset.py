"""Offset Line/Arc segments in a tool path to compensate for tool trail offset."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import geom2d

from . import toolpath

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


DEFAULT_TOLERANCE = 0.0001
DEFAULT_FLATNESS = 0.0001


def offset_path(
    path: toolpath.Toolpath,
    offset: float,
    min_arc_dist: float,
    g1_tolerance: float | None = None,
) -> toolpath.Toolpath:
    """Recalculate path to compensate for a trailing tangential offset.

    This will shift all of the segments by `offset` amount. Arcs will
    be recalculated to correct for the shift offset.

    Args:
        path: The path to recalculate.
        offset: The amount of tangential tool trail.
        min_arc_dist: The minimum distance between two connected
            segment end points that can be bridged with an arc.
            A line will be used if the distance is less than this.
        g1_tolerance: The tangent angle tolerance to determine if
            two segments are g1 continuous.

    Returns:
        A new path

    Raises:
        :class:`cam.toolpath.ToolpathError`: if the path contains segment
            types other than Line or Arc.
    """
    if geom2d.float_eq(offset, 0.0):
        return path

    # New offset path
    o_path = toolpath.Toolpath()

    prev_seg = None
    prev_offset_seg = None
    for seg in path:
        if seg.p1 == seg.p2:
            # Skip zero length segments
            continue

        # The toolpath should be just Line and Arc segments at this point.
        if isinstance(seg, geom2d.Line):
            # Line segments are easy - just shift them forward by offset
            offset_seg = toolpath.transfer_hints(seg, seg.shift(offset))
        elif isinstance(seg, geom2d.Arc):
            offset_seg = toolpath.transfer_hints(seg, offset_arc(seg, offset))
        else:
            raise toolpath.ToolpathError('Unrecognized path segment type.')

        # Fix discontinuities caused by offsetting non-G1 segments
        if prev_seg is not None:
            if prev_offset_seg.p2 != offset_seg.p1:
                seg_distance = prev_offset_seg.p2.distance(offset_seg.p1)
                # If the distance between the two segments is less than the
                # minimum arc distance or if the segments are G1 continuous
                # then just insert a connecting line.
                if seg_distance < min_arc_dist or geom2d.segments_are_g1(
                    prev_offset_seg, offset_seg, g1_tolerance
                ):
                    connect_seg = toolpath.ToolpathLine(
                        prev_offset_seg.p2, offset_seg.p1
                    )
                else:
                    # Insert an arc in tool path to rotate the tool to the next
                    # starting tangent when the segments are not G1 continuous.
                    # TODO: avoid creating tiny segments by extending
                    # offset segment.
                    p1 = prev_offset_seg.p2
                    p2 = offset_seg.p1
                    angle = prev_seg.p2.angle2(p1, p2)
                    # TODO: This should be a straight line if the arc is tiny
                    connect_seg = toolpath.ToolpathArc(
                        p1, p2, offset, angle, prev_seg.p2
                    )
                # if connect_seg.length() < 0.01:
                #    logger.debug('tiny arc! length= %f, radius=%f, angle=%f',
                #        connect_seg.length(), connect_seg.radius,
                #        connect_seg.angle)
                connect_seg.inline_start_angle = prev_seg.end_tangent_angle()
                connect_seg.inline_end_angle = seg.start_tangent_angle()
                o_path.append(connect_seg)
                prev_offset_seg = connect_seg
            elif (
                geom2d.segments_are_g1(prev_seg, seg, g1_tolerance)
                and not hasattr(prev_seg, 'inline_ignore_g1')
                and not hasattr(seg, 'inline_ignore_g1')
            ):
                # Add hint for smoothing pass
                prev_offset_seg.g1 = True

        prev_seg = seg
        prev_offset_seg = offset_seg
        o_path.append(offset_seg)

    # Compensate for starting angle
    start_angle = (o_path[0].p1 - path[0].p1).angle()
    o_path[0].inline_start_angle = start_angle
    return o_path


def offset_arc(
    arc: toolpath.ToolpathArc, offset: float
) -> toolpath.ToolpathArc:
    """Offset the arc by the specified offset."""
    start_angle = arc.start_tangent_angle()
    end_angle = arc.end_tangent_angle()
    p1 = arc.p1 + geom2d.P.from_polar(offset, start_angle)
    p2 = arc.p2 + geom2d.P.from_polar(offset, end_angle)
    radius = math.hypot(offset, arc.radius)
    o_arc = toolpath.ToolpathArc(p1, p2, radius, arc.angle, arc.center)
    o_arc.inline_start_angle = start_angle
    o_arc.inline_end_angle = end_angle
    return o_arc


def fix_g1_path(
    path: toolpath.Toolpath,
    tolerance: float,
    line_flatness: float,
) -> toolpath.Toolpath:
    """Add smoothing arcs to fix formerly G1 continuous offset segments.

    Tool-width compensation fillets are ignored.
    """
    new_path = toolpath.Toolpath()
    if len(path) < 2:  # noqa: PLR2004
        return path
    seg1 = path[0]
    cp1 = seg1.p1
    for seg2 in path[1:]:
        if getattr(seg1, 'g1', False):
            arcs, cp1 = smoothing_arcs(
                seg1,
                seg2,
                cp1,
                tolerance=tolerance,
                max_depth=1,
                line_flatness=line_flatness,
            )
            new_path.extend(arcs)
        else:
            cp1 = seg2.p1
            new_path.append(seg1)
        seg1 = seg2
    # Process last segment...
    if getattr(seg1, 'g1', False):
        arcs, cp1 = smoothing_arcs(
            seg1,
            None,
            cp1,
            tolerance=tolerance,
            max_depth=1,
            line_flatness=line_flatness,
        )
        new_path.extend(arcs)
    else:
        new_path.append(seg1)
    return new_path


def smoothing_arcs(
    seg1: toolpath.ToolpathSegment,
    seg2: toolpath.ToolpathSegment | None,
    cp1: tuple[float, float] | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
    line_flatness: float = DEFAULT_FLATNESS,
    max_depth: float = 1,
    match_arcs: bool = True,
) -> tuple[Sequence[toolpath.ToolpathSegment], geom2d.P]:
    """Create circular smoothing biarcs between two segments.

    Assuming the segments are not currently G1 continuous.

    Args:
        seg1: First path segment containing first and second points.
            Can be a geom2d.Line or geom2d.Arc.
        seg2: Second path segment containing second and third points.
            Can be a geom2d.Line or geom2d.Arc.
        cp1: Control point computed from previous invocation.
        tolerance: Biarc matching tolerance.
        line_flatness: Curve to line tolerance.
        max_depth: Max Bezier subdivision recursion depth.
        match_arcs: Attempt to more closely match existing arc segments.
            Default is True.

    Returns:
        A tuple containing a list of biarc segments and the control point
        for the next curve.
    """
    curve, cp1 = geom2d.bezier.smoothing_curve(seg1, seg2, cp1, match_arcs)
    # geom2d.debug.draw_bezier(curve, color='#00ff44') #DEBUG
    biarc_segs = curve.biarc_approximation(
        tolerance=tolerance, max_depth=max_depth, line_flatness=line_flatness
    )
    if not biarc_segs:
        return (
            [
                seg1,
            ],
            seg1.p2,
        )
    # Compute total arc length of biarc approximation
    biarc_length: float = 0
    for seg in biarc_segs:
        biarc_length += seg.length()
    # Fix inline rotation hints for each new arc segment.
    a_start = toolpath.seg_start_angle(seg1)
    a_end = a_start
    sweep = geom2d.normalize_angle(
        toolpath.seg_end_angle(seg1) - a_start, center=0.0
    )
    sweep_scale = sweep / biarc_length
    toolpath_biarcs: list[toolpath.ToolpathSegment] = []
    for seg in [toolpath.toolpath_segment(s) for s in biarc_segs]:
        a_end = a_start + (seg.length() * sweep_scale)
        seg.inline_start_angle = a_start
        seg.inline_end_angle = a_end
        a_start = a_end
        toolpath_biarcs.append(seg)
    return (toolpath_biarcs, cp1)
