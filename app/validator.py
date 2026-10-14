"""HTML validator for the core area.

The validator parses a string of HTML and returns a list of human‑readable error
messages.  It never mutates the supplied HTML – callers receive the original
string unchanged.

Rules enforced (as described in issue #4):

* The document must contain a ``<title>`` element with non‑empty content.
* Exactly one ``<h1>`` element is required.
* At least three ``<section>`` elements must be present.
* The total byte size of the HTML must not exceed 100 KB.
* No ``<script>`` tags are allowed.
* No ``<iframe>`` tags are allowed.
* External resources are prohibited – this includes ``<link>`` tags whose
  ``href`` attribute starts with ``http://``/``https://``/``//`` and ``<img>``
  tags with an ``src`` attribute that is an absolute URL.

The implementation uses the standard library ``html.parser`` to avoid adding a
runtime dependency.  For each rule that fails a clear message is appended to the
``errors`` list which is ultimately returned to the caller.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import List

__all__ = ["validate_html"]


class _TagCollector(HTMLParser):
    """Collect tags and relevant attribute values while parsing HTML.

    The parser gathers:
    * ``titles`` – text inside the first ``<title>`` element.
    * ``h1_count`` – number of ``<h1>`` tags.
    * ``section_count`` – number of ``<section>`` tags.
    * ``script_present`` – ``True`` if any ``<script>`` tag appears.
    * ``iframe_present`` – ``True`` if any ``<iframe>`` tag appears.
    * ``external_links`` – ``href`` values that are absolute URLs.
    * ``external_images`` – ``src`` values that are absolute URLs.
    """

    def __init__(self) -> None:
        super().__init__()
        self.titles: List[str] = []
        self._in_title = False
        self.h1_count = 0
        self.section_count = 0
        self.script_present = False
        self.iframe_present = False
        self.external_links: List[str] = []
        self.external_images: List[str] = []
        # New collections for additional validation rules
        self.inline_event_handlers: List[tuple[str, str]] = []  # (tag, attribute)
        self.javascript_urls: List[tuple[str, str]] = []  # (tag, attribute)
        self.css_issues: List[str] = []  # descriptions of CSS problems
        self.forbidden_tags: List[str] = []  # e.g., object, embed, meta[refresh]
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_low = tag.lower()
        if tag_low == "title":
            self._in_title = True
        elif tag_low == "h1":
            self.h1_count += 1
        elif tag_low == "section":
            self.section_count += 1
        elif tag_low == "script":
            self.script_present = True
        elif tag_low == "iframe":
            self.iframe_present = True
        elif tag_low == "link":
            href = dict(attrs).get("href", "")
            if _is_absolute_url(href):
                self.external_links.append(href)
        elif tag_low == "img":
            src = dict(attrs).get("src", "")
            if _is_absolute_url(src):
                self.external_images.append(src)
            # Detect javascript: URLs in img src
            if src and src.strip().lower().startswith("javascript:"):
                self.javascript_urls.append((tag_low, "src"))
        elif tag_low == "style":
            # Enter style tag to capture its inner CSS content
            self._in_style = True

        # Detect forbidden tags immediately
        if tag_low in {"object", "embed"}:
            self.forbidden_tags.append(tag_low)
        if tag_low == "meta":
            attrs_dict = dict(attrs)
            if attrs_dict.get("http-equiv", "").lower() == "refresh":
                self.forbidden_tags.append("meta[http-equiv=refresh]")

        # Scan attributes for inline event handlers and javascript: schemes
        for name, value in attrs:
            if not value:
                continue
            name_low = name.lower()
            # Inline event handlers (e.g., onclick, onmouseover)
            if name_low.startswith("on"):
                self.inline_event_handlers.append((tag_low, name_low))
            # javascript: URLs in any attribute (scheme detection independent of URL type)
            if value.strip().lower().startswith("javascript:"):
                self.javascript_urls.append((tag_low, name_low))
            # Style attribute: check for CSS url(...) or @import
            if name_low == "style":
                if re.search(r"url\s*\(", value, re.IGNORECASE) or re.search(r"@import", value, re.IGNORECASE):
                    self.css_issues.append(f"style attribute in <{tag_low}> contains disallowed CSS")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        if tag.lower() == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.titles.append(data)
        # Capture CSS inside <style> tag content
        if self._in_style:
            if re.search(r"url\s*\(", data, re.IGNORECASE) or re.search(r"@import", data, re.IGNORECASE):
                self.css_issues.append("<style> tag contains disallowed CSS")


def _is_absolute_url(url: str) -> bool:
    """Return ``True`` if *url* looks like an absolute HTTP(S) URL.

    The check is deliberately simple – it matches schemes ``http``, ``https`` and
    protocol‑relative URLs starting with ``//``.
    """
    if not url:
        return False
    return bool(re.match(r"^(https?:)?//", url, re.IGNORECASE))


def validate_html(html: str) -> List[str]:
    """Validate *html* against the repository's core rules.

    Parameters
    ----------
    html: str
        The raw HTML document to validate.

    Returns
    -------
    list[str]
        A list of error messages.  An empty list indicates the document passed all
        checks.
    """
    errors: List[str] = []

    # 1. Size check – UTF‑8 bytes must be <= 100 KB.
    if len(html.encode("utf-8")) > 100 * 1024:
        errors.append("HTML size exceeds 100 KB limit.")

    parser = _TagCollector()
    try:
        parser.feed(html)
    except Exception as exc:  # pragma: no cover – unexpected parser errors.
        errors.append(f"Failed to parse HTML: {exc}")
        return errors

    # 2. Title check.
    title_text = "".join(parser.titles).strip()
    if not title_text:
        errors.append("Missing or empty <title> element.")

    # 3. Exactly one <h1>.
    if parser.h1_count != 1:
        errors.append(f"Expected exactly one <h1>, found {parser.h1_count}.")

    # 4. At least three <section>.
    if parser.section_count < 3:
        errors.append(
            f"Expected at least three <section> elements, found {parser.section_count}."
        )

    # 5. No script tags.
    if parser.script_present:
        errors.append("<script> tags are not allowed.")

    # 6. No iframe tags.
    if parser.iframe_present:
        errors.append("<iframe> tags are not allowed.")

    # 7. No external resources (links or images).
    if parser.external_links:
        errors.append("External <link> resources are prohibited.")
    if parser.external_images:
        errors.append("External <img> sources are prohibited.")

    # 8. Inline event handlers (attributes starting with 'on').
    for tag, attr in parser.inline_event_handlers:
        errors.append(f"Inline event handler attribute '{attr}' found on <{tag}> tag.")

    # 9. javascript: URLs in any attribute.
    for tag, attr in parser.javascript_urls:
        errors.append(f"javascript: URL found in attribute '{attr}' on <{tag}> tag.")

    # 10. Disallowed CSS constructs (url(...) or @import) in style tags or attributes.
    for issue in parser.css_issues:
        errors.append(issue)

    # 11. Forbidden tags: <object>, <embed>, and <meta http-equiv='refresh'>.
    for tag in parser.forbidden_tags:
        errors.append(f"Forbidden tag '<{tag}>' is not allowed.")

    return errors

