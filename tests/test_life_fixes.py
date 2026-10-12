"""Kit's inner life, the fixes from the review: sulks that pass, no bored pipe-ups on
a bad night, the camera honouring the keyboard, calls not counting as ignoring him,
a restart mid-day, look events kept apart, zone-aware clocks, and the plan saying
which wants a reply brought up."""

import random
from datetime import timedelta

import pytest

from fakes import Clock, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.life import (
    IGNORED_KEEPS,
    MAX_LOOKS,
    MAX_PIPES,
    SULK_FOR,
    THOUGHT_FEELINGS,
    THOUGHT_FEELS,
    Held,
    Life,
    pipe_up_prompt,
)
from kit.memory import Memory
from kit.notebook import share_kind
from kit.pc_context import PcContext
from kit.recall import Recall
from kit.reply import Plan, brought_up_in, early_plan, parse_plan, plan_schema
from kit.scene_context import Happening, SceneContext
from kit.settings import Settings
from kit.settings_store import SettingsStore
from test_life import Saved, run, snap


def setup(when="2026-10-06T10:00:00", tz=None, store=None, eyes=False, **life):
    clock = Clock(when, tz)
    pc = PcContext(clock)
    scene = SceneContext(clock) if eyes else None
    s = Settings.model_validate({"life": life})
    return Life(lambda: s, pc, clock, random.Random(1), store=store, scene=scene), pc, clock


def ignored_once(life, pc, clock):
    """He pipes up, and Dan sits there not answering."""
    assert run(life, pc, clock, 60, snap())
    life.piped_up()
    run(life, pc, clock, 11, snap())
    assert life.ignored == 1 and life.sulky and life.mood() == "sulky"


# 1.1 A sulk passes, and being ignored is forgotten


def test_a_sulk_passes_by_itself_and_being_ignored_is_forgotten_in_an_hour(zone):
    life, pc, clock = setup(tz=zone, chattiness=1, max_per_hour=6)
    ignored_once(life, pc, clock)
    assert clock.now < life.sulky_until <= clock.now + SULK_FOR
    clock.now = life.sulky_until + timedelta(seconds=1)
    assert not life.sulky and life.mood() != "sulky"
    assert life.ignored == 1  # still backs off a bit till the hour's up
    clock.now = life.last_pipe + IGNORED_KEEPS
    pc.update(snap())
    life.tick()
    assert life.ignored == 0


def test_a_sulk_survives_a_restart_only_as_long_as_it_would_have_lasted(zone):
    saved = Saved()
    life, pc, clock = setup(tz=zone, store=saved, chattiness=1, max_per_hour=6)
    ignored_once(life, pc, clock)
    s = Settings.model_validate({"life": {"chattiness": 1, "max_per_hour": 6}})
    clock.now += timedelta(minutes=5)
    again = Life(lambda: s, pc, clock, random.Random(1), store=saved)
    assert again.sulky and again.ignored == 1
    clock.now += SULK_FOR
    later = Life(lambda: s, pc, clock, random.Random(1), store=saved)
    assert not later.sulky and later.mood() != "sulky"


# 1.2 Being on a call isn't ignoring him


def test_an_unanswered_pipe_up_during_a_call_isnt_being_ignored():
    life, pc, clock = setup(chattiness=1, max_per_hour=6)
    assert run(life, pc, clock, 60, snap())
    life.piped_up()
    run(life, pc, clock, 11, snap(app="Teams", title="Call with site"))
    assert not life.awaiting_reply and life.ignored == 0 and not life.sulky
    life, pc, clock = setup(chattiness=1, max_per_hour=6)
    assert run(life, pc, clock, 60, snap())
    life.piped_up()
    run(life, pc, clock, 11, snap(app="PowerPoint", title="PowerPoint Slide Show"))
    assert life.ignored == 0


# 1.3 Someone the camera sees arrive while Dan is typing never left


def test_the_camera_seeing_someone_arrive_while_dan_types_is_no_hello():
    life, pc, clock = setup(eyes=True)
    run(life, pc, clock, 30, snap(idle=2))  # typing away, out of the camera's view
    life.on_scene([Happening("arrived", "Someone sat down.", away_s=1200)])
    assert life.homecoming is None and life.came_back is None
    # The keyboard saw him five minutes ago: the camera's twenty minutes are capped there.
    life, pc, clock = setup(eyes=True)
    pc.update(snap(idle=40))
    life.on_report()
    clock.now += timedelta(minutes=5)
    pc.update(snap(idle=340))
    life.on_report()
    life.on_scene([Happening("arrived", "Someone sat down.", away_s=1200)])
    assert life.homecoming is None  # five minutes isn't worth a hello
    # Nothing from the keyboard for an hour: his eyes are right, and he says hello.
    life, pc, clock = setup(eyes=True)
    clock.now += timedelta(hours=1)
    pc.update(snap(idle=3600))
    life.on_report()
    life.on_scene([Happening("arrived", "Someone sat down.", away_s=1200)])
    assert life.homecoming is not None and life.homecoming.seen


# 1.4 A restart mid-day keeps the hourly count, the desk time and what he held


def test_a_restart_keeps_the_hourly_count_desk_time_and_what_he_was_holding(zone):
    saved = Saved()
    life, pc, clock = setup("2026-10-06T08:00:00", tz=zone, store=saved)
    pc.update(snap())
    life.on_report()
    since = life.present_since
    assert since is not None
    clock.now += timedelta(hours=3)
    life.pipes.extend([clock.now - timedelta(minutes=90), clock.now - timedelta(minutes=20)])
    life.holding = Held("bored", clock.now - timedelta(minutes=5), "phone")
    life.held_until = clock.now + timedelta(minutes=15)
    life._to_think.append(("new", "Dan just opened Blender, first time today."))
    life.nags = 1
    life.save()
    clock.now += timedelta(minutes=2)
    s = Settings()
    again = Life(lambda: s, pc, clock, random.Random(1), store=saved)
    assert again.present_since == since
    assert list(again.pipes) == [clock.now - timedelta(minutes=22)]  # the old one is gone
    assert again.holding == life.holding and again.held_until == life.held_until
    assert list(again._to_think) == [("new", "Dan just opened Blender, first time today.")]
    assert again.nags == 1
    clock.now += timedelta(hours=1)
    later = Life(lambda: s, pc, clock, random.Random(1), store=saved)
    assert not later.pipes and later.holding is None and later.held_until is None


# 1.5 Look events don't push out what bodies need to hear


def test_look_events_have_their_own_small_ring_and_bodies_learn_when_they_missed_some():
    life, _, _ = setup()
    life.publish({"type": "state", "state": "asleep"})
    for n in range(300):
        life.publish({"type": "look", "x": n / 300, "y": 0.0}, ring=life._looks)
    events = life.events_after(0)
    assert events[0]["type"] == "state"
    assert sum(1 for e in events if e["type"] == "look") == MAX_LOOKS
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)
    assert not life.missed_since(0) and not life.missed_since(events[-1]["id"])
    for _ in range(250):
        life.publish({"type": "fidget", "gesture": "sigh"})
    assert life.missed_since(1)  # the ring has moved on past the state change
    oldest = min(e["id"] for e in life.events_after(0) if e["type"] != "look")
    assert not life.missed_since(oldest - 1) and life.missed_since(oldest - 2)


# 1.6 A thought's feeling never displaces one Dan caused


def test_a_thought_cant_hurt_him_or_push_out_what_dan_made_him_feel():
    assert "hurt" not in THOUGHT_FEELINGS and "put_out" not in THOUGHT_FEELINGS
    assert "amused" in THOUGHT_FEELINGS
    life, _, clock = setup()
    life.feel("chuffed", "Dan called you a legend")
    clock.now += timedelta(minutes=60)  # chuffed lasts two hours: half left
    assert not life.feel("amused", "a thought", THOUGHT_FEELS)
    assert life.feeling_now().name == "chuffed"


# 1.8 A held pipe-up keeps his manners


def test_a_held_pipe_up_waits_for_a_pause_in_the_typing():
    life, pc, clock = setup(hold_pipe_ups=True)
    life.last_chat -= timedelta(hours=1)
    life.holding = Held("bored", clock.now, "phone")
    clock.now += timedelta(seconds=30)
    pc.update(snap(idle=2))
    assert life.tick() is None and life.quiet_because.startswith("you're typing")
    assert life.holding is not None and life.delivering is None
    clock.now += timedelta(seconds=30)
    pc.update(snap(idle=40))
    assert life.tick() == "bored" and life.delivering is not None and life.holding is None


# 1.10 The hourly limit isn't capped under the setting


def test_he_can_count_as_many_pipe_ups_as_the_setting_allows():
    life, _, _ = setup()
    assert life.pipes.maxlen == MAX_PIPES >= 30  # life.max_per_hour tops out at 30


# 1.11 How a pipe-up lands is counted by what he brought up


def test_take_up_is_counted_by_the_kind_of_thing_he_brought_up():
    class Item:
        def __init__(self, kind, **meta):
            self.kind, self.meta = kind, meta

    assert share_kind(None) == ""
    assert share_kind(Item("want", game="weather_bet")) == "game"
    assert share_kind(Item("want", nudge="outside")) == "nudge"
    assert share_kind(Item("want", interview="partner")) == "interview"
    assert share_kind(Item("thought")) == "thought"
    life, _, clock = setup(store=Saved())
    for _ in range(3):
        life.piped_up("want", kind="game")
        clock.now += timedelta(minutes=2)
        life.note_chat("31, you're on")
    assert life.take_up_rate("game") == 1.0 and life.take_up_rate("want") is None


# 4.2 No bored or curious pipe-ups during a bad night: one gentle check-in


def test_on_a_bad_night_he_checks_in_once_and_otherwise_stays_quiet():
    life, pc, clock = setup(chattiness=1, max_per_hour=6)
    life.note_chat("I can't cope")
    life.start_bad_night('Dan said "I can\'t cope"')
    life.drives.boredom = 1.0
    life.spotted = ("the cat", clock.now)
    reasons = run(life, pc, clock, 25, snap())
    assert reasons and set(reasons) == {"check_in"}  # never bored or curious
    life.piped_up("check_in")
    assert not life.awaiting_reply  # it needs no answer: no sulking tonight
    assert run(life, pc, clock, 90, snap()) == []
    assert life.quiet_because == "you're staying quiet: Dan's having a hard time"
    assert life.bad_night_checked
    prompt = pipe_up_prompt("check_in", "Dan", life.cheek(), "", 0.5)
    assert "check they're okay" in prompt and "bored" not in prompt
    # The bad night over, his drives have their say again.
    clock.now = life.bad_night_until + timedelta(minutes=1)
    life.drives.boredom = 1.0
    assert "bored" in run(life, pc, clock, 20, snap())


def test_a_check_in_he_couldnt_put_into_words_isnt_tried_again():
    life, _, _ = setup()
    life.start_bad_night("Dan said so")
    life.held_back("check_in")
    assert life.bad_night_checked
    life.start_bad_night("Dan said so again")  # the same bad night, kept going
    assert life.bad_night_checked


# 4.5 The plan says which wants a reply brought up


def test_the_plan_carries_which_things_on_his_mind_he_brings_up():
    assert "brought_up" in plan_schema()["properties"]
    assert "brought_up" in plan_schema(read=True)["properties"]
    assert brought_up_in('{"emotion": "happy", "brought_up": [1, 3], "action"') == [1, 3]
    assert brought_up_in('{"emotion": "happy", "brought_up": []}') == []
    early = early_plan(
        '{"emotion": "happy", "gesture": "nod", "brought_up": [2], "action": {"kind": "none"'
    )
    assert early is not None and early.brought_up == [2]
    plan = parse_plan('{"emotion": "happy", "gesture": "nod", "action": {"kind": "none"}}')
    assert plan.brought_up == [] and Plan.default().brought_up == []


@pytest.fixture
def kit(paths):
    made = []

    def make(*outputs, tz=None):
        paths.ensure()
        store = SettingsStore(paths)
        memory = Memory(paths.state_dir / "memory.db", Clock("2026-10-07T10:00:00", tz))
        model = FakeModel(*outputs)
        recall = Recall(memory, FakeEmbedder(), store.current)
        brain = Brain(store.current, memory, model, make_cloud(memory, key="k"), recall)
        made.append(memory)
        return brain, model

    yield make
    for memory in made:
        memory.close()


def test_a_want_asked_in_other_words_counts_as_said_when_the_plan_says_so(kit):
    brain, model = kit(reply("So who's your other half, then?", brought_up=[1]))
    want = brain.notebook.write("want", "Ask Dan: what's your partner's name?")
    collect(brain.chat("Morning Kit"))
    system = model.calls[0][0]["content"]
    assert "put its number in brought_up" in system
    assert "1. (you want to ask Dan) what's your partner's name?" in system
    assert brain.notebook.index.get(want).meta["said"]


def test_without_the_plan_saying_so_only_a_reply_in_the_same_words_counts(kit):
    brain, model = kit(reply("So who's your other half, then?"))
    want = brain.notebook.write("want", "Ask Dan: what's your partner's name?")
    collect(brain.chat("Morning Kit"))
    assert not brain.notebook.index.get(want).meta.get("said")
    brain, model = kit(reply("How did the shutdown go, by the way?", brought_up=[]))
    want = brain.notebook.write("want", "Ask Dan how the shutdown went.")
    collect(brain.chat("Morning Kit"))
    assert brain.notebook.index.get(want).meta["said"]  # the words match: the backstop


def test_a_number_that_isnt_a_want_marks_nothing(kit):
    brain, model = kit(reply("Hydrocyclones are elegant, you know.", brought_up=[1, 7]))
    thought = brain.notebook.write("thought", "I've decided hydrocyclones are elegant.")
    collect(brain.chat("Morning Kit"))
    assert not brain.notebook.index.get(thought).meta.get("said")


def test_his_life_and_notebook_keep_time_with_a_zone_aware_clock(kit, zone):
    """Production's clock is zone-aware; the notebook's times are saved naive."""
    brain, model = kit(reply("So who's your other half, then?", brought_up=[1]), tz=zone)
    want = brain.notebook.write("want", "Ask Dan: what's your partner's name?")
    assert brain.notebook.unsaid_wants()[0].id == want
    collect(brain.chat("Morning Kit"))
    assert brain.notebook.index.get(want).meta["said"]
    now = brain.memory.clock()
    assert brain.life.last_chat == now and (now.tzinfo is None) == (zone is None)
    brain.life.tick()
    assert brain.notebook.mind("Dan") == []
    assert brain.life.time_line("Dan") == ""
