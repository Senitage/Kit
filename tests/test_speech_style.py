"""A speech style of the owner's own ("talk like a character from a book") has to
win over everything else in the prompt that says how Kit sounds: his self-sheet,
the default examples, the cheek style and how he sounded earlier."""

from datetime import datetime

from kit.life import Voice
from kit.notebook import basis
from kit.prompt import TURN_PART, speak_note, system_prompt
from kit.recall import Recalled
from kit.reply import Action
from kit.settings import PersonaSettings

STYLE = (
    "Speak like a cheerful alien engineer who drops small words and ends questions with 'question'."
)
NOW = datetime(2026, 10, 9, 9)
SHEET = "I'm Kit. I talk short and Australian-casual, a bit of a larrikin."
CHEEKY = Voice(feeling="chirpy", style="properly cheeky, a little larrikin", examples=[], said=[])


def chat_prompt(persona: PersonaSettings) -> str:
    return system_prompt(
        persona, Recalled([], [], []), NOW, role="chat", sheet=SHEET, traits=False, voice=CHEEKY
    )


def test_his_own_style_beats_the_sheet_examples_and_cheek():
    prompt = chat_prompt(PersonaSettings(speech=STYLE))
    fixed, _, turn = prompt.partition(TURN_PART)
    # Said with what it beats, after the self-sheet...
    first = fixed.index(f"Your voice: {STYLE}")
    assert first > fixed.index(SHEET)
    assert "beats anything else here about how you talk" in fixed
    # ...and again last in the part that stays the same, after every list and rule.
    assert fixed.rstrip().endswith(f"Above all, your voice: {STYLE}")
    # The default examples are in the default voice, so they go.
    assert "Coffee first, or straight into it?" not in prompt
    # The cheek style bends to it rather than replacing it.
    assert "a little larrikin, in your own voice" in turn


def test_the_default_voice_keeps_its_examples():
    prompt = chat_prompt(PersonaSettings())
    assert "Coffee first, or straight into it?" in prompt
    assert "Above all, your voice: Short sentences" in prompt


def test_his_own_examples_stay_with_his_own_style():
    persona = PersonaSettings(
        speech=STYLE, examples=[{"user": "Morning.", "kit": "Good morning, question?"}]
    )
    assert "Good morning, question?" in chat_prompt(persona)


def test_a_new_style_makes_his_self_sheet_out_of_date():
    """So his next reflection rewrites the sheet, which says how he talks."""
    default = PersonaSettings()
    assert basis(default) == f"{default.backstory} | {'; '.join(default.traits)}"
    assert basis(PersonaSettings(speech=STYLE)) != basis(default)


def test_the_local_speaking_step_says_his_style_again():
    note = speak_note(Action(kind="none"), "Dan", "sonnet", "opus", speech=STYLE)
    assert f"Your voice: {STYLE}" in note
