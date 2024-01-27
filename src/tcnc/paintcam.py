"""CAM module specifically for a brush type tool."""

from __future__ import annotations

import math

import geom2d

from . import gcode, simplecam, toolpath


class PaintCAM(simplecam.SimpleCAM):
    """CAM interface for a brush-type tool."""

    # : Add overshoot to path end
    brush_overshoot_enable: bool = False
    # : Use tool width to determine overshoot
    # : Overrides manual overshoot distance
    brush_overshoot_auto: bool = False
    # : Manual overshoot distance
    brush_overshoot_distance: float = 0
    # : Add a soft landing to lower tool during feed at start of path.
    brush_soft_landing: bool = False
    # : Landing strip distance to prepend to start of path
    brush_landing_strip: float = 0

    # : Enable brush reload sequence
    brush_reload_enable: bool = False
    # : Enable rotation to reload angle before pause.
    brush_reload_rotate: bool = False
    # : Brush reload angle.
    brush_reload_angle: float = 0
    # : Pause/dwell brush at reload (after rotation).
    brush_reload_pause: bool = False
    # : Dwell time for brush reload.
    brush_reload_dwell: float = 0
    # : Number of paths to process before brush reload.
    brush_reload_max_paths: int = 1

    def __init__(self, gc: gcode.GCodeGenerator) -> None:
        """Constructor.

        Args:
            gc: a GCodeGenerator instance
        """
        super().__init__(gc)
        self.brush_overshoot_distance = self.tool_trail_offset

    def postprocess_toolpaths(
        self, path_list: list[toolpath.Toolpath]
    ) -> list[toolpath.Toolpath]:
        """Create brush overshoots.

        Overrides SimpleCAM.postprocess_toolpaths() to handle brush
        specific path post processing.
        """
        for path in path_list:
            self._process_brush_path(path)

        return path_list

    def generate_rapid_move(self, path: toolpath.Toolpath) -> None:
        """Generate G code for a rapid move to the beginning of the tool path."""
        if (
            self.brush_reload_enable
            # and (self._path_count % self.brush_reload_max_paths) == 0
        ):
            start_segment = path[0]
            if self.brush_reload_rotate:
                # Coordinated move to XY and A reload angle
                rotation = geom2d.calc_rotation(
                    self.current_angle, self.brush_reload_angle
                )
                self.current_angle += rotation
                self.gc.rapid_move(
                    start_segment.p1.x, start_segment.p1.y, a=self.current_angle
                )
            else:
                self.gc.rapid_move(start_segment.p1.x, start_segment.p1.y)
            if self.brush_reload_dwell > 0:
                self.gc.dwell(self.brush_reload_dwell)
            elif self.brush_reload_pause:
                self.gc.pause()
        super().generate_rapid_move(path)

    def _process_brush_path(self, path: toolpath.Toolpath) -> None:
        # Prepend a landing strip if any
        if self.brush_landing_strip > self.gc.tolerance:
            self._prepend_landing_strip(path)

        # Then prepend the soft landing segment.
        if self.brush_soft_landing and self.tool_trail_offset > self.gc.tolerance:
            _prepend_soft_landing(path)

        # Append overshoot segments if brush overshoot is enabled
        if self.brush_overshoot_enable:
            _append_overshoot(path)

    def _prepend_landing_strip(self, path: toolpath.Toolpath) -> None:
        """Prepend a landing strip."""
        start_angle = toolpath.seg_start_angle(path[0]) + math.pi
        delta = geom2d.P.from_polar(self.brush_landing_strip, start_angle)
        segment = toolpath.ToolpathLine(path[0].p1 + delta, path[0].p1)
        if hasattr(path[0], 'inline_start_angle'):
            segment.inline_end_angle = path[0].inline_start_angle
        path.insert(0, segment)

    def _prepend_soft_landing(self, path: toolpath.Toolpath) -> None:
        """Prepend a soft landing strip."""
        start_angle = toolpath.seg_start_angle(path[0]) + math.pi
        delta = geom2d.P.from_polar(self.tool_trail_offset, start_angle)
        segment = toolpath.ToolpathLine(path[0].p1 + delta, path[0].p1)

        if hasattr(path[0], 'inline_start_angle'):
            segment.inline_end_angle = path[0].inline_start_angle

        path.insert(0, segment)

        # d = max(self.tool_trail_offset, 0.01)
        # if first_segment.length() > d:
        #     # If the segment is longer than the brush trail
        #     # cut it into two segments and use the first as the landing.
        #     seg1, seg2 = first_segment.subdivide(
        #           d / first_segment.length())
        #     path[0] = seg1
        #     path.insert(1, seg2)

        path[0].inline_z = self.z_step

    def _append_overshoot(self, path: toolpath.Toolpath) -> None:
        """Append an overshoot line segment."""
        if self.brush_overshoot_auto:
            overshoot_dist = self.tool_width / 2
        else:
            overshoot_dist = self.brush_overshoot_distance

        if overhoot_dist < self.gc.tolerence:
            return

        # logger.debug('tw=%f, od=%f' % (self.tool_width, overshoot_dist))
        segment = path[-1]
        brush_direction = toolpath.seg_end_angle(segment)
        if overshoot_dist > self.gc.tolerance:
            delta = geom2d.P.from_polar(overshoot_dist, brush_direction)
            overshoot_endp = segment.p2 + delta
            overshoot_line = toolpath.ToolpathLine(
                segment.p2, overshoot_endp
            )
            path.append(overshoot_line)

        if self.brush_soft_landing:
            liftoff_dist = self.tool_trail_offset
            if liftoff_dist > self.gc.tolerance:
                delta = geom2d.P.from_polar(liftoff_dist, brush_direction)
                liftoff_endp = overshoot_endp + delta
                liftoff_line = toolpath.ToolpathLine(
                    overshoot_endp, liftoff_endp
                )
                liftoff_line.inline_z = 0.0
                path.append(liftoff_line)
