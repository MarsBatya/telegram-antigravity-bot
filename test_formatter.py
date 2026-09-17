from formatter import markdown_to_telegram_html

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

result = markdown_to_telegram_html(sample_markdown)
print("=== RESULT TELEGRAM HTML ===")
print(result)
