package io.github.senitage.kit.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.senitage.kit.Kit
import io.github.senitage.kit.Tab

/** Pairing until the phone knows Kit (or a pairing code arrives), then his pages. */
@Composable
fun Root(kit: Kit) {
    KitTheme {
        val paired by kit.paired.collectAsStateWithLifecycle()
        val link by kit.pairingLink.collectAsStateWithLifecycle()
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            if (!paired || link != null) PairScreen(kit) else Pages(kit)
        }
    }
}

private val Tab.label: String
    get() = when (this) {
        Tab.CHAT -> "Chat"
        Tab.KIT -> "Kit"
        Tab.MEMORY -> "Memory"
        Tab.SETTINGS -> "Settings"
    }

private val Tab.icon: ImageVector
    get() = when (this) {
        Tab.CHAT -> Icons.AutoMirrored.Filled.Send
        Tab.KIT -> Icons.Filled.Face
        Tab.MEMORY -> Icons.Filled.Search
        Tab.SETTINGS -> Icons.Filled.Settings
    }

/** The chat, Kit himself, his memory and the settings, with tabs along the bottom. */
@Composable
private fun Pages(kit: Kit) {
    val tab by kit.tab.collectAsStateWithLifecycle()
    val hello by kit.hello.collectAsStateWithLifecycle()
    // The tabs make way for the keyboard.
    val keyboardUp = WindowInsets.ime.getBottom(LocalDensity.current) > 0
    AskForNotifications(kit)
    Scaffold(
        bottomBar = {
            if (!keyboardUp) {
                NavigationBar {
                    Tab.entries.forEach { t ->
                        NavigationBarItem(
                            selected = t == tab,
                            onClick = { kit.tab.value = t },
                            icon = { Icon(t.icon, contentDescription = t.label) },
                            label = { Text(if (t == Tab.KIT) hello?.name ?: t.label else t.label) },
                        )
                    }
                }
            }
        },
    ) { padding ->
        Box(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .consumeWindowInsets(padding),
        ) {
            when (tab) {
                Tab.CHAT -> ChatScreen(kit)
                Tab.KIT -> KitPage(kit)
                Tab.MEMORY -> MemoryPage(kit)
                Tab.SETTINGS -> SettingsPage(kit)
            }
        }
    }
}

/** Once, after pairing: may Kit's pipe-ups show as notifications? */
@Composable
private fun AskForNotifications(kit: Kit) {
    if (Build.VERSION.SDK_INT < 33) return
    val context = LocalContext.current
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    LaunchedEffect(Unit) {
        val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        if (!granted && !kit.askedForNotifications) {
            kit.askedForNotifications = true
            ask.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
}
