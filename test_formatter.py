from formatter import format_error_card, format_response_header, markdown_to_telegram_html

sample_markdown = """
# Project Main Title
Here is a brief overview of the **rich text features** in Telegram.

## Example Python Code:
```python
def calculate(a, b):
    # Returns the sum of two numbers
    return a + b
```

> This is a long explanatory quote that can be expanded (collapsible blockquote) in Telegram chat!
> Very neat and does not clutter the screen.

### Other Features:
* Use `inline code` for variable names.
* Automatic *italic* and **bold** formatting.
"""


def test_markdown_to_telegram_html_sample():
    result = markdown_to_telegram_html(sample_markdown)
    assert "<b>🚀 Project Main Title</b>" in result
    assert "<b>📌 Example Python Code:</b>" in result
    assert "<b>🔹 Other Features:</b>" in result
    assert '<pre><code class="language-python">' in result
    assert "def calculate(a, b):" in result
    assert "<blockquote expandable>" in result
    assert "<code>inline code</code>" in result
    assert "<b>bold</b>" in result
    assert "<i>italic</i>" in result


def test_markdown_to_telegram_html_empty():
    assert markdown_to_telegram_html("") == ""
    assert markdown_to_telegram_html(None) == ""


def test_markdown_to_telegram_html_code_block():
    md = "```python\ndef hello():\n    return 'world'\n```"
    html_out = markdown_to_telegram_html(md)
    assert '<pre><code class="language-python">' in html_out
    assert "def hello():" in html_out


def test_markdown_to_telegram_html_inline_code():
    md = "Use `var_name` here"
    assert "<code>var_name</code>" in markdown_to_telegram_html(md)


def test_markdown_to_telegram_html_headers():
    md = "# Header 1\n## Header 2\n### Header 3"
    html_out = markdown_to_telegram_html(md)
    assert "<b>🚀 Header 1</b>" in html_out
    assert "<b>📌 Header 2</b>" in html_out
    assert "<b>🔹 Header 3</b>" in html_out


def test_markdown_to_telegram_html_formatting():
    md = "**bold text** and *italic text*"
    html_out = markdown_to_telegram_html(md)
    assert "<b>bold text</b>" in html_out
    assert "<i>italic text</i>" in html_out


def test_markdown_to_telegram_html_blockquote():
    md = "> Quote line 1\n> Quote line 2"
    html_out = markdown_to_telegram_html(md)
    assert "<blockquote expandable>" in html_out
    assert "Quote line 1\nQuote line 2" in html_out


def test_format_response_header():
    header = format_response_header("gemini-3.6-flash-high", "high", "/root/my-project")
    assert header == ""


def test_format_error_card():
    card = format_error_card("something broke", "try /new")
    assert "<code>something broke</code>" in card
    assert "💡 try /new" in card


if __name__ == "__main__":
    result = markdown_to_telegram_html(sample_markdown)
    print("=== RESULT TELEGRAM HTML ===")
    print(result)
