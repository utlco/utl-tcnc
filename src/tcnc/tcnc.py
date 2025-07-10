#!/usr/bin/env python
"""Inkscape extension that will generate G-code from selected paths.

The G-code is suitable for a CNC machine
that has a tangential tool (ie a knife or a brush).
"""
from __future__ import annotations

import gettext
import logging
import math
import pathlib

# For performance measuring and debugging
import timeit
from datetime import timedelta
from typing import TYPE_CHECKING, TextIO

import geom2d
from geom2d import transform2d
from inkext import geomsvg, inkext, inksvg

from . import gcode, gcodesvg, paintcam

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

__version__ = '0.2.3'

_ = gettext.gettext
logger = logging.getLogger(__name__)


class Tcnc(inkext.InkscapeExtension):
    """Inkscape extension that converts selected SVG elements into gcode.

    Suitable for a four axis (XYZA) CNC machine with a tangential tool,
    such as a knife or a brush, that rotates about the Z axis.
    """

    # Document units that can be expressed as imperial (inches)
    _IMPERIAL_UNITS = ('in', 'ft', 'yd', 'pc', 'pt', 'px')
    # Document units that can be expressed as metric (mm)
    _METRIC_UNITS = ('mm', 'cm', 'm', 'km')
    _DEFAULT_DIR = '~'
    _DEFAULT_FILEROOT = 'output'
    _DEFAULT_FILEEXT = '.ngc'

    def add_options(  # noqa: PLR0915 PLR6301 # pylint: disable=too-many-statements
        self, parser: argparse.ArgumentParser
    ) -> None:
        """Add CLI options."""
        parser.add_argument(
            '--flip-y-axis',
            type=inkext.inkbool,
            default=True,
            help=_('Flip Y axis so toolpath origin is at lower left.'),
        )
        parser.add_argument(
            '--path-sort-method', default='none', help=_('Path sorting method.')
        )
        parser.add_argument(
            '--biarc-tolerance',
            type=inkext.docunits,
            default=0.001,
            help=_('Biarc approximation fitting tolerance.'),
        )
        parser.add_argument(
            '--biarc-max-depth',
            type=int,
            default=3,
            help=_(
                'Biarc approximation maximum curve splitting recursion depth.'
            ),
        )
        parser.add_argument(
            '--line-flatness',
            type=inkext.docunits,
            default=0.001,
            help=_('Curve to line flatness.'),
        )
        parser.add_argument(
            '--min-arc-radius',
            type=inkext.degrees,
            default=0.001,
            help=_(
                'All arcs having radius less than minimum '
                'will be considered as straight line.'
            ),
        )
        parser.add_argument(
            '--tolerance', type=float, default=0.000001, help=_('Tolerance')
        )
        parser.add_argument(
            '--gc-tolerance',
            type=float,
            default=0.0001,
            help=_('GCode tolerance'),
        )

        parser.add_argument(
            '--gcode-target',
            default='linuxcnc',
            help=_('G code target interpreter'),
        )
        parser.add_argument(
            '--gcode-units',
            default='in',
            help=_('G code output units (inch or mm).'),
        )
        parser.add_argument(
            '--gcode-comments',
            type=inkext.inkbool,
            default=True,
            help=_('Show G code comments'),
        )
        parser.add_argument(
            '--gcode-line-numbers',
            type=inkext.inkbool,
            default=True,
            help=_('Show G code line numbers'),
        )
        parser.add_argument(
            '--xy-feed',
            type=float,
            default=10.0,
            help=_('XY axis feed rate in unit/m'),
        )
        parser.add_argument(
            '--z-feed',
            type=float,
            default=10.0,
            help=_('Z axis feed rate in unit/m'),
        )
        parser.add_argument(
            '--a-feed',
            type=float,
            default=60.0,
            help=_('A axis feed rate in deg/m'),
        )
        parser.add_argument(
            '--z-safe',
            type=float,
            default=1.0,
            help=_('Z axis safe height for rapid moves'),
        )
        parser.add_argument(
            '--z-wait',
            type=float,
            default=500,
            help=_('Z axis wait (milliseconds)'),
        )
        parser.add_argument(
            '--blend-mode', default='', help=_('Trajectory blending mode.')
        )
        parser.add_argument(
            '--blend-tolerance',
            type=float,
            default='0',
            help=_('Trajectory blending tolerance.'),
        )

        parser.add_argument(
            '--enable-tangent',
            type=inkext.inkbool,
            default=True,
            help=_('Enable tangent rotation'),
        )
        parser.add_argument(
            '--z-depth',
            type=float,
            default=-0.25,
            help=_('Z final depth of cut'),
        )
        parser.add_argument(
            '--z-step',
            type=float,
            default=-0.25,
            help=_('Z cutting step depth'),
        )

        parser.add_argument(
            '--tool-width',
            type=inkext.docunits,
            default=1.0,
            help=_('Tool width'),
        )
        parser.add_argument(
            '--a-feed-match',
            type=inkext.inkbool,
            default=False,
            help=_('A axis feed rate match XY feed'),
        )
        parser.add_argument(
            '--tool-trail-offset',
            type=inkext.docunits,
            default=0.25,
            help=_('Tool trail offset'),
        )
        parser.add_argument(
            '--a-offset',
            type=inkext.degrees,
            default=0,
            help=_('Tool offset angle'),
        )
        parser.add_argument(
            '--allow-tool-reversal',
            type=inkext.inkbool,
            default=False,
            help=_('Allow tool reversal'),
        )

        parser.add_argument(
            '--tool-wait',
            type=float,
            default=0,
            help=_('Tool up/down wait time in seconds'),
        )

        parser.add_argument(
            '--spindle-mode', default='', help=_('Spindle startup mode.')
        )
        parser.add_argument(
            '--spindle-speed', type=int, default=0, help=_('Spindle RPM')
        )
        parser.add_argument(
            '--spindle-wait-on',
            type=float,
            default=0,
            help=_('Spindle warmup delay'),
        )
        parser.add_argument(
            '--spindle-clockwise',
            type=inkext.inkbool,
            default=True,
            help=_('Clockwise spindle rotation'),
        )

        parser.add_argument(
            '--skip-path-count',
            type=int,
            default=0,
            help=_('Number of paths to skip.'),
        )
        parser.add_argument(
            '--ignore-segment-angle',
            type=inkext.inkbool,
            default=False,
            help=_('Ignore segment start angle.'),
        )
        parser.add_argument(
            '--path-tool-fillet',
            type=inkext.inkbool,
            default=False,
            help=_('Fillet paths for tool width'),
        )
        parser.add_argument(
            '--path-tool-offset',
            type=inkext.inkbool,
            default=False,
            help=_('Offset paths for tool trail offset'),
        )
        parser.add_argument(
            '--path-preserve-g1',
            type=inkext.inkbool,
            default=False,
            help=_('Preserve G1 continuity for offset arcs'),
        )
        parser.add_argument(
            '--path-smooth-fillet',
            type=inkext.inkbool,
            default=False,
            help=_('Fillets at sharp corners'),
        )
        parser.add_argument(
            '--path-smooth-radius',
            type=inkext.docunits,
            default=0.0,
            help=_('Smoothing radius'),
        )
        parser.add_argument(
            '--path-close-polygons',
            type=inkext.inkbool,
            default=False,
            help=_('Close polygons with overlap'),
        )
        parser.add_argument(
            '--path-close-overlap',
            type=inkext.docunits,
            default=0.0,
            help=_('Path close overlap distance'),
        )
        parser.add_argument(
            '--path-split-cusps',
            type=inkext.inkbool,
            default=False,
            help=_('Split paths at non-tangent control points'),
        )

        # parser.add_argument('--brush-flip-stroke', type=inkext.inkbool,
        #             default=False, help=_('Flip brush before every stroke.'))
        # parser.add_argument('--brush-flip-path', type=inkext.inkbool,
        #                     default=False, help=_('Flip after each path.'))
        # parser.add_argument('--brush-flip-reload', type=inkext.inkbool,
        #    default=False, help=_('Flip before reload.'))

        parser.add_argument(
            '--brush-reload-enable',
            type=inkext.inkbool,
            default=False,
            help=_('Enable brush reload.'),
        )
        parser.add_argument(
            '--brush-reload-rotate',
            type=inkext.inkbool,
            default=False,
            help=_('Rotate brush before reload.'),
        )
        parser.add_argument(
            '--brush-pause-resume',
            type=inkext.inkbool,
            default=False,
            help=_('Pause brush for reload until manual resume.'),
        )
        parser.add_argument(
            '--brush-pause-mode', default='', help=_('Brush reload pause mode.')
        )
        parser.add_argument(
            '--brush-reload-max-paths',
            type=int,
            default=1,
            help=_('Number of paths between reload.'),
        )
        parser.add_argument(
            '--brush-reload-dwell',
            type=float,
            default=0.0,
            help=_('Brush reload time (seconds).'),
        )
        parser.add_argument(
            '--brush-reload-angle',
            type=inkext.degrees,
            default=90.0,
            help=_('Brush reload angle (degrees).'),
        )

        parser.add_argument(
            '--brush-takeoff-mode',
            default='',
            help=_('Brush takeoff mode.'),
        )
        parser.add_argument(
            '--brush-takeoff',
            type=inkext.docunits,
            default=0.0,
            help=_('Brush takeoff distance.'),
        )
        parser.add_argument(
            '--brush-soft-takeoff',
            type=inkext.inkbool,
            default=False,
            help=_('Enable soft takeoff.'),
        )

        parser.add_argument(
            '--brush-landing-mode',
            default='',
            help=_('Brush landing mode.'),
        )
        parser.add_argument(
            '--brush-landing',
            type=inkext.docunits,
            default=0.0,
            help=_('Brush landing distance.'),
        )
        parser.add_argument(
            '--brush-soft-landing',
            type=inkext.inkbool,
            default=False,
            help=_('Enable soft landing.'),
        )

        parser.add_argument(
            '--brushstroke-max',
            type=inkext.docunits,
            default=0.0,
            help=_('Max brushstroke distance before reload.'),
        )

        parser.add_argument(
            '--file-layer',
            type=inkext.inkbool,
            default=False,
            help=_('Use <file>-<layer>.ngc as filename'),
        )
        parser.add_argument(
            '--output-path', default='~/output.ngc', help=_('Output path name')
        )
        parser.add_argument(
            '--append-suffix',
            type=inkext.inkbool,
            default=False,
            help=_('Append auto-incremented numeric suffix to filename'),
        )
        parser.add_argument(
            '--separate-layers',
            type=inkext.inkbool,
            default=False,
            help=_('Separate gcode file per layer'),
        )

        parser.add_argument(
            '--preview-toolmarks',
            type=inkext.inkbool,
            default=False,
            help=_('Show tangent tool preview.'),
        )
        parser.add_argument(
            '--preview-toolmarks-outline',
            type=inkext.inkbool,
            default=False,
            help=_('Show tangent tool preview outline.'),
        )
        parser.add_argument(
            '--preview-scale', default='medium', help=_('Preview scale.')
        )

        parser.add_argument(
            '--write-settings',
            type=inkext.inkbool,
            default=False,
            help=_('Write Tcnc command line options in header.'),
        )

        parser.add_argument(
            '--x-subpath-render',
            type=inkext.inkbool,
            default=False,
            help=_('Render subpaths'),
        )
        parser.add_argument(
            '--x-subpath-offset',
            type=inkext.docunits,
            default=0.0,
            help=_('Subpath spacing'),
        )
        parser.add_argument(
            '--x-subpath-smoothness',
            type=float,
            default=0.0,
            help=_('Subpath smoothness'),
        )
        parser.add_argument(
            '--x-subpath-layer',
            default='subpaths_tcnc',
            help=_('Subpath layer name'),
        )

    def post_process_options(self) -> None:
        """Fix CLI option values after parsing SVG document."""
        super().post_process_options()
        if not self.options.path_close_polygons:
            self.options.path_close_overlap = 0

    # pylint: enable=too-many-statements

    def effect(self) -> None:
        """Main entry point for Inkscape plugins."""
        # Initialize the geometry module with tolerances
        geom2d.set_epsilon(self.options.tolerance)

        # Get a list of selected SVG shape elements and their transforms
        svg_elements = self.svg.get_shape_elements(
            self.selected_elements(), skip_layers=['tcnc .*']
        )
        if not svg_elements:
            return  # Nothing selected or document is empty

        timer_start = timeit.default_timer()

        # Flip the Y axis so origin is on bottom-left.
        flip_transform = (
            transform2d.matrix_scale_translate(
                1.0, -1.0, 0.0, self.svg.get_document_size()[1]
            )
            if self.options.flip_y_axis
            else None
        )

        # Convert SVG elements to path geometry.
        path_list: list[Sequence[geomsvg.TPathGeom]] = (
            geomsvg.svg_to_geometry(  # type: ignore [assignment]
                svg_elements, flip_transform
            )
        )

        # Create the output file path name
        default_stem = pathlib.Path(self.svg.doc_name).stem
        if self.svg.selected_layer_name:
            stem_suffix = self.svg.selected_layer_name.replace(' ', '_')
            default_stem = f'{default_stem}-{stem_suffix}'
        filepath = inkext.output_path(
            self.options.output_path,
            auto_incr=self.options.append_suffix,
            default_stem=default_stem,
            default_suffix='.ngc',
        )
        #inkext.errormsg(filepath)
        # logger.debug('gcode output: %s', filepath)
        try:
            with filepath.open('w', encoding='utf-8') as output:
                gcgen = self._init_gcode(output)
                cam = self._init_cam(gcgen)
                cam.generate_gcode(path_list)
        except OSError as error:
            inkext.errormsg(str(error))

        total_time = timeit.default_timer() - timer_start
        logger.info('Tcnc time: %s', str(timedelta(seconds=total_time)))

    def _init_gcode(self, output: TextIO) -> gcode.GCodeGenerator:
        """Create and initialize the G code generator with machine details."""
        if self.options.a_feed_match:
            # This option sets the angular feed rate of the A axis so
            # that the outside edge of the brush matches the linear feed
            # rate of the XY axes when doing a simple rotation.
            # TODO: verify correctness here
            angular_rate = self.options.xy_feed / self.options.tool_width / 2
            self.options.a_feed = math.degrees(angular_rate)
        # Create G-code preview plotter.
        preview_svg_context = inksvg.InkscapeSVGContext(self.svg.document)
        preview_plotter = gcodesvg.SVGPreviewPlotter(
            preview_svg_context,
            tool_width=self.options.tool_width,
            tool_offset=self.options.tool_trail_offset,
            style_scale=self.options.preview_scale,
            show_toolmarks=self.options.preview_toolmarks,
            show_tm_outline=self.options.preview_toolmarks_outline,
            flip_y_axis=self.options.flip_y_axis,
        )
        # Experimental options
        preview_plotter.x_subpath_render = self.options.x_subpath_render
        preview_plotter.x_subpath_layer_name = self.options.x_subpath_layer
        preview_plotter.x_subpath_offset = self.options.x_subpath_offset
        preview_plotter.x_subpath_smoothness = self.options.x_subpath_smoothness
        # Create G-code generator.
        gcgen = gcode.GCodeGenerator(
            xyfeed=self.options.xy_feed,
            zsafe=self.options.z_safe,
            zfeed=self.options.z_feed,
            afeed=self.options.a_feed,
            plotter=preview_plotter,
            output=output,
            target=self.options.gcode_target,
        )
        # The 'Z' axis is the rotational tangent axis for this machine
        # (The Valiani/CMC instance of the Rubens6k controller.)
        if self.options.gcode_target == 'rubens6k':
            gcgen.disable_axis('Z')
            gcgen.map_axis('A', 'Z')
        gcgen.add_header_comment(f'Generated by TCNC Version {__version__}')
        # Show option settings in header
        if self.options.write_settings:
            gcgen.add_header_comment('Settings:')
            option_dict = vars(self.options)
            for name in option_dict:
                val = str(option_dict.get(name))
                # if val is not None:
                #     if val == None or val == option.default:
                #         # Skip default settings...
                #         continue
                #         # valstr = '%s (default)' % str(val)
                #     else:
                #         valstr = str(val)
                optname = name.replace('_', '-')
                gcgen.add_header_comment(f'--{optname} = {val}')
        units = self.options.gcode_units
        doc_units = self.svg.doc_units
        if units == 'doc':
            if doc_units not in {'in', 'mm'}:
                # Determine if the units are metric or imperial.
                # Pica and pixel units are considered imperial for now...
                if doc_units in self._IMPERIAL_UNITS:
                    units = 'in'
                elif doc_units in self._METRIC_UNITS:
                    units = 'mm'
                else:
                    inkext.errormsg(
                        _('Document units must be imperial or metric.')
                    )
                    raise RuntimeError
            else:
                units = doc_units
        unit_scale = self.svg.unit_convert(
            '1.0', from_unit=doc_units, to_unit=units
        )
        gcgen.set_units(units, unit_scale)
        # logger.debug('units=%s, unit_scale=%s', units, unit_scale)
        # logger.debug('doc units: %s' % doc_units)
        # logger.debug('view_scale: %f' % self.svg.view_scale)
        # logger.debug('unit_scale: %f' % unit_scale)
        gcgen.set_tolerance(self.options.tolerance)
        precision = max(
            0, int(round(abs(math.log10(self.options.gc_tolerance))))
        )
        gcgen.set_output_precision(precision)
        if self.options.blend_mode:
            gcgen.set_path_blending(
                self.options.blend_mode, self.options.blend_tolerance
            )
        gcgen.spindle_speed = self.options.spindle_speed
        gcgen.spindle_wait_on = self.options.spindle_wait_on * 1000
        gcgen.spindle_clockwise = self.options.spindle_clockwise
        gcgen.spindle_auto = self.options.spindle_mode == 'path'
        gcgen.tool_wait_down = self.options.tool_wait
        gcgen.tool_wait_up = self.options.tool_wait
        gcgen.show_comments = self.options.gcode_comments
        gcgen.show_line_numbers = self.options.gcode_line_numbers
        return gcgen

    def _init_cam(self, gc: gcode.GCodeGenerator) -> paintcam.PaintCAM:
        """Create and initialize the tool path generator."""
        # Transfer CLI args to CAMOptions
        cam_options = paintcam.PaintCAMOptions.from_options(self.options)
        return paintcam.PaintCAM(gc, cam_options)


def main() -> None:
    """CLI entry point."""
    Tcnc().main(flip_debug_layer=True)


if __name__ == '__main__':
    main()
