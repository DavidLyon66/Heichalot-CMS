from tools.renderhtml import has_dialog_blocks, preprocess_dialogs


def test_dialog_to_h3_and_ai_status_removed():
    text = '"""Narrator\nHello.\n"""\n"""Ai\n(Status check).\nAnswer.\n"""'
    result = preprocess_dialogs(text)
    assert '### Narrator' in result
    assert '### Ai' in result
    assert 'Hello.' in result
    assert 'Answer.' in result
    assert 'Status check' not in result
    assert '"""' not in result


def test_plain_markdown_is_unchanged():
    text = '# Title\n\nParagraph.\n'
    assert has_dialog_blocks(text) is False
    assert preprocess_dialogs(text) == text


def test_inline_parenthetical_is_preserved():
    text = '"""Ai\nHe said (quietly) to himself.\n"""'
    assert '(quietly)' in preprocess_dialogs(text)
