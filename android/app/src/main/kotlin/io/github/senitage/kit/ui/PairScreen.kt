package io.github.senitage.kit.ui

import android.content.ClipboardManager
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.senitage.kit.Kit
import io.github.senitage.kit.Net
import io.github.senitage.kit.core.PairingLink
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Meeting Kit: type his address and his token (both on the desk app's This PC
 * page) and the app swaps the token for one of its own. A `kit pair` QR code,
 * scanned with the phone's camera, opens the app here too.
 */
@Composable
fun PairScreen(kit: Kit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val link by kit.pairingLink.collectAsStateWithLifecycle()
    var address by remember { mutableStateOf(kit.address.removePrefix("http://").removeSuffix(":8600")) }
    var token by remember { mutableStateOf("") }
    var name by remember { mutableStateOf(kit.deviceName) }
    var busy by remember { mutableStateOf(false) }
    var problem by remember { mutableStateOf<String?>(null) }
    var vpnUp by remember { mutableStateOf(Net.vpnUp(context)) }
    LaunchedEffect(Unit) {
        while (true) {
            vpnUp = Net.vpnUp(context)
            delay(2000)
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        KitFace(kit.director, page = null, modifier = Modifier.size(170.dp))
        Text("Let's meet properly", fontSize = 24.sp, fontWeight = FontWeight.SemiBold)

        val pending = link
        if (pending != null) {
            LinkCard(pending, busy) {
                busy = true
                problem = null
                scope.launch {
                    problem = kit.pair(pending)
                    busy = false
                    if (problem == null) kit.pairingLink.value = null
                }
            }
            TextButton(onClick = { kit.pairingLink.value = null }) { Text("Type the details instead") }
        } else {
            Text(
                "Kit's address and his token are on the desk app's This PC page. " +
                    "Copy the token there, then paste it here. This phone gets a token of its own; " +
                    "Kit's token isn't kept.",
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedTextField(
                value = address,
                onValueChange = { address = it },
                label = { Text("Kit's address") },
                placeholder = { Text("kit-server or 192.168.1.50") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = token,
                onValueChange = { token = it },
                label = { Text("Kit's token") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                trailingIcon = {
                    TextButton(onClick = {
                        val clip = context.getSystemService(ClipboardManager::class.java)?.primaryClip
                        clip?.getItemAt(0)?.coerceToText(context)?.toString()?.trim()?.let { token = it }
                    }) { Text("Paste") }
                },
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                label = { Text("What Kit calls this phone") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = {
                    busy = true
                    problem = null
                    scope.launch {
                        problem = kit.pair(address, token, name)
                        busy = false
                    }
                },
                enabled = !busy && address.isNotBlank() && token.isNotBlank(),
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp) else Text("Pair")
            }
        }

        problem?.let { Text(it, color = MaterialTheme.colorScheme.error, textAlign = TextAlign.Center) }

        Surface(color = MaterialTheme.colorScheme.surfaceContainer, shape = MaterialTheme.shapes.medium) {
            Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    if (vpnUp) "Tailscale looks on." else "Tailscale looks off. Kit is reached through it.",
                    fontSize = 13.sp,
                    modifier = Modifier.weight(1f),
                )
                if (!vpnUp) OutlinedButton(onClick = { Net.openTailscale(context) }) { Text("Open Tailscale") }
            }
        }
        Text(
            "On Kit's PC, `kit pair phone` shows a code you can scan with the camera instead.",
            fontSize = 12.sp,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
    }
}

@Composable
private fun LinkCard(link: PairingLink, busy: Boolean, pair: () -> Unit) {
    Surface(color = MaterialTheme.colorScheme.surfaceContainer, shape = MaterialTheme.shapes.large) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Pair with the code from kit pair?", fontWeight = FontWeight.SemiBold)
            Text("Kit at ${link.url}, calling this phone \"${link.name}\".", color = MaterialTheme.colorScheme.onSurfaceVariant)
            Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
                Button(onClick = pair, enabled = !busy) {
                    if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp) else Text("Pair")
                }
            }
        }
    }
}
