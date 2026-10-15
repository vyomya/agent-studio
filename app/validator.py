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
* External resources are prohibited in src/srcset attributes and in external
  href values on link/base elements.

The implementation uses the standard library ``html.parser`` to avoid adding a
runtime dependency.  For each rule that fails a clear message is appended to the
``errors`` list which is ultimately returned to the caller.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import List

__all__ = ["validate_html"]

_VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
_OPTIONAL_END_TAGS = {
    "body", "dd", "dt", "head", "html", "li", "optgroup",
    "option", "p", "rp", "rt", "tbody", "td", "tfoot",
    "th", "thead", "tr",
}
_IMPLIED_CLOSES = {
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "p": {"address", "article", "aside", "blockquote", "div", "dl",
           "fieldset", "footer", "form", "h1", "h2", "h3", "h4",
           "h5", "h6", "header", "hr", "menu", "nav", "ol",
           "p", "pre", "section", "table", "ul"},
    "option": {"option"},
    "optgroup": {"optgroup"},
    "rt": {"rp", "rt"},
    "rp": {"rp", "rt"},
    "td": {"td", "th"},
    "th": {"td", "th"},
    "tr": {"tr"},
    "thead": {"tbody", "tfoot", "thead"},
    "tbody": {"tbody", "tfoot", "thead"},
    "tfoot": {"tbody", "tfoot", "thead"},
}


class _TagCollector(HTMLParser):
    """Collect tags and relevant attribute values while parsing HTML.

    The parser gathers:
    * ``titles`` – text inside the first ``<title>`` element.
    * ``h1_count`` – number of ``<h1>`` tags.
    * ``section_count`` – number of ``<section>`` tags.
    * ``script_present`` – ``True`` if any ``<script>`` tag appears.
    * ``iframe_present`` – ``True`` if any ``<iframe>`` tag appears.
    * ``external_links``/``external_bases`` – external href values.
    * ``external_sources`` – external src or srcset values.
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
        self.external_sources: List[tuple[str, str]] = []
        self.external_bases: List[str] = []
        # New collections for additional validation rules
        self.inline_event_handlers: List[tuple[str, str]] = []  # (tag, attribute)
        self.javascript_urls: List[tuple[str, str]] = []  # (tag, attribute)
        self.css_issues: List[str] = []  # descriptions of CSS problems
        self.forbidden_tags: List[str] = []  # e.g., object, embed, meta[refresh]
        self._in_style = False
        self.tag_stack: List[str] = []
        self.syntax_errors: List[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_low = tag.lower()
        implied = _IMPLIED_CLOSES.get(tag_low, set())
        while self.tag_stack and self.tag_stack[-1] in implied:
            self.tag_stack.pop()
        if tag_low not in _VOID_ELEMENTS:
            self.tag_stack.append(tag_low)
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
            href = dict(attrs).get("href", "") or ""
            if _is_absolute_url(href):
                self.external_links.append(href)
        elif tag_low == "base":
            href = dict(attrs).get("href", "") or ""
            if _is_absolute_url(href):
                self.external_bases.append(href)
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
            # Browsers ignore ASCII whitespace/control characters in URL schemes.
            if _is_javascript_url(value):
                self.javascript_urls.append((tag_low, name_low))
            if name_low == "src" and _is_absolute_url(value):
                self.external_sources.append((tag_low, name_low))
            elif name_low == "srcset" and _srcset_has_external_url(value):
                self.external_sources.append((tag_low, name_low))
            # Style attribute: check for CSS url(...) or @import
            if name_low == "style":
                if re.search(r"url\s*\(", value, re.IGNORECASE) or re.search(r"@import", value, re.IGNORECASE):
                    self.css_issues.append(f"style attribute in <{tag_low}> contains disallowed CSS")

    def handle_endtag(self, tag: str) -> None:
        tag_low = tag.lower()
        if tag_low == "title":
            self._in_title = False
        if tag_low == "style":
            self._in_style = False
        if tag_low not in self.tag_stack:
            self.syntax_errors.append(f"Unexpected closing tag </{tag_low}>.")
            return
        index = len(self.tag_stack) - 1 - self.tag_stack[::-1].index(tag_low)
        intervening = self.tag_stack[index + 1:]
        invalid = [name for name in intervening if name not in _OPTIONAL_END_TAGS]
        if invalid:
            self.syntax_errors.append(
                f"Mismatched closing tag </{tag_low}> before </{invalid[-1]}>."
            )
        del self.tag_stack[index:]

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.titles.append(data)
        # Capture CSS inside <style> tag content
        if self._in_style:
            if re.search(r"url\s*\(", data, re.IGNORECASE) or re.search(r"@import", data, re.IGNORECASE):
                self.css_issues.append("<style> tag contains disallowed CSS")


def _normalize_url(url: str) -> str:
    return "".join(char for char in url if ord(char) > 32 and ord(char) != 127)


def _is_javascript_url(value: str) -> bool:
    return _normalize_url(value).lower().startswith("javascript:")


def _srcset_has_external_url(srcset: str) -> bool:
    candidates = (candidate.strip().split(maxsplit=1)[0] for candidate in srcset.split(",") if candidate.strip())
    return any(_is_absolute_url(candidate) for candidate in candidates)


def _is_absolute_url(url: str) -> bool:
    """Return ``True`` if *url* looks like an absolute HTTP(S) URL.

    The check is deliberately simple – it matches schemes ``http``, ``https`` and
    protocol‑relative URLs starting with ``//``.
    """
    normalized = _normalize_url(url)
    if not normalized:
        return False
    return bool(re.match(r"^(https?:)?//", normalized, re.IGNORECASE))


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
        parser.close()
    except Exception as exc:  # pragma: no cover – unexpected parser errors.
        errors.append(f"Failed to parse HTML: {exc}")
        return errors

    unclosed = [tag for tag in parser.tag_stack if tag not in _OPTIONAL_END_TAGS]
    if unclosed:
        parser.syntax_errors.append("Unclosed HTML elements: " + ", ".join(unclosed) + ".")
    errors.extend(parser.syntax_errors)

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

    # 7. No external resources in src/srcset or relevant href attributes.
    if parser.external_links:
        errors.append("External <link> resources are prohibited.")
    if parser.external_sources:
        errors.append("External src/srcset resources are prohibited.")
    if parser.external_bases:
        errors.append("External <base> URLs are prohibited.")

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

