"""Connect Line/Arc segments with a fillet arc.

Note: This overrides geom2d.fillet.fillet_path to handle
and preserve toolpath hints.
"""

from __future__ import annotations

import geom2d
import geom2d.fillet

from . import toolpath
from .toolpath import ToolpathArc, ToolpathSegment

_MIN_PATH = 2


def fillet_toolpath(
    path: toolpath.Toolpath,
    radius: float,
    fillet_close: bool = True,
    adjust_rotation: bool = False,
    mark_fillet: bool = False,
) -> toolpath.Toolpath:
    """Add fillets to path.

    Attempt to insert a circular arc of the specified radius
    to blend adjacent path segments that have C0 or G0 continuity.

    Args:
        path: List of geom2d.Line or geom2d.Arc segments.
        radius: Fillet radius.
        fillet_close: If True and the path is closed then
            add a terminating fillet. Default is False.
        adjust_rotation: If True adjust the A axis rotation hints
            to compensate for the offset caused by the fillet.
        mark_fillet: If True add an attribute to the fillet arc
            to mark it to ignore G1. Default is False.

    Returns:
        A new path with fillet arcs. If no fillets are created then
        the original path will be returned.
    """
    if radius < geom2d.const.EPSILON or len(path) < _MIN_PATH:
        return path

    new_path = toolpath.Toolpath()

    seg1 = path[0]
    for seg2 in path[1:]:
        new_segs = _create_adjusted_fillet(
            seg1,
            seg2,
            radius,
            adjust_rotation=adjust_rotation,
            mark_fillet=mark_fillet,
        )
        if new_segs:
            new_path.extend(new_segs[:-1])
            seg1 = new_segs[-1]
        else:
            new_path.append(seg1)
            seg1 = seg2

    new_path.append(seg1)

    # Close the path with a fillet
    if fillet_close and len(path) > _MIN_PATH and path[0].p1 == path[-1].p2:
        # geom2d.debug.draw_point(path[0].p1, color='#0000ff')
        # geom2d.debug.draw_point(path[-1].p2, color='#00ffff')
        new_segs = _create_adjusted_fillet(
            new_path[-1],
            new_path[0],
            radius,
            adjust_rotation=adjust_rotation,
            mark_fillet=mark_fillet,
        )
        if new_segs:
            new_path[-1] = new_segs[0]
            new_path.append(new_segs[1])
            new_path[0] = new_segs[2]

    # Discard the path copy if no fillets were created...
    return new_path if len(new_path) > len(path) else path


def _create_adjusted_fillet(
    seg1: ToolpathSegment,
    seg2: ToolpathSegment,
    radius: float,
    adjust_rotation: bool = False,
    mark_fillet: bool = False,
) -> tuple | tuple[ToolpathSegment, ToolpathArc, ToolpathSegment]:
    """Try to create a fillet between two segments.

    Any GCode rendering hints attached to the segments will
    be preserved.

    Args:
        seg1: First segment, an Arc or a Line.
        seg2: Second segment, an Arc or a Line.
        radius: Fillet radius.
        adjust_rotation: If True adjust the A axis rotation hints
            to compensate for the offset caused by the fillet.
        mark_fillet: If True add an attribute to the fillet arc
            to mark it to ignore G1. Default is False.

    Returns:
        A tuple containing the adjusted segments and fillet arc
        (seg1, fillet_arc, seg2),
        or an empty tuple if the segments cannot be connected
        with a fillet arc (either they are too small, already G1
        continuous, or are somehow degenerate.)
    """
    if geom2d.segments_are_g1(seg1, seg2):
        # geom2d.debug.draw_point(seg2.p1, color='#0000ff')
        # Segments are already tangentially connected (G1)
        return ()

    arc = geom2d.fillet.create_fillet_arc(seg1, seg2, radius)
    if arc is None:
        return ()

    farc = ToolpathArc(*arc)
    if mark_fillet:
        # Mark fillet as connecting two possible non-G1 segments
        farc.inline_ignore_g1 = True

    new_segs = geom2d.fillet.connect_fillet(seg1, farc, seg2)
    if not new_segs:
        return ()
    fseg1 = toolpath.toolpath_segment(new_segs[0])
    fseg2 = toolpath.toolpath_segment(new_segs[2])

    if adjust_rotation:
        # Adjust the A axis rotation hints to
        # compensate for the offset caused by a fillet arc.
        seg1_start_angle = seg1.start_tangent_angle()
        seg1_end_angle = seg1.end_tangent_angle()
        mu = 1.0 - seg1.mu(farc.p1)
        seg1_offset_angle = (
            geom2d.calc_rotation(seg1_start_angle, seg1_end_angle) * mu
        )
        if not geom2d.is_zero(seg1_offset_angle):
            fseg1.inline_end_angle = seg1_end_angle - seg1_offset_angle
            farc.inline_start_angle = fseg1.inline_end_angle
        else:
            farc.inline_start_angle = seg1_end_angle

        seg2_start_angle = seg2.start_tangent_angle()
        seg2_end_angle = seg2.end_tangent_angle()
        mu = seg2.mu(farc.p2)
        seg2_offset_angle = (
            geom2d.calc_rotation(seg2_start_angle, seg2_end_angle) * mu
        )
        if not geom2d.is_zero(seg2_offset_angle):
            seg2.inline_start_angle = seg2_start_angle + seg2_offset_angle
            farc.inline_end_angle = seg2.inline_start_angle
        else:
            farc.inline_end_angle = seg2_start_angle

    return (fseg1, farc, fseg2)
