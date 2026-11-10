"""Minimal PDF writer (standard library only). Text-only pages, Helvetica, A4.
Enough for a police-complaint evidence pack. Non-latin-1 characters are replaced -
money is written as 'Rs', so nothing is lost."""

PAGE_W, PAGE_H = 595, 842
MARGIN, LINE = 50, 16


def _esc(s):
    s = s.encode("latin-1", "replace").decode("latin-1")
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def wrap(text, width=88):
    words, line, out = (text or "").split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out or [""]


def build_pdf(title, sections):
    """sections: list of (heading, [lines]). Returns PDF bytes."""
    pages, cur, left = [], [], 0

    def newpage():
        nonlocal cur, left
        cur, left = [], (PAGE_H - 2 * MARGIN) // LINE
        pages.append(cur)

    def emit(text, size, gap=0):
        nonlocal left
        need = 1 + gap
        if left < need:
            newpage()
        for ln in wrap(text, 88 if size <= 11 else 60):
            if left < 1:
                newpage()
            cur.append((ln, size))
            left -= 1
        left -= gap

    newpage()
    emit(title, 18, 1)
    for heading, lines in sections:
        emit(heading, 13, 0)
        for ln in lines:
            emit(ln, 10)

    objects = []

    def add(body):
        objects.append(body)
        return len(objects)

    page_ids = []
    content_ids = []
    for pg in pages:
        stream = ["BT"]
        y = PAGE_H - MARGIN
        for text, size in pg:
            stream.append(f"/F1 {size} Tf 1 0 0 1 {MARGIN} {y} Tm ({_esc(text)}) Tj")
            y -= LINE
        stream.append("ET")
        data = " ".join(stream).encode("latin-1")
        content_ids.append(add(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"))
        page_ids.append(None)  # filled after pages-parent id known
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, cid in enumerate(content_ids):
        page_ids[i] = add(b"")  # placeholder, patched below
    pages_id = add(b"")
    for i, cid in enumerate(content_ids):
        objects[page_ids[i] - 1] = (b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
                                    b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                                    % (pages_id, PAGE_W, PAGE_H, font_id, cid))
    objects[pages_id - 1] = (b"<< /Type /Pages /Kids [%s] /Count %d >>"
                             % (b" ".join(b"%d 0 R" % p for p in page_ids), len(page_ids)))
    catalog_id = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets[1:]:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF"
            % (len(objects) + 1, catalog_id, xref))
    return bytes(out)
