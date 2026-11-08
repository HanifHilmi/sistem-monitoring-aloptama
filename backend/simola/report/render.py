"""The monthly report as HTML (Jinja2 template) and as PDF (WeasyPrint).

Nothing outside this folder is ever loaded while rendering: the fetcher serves the bundled font files and refuses
every other address, so text in the data (alarm messages, notes) can never make the server fetch anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from simola.report.model import ReportInputs, context

HERE = Path(__file__).resolve().parent
FONTS = HERE / "fonts"
TEMPLATES = HERE / "templates"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


def css_string(s: str) -> Markup:
    """A CSS string literal for generated content (running footer, page numbers), safe inside <style>."""
    out = []
    for ch in s:
        if ch.isalnum() or ch in " .,:;·()/-_%+#'":
            out.append(ch)
        else:
            out.append(f"\\{ord(ch):x} ")  # CSS escape: quotes, backslashes and < can never close anything
    return Markup('"' + "".join(out) + '"')  # noqa: S704 - every other character is escaped above


_env.filters["css_string"] = css_string


def render_html(r: ReportInputs) -> str:
    ctx: dict[str, Any] = context(r)
    ctx["days"]["chart"] = Markup(ctx["days"]["chart"])  # noqa: S704 - SVG built by charts.py, text escaped there
    if ctx["alarms"]["chart"]:
        ctx["alarms"]["chart"] = Markup(ctx["alarms"]["chart"])  # noqa: S704 - as above
    ctx["css"] = Markup((TEMPLATES / "report.css").read_text(encoding="utf-8"))  # noqa: S704 - our own file
    return _env.get_template("report.html.j2").render(ctx)


def bundled_path(url: str) -> Path | None:
    """The bundled font file a URL names, or None: the only thing a report may load."""
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    path = Path(url2pathname(parsed.path)).resolve()
    if path.parent != FONTS or path.suffix != ".otf" or not path.is_file():
        return None
    return path


def _fetcher() -> Any:
    # Imported here: WeasyPrint loads Pango when imported, which only the API image needs.
    from weasyprint.urls import URLFetcher, URLFetcherResponse

    class BundledOnly(URLFetcher):  # type: ignore[misc]
        def fetch(self, url: str, headers: Any = None) -> URLFetcherResponse:
            path = bundled_path(url)
            if path is None:
                raise ValueError(f"not loaded while rendering a report: {url[:80]}")
            return URLFetcherResponse(url, path.read_bytes(), {"Content-Type": "font/otf"})

    return BundledOnly()


def render_pdf(r: ReportInputs) -> bytes:
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration

    fonts = FontConfiguration()
    doc = HTML(string=render_html(r), base_url=HERE.as_uri() + "/", url_fetcher=_fetcher())
    pdf: bytes = doc.write_pdf(font_config=fonts)
    return pdf


def selftest() -> int:
    """Draws one line with the bundled font: the image has what WeasyPrint needs (CI ``images`` job)."""
    from weasyprint import CSS, HTML
    from weasyprint.text.fonts import FontConfiguration

    fonts = FontConfiguration()
    css = CSS(
        string="@font-face { font-family: Inter; src: url(fonts/Inter-Regular.otf); } p { font-family: Inter; }",
        base_url=HERE.as_uri() + "/",
        font_config=fonts,
        url_fetcher=_fetcher(),
    )
    pdf: bytes = HTML(string="<p>SIMOLA 99,84 %</p>").write_pdf(
        stylesheets=[css], font_config=fonts, uncompressed_pdf=True
    )
    if not pdf.startswith(b"%PDF-") or b"Inter" not in pdf:
        raise RuntimeError("the bundled font was not used")
    return len(pdf)


if __name__ == "__main__":
    print(f"report renderer ok: {selftest()} bytes")
