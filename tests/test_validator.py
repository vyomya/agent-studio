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

