"""Sélecteurs des champs de fichier dans un fragment de formulaire observé."""

from collections import Counter
from html.parser import HTMLParser


class FileInputs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inputs = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "input" and (values.get("type") or "").lower() == "file":
            self.inputs.append(values)


def css_string(value):
    escaped = []
    for char in value:
        if char in {'"', "\\"}:
            escaped.append("\\" + char)
        elif ord(char) < 32 or ord(char) == 127:
            escaped.append(f"\\{ord(char):x} ")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


def file_fields(html, container):
    parser = FileInputs()
    parser.feed(html)
    attributes = ("id", "name", "data-testid", "aria-label")
    counts = Counter(
        (key, field[key])
        for field in parser.inputs
        for key in attributes
        if field.get(key)
    )
    results = []
    for field in parser.inputs:
        if "disabled" in field:
            continue
        attr = next(
            (
                key
                for key in attributes
                if field.get(key) and counts[key, field[key]] == 1
            ),
            None,
        )
        selector = f":is({container}) input[type=file]"
        if attr:
            selector += f"[{attr}={css_string(field[attr])}]"
        elif len(parser.inputs) != 1:
            selector = None
        results.append(
            {
                "selector": selector,
                "name": field.get("name"),
                "accept": field.get("accept"),
                "label": field.get("aria-label") or field.get("title"),
            }
        )
    return results
