package io.github.senitage.kit.core

import kotlinx.serialization.json.JsonObject

/**
 * A 2D "glow" look from the character sheet, read once so the painter only deals
 * with numbers: his screen, eyes, glow, blush, and Kit 2D's brows, mouth and
 * shaded shell. Sizes are fractions of the face's size. See Face In Depth.
 */
data class GlowLook(
    val colours: Map<String, String>,
    val neck: Double,
    val screen: Screen,
    val eyes: Eyes,
    val glow: Glow,
    val blush: Blush,
    val brows: Brows?,
    val mouth: Mouth?,
    val shell: Shell?,
) {
    data class Screen(val x: Double, val y: Double, val width: Double, val height: Double, val corner: Double, val bezel: Double)

    data class Eyes(
        val apart: Double,
        val y: Double,
        val width: Double,
        val height: Double,
        val corner: Double,
        val reachX: Double,
        val reachY: Double,
        val talkPulse: Double,
        val squintLift: Double,
        val squintRound: Double,
    )

    data class Glow(val rings: List<Double>, val ringWidth: Double, val dim: Double)

    data class Blush(val apart: Double, val y: Double, val width: Double, val height: Double, val from: Double, val strength: Double)

    data class Brows(val above: Double, val width: Double, val thick: Double, val arch: Double, val slant: Double, val lift: Double, val alpha: Double)

    data class Mouth(val y: Double, val width: Double, val thick: Double, val curve: Double, val open: Double, val round: Double, val talk: Double)

    data class Shell(val shine: Double, val shadow: Double)

    fun colour(name: String, fallback: String = "#4DFFC0"): String = colours[name] ?: fallback

    companion object {
        fun from(look: JsonObject): GlowLook {
            fun part(name: String) = look.obj(name) ?: JsonObject(emptyMap())
            val scr = part("screen")
            val eyes = part("eyes")
            val glow = part("glow")
            val blush = part("blush")
            return GlowLook(
                colours = part("colours").mapNotNull { (k, _) -> part("colours").str(k)?.let { k to it } }.toMap(),
                neck = look.num("neck") ?: 0.55,
                screen = Screen(
                    scr.num("x") ?: 0.1, scr.num("y") ?: 0.17, scr.num("width") ?: 0.8, scr.num("height") ?: 0.66,
                    scr.num("corner") ?: 0.25, scr.num("bezel") ?: 0.0,
                ),
                eyes = Eyes(
                    eyes.num("apart") ?: 0.165, eyes.num("y") ?: 0.47, eyes.num("width") ?: 0.115, eyes.num("height") ?: 0.17,
                    eyes.num("corner") ?: 0.045, eyes.num("reach_x") ?: 0.05, eyes.num("reach_y") ?: 0.035,
                    eyes.num("talk_pulse") ?: 0.0, eyes.num("squint_lift") ?: 0.85, eyes.num("squint_round") ?: 1.15,
                ),
                glow = Glow(
                    (glow["rings"] as? kotlinx.serialization.json.JsonArray)?.mapNotNull {
                        (it as? kotlinx.serialization.json.JsonPrimitive)?.content?.toDoubleOrNull()
                    } ?: listOf(34.0, 22.0, 13.0, 7.0),
                    glow.num("ring_width") ?: 0.014,
                    glow.num("dim") ?: 0.35,
                ),
                blush = Blush(
                    blush.num("apart") ?: 0.285, blush.num("y") ?: 0.585, blush.num("width") ?: 0.034,
                    blush.num("height") ?: 0.021, blush.num("from") ?: 0.2, blush.num("strength") ?: 0.75,
                ),
                brows = look.obj("brows")?.let {
                    Brows(
                        it.num("above") ?: 0.155, it.num("width") ?: 0.1, it.num("thick") ?: 0.013, it.num("arch") ?: 0.022,
                        it.num("slant") ?: 0.03, it.num("lift") ?: 0.03, it.num("alpha") ?: 0.85,
                    )
                },
                mouth = look.obj("mouth")?.let {
                    Mouth(
                        it.num("y") ?: 0.625, it.num("width") ?: 0.07, it.num("thick") ?: 0.012, it.num("curve") ?: 0.022,
                        it.num("open") ?: 0.05, it.num("round") ?: 0.04, it.num("talk") ?: 0.8,
                    )
                },
                shell = look.obj("shell")?.let { Shell(it.num("shine") ?: 0.13, it.num("shadow") ?: 0.27) },
            )
        }
    }
}

/** Which mouth to draw and how much: "o", "open" (a "D") or "line" (smile to frown). */
fun mouthShape(f: FaceFrame, mouth: GlowLook.Mouth): Pair<String, Double> {
    val talk = f.talk * mouth.talk
    if (f.mouthO > 0.2) return "o" to f.mouthO
    val opened = maxOf(f.mouthOpen, talk)
    if (opened > 0.12) return "open" to opened
    return "line" to f.mouth
}
