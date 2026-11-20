"""Squircle title box for the 'box' title style (stdlib only).

Measures the title with the real font metrics (OTF/TTF hmtx + cmap), wraps it to fit,
and returns two ASS events: a white superellipse box (\\p1 drawing) and the black text on top.
libass sizes a font so that winAscent+winDescent == font size, so widths scale by size/(asc+desc).
"""
import math, os, struct

_CACHE = {}


def _tables(data):
    n = struct.unpack(">H", data[4:6])[0]
    t = {}
    for i in range(n):
        tag, _, off, ln = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        t[tag.decode("latin1")] = (off, ln)
    return t


def load_metrics(path):
    if path in _CACHE:
        return _CACHE[path]
    data = open(path, "rb").read()
    t = _tables(data)
    o = t["hhea"][0]
    asc, desc = struct.unpack(">hh", data[o + 4:o + 8])
    nhm = struct.unpack(">H", data[o + 34:o + 36])[0]
    if "OS/2" in t:
        o2 = t["OS/2"][0]
        wa, wd = struct.unpack(">HH", data[o2 + 74:o2 + 78])
        if wa + wd > 0:
            asc, desc = wa, -wd
    o = t["hmtx"][0]
    adv = [struct.unpack(">H", data[o + 4 * i:o + 4 * i + 2])[0] for i in range(nhm)]
    cmap = {}
    o = t["cmap"][0]
    nsub = struct.unpack(">H", data[o + 2:o + 4])[0]
    subs = []
    for i in range(nsub):
        pid, eid, off = struct.unpack(">HHI", data[o + 4 + 8 * i:o + 12 + 8 * i])
        fmt = struct.unpack(">H", data[o + off:o + off + 2])[0]
        subs.append((fmt, o + off))
    subs.sort(key=lambda s: {12: 0, 4: 1}.get(s[0], 9))
    fmt, so = subs[0]
    if fmt == 12:
        ng = struct.unpack(">I", data[so + 12:so + 16])[0]
        for i in range(ng):
            a, b, g = struct.unpack(">III", data[so + 16 + 12 * i:so + 28 + 12 * i])
            if a > 0x2FFF:
                continue
            for c in range(a, min(b, 0x2FFF) + 1):
                cmap[c] = g + c - a
    elif fmt == 4:
        segx2 = struct.unpack(">H", data[so + 6:so + 8])[0]
        seg = segx2 // 2
        ends = struct.unpack(">%dH" % seg, data[so + 14:so + 14 + segx2])
        st = so + 16 + segx2
        starts = struct.unpack(">%dH" % seg, data[st:st + segx2])
        deltas = struct.unpack(">%dh" % seg, data[st + segx2:st + 2 * segx2])
        ro = st + 2 * segx2
        ranges = struct.unpack(">%dH" % seg, data[ro:ro + segx2])
        for i in range(seg):
            for c in range(starts[i], min(ends[i], 0x2FFF) + 1):
                if ranges[i] == 0:
                    g = (c + deltas[i]) & 0xFFFF
                else:
                    p = ro + 2 * i + ranges[i] + 2 * (c - starts[i])
                    g = struct.unpack(">H", data[p:p + 2])[0]
                    if g:
                        g = (g + deltas[i]) & 0xFFFF
                cmap[c] = g
    m = {"em": asc - desc, "adv": adv, "cmap": cmap}
    _CACHE[path] = m
    return m


def text_width(s, m, size):
    adv, cmap = m["adv"], m["cmap"]
    u = 0
    for ch in s:
        g = cmap.get(ord(ch), 0)
        u += adv[min(g, len(adv) - 1)]
    return u * size / m["em"]


def wrap(text, m, size, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if cur and text_width(trial, m, size) > maxw:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    # balance two-line titles so the box isn't one long line + a stub
    if len(lines) == 2:
        best = lines
        ws = text.split()
        for k in range(1, len(ws)):
            a, b = " ".join(ws[:k]), " ".join(ws[k:])
            if max(text_width(a, m, size), text_width(b, m, size)) <= maxw and \
               max(text_width(a, m, size), text_width(b, m, size)) < max(text_width(x, m, size) for x in best):
                best = [a, b]
        lines = best
    return lines


def squircle_path(w, h, r, n=4.0, steps=18):
    """Closed superellipse-cornered rectangle (continuous curvature, iOS-style), origin top-left."""
    r = min(r, w / 2, h / 2)
    pts = []
    corners = [(w - r, r, 0), (w - r, h - r, 1), (r, h - r, 2), (r, r, 3)]  # TR, BR, BL, TL (clockwise)
    for cx, cy, q in corners:
        for i in range(steps + 1):
            a = (q - 1) * math.pi / 2 + (math.pi / 2) * i / steps   # -90..0 for TR, 0..90 BR, ...
            c, s = math.cos(a), math.sin(a)
            x = cx + r * math.copysign(abs(c) ** (2 / n), c)
            y = cy + r * math.copysign(abs(s) ** (2 / n), s)
            pts.append((x, y))
    d = "m %d %d" % (round(pts[0][0]), round(pts[0][1]))
    d += " l " + " ".join("%d %d" % (round(x), round(y)) for x, y in pts[1:])
    return d


def events(title, cx, cy, start_ts, end_ts, font_path, size=64, pad_x=34, pad_y=22,
           radius=48, max_w=840, line_gap=1.08, box_colour="&H00FFFFFF&", box_layer=2, text_layer=3):
    m = load_metrics(font_path)
    lines = wrap(title, m, size, max_w)
    tw = max(text_width(l, m, size) for l in lines)
    lh = size * line_gap
    bw = round(tw + 2 * pad_x)
    bh = round(lh * len(lines) + 2 * pad_y - (lh - size))
    x0, y0 = round(cx - bw / 2), round(cy - bh / 2)
    path = squircle_path(bw, bh, radius)
    box = (f"Dialogue: {box_layer},{start_ts},{end_ts},TitleBox,,0,0,0,,"
           f"{{\\an7\\pos({x0},{y0})\\bord0\\shad0\\1c{box_colour}\\p1}}{path}{{\\p0}}")
    txt = (f"Dialogue: {text_layer},{start_ts},{end_ts},TitleText,,0,0,0,,"
           f"{{\\an5\\pos({cx},{cy})\\q2}}" + "\\N".join(lines))
    return [box, txt]
