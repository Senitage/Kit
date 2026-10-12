package io.github.senitage.kit.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** Kit's own colours: his mint glow on night blue, and a light look to match. */
object KitColours {
    val Mint = Color(0xFF4DFFC0)
    val MintDeep = Color(0xFF00A877)
    val Night = Color(0xFF10151C)
    val NightRaised = Color(0xFF1A212B)
    val NightHigh = Color(0xFF242D39)
    val Screen = Color(0xFF2E3035)
    val Muted = Color(0xFF8C96A0)
    val Blush = Color(0xFFFF8FA8)
    val Claude = Color(0xFFD97757)
}

private val Dark = darkColorScheme(
    primary = KitColours.Mint,
    onPrimary = Color(0xFF00382A),
    primaryContainer = Color(0xFF0F4D3B),
    onPrimaryContainer = Color(0xFFB8FFE4),
    secondary = Color(0xFF9FCBBB),
    background = KitColours.Night,
    onBackground = Color(0xFFE2E8EE),
    surface = KitColours.Night,
    onSurface = Color(0xFFE2E8EE),
    surfaceVariant = KitColours.NightRaised,
    onSurfaceVariant = Color(0xFFC1CAD3),
    surfaceContainer = KitColours.NightRaised,
    surfaceContainerHigh = KitColours.NightHigh,
    outline = Color(0xFF4A5563),
    error = Color(0xFFFF8A80),
)

private val Light = lightColorScheme(
    primary = KitColours.MintDeep,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFC7F7E4),
    onPrimaryContainer = Color(0xFF002117),
    secondary = Color(0xFF4C6358),
    background = Color(0xFFF6F8FA),
    onBackground = Color(0xFF161C22),
    surface = Color(0xFFF6F8FA),
    onSurface = Color(0xFF161C22),
    surfaceVariant = Color(0xFFE6EBEF),
    onSurfaceVariant = Color(0xFF424A52),
    surfaceContainer = Color(0xFFEDF1F4),
    surfaceContainerHigh = Color(0xFFE2E8EC),
    outline = Color(0xFF9AA4AE),
    error = Color(0xFFB3261E),
)

@Composable
fun KitTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, content = content)
}
