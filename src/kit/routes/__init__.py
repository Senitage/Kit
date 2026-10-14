"""The brain service's routes, one router per part of Kit. They share one
``AppState`` (kit.routes.state) that ``kit.server.create_app`` builds."""

from __future__ import annotations

from kit.routes import (
    bodies,
    chat,
    desk,
    eyes,
    face,
    files,
    hearing,
    life,
    memory,
    pages,
    settings,
    speech,
    status,
    things,
    tools,
)

ROUTERS = (
    pages.router,
    status.router,
    face.router,
    settings.router,
    chat.router,
    memory.router,
    files.router,
    things.router,
    desk.router,
    eyes.router,
    hearing.router,
    life.router,
    bodies.router,
    speech.router,
    tools.router,
)
