"""The house, through Home Assistant: Kit's own non-admin user on its WebSocket API
(kit.house.client), the rooms and things he may see (kit.house.model: only what
Home Assistant exposes to Assist), what he notices (kit.house.noticing) and what he
remembers of it (kit.house.contents). The tools are kit.tools.house.
See docs/2 How Kit Works/The House.md."""

HOUSE = "house"  # the knowledge index source for rooms and things
