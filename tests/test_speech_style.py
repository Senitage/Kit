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
    # ...and once only: said again at the end, with "in your own voice" and "not a
    # help desk" after it, it was eight notes on how he sounds in one prompt.
    assert prompt.count(STYLE) == 1 and "Above all" not in prompt
    assert "your voice" not in prompt.lower().replace(f"your voice: {STYLE.lower()}", "")
    # The default examples are in the default voice, so they go.
    assert "Coffee first, or straight into it?" not in prompt
    # The cheek style bends to it rather than replacing it.
    assert "Be properly cheeky, a little larrikin, as yourself" in turn


def test_the_default_voice_keeps_its_examples():
    prompt = chat_prompt(PersonaSettings())
    assert "Coffee first, or straight into it?" in prompt
    assert "Your voice: Plain, neutral English" in prompt


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


def test_the_local_speaking_step_points_back_at_his_style_rather_than_repeating_it():
    note = speak_note(Action(kind="none"), "Dan", "sonnet", "opus", speech=STYLE)
    assert STYLE not in note and "your voice" in note  # one short reminder, no second copy


def test_a_borrowed_voice_keeps_his_own_name():
    """Speaking like a character had him calling himself by the character's name."""
    prompt = chat_prompt(PersonaSettings(speech=STYLE))
    assert "When you talk about yourself, use 'I' or Kit, never another name" in prompt
    renamed = chat_prompt(PersonaSettings(name="Pip", speech=STYLE))
    assert "use 'I' or Pip" in renamed
