# Test fixtures

`two_page_text.pdf` — a 953-byte, two-page PDF built by hand (catalogue, pages,
a Helvetica font object and two content streams) so that `test_pdf_parser.py`
runs everywhere rather than skipping. It was first written against a PDF that
happened to be on one machine, which is a test that passes by not running.

Page 1: "Hrafnkell rode to Adalbol. / Einarr met him there."
Page 2: "Samr rode to the Thing. / The suit was heard."

Regenerate only if the parser's contract changes; the bytes are an input the
tests pin offsets against, so changing them invalidates those assertions.
