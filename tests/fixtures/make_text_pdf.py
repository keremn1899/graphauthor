"""Minimal text-only PDF writer, so the fidelity probe has a paper-sized input."""
def make_pdf(pages: list[list[str]], path: str) -> None:
    objs, page_ids = [], []
    def esc(s):
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    for lines in pages:
        content = "BT\n/F1 9 Tf\n1 0 0 1 40 750 Tm\n11 TL\n"
        for ln in lines:
            content += f"({esc(ln)}) Tj T*\n"
        content += "ET"
        objs.append(("stream", content))
    n_pages = len(pages)
    # 1 catalog, 2 pages tree, 3 font, then per page: page obj + content stream
    body, offsets = [], []
    def add(s): body.append(s)
    kids = " ".join(f"{4 + 2*i} 0 R" for i in range(n_pages))
    add(f"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    add(f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>\nendobj\n")
    add("3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")
    for i, (_kind, content) in enumerate(objs):
        pid, cid = 4 + 2*i, 5 + 2*i
        add(f"{pid} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>\nendobj\n")
        add(f"{cid} 0 obj\n<< /Length {len(content)} >>\nstream\n{content}\nendstream\nendobj\n")
    out = "%PDF-1.4\n"
    for chunk in body:
        offsets.append(len(out))
        out += chunk
    xref_at = len(out)
    total = len(body) + 1
    out += f"xref\n0 {total}\n0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n"
    out += (f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n")
    open(path, "wb").write(out.encode("latin-1"))
