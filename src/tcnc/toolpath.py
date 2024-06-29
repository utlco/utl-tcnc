"""Toolpath wrapper."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Union

import geom2d

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from typing_extensions import TypeAlias


_MIN_TOOLPATH_LEN = 3


class ToolpathError(Exception):
    """Error processing toolpath."""


class ToolpathArc(geom2d.Arc):
    """geom2d.Arc with toolpath render hints."""

    inline_start_angle: float
    inline_end_angle: float
    inline_z: float
    inline_ignore_a: bool
    inline_ignore_g1: bool


class ToolpathLine(geom2d.Line):
    """geom2d.Line with toolpath render hints."""

    inline_start_angle: float
    inline_end_angle: float
    inline_z: float
    inline_ignore_a: bool
    inline_ignore_g1: bool


ToolpathSegment: TypeAlias = Union[ToolpathArc, ToolpathLine]


def toolpath_segment(
    segment: geom2d.Line | geom2d.Arc | ToolpathSegment,
) -> ToolpathSegment:
    """Create a ToolpathSegment subtype if not already."""
    if not isinstance(segment, (ToolpathLine, ToolpathArc)):
        if isinstance(segment, geom2d.Line):
            segment = ToolpathLine(*segment)
        elif isinstance(segment, geom2d.Arc):
            segment = ToolpathArc(*segment)
        else:
            msg = f'Invalid toolpath segment type {type(segment)}'
            raise TypeError(msg)
    return segment


def transfer_hints(
    proto_segment: ToolpathSegment,
    segment: geom2d.Line | geom2d.Arc | ToolpathSegment,
) -> ToolpathSegment:
    """Transfer render hints.

    Returns:
        A copy of the segment if it is not already
        a ToolpathArc or ToolpathLine,
        otherwise the segment. With render hints from proto.
    """
    segment = toolpath_segment(segment)
    # segment.inline_start_angle = proto_segment.inline_start_angle
    # segment.inline_end_angle = proto_segment.inline_end_angle
    # segment.inline_z = proto_segment.inline_z
    # segment.inline_ignore_a = proto_segment.inline_ignore_a
    # segment.inline_ignore_g1 = proto_segment.inline_ignore_g1
    for name in vars(proto_segment):
        if name.startswith('inline_'):
            setattr(segment, name, getattr(proto_segment, name))

    return segment


def seg_start_angle(segment: geom2d.Line | geom2d.Arc) -> float:
    """The tangent angle of this segment at the first end point.

    If there is a cam segment hint attribute ('inline_start_angle')
    its value will be returned instead.
    """
    return getattr(segment, 'inline_start_angle', segment.start_tangent_angle())


def seg_end_angle(segment: geom2d.Line | geom2d.Arc) -> float:
    """The tangent angle of this segment at the last end point.

    If there is a cam segment hint  attribute ('inline_end_angle')
    its value will be returned instead.
    """
    return getattr(segment, 'inline_end_angle', segment.end_tangent_angle())


class Toolpath(list[ToolpathSegment]):
    """A Toolpath is an ordered list of Line and Arc segments."""

    @staticmethod
    def toolpath(
        path: Iterable[geom2d.Line | geom2d.Arc | geom2d.CubicBezier],
        biarc_tolerance: float = 0.001,
        biarc_max_depth: float = 4,
        biarc_line_flatness: float = 0.001,
    ) -> Toolpath:
        """Create a Toolpath from geometry path.

        CubicBezier segments are approximated with biarcs.
        """
        return Toolpath(
            Toolpath.toolpath_iter(
                path, biarc_tolerance, biarc_max_depth, biarc_line_flatness
            )
        )

    @staticmethod
    def toolpath_iter(
        path: Iterable[geom2d.Line | geom2d.Arc | geom2d.CubicBezier],
        biarc_tolerance: float = 0.001,
        biarc_max_depth: float = 4,
        biarc_line_flatness: float = 0.001,
    ) -> Iterator[ToolpathLine | ToolpathArc]:
        """Create a Toolpath iterator from geometry path.

        CubicBezier segments are approximated with biarcs.
        """
        for segment in path:
            if segment.p1 == segment.p2:
                # Skip zero length segments
                continue
            if isinstance(segment, geom2d.CubicBezier):
                # Convert Bezier curves to biarcs.
                biarcs = segment.biarc_approximation(
                    tolerance=biarc_tolerance,
                    max_depth=biarc_max_depth,
                    line_flatness=biarc_line_flatness,
                )
                for biarc_seg in biarcs:
                    if isinstance(biarc_seg, geom2d.Arc):
                        yield ToolpathArc(*biarc_seg)
                    else:
                        yield ToolpathLine(*biarc_seg)
            elif isinstance(segment, geom2d.Line):
                yield ToolpathLine(*segment)
            elif isinstance(segment, geom2d.Arc):
                if abs(segment.angle) < math.pi / 2:
                    yield ToolpathArc(*segment)
                else:
                    # Keep arcs under 90deg. to simplify toolpath processing.
                    for arc in _subdivide_arc(segment):
                        yield ToolpathArc(*arc)
            elif isinstance(segment, (ToolpathLine, ToolpathArc)):
                # Already converted segment. Shouldn't happen.
                yield segment
            else:
                msg = f'Unexpected path segment type: {type(segment)}'
                raise TypeError(msg)

    def path_reversed(self) -> None:
        """Reverse in place the order of path segments and flip each segment."""
        self.reverse()
        for i, segment in enumerate(self):
            self[i] = transfer_hints(segment, segment.path_reversed())

    def verify_continuity(self) -> bool:
        """Verify that this path has point continuity (C0/G0)."""
        prev_seg = self[0]
        for segment in self[1:]:
            if prev_seg.p2 != segment.p1:
                return False
            prev_seg = segment
        return True

    def is_closed(self) -> bool:
        """Return True if this path forms a closed polygon."""
        return len(self) >= _MIN_TOOLPATH_LEN and self[0].p1 == self[-1].p2


def _subdivide_arc(arc: geom2d.Arc) -> list[geom2d.Arc]:
    """Subdivide arc if the sweep angle is larger than PI/2."""
    mu = 1 / ((abs(arc.angle) + (math.pi / 4)) / (math.pi / 2))
    smaller_arcs: list[geom2d.Arc] = []
    arc2: geom2d.Arc | None = arc
    while arc2 and abs(arc2.angle) > (math.pi / 2):
        arcs = arc2.subdivide(mu)
        smaller_arcs.append(arcs[0])
        arc2 = arcs[1] if len(arcs) > 1 else None
    if arc2:
        smaller_arcs.append(arc2)
    return smaller_arcs
