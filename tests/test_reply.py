import json

import pytest

from fakes import reply
from kit.reply import Reply, ReplyError, SayExtractor, parse_reply, reply_schema


def feed_all(text, size):
    x = SayExtractor()
    return "".join(x.feed(text[i : i + size]) for i in range(0, len(text), size))


@pytest.mark.parametrize("size", [1, 2, 3, 7, 1000])
def test_extractor_gets_spoken_text_at_any_chunk_size(size):
    raw = reply('Hi "Dan", café\\n time.', "Second one.", action="ask_claude", text="say: no")
    assert feed_all(raw, size) == 'Hi "Dan", café\\n time. Second one.'


def test_extractor_handles_unicode_escapes_and_spacing():
    raw = '{"emotion": "happy", "segments": [ { "say" : "caf\\u00e9 \\ud83d" } ]}'
    assert feed_all(raw, 1).startswith("café")


@pytest.mark.parametrize("size", [1, 3, 1000])
def test_extractor_joins_surrogate_pairs(size):
    raw = '{"segments": [{"say": "Go \\ud83d\\ude00 now"}]}'
    assert feed_all(raw, size) == "Go 😀 now"


def test_extractor_survives_bad_escapes_and_empty_sentences():
    raw = '{"segments": [{"say": "a\\uZZZZb"}, {"say": ""}, {"say": "\\udc00c"}]}'
    assert feed_all(raw, 1) == "ab c"


def test_extractor_ignores_other_fields_named_like_say():
    raw = json.dumps({"emotion": "say", "segments": [{"gesture": "nod", "say": "Yes."}]})
    assert feed_all(raw, 2) == "Yes."


def test_parse_valid_reply():
    r = parse_reply(reply("One.", "Two."))
    assert r.text == "One. Two." and r.action.kind == "none"


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        reply("x", emotion="furious"),
        reply("x", gesture="backflip"),
        json.dumps({"emotion": "happy", "segments": [], "action": {"kind": "none"}}),
    ],
)
def test_parse_rejects_bad_replies(bad):
    with pytest.raises(ReplyError):
        parse_reply(bad)


def test_schema_is_self_contained():
    schema = json.dumps(reply_schema())
    assert "$ref" not in schema and "$defs" not in schema
    assert list(reply_schema()["properties"]) == ["emotion", "segments", "action"]


def test_plain_reply():
    assert Reply.plain("Hello").segments[0].gesture == "none"
