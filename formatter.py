import html
import re


def markdown_to_telegram_html(text: str) -> str:
    """Converts AI Markdown output into rich, beautifully formatted Telegram HTML"""
    if not text:
        return ""

    # 1. Protect code blocks ```lang\ncode\n```
    code_blocks = []

    def save_code_block(match):
        lang = match.group(1) or ""
        code = match.group(2)
        escaped_code = html.escape(code.strip("\n"))
        idx = len(code_blocks)
        if lang:
            replacement = (
                f'<pre><code class="language-{lang}">{escaped_code}</code></pre>'
            )
        else:
            replacement = f"<pre><code>{escaped_code}</code></pre>"
        code_blocks.append(replacement)
        return f"___CODE_BLOCK_{idx}___"

    text = re.sub(r"```(\w+)?\n?(.*?)```", save_code_block, text, flags=re.DOTALL)

    # 2. Protect inline code `code`
    inline_codes = []

    def save_inline_code(match):
        code = match.group(1)
        escaped = html.escape(code)
        idx = len(inline_codes)
        inline_codes.append(f"<code>{escaped}</code>")
        return f"___INLINE_CODE_{idx}___"

    text = re.sub(r"`([^`\n]+)`", save_inline_code, text)

    # 3. Escape raw HTML characters in remaining text
    text = html.escape(text)

    # 4. Format headers #, ##, ###
    text = re.sub(r"^### (.*?)$", r"<b>🔹 \1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.*?)$", r"<b>📌 \1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"^# (.*?)$", r"<b>🚀 \1</b>", text, flags=re.MULTILINE)

    # 5. Format Bold **text** and Italic *text*
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", text)

    # 6. Format expandable blockquotes
    text = _format_expandable_blockquotes(text)

    # 7. Restore inline code and code blocks
    for idx, code_html in enumerate(inline_codes):
        text = text.replace(f"___INLINE_CODE_{idx}___", code_html)

    for idx, block_html in enumerate(code_blocks):
        text = text.replace(f"___CODE_BLOCK_{idx}___", block_html)

    return text


def _format_expandable_blockquotes(text: str) -> str:
    """Converts markdown quotes into Telegram expandable blockquotes."""
    lines = text.split("\n")
    new_lines = []
    quote_lines = []
    in_quote = False

    for line in lines:
        if line.startswith("&gt; ") or line.startswith("> "):
            content = line[5:] if line.startswith("&gt; ") else line[2:]
            quote_lines.append(content)
            in_quote = True
        else:
            if in_quote:
                q_text = "\n".join(quote_lines)
                new_lines.append(f"<blockquote expandable>{q_text}</blockquote>")
                quote_lines = []
                in_quote = False
            new_lines.append(line)

    if in_quote:
        q_text = "\n".join(quote_lines)
        new_lines.append(f"<blockquote expandable>{q_text}</blockquote>")

    return "\n".join(new_lines)


def format_response_header(model: str, effort: str, workspace: str) -> str:
    """Returns empty string so no branding header is added"""
    return ""


def format_error_card(error_msg: str, suggestion: str | None = None) -> str:
    """Builds a friendly casual error message"""
    clean_err = html.escape(error_msg)
    sug_text = f"\n\n💡 {suggestion}" if suggestion else ""
    return f"oops, something went wrong 😅\n<code>{clean_err}</code>{sug_text}"
