"""Kit as a companion (stage 2): he follows your life. Times the way people say them,
things coming up that he asks about once they're over, check-ins he was asked for,
"now" facts, relations put right, the nightly picture of Dan, one thing from the last
chat, the getting-to-know-you questions, the two nudges, running jokes, key moments
for the work model and the budget order."""

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.cloud import CloudError
from kit.learning import relations_in
from kit.life import is_farewell
from kit.memory import Memory
from kit.notebook import Notebook, asks_later, later_want, thread_in
from kit.pc_context import Snapshot
from kit.recall import Recall, weight
from kit.reflection import Reflector
from kit.settings import Settings
from kit.when import asked_for, find_when, follow_up, label

TUESDAY = datetime(2026, 10, 6, 10, 0)


def snap(idle=5, app="Chrome", title="Weekend weather - Google Chrome"):
    return Snapshot.model_validate({"focus": {"app": app, "title": title}, "idle_seconds": idle})


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock("2026-10-06T10:00:00"))
    yield m
    m.close()


def make(memory, *outputs, claude=None, **sections):
    s = Settings.model_validate({"memory": {"min_similarity": 0.3}, **sections})
    model = FakeModel(*outputs)
    claude = claude or FakeAnthropic()
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    brain = Brain(lambda: s, memory, model, make_cloud(memory, claude), recall)
    return brain, model, claude


def at(memory, when: str) -> None:
    memory.clock.now = datetime.fromisoformat(when)


def asked(model) -> str:
    """What the model was last asked: Dan's message and the notes beside it."""
    return model.calls[-1][-1]["content"]


# Times, the way people say them


def test_he_understands_times_the_way_people_say_them():
    w = find_when("Got the dentist Thursday arvo", TUESDAY)
    assert (w.start, w.end) == (datetime(2026, 10, 8, 13, 30), datetime(2026, 10, 8, 17, 0))
    assert label(w) == "Thursday afternoon"
    assert follow_up(w, "07:00") == datetime(2026, 10, 8, 17, 0)  # once it's over
    w = find_when("check in after my 2 pm", TUESDAY)
    assert asked_for(w, TUESDAY, "07:00") == datetime(2026, 10, 6, 14, 30)
    w = find_when("footy tonight", TUESDAY)
    assert w.shown(TUESDAY) == "tonight"
    assert follow_up(w, "07:00") == datetime(2026, 10, 7, 7, 0)  # asked next morning
    assert find_when("next Thursday", TUESDAY).start.date() == datetime(2026, 10, 15).date()
    w = find_when("off camping on the weekend", TUESDAY)
    assert follow_up(w, "07:00") == datetime(2026, 10, 12, 7, 0)  # Monday morning
    assert find_when("after work", TUESDAY).start == datetime(2026, 10, 6, 17, 30)
    assert find_when("in the morning", TUESDAY).start == datetime(2026, 10, 7, 7, 0)


def test_numbers_and_cmon_are_not_times():
    assert find_when("around 20 people turned up", TUESDAY) is None
    assert find_when("c'mon mate", TUESDAY) is None
    assert find_when("I need 5 more minutes", TUESDAY) is None


def test_being_asked_to_check_in_is_a_time_and_a_want():
    assert asks_later("check in after my 2 pm", TUESDAY, "07:00") == datetime(2026, 10, 6, 14, 30)
    assert asks_later("remind me at 5 to call Bob", TUESDAY, "07:00") == datetime(
        2026, 10, 6, 17, 0
    )
    assert later_want("remind me at 5 to call Bob", "Dan") == "Remind Dan to call Bob."
    assert later_want("check in after my 2 pm", "Dan").startswith("Check in with Dan")
    assert asks_later("I'll check in at 2 pm", TUESDAY, "07:00") is None  # Dan, not Kit


def test_what_makes_a_thread_and_what_doesnt():
    about, w = thread_in("Got the dentist Thursday arvo", TUESDAY, "07:00")
    assert about == "dentist" and w.part == "arvo"
    assert thread_in("Mum's birthday lunch on Sunday", TUESDAY, "07:00")[0].startswith("Mum")
    assert thread_in("Had the dentist yesterday", TUESDAY, "07:00") is None  # over
    assert thread_in("Is the dentist Thursday?", TUESDAY, "07:00") is None  # a question
    assert thread_in("Big meeting with the boss Thursday", TUESDAY, "07:00") is None  # work
    assert thread_in("Holiday in March", TUESDAY, "07:00") is None  # too far off


def test_a_plan_for_saturday_isnt_a_goodbye():
    assert not is_farewell("Heading to the footy Saturday")
    assert is_farewell("Off to bed, see you tomorrow")
    assert is_farewell("Popping out to the shops")


# Desk test: "dentist Thursday arvo" on Tuesday is asked about Thursday evening only


def test_the_dentist_on_thursday_arvo_is_asked_about_thursday_evening_only(memory):
    brain, model, _ = make(
        memory,
        reply("Ugh, the dentist. Good luck."),
        reply("Morning! Big day?"),
        reply("So, how'd the dentist go?"),
        reply("No fillings! Nice one."),
        reply("Ha, fair."),
    )
    collect(brain.chat("Got the dentist Thursday arvo"))
    thread = brain.notebook.threads()[0]
    assert thread.text == "dentist, Thursday afternoon"
    assert thread.meta["after"] == "2026-10-08T17:00:00"
    assert thread.meta["heard"] == "Got the dentist Thursday arvo"
    at(memory, "2026-10-07T09:00:00")  # Wednesday: not yet
    collect(brain.chat("Morning Kit"))
    assert brain.notebook.open_wants() == []
    assert "dentist" not in model.calls[-1][0]["content"]  # not even on his mind yet
    at(memory, "2026-10-08T17:30:00")  # Thursday evening
    brain.pc.update(snap())
    assert brain.notebook.open_wants()[0].id == thread.id
    collect(brain.pipe_up("want"))
    assert "You've been wanting to ask Dan how it went" in asked(model)
    assert "dentist, this afternoon" in asked(model)  # as of now
    assert brain.memory.index.get(thread.id).meta["said"]
    collect(brain.chat("Yeah good, no fillings for once"))
    assert brain.memory.index.get(thread.id).meta["outcome"] == "Yeah good, no fillings for once"
    collect(brain.chat("haha"))
    assert brain.notebook.threads() == [] and brain.notebook.followed()[0].id == thread.id


def test_saying_how_it_went_first_means_he_doesnt_ask(memory):
    book = Notebook(memory)
    w = find_when("dentist Thursday arvo", TUESDAY)
    thread = book.write_thread("dentist", w, follow_up(w, "07:00"))
    at(memory, "2026-10-08T14:30:00")
    assert book.heard_about("Dentist in an hour, wish me luck") == []  # still to come
    assert book.heard_about("How long does the dentist take?") == []
    assert book.heard_about("Dentist was fine, no fillings") == [thread]
    assert book.threads() == []
    assert book.write_thread("dentist", w, follow_up(w, "07:00")) is None  # not again


def test_a_thread_named_again_moves(memory):
    book = Notebook(memory)
    first = book.write_thread("dentist", find_when("Thursday arvo", TUESDAY), TUESDAY)
    moved = book.write_thread("dentist", find_when("Friday morning", TUESDAY), TUESDAY)
    assert moved == first and len(book.threads()) == 1
    assert book.threads()[0].text == "dentist, Friday morning"


def test_no_thread_from_work_a_goodbye_or_something_kept_local(memory):
    brain, model, _ = make(memory, reply("Okay."), reply("Okay."), reply("Okay."))
    collect(brain.chat("Big deadline at work Thursday arvo"))
    collect(brain.chat("Keep it local: specialist appointment Thursday arvo"))
    collect(brain.chat("Off to bed, see you tomorrow"))
    assert brain.notebook.threads() == []


# Desk test: "check in after my 2 pm" gets a check-in at about 2:30


def test_check_in_after_my_2pm_comes_up_about_half_past(memory):
    brain, model, _ = make(memory, reply("Will do."), reply("Hey, how'd the 2 pm go?"))
    at(memory, "2026-10-06T13:55:00")
    collect(brain.chat("Can you check in after my 2 pm?"))
    want = next(w for w in brain.notebook.unsaid_wants() if w.kind == "want")
    assert want.meta["after"] == "2026-10-06T14:30:00"
    assert brain.notebook.open_wants() == []
    at(memory, "2026-10-06T14:31:00")
    assert brain.notebook.pressing() >= 0.95  # Dan asked: it comes up at once
    brain.pc.update(snap())
    collect(brain.pipe_up("want"))
    assert "You've been wanting to check in with Dan" in asked(model)
    assert brain.memory.index.get(want.id).meta["said"]


# Desk test: "Emma's my cousin" supersedes the old fact


def test_emma_is_my_cousin_puts_the_old_fact_right(memory):
    brain, model, _ = make(memory, reply("Ah, cousin. Noted."))
    old = memory.add_fact("Emma, Dan's sister, celebrates her birthday on the 14th of March.")
    asyncio.run(brain.recall.index_pending())
    events = collect(brain.chat("Emma's my cousin, not my sister"))
    learned = next(e for e in events if e["type"] == "remembered")
    assert learned["decision"] == "update"
    assert learned["fact"] == "Emma, Dan's cousin, celebrates her birthday on the 14th of March."
    assert memory.index.get(old).superseded_by  # the old one is in its history
    texts = [f.text for f in memory.facts()]
    assert texts == ["Emma, Dan's cousin, celebrates her birthday on the 14th of March."]


# Desk test: Monday morning, he asks about the weekend once


def test_monday_morning_he_asks_about_the_weekend_once(memory):
    brain, model, _ = make(memory)
    at(memory, "2026-10-12T08:30:00")  # a Monday
    brain.pc.update(snap())
    assert brain.offer_wants() == ["weekend"]
    thread = brain.notebook.threads()[0]
    assert thread.text == "the weekend of 10 October" and brain.notebook.due(thread)
    assert brain.offer_wants() == []  # once
    at(memory, "2026-10-13T08:30:00")
    brain.pc.update(snap())
    assert "weekend" not in brain.offer_wants()


def test_a_weekend_thread_already_asks_about_it_better(memory):
    brain, model, _ = make(memory)
    book = brain.notebook
    book.write_thread("camping", find_when("on the weekend", TUESDAY), TUESDAY)
    at(memory, "2026-10-12T08:30:00")
    brain.pc.update(snap())
    assert "weekend" not in brain.offer_wants()
    assert [t.meta["about"] for t in book.threads()] == ["camping"]


# Desk test: a new chat opens with one thing from the last


def test_a_new_chat_picks_up_one_thing_from_the_last(memory):
    brain, model, _ = make(
        memory, reply("Go Eagles!"), reply("Morning! How'd the final go?"), reply("Ha.")
    )
    at(memory, "2026-10-06T18:00:00")
    collect(brain.chat("Been flat out sorting the shed, it's a mess."))
    at(memory, "2026-10-07T08:00:00")
    collect(brain.chat("Morning Kit"))
    note = asked(model)
    assert note.count("When you two last talked (last night)") == 1
    assert "'Been flat out sorting the shed, it's a mess.'" in note
    at(memory, "2026-10-07T08:05:00")
    collect(brain.chat("What's the weather doing?"))
    assert "A new chat" not in asked(model)  # once


def test_a_new_chat_asks_about_a_thread_thats_over_first(memory):
    brain, model, _ = make(memory, reply("Okay."), reply("Hey! How was the dentist?"))
    at(memory, "2026-10-06T12:00:00")
    collect(brain.chat("Got the dentist this arvo. Reckon the Eagles will win?"))
    at(memory, "2026-10-06T18:00:00")
    collect(brain.chat("Hey Kit"))
    assert "Something of Dan's is over now: dentist, this afternoon." in asked(model)
    assert "Eagles" not in asked(model)


def test_no_opener_when_turned_off_or_the_last_chat_was_just_now(memory):
    brain, model, _ = make(memory, reply("Okay."), reply("Okay."), life={"chat_opener": False})
    at(memory, "2026-10-06T18:00:00")
    collect(brain.chat("Big footy final tonight, can't wait."))
    at(memory, "2026-10-07T08:00:00")
    collect(brain.chat("Morning Kit"))
    assert "A new chat" not in asked(model)


# The two nudges, once a day each


def test_past_bedtime_he_nudges_once_a_night(memory):
    brain, model, _ = make(memory, reply("Okay."), reply("Bed, you."), reply("Night!"))
    at(memory, "2026-10-06T22:45:00")
    collect(brain.chat("Just one more episode"))
    brain.pc.update(snap())
    assert brain.offer_wants() == ["sleep"]
    collect(brain.chat("This show is so good"))
    assert "past Dan's usual bedtime" in asked(model)
    collect(brain.chat("Fine, fine"))
    assert "bedtime" not in asked(model)
    at(memory, "2026-10-07T00:30:00")  # still the same night
    brain.pc.update(snap())
    assert "sleep" not in brain.offer_wants()


def test_a_bedtime_nudge_he_never_got_to_lapses_by_morning(memory):
    brain, model, _ = make(memory)
    at(memory, "2026-10-06T23:00:00")
    brain.pc.update(snap())
    assert brain.offer_wants() == ["sleep"]
    at(memory, "2026-10-07T04:30:00")
    assert brain.notebook.unsaid_wants() == []
    assert brain.notebook.tidy() == 1


def test_after_hours_at_the_desk_he_nudges_you_outside(memory):
    brain, model, _ = make(memory, life={"desk_hours": 2})
    at(memory, "2026-10-06T09:00:00")
    brain.pc.update(snap())
    brain.life.on_report()
    for _ in range(9):
        memory.clock.now += timedelta(minutes=15)
        brain.pc.update(snap())
        brain.life.on_report()
    assert brain.offer_wants() == ["outside"]
    want = brain.notebook.open_wants()[0]
    assert want.text.startswith("Tell Dan to get some fresh air") and "since 8:59" in want.text
    assert brain.offer_wants() == []  # once a day


def test_no_nudges_when_turned_off(memory):
    brain, model, _ = make(memory, life={"nudges": False})
    at(memory, "2026-10-06T23:00:00")
    brain.pc.update(snap())
    assert brain.offer_wants() == []


# Getting to know Dan


def test_getting_to_know_you_a_question_at_a_time(memory):
    brain, model, _ = make(
        memory,
        reply("Hey!"),
        reply("So what's your partner's name?"),
        reply("Sarah! Lovely."),
    )
    brain.pc.update(snap())
    assert brain.offer_wants() == []  # never out of the blue
    collect(brain.chat("hey"))
    assert brain.offer_wants() == ["interview"]
    want = brain.notebook.open_wants()[0]
    assert want.text == "Ask Dan: what's your partner's name?"
    collect(brain.pipe_up("want"))
    events = collect(brain.chat("Sarah"))
    assert "answering your getting-to-know-you question" in asked(model)
    assert any(e["type"] == "remembered" for e in events)
    assert "Sarah is Dan's partner." in [f.text for f in memory.facts()]
    assert brain.daily.next_question().key == "cat"  # known now: on to the next one
    assert brain.offer_wants() == []  # one a day


def test_he_skips_what_he_already_knows(memory):
    brain, model, _ = make(memory)
    memory.add_fact("Sarah is Dan's partner.", "person")
    memory.add_fact("Dan's cat is called Milo.", "person")
    assert brain.daily.next_question().key == "family"
    assert brain.daily.name_answer("cat", "Milo, she's a menace") == "Milo is Dan's cat."
    assert brain.daily.name_answer("cat", "We don't have one any more, sadly") == ""


# Running jokes


def test_a_running_joke_comes_back_and_a_laugh_counts(memory):
    brain, model, _ = make(
        memory, reply("Milo's coup has begun, then."), reply("Told you."), reply("Okay.")
    )
    book = brain.notebook
    bit = book.write_bit("Kit insists Milo the cat is plotting a coup.", "Milo")
    collect(brain.chat("Milo knocked my coffee over"))
    assert "A running joke you two share" in model.calls[-1][0]["content"]
    assert memory.index.get(bit).meta["uses"] == 1
    collect(brain.chat("haha"))
    assert memory.index.get(bit).meta["landed"] == 1
    collect(brain.chat("Milo's asleep on the keyboard now"))
    assert "A running joke" not in model.calls[-1][0]["content"]  # once a day at most


def test_a_joke_that_keeps_falling_flat_is_retired(memory):
    book = Notebook(memory)
    bit = book.write_bit("Kit calls the ute the beast.", "ute")
    for _ in range(3):
        book.bit_used(bit)
    assert book.tidy() == 1 and book.entries("bit") == []


# Memory: now facts, plans with dates, importance in recall


def test_now_facts_go_after_two_weeks_and_never_pin(memory):
    fact = memory.add_fact("Dan's been sleeping badly.", "now", pinned=True)
    assert not memory.index.get(fact).pinned
    memory.clock.now += timedelta(days=15)
    assert memory.tidy_now(14) == 1


def test_a_plan_carries_its_date(memory):
    fact = memory.add_fact("Dan has the dentist on Thursday.", "plan")
    assert memory.index.get(fact).meta["when"] == "2026-10-08"


def test_recall_weighs_what_matters_and_what_came_up_lately(memory):
    now = memory.clock()
    person = memory.index.get(memory.add_fact("Sarah is Dan's partner.", "person"))
    other = memory.index.get(memory.add_fact("Dan once had a red bike.", "other"))
    assert weight(person, now, 0.3) > weight(other, now, 0.3)
    later = now + timedelta(days=90)
    assert weight(person, later, 0.3) < weight(person, now, 0.3)
    assert weight(other, later, 0.3) >= 0.3  # never below the floor
    assert weight(other, later, 1.0) == 1.0  # a floor of 1 weighs them all the same


# Key moments and the budget


def test_bad_news_goes_to_the_work_model_unless_kept_local(memory):
    brain, model, claude = make(memory, reply("Oh mate. I'm so sorry."))
    collect(brain.chat("My dog died this morning."))
    assert len(claude.calls) == 1 and model.calls == []
    collect(brain.chat("Keep it local: my dog died this morning."))
    assert len(claude.calls) == 1 and len(model.calls) == 1


def test_no_key_moments_when_turned_off(memory):
    brain, model, claude = make(
        memory, reply("Oh mate. I'm so sorry."), routing={"key_moments": False}
    )
    collect(brain.chat("My dog died this morning."))
    assert claude.calls == [] and len(model.calls) == 1


def test_a_hello_after_a_night_away_is_the_work_models(memory):
    hello = json.dumps(
        {"emotion": "happy", "segments": [{"say": "Morning, you.", "gesture": "nod"}]}
    )
    brain, model, claude = make(memory, claude=FakeAnthropic(answer=hello))
    at(memory, "2026-10-06T21:30:00")
    brain.pc.update(snap())
    brain.life.on_report()
    collect(brain.chat("Night Kit"))
    at(memory, "2026-10-07T08:00:00")
    brain.pc.update(snap())
    brain.life.on_report()
    events = collect(brain.pipe_up("back"))
    reply_event = next(e for e in events if e["type"] == "reply")
    assert reply_event["reply"]["segments"][0]["say"] == "Morning, you."
    assert len(claude.calls) == 1


def test_the_budget_keeps_the_last_few_dollars_for_the_nightly_reflection(memory):
    settings = Settings.model_validate({"cloud": {"monthly_cap_usd": 20, "reserve_usd": 3}})
    cloud = make_cloud(memory, FakeAnthropic())
    profile = settings.profile("work")
    messages = [{"role": "user", "content": "hi"}]
    memory.record_spend("m", 0, 0, 15.0, "earlier")  # $5 left

    def ask(priority):
        return asyncio.run(cloud.answer(profile, messages, settings, "q", priority=priority))

    with pytest.raises(CloudError, match="keeping the last"):
        ask("eval")  # stops at $11
    with pytest.raises(CloudError):
        ask("moment")  # stops at $14
    assert ask("chat").text  # stops at $17
    assert ask("reflect").text  # runs to the cap


# The nightly picture of Dan, and what's kept local


def test_what_dan_kept_local_stays_off_the_cloud_reflection(memory):
    memory.add_message("user", "Rough day at the shops.")
    memory.add_message("kit", "Oof.")
    memory.add_message("user", "Keep it local: the doctor called about my results.")
    memory.add_message("kit", "That's a lot. I'm here.")
    said = memory.messages_on("2026-10-06")
    assert [m.text for m in memory.shared(said)] == ["Rough day at the shops.", "Oof."]


def test_the_nightly_picture_of_dan_goes_in_every_prompt(memory):
    picture = (
        "Dan's had a big week: the dentist on Thursday went fine, the Eagles lost the "
        "final and he's keen for a quiet weekend. Sleeping a bit better. Sarah's away "
        "visiting her mum till Sunday, so the house is quiet and Milo is clingy."
    )
    data = {
        "journal": "A good day.",
        "self_sheet": "I'm Kit.",
        "quirks": [],
        "opinions": [],
        "moments": [],
        "wants": [],
        "dan": picture,
        "threads": [
            {"about": "Sarah's back from her mum's", "day": "2026-10-11", "part": "evening"}
        ],
        "bit": {"line": "Kit insists Milo is plotting a coup.", "trigger": "Milo"},
    }
    claude = FakeAnthropic(answer=json.dumps(data))
    brain, model, _ = make(memory, reply("Hey."), reply("Hey."), claude=claude)
    memory.add_message("user", "Sarah's off to her mum's till Sunday.")
    at(memory, "2026-10-06T22:00:00")
    done = asyncio.run(brain.reflector.reflect_day("2026-10-06"))
    assert done.dan == picture
    assert brain.notebook.dan().text == picture
    assert not brain.notebook.dan().meta["private"]
    assert [t.meta["about"] for t in brain.notebook.threads()] == ["Sarah's back from her mum's"]
    assert brain.notebook.entries("bit")[0].meta["trigger"] == "Milo"
    at(memory, "2026-10-07T09:00:00")
    collect(brain.chat("Morning"))
    assert "What's going on with Dan lately" in model.calls[-1][0]["content"]
    assert picture in model.calls[-1][0]["content"]


def test_a_picture_written_at_home_from_what_dan_kept_local_is_marked_so(memory):
    data = {"journal": "A quiet day.", "self_sheet": "I'm Kit.", "dan": "Dan's waiting on news."}
    s = Settings.model_validate({"life": {"reflect_with": "local"}})
    book = Notebook(memory)
    reflector = Reflector(memory, book, FakeModel(json.dumps(data)), make_cloud(memory), lambda: s)
    memory.add_message("user", "Keep it local: the doctor called about my results.")
    asyncio.run(reflector.reflect_day("2026-10-06"))
    assert book.dan().text == "Dan's waiting on news." and book.dan().meta["private"]


def test_a_picture_written_from_what_dan_kept_local_never_reaches_the_cloud(memory):
    brain, model, claude = make(memory, routing={"mode": "cloud-first"})
    brain.notebook.set_dan("Dan's waiting on test results.", private=True)
    assert brain._about_dan("local") == "Dan's waiting on test results."
    assert brain._about_dan("work") == ""


def test_dan_can_forget_the_picture(memory):
    book = Notebook(memory)
    first = book.set_dan("Dan's busy.")
    second = book.set_dan("Dan's less busy.")
    assert [i.id for i in book.dan_history()] == [second, first]
    assert book.forget(second) and book.dan() is None


def test_the_defaults_dan_chose():
    s = Settings()
    assert s.life.reflect_role == "expert"  # Opus writes his self-sheet and the picture
    assert s.routing.key_moments and s.routing.key_moment_hellos == ["overnight", "days", "long"]
    assert s.life.threads and s.life.chat_opener and s.life.interview and s.life.nudges
    assert not s.life.work_triggers  # code and builds on screen set nothing off


def test_what_dan_keeps_local_isnt_kept_with_a_thread(memory):
    brain, model, _ = make(memory, reply("Okay."), reply("Okay."))
    w = find_when("dentist this arvo", TUESDAY)
    thread = brain.notebook.write_thread("dentist", w, follow_up(w, "07:00"))
    at(memory, "2026-10-06T18:00:00")
    collect(brain.chat("Keep it local: the dentist found something, more tests."))
    assert memory.index.get(thread).meta.get("outcome") is None
    collect(brain.chat("Keep it local, but remind me tomorrow to ring the specialist"))
    want = next(w for w in brain.notebook.unsaid_wants() if w.kind == "want")
    assert want.meta["private"]


# What Dan keeps local never reaches a cloud model, whatever Kit kept from it


def test_a_key_moment_never_shows_the_cloud_what_dan_kept_local(memory):
    brain, model, claude = make(memory, reply("That's a lot. I'm here."))
    memory.add_fact("Dan is waiting on biopsy results.", "about", pinned=True, private=True)
    collect(brain.chat("Keep it local: the doctor called about my results."))
    assert "biopsy" in model.calls[0][0]["content"]  # at home, he knows
    collect(brain.chat("My dog died this morning."))
    assert len(claude.calls) == 1  # the work model answered
    sent = json.dumps(claude.calls[0], default=str)
    assert "doctor" not in sent and "a lot. I'm here" not in sent and "biopsy" not in sent


def test_kits_own_lines_from_what_dan_kept_local_are_left_out_too(memory):
    memory.add_message("user", "Morning")
    reminder = memory.add_message("kit", "Time to ring the specialist.")
    memory.said_privately(reminder)
    memory.add_message("user", "Done, all good")
    said = memory.messages_on("2026-10-06")
    assert [m.text for m in memory.shared(said)] == ["Morning", "Done, all good"]


def test_a_day_dan_kept_something_local_is_summed_up_privately(memory):
    day = json.dumps(
        {
            "summary": "Dan heard from the doctor and walked the dog.",
            "facts": [{"kind": "now", "text": "Dan is waiting on test results.", "importance": 4}],
        }
    )
    brain, model, _ = make(memory, day)
    memory.add_message("user", "Keep it local: the doctor wants more tests.")
    memory.add_message("kit", "I'm here.")
    at(memory, "2026-10-07T09:00:00")
    assert asyncio.run(brain.learner.summarise_day("2026-10-06", "Dan", "Kit"))
    assert memory.facts()[0].meta["private"]
    assert memory.index.items("days")[0].meta["private"]


def test_a_private_fact_stays_private_when_its_put_right(memory):
    old = memory.add_fact("Dan is seeing a specialist.", "about", private=True)
    new = memory.replace_fact(old, "Dan is seeing a specialist on Friday.")
    assert memory.index.get(new).meta["private"]


def test_a_relation_kept_local_is_learned_privately(memory):
    brain, model, _ = make(memory, reply("Got it."))
    collect(brain.chat("Keep it local: Jess is my sister."))
    assert [(f.text, f.meta.get("private")) for f in memory.facts()] == [
        ("Jess is Dan's sister.", True)
    ]


# Edges the review found


def test_a_bedtime_after_midnight_counts_that_night(memory):
    brain, _, _ = make(memory, life={"bedtime": "00:30"})
    at(memory, "2026-10-06T23:30:00")
    brain.pc.update(snap())
    assert "sleep" not in brain.offer_wants()  # not yet
    at(memory, "2026-10-07T00:45:00")
    brain.pc.update(snap())
    assert "sleep" in brain.offer_wants()
    later, _, _ = make(memory)
    at(memory, "2026-10-08T00:30:00")  # 22:30 bedtime, and he's still up
    later.pc.update(snap())
    assert "sleep" in later.offer_wants()


def test_the_weekend_comes_round_every_monday_morning(memory):
    brain, _, _ = make(memory)
    at(memory, "2026-10-12T08:30:00")
    brain.pc.update(snap())
    assert "weekend" in brain.offer_wants()
    at(memory, "2026-10-19T13:00:00")  # Monday afternoon: too late to ask
    brain.pc.update(snap())
    assert "weekend" not in brain.offer_wants()
    at(memory, "2026-10-26T08:30:00")
    brain.pc.update(snap())
    assert "weekend" in brain.offer_wants()


def test_the_weather_and_nothing_on_are_not_threads():
    assert thread_in("Gonna be hot today, 35 this arvo", TUESDAY, "07:00") is None
    assert thread_in("Nothing on this weekend", TUESDAY, "07:00") is None


def test_remind_me_what_is_a_question_not_a_reminder():
    assert asks_later("Remind me what we said about Saturday", TUESDAY, "07:00") is None


def test_a_name_question_answered_with_no_name_learns_nothing(memory):
    brain, _, _ = make(memory)
    for answer in ("Nope, single", "Don't have one", "Dunno", "Lol", "Why?"):
        assert brain.daily.name_answer("partner", answer) == ""
    assert brain.daily.name_answer("cat", "Milo") == "Milo is Dan's cat."


def test_someone_elses_relation_isnt_dans():
    assert relations_in("Steve is my mate's dad", "Dan") == []
    assert relations_in("Steve is my mate", "Dan") == ["Steve is Dan's mate."]


def test_how_dan_is_lately_doesnt_replace_what_kit_knows_for_good(memory):
    brain, model, _ = make(memory, json.dumps({"decision": "update", "which": 1, "fact": "x"}))
    lasting = memory.add_fact("Dan usually sleeps like a log.", "about")
    asyncio.run(brain.recall.index_pending())
    learned = asyncio.run(brain.learner.learn("Dan has been sleeping badly lately.", "now"))
    assert learned.decision == "new"
    assert memory.index.get(lasting).superseded_by is None


def test_a_relation_finds_the_person_even_when_the_search_doesnt(memory):
    brain, _, _ = make(memory)

    async def nothing(*args, **kwargs):
        return []

    brain.learner.recall.search = nothing
    emma = memory.add_fact("Emma, Dan's sister, loves her horses.")
    memory.add_fact("Sarah's husband Tom is a sparky.")
    learned = asyncio.run(brain.learner.learn("Emma is Dan's cousin.", "person"))
    assert learned.decision == "update" and memory.index.get(emma).superseded_by
    learned = asyncio.run(brain.learner.learn("Tom is Dan's mate.", "person"))
    assert learned.decision == "new"  # Sarah's husband isn't Dan's anything


def test_the_thread_a_new_chat_picks_up_counts_as_asked(memory):
    brain, model, _ = make(memory, reply("Okay."), reply("Hey you."), reply("Nice one."))
    at(memory, "2026-10-06T12:00:00")
    collect(brain.chat("Got the dentist this arvo."))
    thread = brain.notebook.threads()[0].id
    at(memory, "2026-10-06T18:00:00")
    collect(brain.chat("Hey Kit"))
    assert brain.notebook.threads() == []  # once, even though he didn't name it
    collect(brain.chat("No fillings!"))
    assert memory.index.get(thread).meta["outcome"] == "No fillings!"
