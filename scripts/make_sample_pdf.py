"""Generate workspace/inbox/invoices/cloudnine_hosting_sep.pdf, a one-page text PDF invoice.

Writes the PDF by hand (it is a simple text format) so no PDF library is needed.
Run from the project root:  python scripts/make_sample_pdf.py
"""
from pathlib import Path

LINES = [
    "CloudNine Hosting Inc.",
    "Vendor: CloudNine Hosting Inc.",
    "500 Market Street, San Francisco, CA 94105",
    "",
    "INVOICE",
    "",
    "Invoice Number: CN-INV-7781",
    "Invoice Date:   2026-09-25",
    "Due Date:       2026-10-25",
    "",
    "Description                          Amount",
    "Dedicated server (Sep 2026)        1,100.00",
    "Backup storage 2 TB                  140.00",
    "",
    "Subtotal                           1,240.00",
    "Total Due:                     USD 1,240.00",
]


def build_pdf(lines: list[str]) -> bytes:
    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content = "\n".join(["BT", "/F1 11 Tf", "15 TL", "50 790 Td"]
                        + [f"({escape(line)}) Tj T*" for line in lines] + ["ET"]).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    pdf += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_at)
    return bytes(pdf)


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "workspace" / "inbox" / "invoices" / "cloudnine_hosting_sep.pdf"
    target.write_bytes(build_pdf(LINES))
    print(f"Wrote {target}")
