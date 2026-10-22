import textwrap

import app.validator as validator
from app.validator import validate_html


def _make_html(**overrides) -> str:
    """Utility to build an HTML document with selectable override parts.

    The base document satisfies all validation rules. Overrides can replace any
    section by providing a keyword matching a placeholder name.
    """
    base = {
        "title": "<title>Test Page</title>",
        "h1": "<h1>Header</h1>",
        "sections": """<section>One</section>
        <section>Two</section>
        <section>Three</section>""",
        "body": "<p>Content</p>",
    }
    base.update(overrides)
    return f"""<!DOCTYPE html>
<html>
<head>{base['title']}</head>
<body>{base['h1']}{base['sections']}{base['body']}</body>
</html>"""


def test_validator_all_pass():
    html = _make_html()
    assert validate_html(html) == []


def test_missing_title():
    html = _make_html(title="")
    errors = validate_html(html)
    assert any("<title>" in e for e in errors)


def test_multiple_h1():
    html = _make_html(h1="<h1>One</h1><h1>Two</h1>")
    errors = validate_html(html)
    assert any("<h1>" in e for e in errors)


def test_insufficient_sections():
    html = _make_html(sections="<section>Only</section>")
    errors = validate_html(html)
    assert any("<section>" in e for e in errors)


def test_disallowed_script():
    html = _make_html(body="<script>alert('x');</script>")
    errors = validate_html(html)
    assert any("script" in e.lower() for e in errors)


def test_disallowed_iframe():
    html = _make_html(body="<iframe src='about:blank'></iframe>")
    errors = validate_html(html)
    assert any("iframe" in e.lower() for e in errors)


def test_external_link_and_image():
    body = (
        "<link href='https://example.com/style.css' rel='stylesheet'>"
        "<img src='http://example.com/image.png'>"
    )
    html = _make_html(body=body)
    errors = validate_html(html)
    assert any("link" in e.lower() for e in errors)
    assert any("src/srcset" in e.lower() for e in errors)


def test_oversized_html():
    # The limit is inclusive, so one byte above 100 KiB must fail.
    limit = 100 * 1024
    empty_body_html = _make_html(body="")
    body = "x" * (limit + 1 - len(empty_body_html.encode("utf-8")))
    html = _make_html(body=body)
    assert len(html.encode("utf-8")) == limit + 1
    errors = validate_html(html)
    assert any("size" in e.lower() for e in errors)


def test_html_at_exactly_100_kib_is_allowed():
    limit = 100 * 1024
    empty_body_html = _make_html(body="")
    body = "x" * (limit - len(empty_body_html.encode("utf-8")))
    html = _make_html(body=body)

    assert len(html.encode("utf-8")) == limit
    assert validate_html(html) == []

def test_inline_event_handler():
    """Validator should flag any attribute that starts with ``on`` (e.g., ``onclick``)."""
    html = _make_html(body="<div onclick='alert(1)'>Click</div>")
    errors = validate_html(html)
    # The error message includes the attribute name and tag.
    assert any("onclick" in e.lower() or "inline event" in e.lower() for e in errors)

def test_javascript_url():
    """Validator should reject ``javascript:`` URLs in any attribute value."""
    html = _make_html(body="<a href='javascript:alert(1)'>bad</a>")
    errors = validate_html(html)
    assert any("javascript" in e.lower() for e in errors)

def test_css_in_style_attribute():
    """Validator should detect disallowed CSS constructs in a ``style`` attribute."""
    html = _make_html(body="<div style='background:url(http://example.com/bg.png)'>test</div>")
    errors = validate_html(html)
    # The implementation flags CSS problems with a generic message; we accept either.
    assert any("css" in e.lower() for e in errors) or any("style attribute" in e.lower() for e in errors)

def test_css_in_style_tag():
    """Validator should detect disallowed CSS in a ``<style>`` block.

    Both ``url(...)`` and ``@import`` are prohibited.
    """
    css = "<style>body { background: url('http://example.com/bg.png'); @import url('foo.css'); }</style>"
    html = _make_html(body=css)
    errors = validate_html(html)
    assert any("css" in e.lower() for e in errors) or any("style" in e.lower() for e in errors)

def test_non_event_data_attributes_are_allowed():
    html = _make_html(body="<div data-onclick='not-an-event'>safe</div>")
    assert validate_html(html) == []

def test_forbidden_tags():
    body = (
        "<object data='movie.swf'></object>"
        "<embed src='video.mp4'>"
        "<meta http-equiv='refresh' content='0;url=https://example.com'>"
    )
    html = _make_html(body=body)
    errors = validate_html(html)
    # Ensure each forbidden tag is reported
    assert any("object" in e.lower() for e in errors)
    assert any("embed" in e.lower() for e in errors)
    assert any("meta" in e.lower() and "refresh" in e.lower() for e in errors)



def test_obfuscated_javascript_url_rejected():
    html = _make_html(body="<a href='java&#x09;script:alert(1)'>bad</a>")
    assert any("javascript" in error.lower() for error in validate_html(html))


def test_safe_relative_url_allowed():
    assert validate_html(_make_html(body="<a href='/about'>About</a>")) == []


def test_non_external_css_is_allowed():
    body = "<style>body { color: navy; }</style><p style='color: navy'>safe</p>"
    assert validate_html(_make_html(body=body)) == []


def test_mismatched_html_tags_are_rejected():
    html = _make_html(body="<div><span>broken</div></span>")
    assert any("mismatched" in error.lower() for error in validate_html(html))


def test_unclosed_html_elements_are_rejected():
    html = _make_html(body="<div>not closed")
    assert any("unclosed" in error.lower() or "mismatched" in error.lower()
               for error in validate_html(html))


def test_valid_void_and_optional_end_tags_parse():
    body = "<img src='/local.png'><p>first<p>second<ul><li>one<li>two</ul>"
    assert validate_html(_make_html(body=body)) == []


def test_paragraph_inside_section_is_valid():
    body = "<section><p>text</p></section>" * 3
    assert validate_html(_make_html(body=body)) == []


def test_nested_elements_with_optional_list_item_closings_are_valid():
    body = (
        "<section><div><article><p>x</p><ul><li>a<li>b</ul>"
        "</article></div></section>"
    ) * 3
    assert validate_html(_make_html(body=body)) == []


def test_unclosed_paragraph_before_section_is_valid():
    body = "<p>text<section>one</section><section>two</section><section>three</section>"
    assert validate_html(_make_html(body=body)) == []


def test_nonoptional_mismatched_closing_tags_still_fail():
    body = "<section><div></section></div>"
    errors = validate_html(_make_html(body=body))
    assert any("mismatched closing tag" in error.lower() for error in errors)


def test_external_resources_in_all_supported_attributes_rejected():
    body = (
        "<video src='https://cdn.example/movie.mp4'></video>"
        "<audio><source src='//cdn.example/audio.mp3'></audio>"
        "<img srcset='/small.png 1x, https://cdn.example/large.png 2x'>"
        "<base href='https://cdn.example/'><link href='//cdn.example/site.css'>"
    )
    errors = validate_html(_make_html(body=body))
    assert any("src/srcset" in error.lower() for error in errors)
    assert any("base" in error.lower() for error in errors)
    assert any("link" in error.lower() for error in errors)


def test_local_resource_attributes_allowed():
    body = (
        "<video src='/movie.mp4'></video><audio><source src='audio.mp3'></audio>"
        "<img srcset='/small.png 1x, /large.png 2x'><base href='/'>"
        "<link href='/local.css' rel='stylesheet'>"
    )
    assert validate_html(_make_html(body=body)) == []



def test_each_external_resource_location_rejected_independently():
    cases = [
        ("<video src='https://cdn.example/movie.mp4'></video>", "src/srcset"),
        ("<audio><source src='//cdn.example/audio.mp3'></audio>", "src/srcset"),
        ("<img srcset='/small.png 1x, https://cdn.example/large.png 2x'>", "src/srcset"),
        ("<base href='https://cdn.example/'>", "base"),
        ("<link href='//cdn.example/site.css'>", "link"),
    ]
    for snippet, expected in cases:
        errors = validate_html(_make_html(body=snippet))
        assert any(expected in error.lower() for error in errors), snippet


def test_safe_resource_locations_allowed_independently():
    cases = [
        "<video src='/movie.mp4'></video>",
        "<audio><source src='audio.mp3'></audio>",
        "<img srcset='/small.png 1x, /large.png 2x'>",
        "<base href='/'>",
        "<link href='/site.css'>",
    ]
    for snippet in cases:
        assert validate_html(_make_html(body=snippet)) == [], snippet

def test_validation_preserves_original_html():
    html = _make_html(body="<video src='https://cdn.example/movie.mp4'></video>")
    original = html[:]
    validate_html(html)
    assert html == original


def test_parser_exception_returns_human_readable_error(monkeypatch):
    def fail_to_parse(self, data):
        raise ValueError("synthetic parser failure")

    monkeypatch.setattr(validator._TagCollector, "feed", fail_to_parse)

    errors = validate_html(_make_html())

    assert any("failed to parse html" in error.lower() for error in errors)
    assert any("synthetic parser failure" in error for error in errors)
