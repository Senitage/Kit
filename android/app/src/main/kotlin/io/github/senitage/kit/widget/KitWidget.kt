package io.github.senitage.kit.widget

import android.content.Context
import android.graphics.Bitmap
import android.os.SystemClock
import androidx.compose.runtime.Composable
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Canvas
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.CanvasDrawScope
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.GlanceTheme
import androidx.glance.Image
import androidx.glance.ImageProvider
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.updateAll
import androidx.glance.background
import androidx.glance.layout.Alignment
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.size
import androidx.glance.layout.width
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import io.github.senitage.kit.Kit
import io.github.senitage.kit.KitApp
import io.github.senitage.kit.MainActivity
import io.github.senitage.kit.core.Face
import io.github.senitage.kit.core.GlowLook
import io.github.senitage.kit.core.PhoneBody
import io.github.senitage.kit.core.Who
import io.github.senitage.kit.ui.paintGlow

/** What the widget shows: his face, how he is, and the last thing he said. */
private data class Shown(val name: String, val how: String, val said: String, val face: Bitmap?)

/**
 * Kit on the home screen: his face (2D), how he's feeling and the last thing he
 * said, redrawn when the app looks in on him. A tap opens the app.
 */
class KitWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val kit = (context.applicationContext as KitApp).kit
        val shown = shown(kit)
        provideContent { GlanceTheme { Content(shown) } }
    }

    @Composable
    private fun Content(g: Shown) {
        Column(
            modifier = GlanceModifier
                .fillMaxSize()
                .background(GlanceTheme.colors.widgetBackground)
                .cornerRadius(18.dp)
                .clickable(actionStartActivity<MainActivity>())
                .padding(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = GlanceModifier.fillMaxWidth()) {
                if (g.face != null) Image(ImageProvider(g.face), contentDescription = g.name, modifier = GlanceModifier.size(56.dp))
                Spacer(GlanceModifier.width(10.dp))
                Column {
                    Text(g.name, style = TextStyle(fontWeight = FontWeight.Bold, fontSize = 16.sp, color = GlanceTheme.colors.onSurface))
                    Text(g.how, style = TextStyle(fontSize = 13.sp, color = GlanceTheme.colors.onSurfaceVariant), maxLines = 2)
                }
            }
            if (g.said.isNotEmpty()) {
                Spacer(GlanceModifier.height(8.dp))
                Text(g.said, style = TextStyle(fontSize = 14.sp, color = GlanceTheme.colors.onSurface), maxLines = 3)
            }
        }
    }

    private fun shown(kit: Kit): Shown {
        val life = kit.life.value
        val quiet = kit.quietUntil.value
        val how = when {
            !kit.paired.value -> "Not paired yet. Open Kit to pair."
            quiet != null -> "Keeping quiet for now."
            life == null -> "Open the app to catch up."
            else -> life.feeling?.takeIf { it.name.isNotEmpty() }?.let { "${it.name.replaceFirstChar(Char::uppercase)}: ${it.why}" }
                ?: life.mood.replaceFirstChar(Char::uppercase)
        }
        val said = kit.conversation.view.value.lines.lastOrNull { it.who == Who.KIT && it.text.isNotBlank() }?.text.orEmpty()
        return Shown(kit.name, how, said, faceBitmap(kit, 168))
    }

    /** His 2D face, as the chat draws it, at rest in his current mood. */
    private fun faceBitmap(kit: Kit, px: Int): Bitmap? {
        val character = kit.face.character
        val look = character.look(PhoneBody.KIND)?.let { GlowLook.from(it) } ?: return null
        val bitmap = Bitmap.createBitmap(px, px, Bitmap.Config.ARGB_8888)
        val face = Face(character)
        val now = SystemClock.elapsedRealtime() / 1000.0
        kit.life.value?.face?.takeIf { it.isNotEmpty() }?.let { face.setEmotion(it, now) }
        if (!kit.paired.value) face.setState("offline")
        // Settle the rig, then draw one frame.
        repeat(20) { face.tick(now + it * 0.1) }
        val frame = face.tick(now + 2.0)
        CanvasDrawScope().draw(Density(1f), LayoutDirection.Ltr, Canvas(bitmap.asImageBitmap()), Size(px.toFloat(), px.toFloat())) {
            paintGlow(look, frame, character.hasMoodColours)
        }
        return bitmap
    }

    companion object {
        /** Redraw every Kit widget on the home screen. */
        suspend fun refresh(context: Context) {
            KitWidget().updateAll(context)
        }
    }
}

class KitWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = KitWidget()
}
