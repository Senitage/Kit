package io.github.senitage.kit.ui

import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathOperation
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.withTransform
import io.github.senitage.kit.core.FaceFrame
import io.github.senitage.kit.core.GlowLook
import io.github.senitage.kit.core.mouthShape
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * Kit's 2D glow face (Kit 2D, or a 3D character's 2D fallback), drawn from one
 * [FaceFrame]: a port of the desk's Glow painter (kit.desk.glow.paint_glow), so
 * both draw the same shapes from the same sheet.
 */
fun DrawScope.paintGlow(look: GlowLook, f: FaceFrame, moodColours: Boolean) {
    val s = min(size.width, size.height)
    val ox = (size.width - s) / 2
    val oy = (size.height - s) / 2
    val scr = look.screen
    val eyes = look.eyes

    look.shell?.let { shell ->
        val x = scr.x + scr.width / 2
        val centre = Offset(ox + s * x.toFloat(), oy + s * (scr.y + scr.height + 0.07).toFloat())
        drawOval(
            Brush.radialGradient(
                listOf(Color.Black.copy(alpha = shell.shadow.toFloat()), Color.Transparent),
                center = centre,
                radius = s * 0.4f,
            ),
            topLeft = Offset(centre.x - s * (scr.width * 0.47).toFloat(), centre.y - s * 0.045f),
            size = androidx.compose.ui.geometry.Size(s * (scr.width * 0.94).toFloat(), s * 0.09f),
        )
    }

    withTransform({
        translate(ox + s / 2 + (f.dx * s).toFloat(), oy + s * look.neck.toFloat() + (f.dy * s).toFloat())
        rotate((f.rot * 57.2958).toFloat(), pivot = Offset.Zero)
        scale((f.sx * f.scale).toFloat(), (f.sy * f.scale).toFloat(), pivot = Offset.Zero)
        translate(-s / 2, -s * look.neck.toFloat())
    }) {
        val screen = Rect(
            s * scr.x.toFloat(),
            s * scr.y.toFloat(),
            s * (scr.x + scr.width).toFloat(),
            s * (scr.y + scr.height).toFloat(),
        )
        val corner = CornerRadius(s * scr.corner.toFloat())
        val shell = look.shell
        if (shell != null) {
            val top = colour(look.colour("shell_top", look.colour("screen")))
            val mid = colour(look.colour("screen"))
            val bottom = colour(look.colour("shell_bottom", look.colour("screen")))
            drawRoundRect(
                Brush.verticalGradient(0f to top, 0.45f to mid, 1f to bottom, startY = screen.top, endY = screen.bottom),
                topLeft = screen.topLeft,
                size = screen.size,
                cornerRadius = corner,
            )
            drawRoundRect(
                Brush.radialGradient(
                    listOf(Color.White.copy(alpha = shell.shine.toFloat()), Color.Transparent),
                    center = Offset(screen.left + screen.width * 0.33f, screen.top + screen.height * 0.15f),
                    radius = s * 0.32f,
                ),
                topLeft = screen.topLeft,
                size = screen.size,
                cornerRadius = corner,
            )
        } else {
            drawRoundRect(colour(look.colour("screen", "#2E3035")), screen.topLeft, screen.size, corner)
            if (scr.bezel > 0) {
                drawRoundRect(
                    colour(look.colour("bezel", "#2E3035")),
                    screen.topLeft,
                    screen.size,
                    corner,
                    style = Stroke(s * scr.bezel.toFloat()),
                )
            }
        }

        val pulse = 1 + f.talk * eyes.talkPulse
        val glowColour = when {
            f.offline -> colour(look.colour("eye_offline", "#8C96A0"))
            moodColours && f.colour != null -> colour(f.colour!!)
            else -> colour(look.colour("eye"))
        }
        val fillAlpha = (look.glow.dim + (1 - look.glow.dim) * f.glow).toFloat()
        for ((side, open) in listOf(-1 to f.openLeft, 1 to f.openRight)) {
            val cx = s / 2 + side * s * eyes.apart.toFloat() + (f.lookX * s * eyes.reachX).toFloat()
            val cy = s * eyes.y.toFloat() + (f.lookY * s * eyes.reachY).toFloat()
            val w = s * (eyes.width * f.size).toFloat()
            val h = s * (eyes.height * f.size * open * pulse).toFloat()
            val eye = eyePath(cx, cy, w, h, s, f, side, eyes.corner, eyes.squintLift, eyes.squintRound)
            look.glow.rings.forEachIndexed { i, alpha ->
                drawPath(
                    eye,
                    glowColour.copy(alpha = (alpha * f.glow / 255).toFloat().coerceIn(0f, 1f)),
                    style = Stroke(
                        width = s * (look.glow.ringWidth * (i + 1)).toFloat(),
                        cap = StrokeCap.Round,
                        join = StrokeJoin.Round,
                    ),
                )
            }
            drawPath(eye, glowColour.copy(alpha = fillAlpha))
            look.brows?.let { brows ->
                val y = cy - s * (brows.above * max(1.0, f.size)).toFloat() - (f.browUp * s * brows.lift).toFloat()
                val half = s * brows.width.toFloat() / 2
                val slant = (f.brow * s * brows.slant).toFloat()
                val inner = -side
                val path = Path().apply {
                    moveTo(cx - inner * half, y + slant * 0.4f)
                    quadraticBezierTo(cx, y - s * brows.arch.toFloat() + slant * 0.2f, cx + inner * half, y - slant)
                }
                drawPath(
                    path,
                    glowColour.copy(alpha = fillAlpha * brows.alpha.toFloat()),
                    style = Stroke(s * brows.thick.toFloat(), cap = StrokeCap.Round),
                )
            }
        }

        look.mouth?.let { mouth ->
            val fill = glowColour.copy(alpha = fillAlpha)
            val mx = s / 2 + (f.lookX * s * eyes.reachX * 0.5).toFloat()
            val my = s * mouth.y.toFloat() + (f.lookY * s * eyes.reachY * 0.5).toFloat()
            val (kind, amount) = mouthShape(f, mouth)
            var w = s * mouth.width.toFloat()
            when (kind) {
                "o" -> {
                    val r = s * (mouth.round * (0.45 + 0.55 * amount)).toFloat()
                    drawOval(fill, Offset(mx - r * 0.85f, my - r), androidx.compose.ui.geometry.Size(r * 1.7f, r * 2))
                }
                "open" -> {
                    val d = s * (mouth.open * amount).toFloat()
                    w *= (0.8 + 0.4 * amount).toFloat()
                    val path = Path().apply {
                        moveTo(mx - w / 2, my - d * 0.25f)
                        quadraticBezierTo(mx, my - d * 0.05f, mx + w / 2, my - d * 0.25f)
                        cubicTo(mx + w / 2, my + d * 0.9f, mx - w / 2, my + d * 0.9f, mx - w / 2, my - d * 0.25f)
                        close()
                    }
                    drawPath(path, fill)
                }
                else -> {
                    val c = (amount * s * mouth.curve).toFloat()
                    val path = Path().apply {
                        moveTo(mx - w / 2, my - c * 0.3f)
                        quadraticBezierTo(mx, my + c, mx + w / 2, my - c * 0.3f)
                    }
                    drawPath(path, fill, style = Stroke(s * mouth.thick.toFloat(), cap = StrokeCap.Round))
                }
            }
        }

        val blush = look.blush
        if (f.blush > blush.from && !f.offline) {
            val cheek = colour(look.colour("blush", "#FF8FA8"))
                .copy(alpha = min(1.0, f.blush * blush.strength * f.glow).toFloat())
            for (side in listOf(-1, 1)) {
                val centre = Offset(s / 2 + side * s * blush.apart.toFloat(), s * blush.y.toFloat())
                val rw = s * blush.width.toFloat()
                val rh = s * blush.height.toFloat()
                drawOval(cheek, Offset(centre.x - rw, centre.y - rh), androidx.compose.ui.geometry.Size(rw * 2, rh * 2))
            }
        }
    }
}

/** One eye as a rounded pill, with the lids cut away. */
private fun eyePath(
    cx: Float,
    cy: Float,
    w: Float,
    hIn: Float,
    s: Float,
    f: FaceFrame,
    side: Int,
    corner: Double,
    lift: Double,
    round: Double,
): Path {
    val h = max(hIn, s * 0.012f)
    val r = min(s * corner.toFloat(), h / 2)
    var eye = Path().apply {
        addRoundRect(RoundRect(Rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), CornerRadius(s * corner.toFloat(), r)))
    }
    val hh = max(h, s * 0.03f)
    if (abs(f.tilt) > 0.02) {
        val slope = (f.tilt * 0.55 * (if (side < 0) -1 else 1)).toFloat()
        val y0 = cy - hh / 2 + hh * 0.32f * abs(f.tilt).toFloat()
        val x0 = cx - w * 1.5f
        val x1 = cx + w * 1.5f
        val lid = Path().apply {
            moveTo(x0, y0 + slope * (x0 - cx))
            lineTo(x1, y0 + slope * (x1 - cx))
            lineTo(x1, cy - hh * 2)
            lineTo(x0, cy - hh * 2)
            close()
        }
        eye = Path.combine(PathOperation.Difference, eye, lid)
    }
    if (f.squint > 0.02) {
        val radius = w * round.toFloat()
        val centreY = cy + hh / 2 + radius - hh * (f.squint * lift).toFloat()
        val lid = Path().apply { addOval(Rect(cx - radius, centreY - radius, cx + radius, centreY + radius)) }
        eye = Path.combine(PathOperation.Difference, eye, lid)
    }
    return eye
}

fun colour(hex: String): Color = try {
    val v = hex.removePrefix("#")
    when (v.length) {
        6 -> Color(0xFF000000 or v.toLong(16))
        8 -> Color(v.toLong(16)) // #AARRGGBB, as Qt reads it
        else -> KitColours.Mint
    }
} catch (e: Exception) {
    KitColours.Mint
}
