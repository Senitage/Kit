"""Private results. A tool marks its result ``private`` when the text came from
somewhere Dan keeps to himself (a private folder, his finances). A cloud model never
reads such text as it is: the local model reads it, with no persona, and answers the
question from it in a few words, and only that summary joins the cloud request. With
the local model off, the cloud model is told the answer is in a private source.
See docs/2 How Kit Works/Privacy.md."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from kit.local_model import LocalModelError

if TYPE_CHECKING:
    from kit.local_model import LocalModel
    from kit.tools import ToolResult

log = logging.getLogger(__name__)

SUMMARY_WORDS = 60
MARK = "[Summarised locally from a private source]"
NO_LOCAL = (
    "I found it, but it's in a private source I can only read locally, and my local model is off."
)

SUMMARISE = (
    "You read a private document so that you can answer one question from it. Answer "
    f"the question from the text in at most {SUMMARY_WORDS} words: only the figures, dates "
    "and names it asks for, and where in the text they are. Nothing else from the text. "
    "If the text doesn't answer it, say so."
)


async def for_cloud(result: ToolResult, question: str, model: LocalModel) -> str:
    """What a cloud model may read of ``result``: the text itself when it isn't
    private, else the local model's short answer to ``question`` from it."""
    if not result.private:
        return result.text
    messages = [
        {"role": "system", "content": SUMMARISE},
        {"role": "user", "content": f"Question: {question}\n\nText:\n{result.text}"},
    ]
    try:
        summary = (await model.complete(messages, None)).strip()
    except LocalModelError as e:
        log.info("couldn't summarise a private result locally: %s", e)
        return NO_LOCAL
    words = summary.split()
    if len(words) > SUMMARY_WORDS * 2:  # a model that rambled: keep the start
        summary = " ".join(words[: SUMMARY_WORDS * 2])
    return f"{MARK} {summary}" if summary else NO_LOCAL
