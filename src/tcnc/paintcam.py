"""CAM module specifically for a brush type tool."""

from __future__ import annotations

import dataclasses
import math

import geom2d

from . import gcode, simplecam, toolpath


@dataclasses.dataclass
class PaintCAMOptions(simplecam.CAMOptions):
    """PaintCAM options."""

    # Add a soft landing to lower tool during feed at start of path.
    brush_soft_landing: bool = False
    # : Landing strip distance to prepend to start of path
    brush_landing: float = 0

    # : Add a soft takeoff to raise tool during feed at end of path.
    brush_soft_takeoff: bool = False
    # : Takeoff strip distance to append to end of path
    brush_takeoff: float = 0

    # Brush reload pause mode
    brush_pause_mode: str | None = None
    # : Brush reload pause manual resume
    brush_pause_resume: bool = False
    # : Enable brush reload sequence
    brush_reload_enable: bool = False
    # : Enable rotation to reload angle before pause.
    brush_reload_rotate: bool = False
    # : Brush reload angle.
    brush_reload_angle: float = 0
    # : Dwell time for brush reload.
    brush_reload_dwell: float = 0
    # : Number of paths to process before brush reload.
    brush_reload_max_paths: int = 1


class PaintCAM(simplecam.SimpleCAM):
    """CAM interface for a brush-type tool."""

    # pylint doesn't seem to understand dataclass inheritance so...
    # pylint: disable=no-member
    options: PaintCAMOptions

    def __init__(
        self, gc: gcode.GCodeGenerator, options: PaintCAMOptions | None = None
    ) -> None:
        """Constructor.

        Args:
            gc: A GCodeGenerator instance.
            options: CAM options.
        """
        super().__init__(gc, options=options)

    def postprocess_toolpaths(
        self, toolpaths: list[toolpath.Toolpath]
    ) -> list[toolpath.Toolpath]:
        """Create brush overshoots.

        Overrides SimpleCAM.postprocess_toolpaths() to handle brush
        specific path post processing.
        """
        toolpaths = super().postprocess_toolpaths(toolpaths)

        for path in toolpaths:
            if self.options.brush_landing > self.gc.tolerance:
                self._prepend_landing(path)

            if self.options.brush_takeoff > self.gc.tolerance:
                self._append_takeoff(path)

        return toolpaths

    def generate_rapid_move(self, path: toolpath.Toolpath) -> None:
        """Generate G code for a rapid move to the beginning of the tool path."""
        if (
            self.options.brush_reload_enable
            # and (self._path_count % self.options.brush_reload_max_paths) == 0
        ):
            start_segment = path[0]
            if self.options.brush_reload_rotate:
                # Coordinated move to XY and A reload angle
                rotation = geom2d.calc_rotation(
                    self.current_angle, self.options.brush_reload_angle
                )
                self.current_angle += rotation
                self.gc.rapid_move(
                    start_segment.p1.x, start_segment.p1.y, a=self.current_angle
                )
            else:
                self.gc.rapid_move(start_segment.p1.x, start_segment.p1.y)
            if self.options.brush_pause_resume:
                self.gc.pause()
            elif self.options.brush_reload_dwell > 0:
                self.gc.dwell(self.options.brush_reload_dwell)
        super().generate_rapid_move(path)

    def _prepend_landing(self, path: toolpath.Toolpath) -> None:
        """Prepend a landing strip."""
        first_segment = path[0]
        start_angle = toolpath.seg_start_angle(first_segment) + math.pi
        delta = geom2d.P.from_polar(self.options.brush_landing, start_angle)
        landing_line = toolpath.ToolpathLine(
            first_segment.p1 + delta, first_segment.p1
        )

        if hasattr(first_segment, 'inline_start_angle'):
            landing_line.inline_end_angle = first_segment.inline_start_angle

        if self.options.brush_soft_landing:
            landing_line.inline_z = -self.options.z_step

        path.insert(0, landing_line)

    def _append_takeoff(self, path: toolpath.Toolpath) -> None:
        """Append an overshoot line segment."""
        last_segment = path[-1]
        brush_direction = toolpath.seg_end_angle(last_segment)
        delta = geom2d.P.from_polar(self.options.brush_takeoff, brush_direction)
        takeoff_line = toolpath.ToolpathLine(
            last_segment.p2, last_segment.p2 + delta
        )

        if self.options.brush_soft_takeoff:
            takeoff_line.inline_z = 0.0

        path.append(takeoff_line)
