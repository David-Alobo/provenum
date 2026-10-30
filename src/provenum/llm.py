"""Ask a local language model (Ollama API) which table value each number reports.

Only the standard library is used, so provenum keeps no runtime dependencies. The model sees the
catalogue of addressable values, optional project notes and one number at a time with its
sentence and paragraph; it answers with a path or null in a fixed JSON schema. Its answer is a
proposal: `anchor.judge` checks the value before anything is trusted.
"""

import json
import urllib.request
from collections.abc import Callable

SYSTEM = """You map numbers in a scientific manuscript to the table value they report.
You are given a catalogue of addressable values. Each block shows a path pattern such as
summary/<engine>/<run>/<column>, the allowed key values and the columns. Answer with the one
full path whose value the marked number [[like this]] reports, or null if the number does not
come from these tables. Give a path only when the sentence clearly reports that exact
quantity; never guess. Do not check arithmetic; another program checks the value."""

SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": ["string", "null"]}},
    "required": ["path"],
}


def ask(
    item: dict, catalogue: str, notes: str, model: str, host: str, timeout: float = 120
) -> str | None:
    """
    Ask the model for the path of one number.

    Args:
        item (dict): From `anchor.items`: number, sentence (target marked [[...]]) and paragraph.
        catalogue (str): Output of `anchor.catalogue`.
        notes (str): Project notes on vocabulary (may be empty).
        model (str): Ollama model name, e.g. "qwen2.5:14b-instruct".
        host (str): Ollama base URL, e.g. "http://127.0.0.1:11434".
        timeout (float): Seconds to wait for one answer.

    Returns:
        str | None: The proposed path, or None.
    """
    user = (
        f"Catalogue:\n{catalogue}\n\n"
        + (f"Notes:\n{notes}\n\n" if notes else "")
        + f"Paragraph: {item['paragraph']}\n\nSentence: {item['sentence']}\n\n"
        + f"Which path does [[{item.get('written', item['number'])}]] report?"
    )
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "format": SCHEMA,
        "stream": False,
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        f"{host.rstrip('/')}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = json.loads(response.read())["message"]["content"]
    try:
        path = json.loads(content).get("path")
    except (json.JSONDecodeError, AttributeError):
        return None
    return path if isinstance(path, str) and path.strip() else None


CHOOSE = """You map numbers in a scientific manuscript to the table value they report.
A program has already found the table values equal to the marked number [[like this]]; most of
these are coincidences. Choose the one path whose quantity the sentence actually reports (same
engine, arm, metric and statistic), or "none" if none of them is what the sentence means."""


def choose(item: dict, candidates: list[str], notes: str, model: str, host: str,
           timeout: float = 120) -> str | None:  # fmt: skip
    """
    Ask the model which of the value-matching paths the sentence means (migration mode).

    Showing only paths whose value already equals the number is safe for migration, which only
    converts numbers that are right; it must not be used to look for errors.

    Args:
        item (dict): From `anchor.items`.
        candidates (list[str]): Paths whose value rounds to the number.
        notes (str): Project notes (may be empty).
        model (str): Ollama model name.
        host (str): Ollama base URL.
        timeout (float): Seconds to wait for one answer.

    Returns:
        str | None: The chosen path, or None.
    """
    schema = {"type": "object", "properties": {"path": {"enum": [*candidates, "none"]}},
              "required": ["path"]}  # fmt: skip
    user = (
        (f"Notes:\n{notes}\n\n" if notes else "")
        + f"Paragraph: {item['paragraph']}\n\nSentence: {item['sentence']}\n\n"
        + "Candidate paths:\n"
        + "\n".join(candidates)
        + f"\n\nWhich path does [[{item.get('written', item['number'])}]] report?"
    )
    content = _chat(CHOOSE, user, schema, model, host, timeout)
    try:
        path = json.loads(content).get("path")
    except (json.JSONDecodeError, AttributeError):
        return None
    return path if path in candidates else None


def _chat(system: str, user: str, schema: dict, model: str, host: str, timeout: float) -> str:
    """
    One deterministic chat call to an Ollama server with a JSON schema for the reply.

    Args:
        system (str): System prompt.
        user (str): User message.
        schema (dict): JSON schema the reply must follow.
        model (str): Ollama model name.
        host (str): Ollama base URL.
        timeout (float): Seconds to wait.

    Returns:
        str: The reply's content (JSON text).
    """
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": schema,
        "stream": False,
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        f"{host.rstrip('/')}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())["message"]["content"]


def anchor_all(
    items: list[dict],
    catalogue: str,
    notes: str,
    model: str,
    host: str,
    progress: Callable[[int, int], None] | None = None,
    shortlists: dict[int, list[str]] | None = None,
) -> list[dict]:
    """
    Ask the model about every item.

    Args:
        items (list[dict]): From `anchor.items`.
        catalogue (str): Output of `anchor.catalogue`.
        notes (str): Project notes (may be empty).
        model (str): Ollama model name.
        host (str): Ollama base URL.
        progress (Callable[[int, int], None] | None): Called with (done, total) after each item.
        shortlists (dict[int, list[str]] | None): Migration mode: per item id, the paths whose
            value matches the number. Items with no candidate get no path and no model call.

    Returns:
        list[dict]: [{id, path}] in item order, for `migrate` and evaluation.
    """
    answers = []
    for n, item in enumerate(items, 1):
        try:
            if shortlists is None:
                path = ask(item, catalogue, notes, model, host)
            else:
                candidates = shortlists.get(item["id"], [])
                path = choose(item, candidates, notes, model, host) if candidates else None
        except OSError:
            path = None
        answers.append({"id": item["id"], "path": path})
        if progress:
            progress(n, len(items))
    return answers
