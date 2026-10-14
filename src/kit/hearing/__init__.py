"""Kit's ears: a microphone process that runs beside the mic and tells the brain
what it heard, in words, never sound.

Like his eyes (kit.eyes), it runs on whichever machine has the microphone (the
desk PC now, a robot later) and connects out to the brain:

    mic -> voice detector (Silero VAD) -> a stretch of talking
        -> speech to text, with tone and sounds (SenseVoice)
        -> whose voice (CAM++ voice prints)  -> POST /api/hearing/heard

Talking over Kit while he speaks posts /api/hearing/hush, which stops his voice.
His own voice coming back from the speakers is recognised by its voice print
and ignored. The brain side is ``kit.heard``.

All three models run on the processor through sherpa-onnx, with no PyTorch and
no graphics card, and are downloaded the first time. Sound never leaves this
machine. Like the eyes, the parts that need a library import it only when
they're built, so the brain, the tests and ``kit check`` never need them.
Install them with ``pip install "kit[hearing]"`` on the machine with the mic.
"""
