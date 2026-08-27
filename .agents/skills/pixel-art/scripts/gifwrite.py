"""Animated GIF89a writer -- pure standard library.

Pixel art is already indexed and small, so writing GIF directly gives exact
control over per-frame delay, transparency and disposal without any dependency.
"""

import os
import struct


def _lzw_encode(indices, min_code_size):
    clear = 1 << min_code_size
    end = clear + 1
    code_size = min_code_size + 1
    table = {}
    def reset():
        table.clear()
        for i in range(clear):
            table[(i,)] = i
    reset()
    next_code = end + 1
    out = bytearray()
    bitbuf = bitcnt = 0

    def emit(code, size):
        nonlocal bitbuf, bitcnt
        bitbuf |= code << bitcnt
        bitcnt += size
        while bitcnt >= 8:
            out.append(bitbuf & 0xFF)
            bitbuf >>= 8
            bitcnt -= 8

    emit(clear, code_size)
    prefix = ()
    for px in indices:
        cur = prefix + (px,)
        if cur in table:
            prefix = cur
            continue
        emit(table[prefix], code_size)
        if next_code < 4096:
            table[cur] = next_code
            next_code += 1
            if next_code > (1 << code_size) and code_size < 12:
                code_size += 1
        else:
            emit(clear, code_size)
            reset()
            next_code = end + 1
            code_size = min_code_size + 1
        prefix = (px,)
    if prefix:
        emit(table[prefix], code_size)
    emit(end, code_size)
    if bitcnt:
        out.append(bitbuf & 0xFF)
    return bytes(out)


def _blocks(data):
    out = bytearray()
    for i in range(0, len(data), 255):
        chunk = data[i:i + 255]
        out.append(len(chunk))
        out += chunk
    out.append(0)
    return bytes(out)


def write_gif(path, frames, palette, width, height, delays_cs=10,
              transparent_index=None, loop=0, scale=1):
    """frames: list of index grids (rows of palette indices).
    palette: list of (r,g,b[,a]).  delays_cs: int or per-frame list, centiseconds."""
    if not frames:
        raise ValueError("no frames")
    scale = max(1, int(scale))
    n = 1
    while (1 << n) < max(2, len(palette)):
        n += 1
    n = min(n, 8)
    size = 1 << n

    out = bytearray(b"GIF89a")
    out += struct.pack("<HHBBB", width * scale, height * scale, 0xF0 | (n - 1), 0, 0)
    for i in range(size):
        c = palette[i] if i < len(palette) else (0, 0, 0)
        out += bytes((c[0] & 255, c[1] & 255, c[2] & 255))
    out += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01" + struct.pack("<H", loop) + b"\x00"

    if isinstance(delays_cs, int):
        delays = [delays_cs] * len(frames)
    else:
        delays = list(delays_cs) + [delays_cs[-1]] * (len(frames) - len(delays_cs))

    for idx, grid in enumerate(frames):
        flags = 0x08 | (0x01 if transparent_index is not None else 0)   # disposal=2 (restore bg)
        flags = (2 << 2) | (0x01 if transparent_index is not None else 0)
        out += b"\x21\xF9\x04" + bytes((flags,)) + struct.pack("<H", max(2, delays[idx])) + \
               bytes((transparent_index if transparent_index is not None else 0,)) + b"\x00"
        out += b"\x2C" + struct.pack("<HHHHB", 0, 0, width * scale, height * scale, 0)
        flat = []
        for row in grid:
            big = [v for v in row for _ in range(scale)]
            for _ in range(scale):
                flat.extend(big)
        mcs = max(2, n)
        out += bytes((mcs,)) + _blocks(_lzw_encode(flat, mcs))
    out += b"\x3B"

    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "wb") as fh:
        fh.write(bytes(out))
    return path
