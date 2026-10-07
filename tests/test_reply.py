import json

import pytest

from fakes import reply
from kit.reply import Reply, ReplyError, SayExtractor, parse_reply, reply_schema


def feed_all(text, size):
    x = SayExtractor()
    return "".join(x.feed(text[i : i + size]) for i in range(0, len(text), size))


@pytest.mark.parametrize("size", [1, 2, 3, 7, 1000])
def test_extractor_gets_spoken_text_at_any_chunk_size(size):
    raw = reply('Hi "Dan", café\\n time.', "Second one.", action="ask_cloud", text="say: no")
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
    assert list(reply_schema()["properties"]) == ["emotion", "segments", "action", "detail"]


def test_plain_reply():
    assert Reply.plain("Hello").segments[0].gesture == "none"


def test_cloud_replies_are_read_generously():
    from kit.reply import parse_cloud_reply

    good = reply("Sunny.", action="remember", text="Dan likes sun.")
    assert parse_cloud_reply(good).action.kind == "remember"
    assert parse_cloud_reply(f"```json\n{good}\n```").text == "Sunny."
    assert parse_cloud_reply(f"Here you go: {good} Hope that helps.").text == "Sunny."
    short = parse_cloud_reply("It's 24 and sunny.")
    assert short.text == "It's 24 and sunny." and short.detail == ""
    long = parse_cloud_reply("First sentence here. " + "More words. " * 40)
    assert long.text == "First sentence here." and long.detail.startswith("First sentence")


def test_cloud_reply_survives_split_json_and_made_up_values():
    from kit.reply import parse_cloud_reply

    # A web search splits the answer: a half-written attempt, then the real one,
    # with an emotion and a gesture that aren't in the list.
    real = json.dumps(
        {
            "emotion": "shrug",
            "segments": [{"say": "About 24 and sunny.", "gesture": "point_up"}],
            "action": {"kind": "none", "category": "weather"},
            "detail": "Max 26 tomorrow.",
        }
    )
    text = '{"emotion": "neutral", "segments": [{"say": "Let me che' + "\n" + real
    r = parse_cloud_reply(text)
    assert r.text == "About 24 and sunny."
    assert r.emotion == "neutral" and r.segments[0].gesture == "none"
    assert r.action.kind == "none" and r.action.category == "other"
    assert r.detail == "Max 26 tomorrow."


def test_cloud_reply_keeps_good_action_fields():
    from kit.reply import parse_cloud_reply

    data = {
        "emotion": "happy",
        "segments": [{"say": "Noted."}, {"say": ""}],
        "action": {"kind": "remember", "text": "Dan likes sun.", "category": "bogus"},
    }
    r = parse_cloud_reply(json.dumps(data))
    assert [s.say for s in r.segments] == ["Noted."]
    assert r.action.kind == "remember" and r.action.text == "Dan likes sun."
    assert r.action.category == "other"
    bad_kind = parse_cloud_reply(json.dumps({**data, "action": {"kind": "explode"}}))
    assert bad_kind.action.kind == "none" and bad_kind.text == "Noted."


def test_full_text_adds_detail():
    from kit.reply import Reply

    r = Reply.plain("Here.")
    assert r.full_text == "Here."
    r.detail = "x = 1"
    assert r.full_text == "Here.\n\nx = 1"
