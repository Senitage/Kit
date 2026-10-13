"""The docs vault (docs/) stays in step with Kit: every link and picture resolves,
every note has its properties, and every module, setting and command is written
up. How the vault works: docs/6 About These Docs/How These Docs Work.md."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote

import pytest

from kit import cli
from kit.settings import ModelProfile, Settings, SpeechEngine

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SRC = ROOT / "src" / "kit"
ASSETS = DOCS / "Assets"
NOT_NOTES = {".obsidian", ".trash", "Templates"}

FENCE = re.compile(r"^[ \t]*(```|~~~)[^\n]*\n.*?^[ \t]*\1[ \t]*$", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
WIKI = re.compile(r"(!?)\[\[([^\]\n]+?)\]\]")
HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
CODE_PATH = re.compile(r"`((?:src|tests|packaging|assets|pod|\.github)/[^`\s]*)`")
DOCS_PATH = re.compile(r"docs/[^\n`'\"()\[\]<>]*?\.(?:md|canvas|png|jpg)")


def _notes() -> list[Path]:
    return sorted(p for p in DOCS.rglob("*.md") if not NOT_NOTES & set(p.relative_to(DOCS).parts))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _prose(text: str) -> str:
    """The text with code blocks and inline code taken out: links in code aren't links."""
    return INLINE_CODE.sub("", FENCE.sub("", text))


def _norm(heading: str) -> str:
    """A heading as Obsidian matches it in a link: case and these characters don't count."""
    return " ".join(re.sub(r"[:#|^\[\]]", " ", heading).lower().split())


def _headings(text: str) -> set[str]:
    return {_norm(h) for h in HEADING.findall(FENCE.sub("", text))}


NOTES = _notes()
BY_NAME = {p.stem: p for p in NOTES}
FILES = {p.name: p for p in DOCS.rglob("*") if p.is_file() and ".obsidian" not in p.parts}


def _links(text: str) -> list[tuple[bool, str, str]]:
    """(embed?, target, heading) for every wiki-link outside code."""
    found = []
    for bang, inner in WIKI.findall(_prose(text)):
        target = inner.replace("\\|", "|").split("|", 1)[0]
        name, _, heading = target.partition("#")
        found.append((bool(bang), name.strip(), heading.strip()))
    return found


def _resolve(name: str) -> Path | None:
    return BY_NAME.get(name) or FILES.get(name)


def _base_views(path: Path) -> set[str]:
    """The view names in a base (an Obsidian Bases .base file)."""
    return set(re.findall(r"^\s+name:\s*(.+?)\s*$", _read(path), re.MULTILINE))


def _canvas_texts() -> list[tuple[Path, str]]:
    texts = []
    for canvas in DOCS.rglob("*.canvas"):
        for node in json.loads(_read(canvas))["nodes"]:
            if node["type"] == "text":
                texts.append((canvas, node["text"]))
    return texts


def test_the_vault_has_notes():
    assert "Home" in BY_NAME
    assert len(NOTES) > 20


def test_note_names_are_unique():
    seen: dict[str, Path] = {}
    for path in DOCS.rglob("*.md"):
        if ".obsidian" in path.parts:
            continue
        assert path.stem not in seen, f"two notes called {path.stem}: {seen[path.stem]}, {path}"
        seen[path.stem] = path


@pytest.mark.parametrize("path", NOTES, ids=lambda p: p.stem)
def test_note_has_properties_and_a_title(path):
    text = _read(path)
    assert text.startswith("---\n"), "start with properties (tags, aliases, summary)"
    end = text.index("\n---\n", 4)
    props = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(": ")
        assert sep and key.isidentifier(), f"one 'key: value' per line, not {line!r}"
        assert ": " not in value, f"no ': ' inside a value (it isn't valid YAML): {line!r}"
        props[key] = value.strip()
    assert props.get("tags", "").startswith("["), "tags: [a, b]"
    assert props.get("summary"), "a one-sentence summary"
    assert re.search(r"^# \S", _prose(text[end:]), re.MULTILINE), "a # title"


def test_links_and_headings_resolve():
    sources = [(p, _read(p)) for p in NOTES] + _canvas_texts()
    broken = []
    for path, text in sources:
        for embed, name, heading in _links(text):
            target = _resolve(name) if name else path
            if target is None:
                broken.append(f"{path.name}: [[{name}]] has no note or file")
            elif heading and target.suffix == ".md":
                if _norm(heading) not in _headings(_read(target)):
                    broken.append(f"{path.name}: [[{name}#{heading}]] has no such heading")
            elif heading and target.suffix == ".base":
                if heading not in _base_views(target):
                    broken.append(f"{path.name}: [[{name}#{heading}]] has no such view")
            elif embed and target.suffix in {".png", ".jpg"} and target.parent != ASSETS:
                broken.append(f"{path.name}: pictures go in docs/Assets ({name})")
    assert not broken, "\n".join(broken)


def test_canvas_files_exist():
    for canvas in DOCS.rglob("*.canvas"):
        for node in json.loads(_read(canvas))["nodes"]:
            if node["type"] == "file":
                assert (DOCS / node["file"]).is_file(), f"{canvas.name}: {node['file']}"


def test_mermaid_note_links_name_notes():
    for path in NOTES:
        for block in re.findall(r"```mermaid\n(.*?)```", _read(path), re.DOTALL):
            labels = dict(re.findall(r"(\w+)\[\"([^\"]+)\"\]", block))
            for ids in re.findall(r"^\s*class\s+(\S+)\s+internal-link", block, re.MULTILINE):
                for node in ids.split(","):
                    assert labels.get(node) in BY_NAME, f"{path.name}: {node} isn't a note"


def test_every_picture_is_used():
    used = "\n".join(_read(p) for p in NOTES) + "\n".join(_read(c) for c in DOCS.rglob("*.canvas"))
    used += _read(ROOT / "README.md")
    unused = [p.name for p in ASSETS.iterdir() if p.name not in used]
    assert not unused, f"pictures no note uses: {unused}"


def test_obsidian_settings_are_valid_json():
    for path in (DOCS / ".obsidian").glob("*.json"):
        json.loads(_read(path))


def test_bases_have_named_views():
    for path in DOCS.rglob("*.base"):
        text = _read(path)
        assert "\t" not in text, f"{path.name}: indent with spaces (it's YAML)"
        views = re.findall(r"^\s+- type:\s*(\w+)", text, re.MULTILINE)
        names = re.findall(r"^\s+name:\s*(.+?)\s*$", text, re.MULTILINE)
        assert views and len(views) == len(names), f"{path.name}: give every view a type and name"
        assert len(set(names)) == len(names), f"{path.name}: view names must differ"


def test_code_paths_in_notes_exist():
    missing = []
    for path in NOTES:
        for found in CODE_PATH.findall(_read(path)):
            found = found.rstrip(".,:;")
            if not (any(ROOT.glob(found)) if "*" in found else (ROOT / found).exists()):
                missing.append(f"{path.name}: {found}")
    assert not missing, "\n".join(missing)


def test_docs_paths_in_code_exist():
    files = [ROOT / "README.md", ROOT / "CLAUDE.md", ROOT / "pyproject.toml"]
    files += [p for p in SRC.rglob("*") if p.suffix in {".py", ".json", ".toml", ".html", ".js"}]
    files += list((ROOT / ".github").rglob("*.yml")) + list((ROOT / "assets").rglob("*.md"))
    files += [p for p in (ROOT / "pod").rglob("*") if p.suffix in {".md", ".ino", ".h", ".py"}]
    missing = []
    for path in files:
        for found in DOCS_PATH.findall(_read(path)):
            if not (ROOT / unquote(found)).is_file():
                missing.append(f"{path.relative_to(ROOT)}: {found}")
    assert not missing, "\n".join(missing)


def test_every_module_is_in_the_code_map():
    code_map = _read(DOCS / "5 Reference" / "Code Map.md")
    missing = [
        f"src/kit/{p.relative_to(SRC).as_posix()}"
        for p in SRC.rglob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in p.parts
    ]
    missing = [m for m in missing if f"`{m}`" not in code_map]
    assert not missing, f"add these to Code Map: {missing}"


def _sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## (\S+)\s*$", text, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_every_setting_is_in_the_reference():
    sections = _sections(_read(DOCS / "5 Reference" / "Settings Reference.md"))
    settings = Settings()
    missing = []
    for name in Settings.model_fields:
        if name == "schema_version":
            continue
        fields = (
            ModelProfile.model_fields
            if name == "models"
            else type(getattr(settings, name)).model_fields
        )
        if name == "speech":
            fields = {**fields, **SpeechEngine.model_fields}
        text = sections.get(name, "")
        missing += [f"{name}.{field}" for field in fields if f"`{field}`" not in text]
    assert not missing, f"add these to Settings Reference: {missing}"


def _parser(monkeypatch) -> argparse.ArgumentParser:
    class Built(Exception):
        pass

    def stop(self, *args, **kwargs):
        raise Built(self)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", stop)
    with pytest.raises(Built) as built:
        cli.main([])
    return built.value.args[0]


def _commands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def test_every_command_is_in_commands(monkeypatch):
    lines = _read(DOCS / "5 Reference" / "Commands.md").splitlines()
    missing = []
    for name, parser in _commands(_parser(monkeypatch)).items():
        words = list(_commands(parser))
        for action in parser._actions:
            if not action.option_strings and action.choices and not words:
                words += list(action.choices)
        ours = [line for line in lines if f"kit {name}" in line]
        if not ours:
            missing.append(f"kit {name}")
        for word in words:
            if not any(re.search(rf"\b{re.escape(word)}\b", line) for line in ours):
                missing.append(f"kit {name} {word}")
    assert not missing, f"add these to Commands: {missing}"


def test_ci_runs_every_python_and_the_desk_job_runs_every_test():
    """The workflows stay honest: ci.yml tests every Python pyproject.toml names, and the
    desk job (the only one with Qt) runs the whole suite, not a list of files that
    forgets the newest one."""
    import tomllib

    ci = _read(ROOT / ".github" / "workflows" / "ci.yml")
    classifiers = tomllib.loads(_read(ROOT / "pyproject.toml"))["project"]["classifiers"]
    pythons = [c.rsplit(":: ", 1)[1] for c in classifiers if "Python :: 3." in c]
    matrix = re.search(r"python: \[([^\]]+)\]", ci).group(1)
    assert sorted(re.findall(r'"([^"]+)"', matrix)) == sorted(pythons) == ["3.11", "3.12", "3.13"]
    desk = _read(ROOT / ".github" / "workflows" / "desk-app.yml")
    assert re.search(r"^\s*run: pytest -q tests/\s*$", desk, re.MULTILINE)
    assert "QT_QPA_PLATFORM: offscreen" in desk
