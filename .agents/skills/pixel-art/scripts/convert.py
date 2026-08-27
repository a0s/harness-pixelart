"""Raster -> .pxa conversion.

Useful in two places: turning a reference (or an AI render) into an editable
starting point, and re-importing a PNG someone edited outside the pipeline.
The output is a *draft*, never a finished sprite -- machine downsampling has no
idea which pixel carries the read.
"""

import os

import pxa
import imaging
import palettes


def image_to_doc(path, width=None, height=None, colors=16, palette=None,
                 dither="none", strength=1.0, name=None, alpha_cut=128,
                 crop_transparent=True):
    px, w, h = imaging.load_image(path)

    scale = imaging.detect_pixel_scale(px)
    if scale > 1 and not width and not height:
        px = imaging.nearest_resize(px, w // scale, h // scale)
        w, h = imaging.size_of(px)

    if width or height:
        if width and height:
            tw, th = width, height
        elif width:
            tw = width; th = max(1, int(round(h * width / float(w))))
        else:
            th = height; tw = max(1, int(round(w * height / float(h))))
        px = imaging.box_resize(px, tw, th)
        w, h = tw, th

    if palette is None:
        palette = palettes.extract(px, colors)
    snapped = palettes.snap_pixels(px, palette, dither=dither, strength=strength,
                                   alpha_cut=alpha_cut)

    doc = pxa.blank(w, h, name or os.path.splitext(os.path.basename(path))[0])
    doc.meta["source"] = os.path.basename(path)
    doc.meta["stage"] = "import"
    for c in palettes.sort_palette(palette):
        doc.add_swatch(c)
    frame = pxa.pixels_to_frame(doc, snapped, pxa.DEFAULT_FRAME, add_missing=True)
    doc.frames = [frame]
    pxa.assign_keys_by_value(doc)
    frame = doc.frames[0]
    if crop_transparent:
        import canvas
        canvas.crop_to_content(doc, frame, margin=0)
        doc.meta["size"] = "%dx%d" % (frame.width, frame.height)
    return doc


def doc_from_pixels(pixels, name="import", palette=None, colors=16, dither="none"):
    if palette is None:
        palette = palettes.extract(pixels, colors)
    snapped = palettes.snap_pixels(pixels, palette, dither=dither)
    w, h = imaging.size_of(pixels)
    doc = pxa.blank(w, h, name)
    for c in palettes.sort_palette(palette):
        doc.add_swatch(c)
    doc.frames = [pxa.pixels_to_frame(doc, snapped, pxa.DEFAULT_FRAME)]
    pxa.assign_keys_by_value(doc)
    return doc


def sheet_to_doc(path, fw, fh, columns=None, rows=None, colors=16, palette=None, name=None):
    """Slice an existing spritesheet into frames."""
    px, w, h = imaging.load_image(path)
    cols = columns or w // fw
    rws = rows or h // fh
    if palette is None:
        palette = palettes.extract(px, colors)
    doc = pxa.blank(fw, fh, name or os.path.splitext(os.path.basename(path))[0])
    for c in palettes.sort_palette(palette):
        doc.add_swatch(c)
    doc.frames = []
    for r in range(rws):
        for c in range(cols):
            cell = imaging.crop(px, c * fw, r * fh, fw, fh)
            snapped = palettes.snap_pixels(cell, palette)
            doc.frames.append(pxa.pixels_to_frame(doc, snapped, "f%d" % len(doc.frames)))
    pxa.assign_keys_by_value(doc)
    return doc
