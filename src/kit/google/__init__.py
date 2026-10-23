"""Dan's Google account: Gmail and Google Calendar, as Kit's own narrow key.

Kit signs in once (``kit google connect``) with an OAuth client of Dan's own and
asks only for what he's given: reading mail, writing drafts and sending (only after
Dan's yes), reading calendars, adding and moving events (after a yes). He never
deletes anything, never changes labels, and never downloads attachments. The
token lives in the secrets folder; ``kit google disconnect`` revokes it at Google.
Mail is searched live and never kept; coming events go into the knowledge index
as the ``calendar`` source so recall and the morning brief find them. See
docs/2 How Kit Works/Mail and Calendar.md."""

CALENDAR = "calendar"  # the knowledge index source for coming events

SCOPES = {
    "gmail": (
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",  # drafts, and sending after a yes
    ),
    "calendar": (
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events",
    ),
}
