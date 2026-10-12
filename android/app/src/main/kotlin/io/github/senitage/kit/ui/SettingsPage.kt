package io.github.senitage.kit.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.senitage.kit.BuildConfig
import io.github.senitage.kit.FaceMode
import io.github.senitage.kit.Kit
import io.github.senitage.kit.Notifier
import io.github.senitage.kit.Nudges
import io.github.senitage.kit.core.FieldKind
import io.github.senitage.kit.core.KitError
import io.github.senitage.kit.core.SettingsField
import io.github.senitage.kit.core.SettingsForm
import io.github.senitage.kit.core.SettingsSection
import io.github.senitage.kit.core.Spend
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.coroutines.launch

/**
 * Settings: this phone's own (notifications, what it tells Kit, his face), then
 * Kit's settings drawn from his settings schema, each change saved on its own
 * with an undo. Sections the phone can't draw point to the PC.
 */
@Composable
fun SettingsPage(kit: Kit) {
    val scope = rememberCoroutineScope()
    val name = kit.name
    var sections by remember { mutableStateOf<List<SettingsSection>>(emptyList()) }
    var settings by remember { mutableStateOf<JsonObject?>(null) }
    var fileProblem by remember { mutableStateOf<String?>(null) }
    var spend by remember { mutableStateOf<Spend?>(null) }
    var problem by remember { mutableStateOf<String?>(null) }
    var open by remember { mutableStateOf<String?>(null) }
    var changed by remember { mutableStateOf(false) }

    suspend fun load() {
        val client = kit.conversation.client ?: return
        try {
            sections = SettingsForm.sections(client.settingsSchema())
            val answer = client.settings()
            settings = answer.settings
            fileProblem = answer.problem
            spend = runCatching { client.spend() }.getOrNull()
            problem = null
        } catch (e: KitError) {
            problem = "Couldn't fetch $name's settings just now."
        }
    }
    LaunchedEffect(Unit) { load() }

    fun change(section: String, field: String, value: JsonElement) {
        val client = kit.conversation.client ?: return
        scope.launch {
            try {
                val answer = client.changeSettings(SettingsForm.patch(section, field, value))
                settings = answer.settings
                fileProblem = answer.problem
                changed = true
                problem = null
            } catch (e: KitError) {
                problem = e.message ?: "$name didn't take that."
            }
        }
    }

    LazyColumn(
        Modifier.fillMaxSize().statusBarsPadding(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item { Text("Settings", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(vertical = 4.dp)) }
        item { ThisPhone(kit) }
        item {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 8.dp)) {
                Text("$name's settings", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                if (changed) {
                    TextButton(onClick = {
                        scope.launch {
                            runCatching { kit.conversation.client?.undoSettings() }.getOrNull()?.let {
                                settings = it.settings
                                fileProblem = it.problem
                            }
                        }
                    }) { Text("Undo last change") }
                }
            }
        }
        spend?.let { item { Text("Cloud this month: $${"%.2f".format(it.monthUsd)} of $${"%.0f".format(it.capUsd)}", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant) } }
        fileProblem?.let { item { Text("His settings file has a problem: $it", color = MaterialTheme.colorScheme.error, fontSize = 13.sp) } }
        problem?.let { item { Text(it, color = MaterialTheme.colorScheme.error, fontSize = 13.sp) } }
        items(sections, key = { it.name }) { section ->
            SectionCard(section, settings, open == section.name, onToggle = { open = if (open == section.name) null else section.name }) { field, value ->
                change(section.name, field, value)
            }
        }
        item { Spacer(Modifier.height(24.dp)) }
    }
}

@Composable
private fun ThisPhone(kit: Kit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val senses by kit.senses.senses.collectAsStateWithLifecycle()
    val nudges by kit.nudges.collectAsStateWithLifecycle()
    val mode by kit.faceMode.collectAsStateWithLifecycle()
    val line by kit.senses.line.collectAsStateWithLifecycle()
    var homeMarked by remember { mutableStateOf(kit.senses.homeMarked) }
    var atHome by remember { mutableStateOf(kit.senses.atHome) }
    var onWifi by remember { mutableStateOf(kit.senses.onWifi) }
    val name = kit.name
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("This phone", fontWeight = FontWeight.SemiBold, fontSize = 15.sp)

            SwitchRow("Notifications when he speaks up", senses.notify) { kit.setNotify(it) }
            Text(
                when {
                    !senses.notify -> "Nothing while the app's closed."
                    !Notifier.allowed(context) -> "The phone is blocking Kit's notifications. Allow them in the phone's settings."
                    nudges == true -> "$name nudges this phone the moment he speaks up."
                    !Nudges.available -> "This build has no push: the phone looks for pipe-ups every half hour."
                    nudges == false -> "$name's PC has no Firebase account yet, so the phone looks every half hour instead."
                    else -> "Asking $name whether he can nudge this phone..."
                },
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            HorizontalDivider()

            SwitchRow("Tell him when I'm home or out", senses.tellPlace) {
                kit.senses.set(senses.copy(tellPlace = it))
                scope.launch { kit.senses.report(force = true) }
            }
            if (senses.tellPlace) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        when {
                            !homeMarked -> "Mark the Wi-Fi you're on as home. He only ever hears \"home\" or \"out\", never where."
                            atHome -> "On the home Wi-Fi now."
                            onWifi -> "On another Wi-Fi: out."
                            else -> "Not on Wi-Fi: out."
                        },
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = {
                        if (homeMarked) kit.senses.forgetHome() else kit.senses.markHomeHere()
                        homeMarked = kit.senses.homeMarked
                        atHome = kit.senses.atHome
                        onWifi = kit.senses.onWifi
                        scope.launch { kit.senses.report(force = true) }
                    }, enabled = homeMarked || onWifi) { Text(if (homeMarked) "Forget home" else "This Wi-Fi is home") }
                }
            }
            SwitchRow("Tell him about the battery", senses.tellBattery) {
                kit.senses.set(senses.copy(tellBattery = it))
                scope.launch { kit.senses.report(force = true) }
            }
            if (line.isNotEmpty()) Text("He sees: $line", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            HorizontalDivider()

            SwitchRow("His 3D face when he has one", mode == FaceMode.AUTO) { kit.setFaceMode(if (it) FaceMode.AUTO else FaceMode.FLAT) }
            Text("Shake the phone to startle him. Battery saver keeps his face 2D.", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            HorizontalDivider()

            Text("Kit for Android ${BuildConfig.VERSION_NAME}. Updates and unpairing are under the menu on the chat.", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun SwitchRow(label: String, on: Boolean, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
        Text(label, fontSize = 14.sp, modifier = Modifier.weight(1f))
        Switch(checked = on, onCheckedChange = onChange)
    }
}

@Composable
private fun SectionCard(
    section: SettingsSection,
    settings: JsonObject?,
    open: Boolean,
    onToggle: () -> Unit,
    onChange: (String, JsonElement) -> Unit,
) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
        modifier = Modifier.clickable(onClick = onToggle),
    ) {
        Column(Modifier.padding(14.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(section.title, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
            if (section.description.isNotEmpty()) Text(section.description, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (open) {
                if (!section.editable) {
                    Text("Change these on the settings page on the PC.", fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp))
                }
                section.fields.forEach { field ->
                    val value = settings?.let { SettingsForm.value(it, section.name, field.name) }
                    FieldRow(field, value) { onChange(field.name, it) }
                }
            }
        }
    }
}

@Composable
private fun FieldRow(field: SettingsField, value: JsonElement?, onChange: (JsonElement) -> Unit) {
    Column(Modifier.padding(top = 6.dp)) {
        when (field.kind) {
            FieldKind.BOOL -> SwitchRow(field.title, SettingsForm.on(value)) { onChange(JsonPrimitive(it)) }
            FieldKind.CHOICE -> {
                Text(field.title, fontSize = 14.sp)
                val now = SettingsForm.text(value)
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    field.choices.forEach { c ->
                        FilterChip(selected = c == now, onClick = { if (c != now) onChange(JsonPrimitive(c)) }, label = { Text(c) })
                    }
                }
            }
            FieldKind.INT, FieldKind.NUMBER, FieldKind.TEXT, FieldKind.LINES -> TypedField(field, value, onChange)
            FieldKind.OTHER -> {
                Text(field.title, fontSize = 14.sp)
                Text("Change this on the PC.", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        if (field.description.isNotEmpty()) {
            Text(field.description, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun TypedField(field: SettingsField, value: JsonElement?, onChange: (JsonElement) -> Unit) {
    val shown = SettingsForm.text(value)
    var typed by remember(shown) { mutableStateOf(shown) }
    val parsed = SettingsForm.parse(field, typed)
    val dirty = typed != shown
    OutlinedTextField(
        value = typed,
        onValueChange = { typed = it },
        label = { Text(field.title) },
        isError = dirty && parsed == null,
        supportingText = if (dirty && parsed == null) {
            {
                Text(
                    when (field.kind) {
                        FieldKind.INT -> "A whole number" + range(field)
                        FieldKind.NUMBER -> "A number" + range(field)
                        else -> "That doesn't fit"
                    },
                )
            }
        } else {
            null
        },
        singleLine = field.kind != FieldKind.LINES && field.kind != FieldKind.TEXT,
        maxLines = if (field.kind == FieldKind.LINES) 8 else 4,
        trailingIcon = if (dirty && parsed != null) {
            { TextButton(onClick = { onChange(parsed) }) { Text("Save") } }
        } else {
            null
        },
        modifier = Modifier.fillMaxWidth(),
    )
}

private fun range(field: SettingsField): String {
    val min = field.min
    val max = field.max
    return when {
        min != null && max != null -> " from ${plain(min)} to ${plain(max)}"
        min != null -> " of at least ${plain(min)}"
        max != null -> " of at most ${plain(max)}"
        else -> ""
    }
}

private fun plain(n: Double): String = if (n == n.toLong().toDouble()) n.toLong().toString() else n.toString()
