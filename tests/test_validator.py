import textwrap

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
    assert any("img" in e.lower() for e in errors)


def test_oversized_html():
    # Create a string >100KB
    big_body = "<p>" + ("x" * 1024 * 101) + "</p>"
    html = _make_html(body=big_body)
    errors = validate_html(html)
    assert any("size" in e.lower() for e in errors)

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

def test_inline_event_handler():
    html = _make_html(body="<div onclick='alert(1)'>Click</div>")
    errors = validate_html(html)
    # Should flag the inline event handler attribute
    assert any("inline event" in e.lower() for e in errors)

def test_javascript_url():
    html = _make_html(body="<a href='javascript:alert(1)'>bad</a>")
    errors = validate_html(html)
    assert any("javascript" in e.lower() for e in errors)

def test_css_in_style_attribute():
    html = _make_html(body="<div style='background:url(http://example.com/bg.png)'>test</div>")
    errors = validate_html(html)
    assert any("css" in e.lower() for e in errors) or any("style attribute" in e.lower() for e in errors)

def test_css_in_style_tag():
    css = "<style>body { background: url('http://example.com/bg.png'); @import url('foo.css'); }</style>"
    html = _make_html(body=css)
    errors = validate_html(html)
    assert any("css" in e.lower() for e in errors) or any("style" in e.lower() for e in errors)

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

