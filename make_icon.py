#!/usr/bin/env python3
"""Generate AppIcon.png (1024x1024 RGBA) — a clipboard icon, no dependencies."""

import math
import struct
import zlib

W = H = 1024


def new_canvas():
    return bytearray(W * H * 4)  # transparent RGBA


def blend(buf, x, y, r, g, b, cov):
    if cov <= 0 or x < 0 or y < 0 or x >= W or y >= H:
        return
    if cov > 1:
        cov = 1.0
    i = (y * W + x) * 4
    ba = buf[i + 3] / 255.0
    out_a = cov + ba * (1 - cov)
    if out_a <= 0:
        return
    for k, sc in enumerate((r, g, b)):
        bc = buf[i + k]
        buf[i + k] = int((sc * cov + bc * ba * (1 - cov)) / out_a)
    buf[i + 3] = int(out_a * 255)


def rrect_cov(px, py, x0, y0, x1, y1, rad):
    """Anti-aliased coverage of point (px,py) inside a rounded rect."""
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hw, hh = (x1 - x0) / 2, (y1 - y0) / 2
    dx = max(abs(px - cx) - (hw - rad), 0.0)
    dy = max(abs(py - cy) - (hh - rad), 0.0)
    dist = math.hypot(dx, dy) - rad
    return max(0.0, min(1.0, 0.5 - dist))


def draw_rrect(buf, x0, y0, x1, y1, rad, color, gradient=None):
    for y in range(int(y0 - 2), int(y1 + 2)):
        if gradient:
            t = (y - y0) / (y1 - y0)
            t = max(0.0, min(1.0, t))
            r = int(gradient[0][0] + (gradient[1][0] - gradient[0][0]) * t)
            g = int(gradient[0][1] + (gradient[1][1] - gradient[0][1]) * t)
            b = int(gradient[0][2] + (gradient[1][2] - gradient[0][2]) * t)
        else:
            r, g, b = color
        for x in range(int(x0 - 2), int(x1 + 2)):
            cov = rrect_cov(x + 0.5, y + 0.5, x0, y0, x1, y1, rad)
            if cov > 0:
                blend(buf, x, y, r, g, b, cov)


def write_png(path, buf):
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    raw = bytearray()
    for y in range(H):
        raw.append(0)  # filter type 0
        raw.extend(buf[y * W * 4:(y + 1) * W * 4])
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def main():
    buf = new_canvas()
    # rounded-square background with a blue vertical gradient (macOS squircle-ish)
    draw_rrect(buf, 90, 90, 934, 934, 210, None,
               gradient=((74, 139, 245), (44, 107, 216)))
    # clip head behind the board
    draw_rrect(buf, 398, 190, 626, 300, 30, (172, 176, 187))
    # white clipboard body
    draw_rrect(buf, 300, 250, 724, 812, 46, (255, 255, 255))
    # clip button on top
    draw_rrect(buf, 452, 172, 572, 250, 26, (150, 154, 165))
    draw_rrect(buf, 470, 186, 554, 232, 18, (206, 210, 220))
    # text lines inside the board
    draw_rrect(buf, 356, 372, 668, 408, 18, (63, 123, 214))   # accent line
    draw_rrect(buf, 356, 456, 668, 492, 18, (200, 205, 214))
    draw_rrect(buf, 356, 540, 668, 576, 18, (200, 205, 214))
    draw_rrect(buf, 356, 624, 560, 660, 18, (200, 205, 214))
    write_png("AppIcon.png", buf)
    print("wrote AppIcon.png")


if __name__ == "__main__":
    main()
