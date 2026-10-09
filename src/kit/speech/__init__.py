"""Kit's voice: swappable speech engines, each in its own background program.

``sentences`` cuts streamed words into speakable pieces (the desk app uses it too,
so it stays free of server-only libraries); ``service`` runs an engine's
``worker`` and asks it for speech; ``bench`` compares engines.
"""
