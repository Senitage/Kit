package io.github.senitage.kit.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.widget.Toast
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.lerp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.senitage.kit.BuildConfig
import io.github.senitage.kit.FaceMode
import io.github.senitage.kit.Kit
import io.github.senitage.kit.Net
import io.github.senitage.kit.UpdateState
import io.github.senitage.kit.core.ChatView
import io.github.senitage.kit.core.Line
import io.github.senitage.kit.core.Reach
import io.github.senitage.kit.core.Sending
import io.github.senitage.kit.core.Who
import io.github.senitage.kit.core.words
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** The main screen: Kit's face on top, the whole conversation, and a box to talk. */
@Composable
fun ChatScreen(kit: Kit) {
    val view by kit.conversation.view.collectAsStateWithLifecycle()
    val reach by kit.reach.collectAsStateWithLifecycle()
    val update by kit.update.collectAsStateWithLifecycle()
    val list = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val atBottom by remember { derivedStateOf { list.firstVisibleItemIndex == 0 && list.firstVisibleItemScrollOffset < 40 } }
    val rows = remember(view) { rows(view) }

    // Near the top of what's loaded: fetch the page before it.
    val nearTop by remember(rows) {
        derivedStateOf {
            val last = list.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0
            rows.isNotEmpty() && last >= rows.size - 4
        }
    }
    LaunchedEffect(nearTop) { if (nearTop) kit.conversation.loadOlder() }
    // A new line at the bottom while you're at the bottom: stay with it.
    LaunchedEffect(rows.size) { if (atBottom) list.scrollToItem(0) }

    Column(
        Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .navigationBarsPadding()
            .imePadding(),
    ) {
        Header(kit, collapsed = !atBottom)
        if (reach != Reach.Online && reach != Reach.Checking) Banner(kit, reach)
        UpdateBanner(kit, update)
        Box(Modifier.weight(1f).fillMaxWidth()) {
            LazyColumn(
                state = list,
                reverseLayout = true,
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                if (view.typing || view.doing != null) {
                    item(key = "typing") { Typing(view.doing) }
                }
                items(rows.asReversed(), key = { it.key }) { row ->
                    when (row) {
                        is ChatRow.Divider -> Divider(row.label)
                        is ChatRow.Said -> Bubble(kit, row.line)
                    }
                }
                if (view.loadingOlder) item(key = "older") { Hint("Looking further back...") }
            }
        }
        InputBar(kit, reach) { scope.launch { list.scrollToItem(0) } }
    }
}

// ---- the header ----

@Composable
private fun Header(kit: Kit, collapsed: Boolean) {
    val hello by kit.hello.collectAsStateWithLifecycle()
    val mode by kit.faceMode.collectAsStateWithLifecycle()
    val lowPower by kit.lowPower.collectAsStateWithLifecycle()
    val life by kit.life.collectAsStateWithLifecycle()
    val reach by kit.reach.collectAsStateWithLifecycle()
    val bubble by kit.director.bubble.collectAsStateWithLifecycle()
    val t by animateFloatAsState(if (collapsed) 1f else 0f, label = "header")
    val page = remember(hello, mode, lowPower) { kit.facePage() }
    val name = hello?.name ?: "Kit"
    val feeling = life?.feeling?.takeIf { it.name.isNotEmpty() }
    val status = when (reach) {
        Reach.Online -> feeling?.let { "${it.name.replaceFirstChar(Char::uppercase)} · ${it.why}" } ?: life?.mood ?: "here"
        Reach.Checking -> "looking for $name..."
        else -> "out of reach"
    }
    var menu by remember { mutableStateOf(false) }
    var about by remember { mutableStateOf(false) }

    Surface(color = MaterialTheme.colorScheme.surfaceContainer, tonalElevation = 2.dp) {
        BoxWithConstraints(
            Modifier
                .fillMaxWidth()
                .statusBarsPadding()
                .height(lerp(236.dp, 68.dp, t)),
        ) {
            val faceSize: Dp = lerp(150.dp, 52.dp, t)
            val faceX = lerp((maxWidth - 150.dp) / 2, 10.dp, t)
            val faceY = lerp(6.dp, 8.dp, t)
            KitFace(
                kit.director,
                page,
                Modifier
                    .offset(faceX, faceY)
                    .size(faceSize),
            )
            // Name and how he is: under his face, or beside it once collapsed.
            Column(
                Modifier
                    .offset(lerp(0.dp, 72.dp, t), lerp(158.dp, 13.dp, t))
                    .widthIn(max = maxWidth - lerp(0.dp, 120.dp, t))
                    .fillMaxWidth(),
                horizontalAlignment = if (t < 0.5f) Alignment.CenterHorizontally else Alignment.Start,
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier
                            .size(8.dp)
                            .clip(CircleShape)
                            .background(if (reach == Reach.Online) KitColours.Mint else KitColours.Muted),
                    )
                    Spacer(Modifier.size(6.dp))
                    Text(name, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
                }
                Text(
                    status,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontSize = 13.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    textAlign = if (t < 0.5f) TextAlign.Center else TextAlign.Start,
                    modifier = Modifier.padding(horizontal = 16.dp * (1 - t)),
                )
                if (t < 0.5f && bubble.isNotEmpty()) {
                    Text(
                        bubble,
                        fontSize = 13.sp,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        textAlign = TextAlign.Center,
                        modifier = Modifier
                            .padding(top = 6.dp, start = 24.dp, end = 24.dp)
                            .clip(RoundedCornerShape(12.dp))
                            .background(MaterialTheme.colorScheme.surfaceContainerHigh)
                            .padding(horizontal = 10.dp, vertical = 4.dp)
                            .animateContentSize(),
                    )
                }
            }
            Box(Modifier.align(Alignment.TopEnd).padding(4.dp)) {
                IconButton(onClick = { menu = true }) { Icon(Icons.Filled.MoreVert, contentDescription = "More") }
                Menu(kit, menu, mode, onClose = { menu = false }, onAbout = { about = true })
            }
        }
    }
    if (about) About(kit) { about = false }
}

@Composable
private fun Menu(kit: Kit, open: Boolean, mode: FaceMode, onClose: () -> Unit, onAbout: () -> Unit) {
    val scope = rememberCoroutineScope()
    DropdownMenu(expanded = open, onDismissRequest = onClose) {
        DropdownMenuItem(text = { Text("New chat") }, onClick = {
            onClose()
            scope.launch { kit.conversation.newChat() }
        })
        DropdownMenuItem(
            text = { Text(if (mode == FaceMode.FLAT) "Show his 3D face" else "Show his 2D face") },
            onClick = {
                onClose()
                kit.setFaceMode(if (mode == FaceMode.FLAT) FaceMode.AUTO else FaceMode.FLAT)
            },
        )
        DropdownMenuItem(text = { Text("Check for a new version") }, onClick = {
            onClose()
            kit.checkForUpdate(force = true)
        })
        DropdownMenuItem(text = { Text("About this phone") }, onClick = {
            onClose()
            onAbout()
        })
    }
}

@Composable
private fun About(kit: Kit, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var forgetting by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("Kit for Android ${BuildConfig.VERSION_NAME}") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Kit's address: ${kit.address}")
                Text("This phone is \"${kit.deviceName}\" to Kit, with a token of its own.")
                if (BuildConfig.TEST_BUILD) Text("This is a test build of a pull request.")
                if (!BuildConfig.SIGNED) Text("Built without Kit's signing key, so it can't update itself.")
                if (forgetting) {
                    Text(
                        "Unpair? Kit forgets this phone's token and you'll need his token again to pair.",
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                if (!forgetting) {
                    forgetting = true
                } else {
                    onClose()
                    scope.launch { kit.unpair() }
                }
            }) { Text(if (forgetting) "Unpair" else "Unpair this phone...") }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("Close") } },
    )
}

// ---- banners ----

@Composable
private fun Banner(kit: Kit, reach: Reach) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    Surface(color = MaterialTheme.colorScheme.errorContainerOr()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(reach.words(kit.hello.value?.name ?: "Kit"), fontSize = 13.sp, modifier = Modifier.weight(1f))
            when {
                reach is Reach.Away && reach.vpnOff -> TextButton(onClick = { Net.openTailscale(context) }) { Text("Open Tailscale") }
                reach == Reach.Unpaired -> TextButton(onClick = { scope.launch { kit.unpair() } }) { Text("Pair again") }
                else -> TextButton(onClick = { kit.watcher.recheck() }) { Text("Try now") }
            }
        }
    }
}

@Composable
private fun androidx.compose.material3.ColorScheme.errorContainerOr(): Color =
    if (background.luminanceIsDark()) Color(0xFF3A2A1E) else Color(0xFFFFF0E0)

private fun Color.luminanceIsDark(): Boolean = (0.299 * red + 0.587 * green + 0.114 * blue) < 0.5

@Composable
private fun UpdateBanner(kit: Kit, update: UpdateState) {
    when (update) {
        UpdateState.None -> Unit
        is UpdateState.Ready -> Surface(color = MaterialTheme.colorScheme.primaryContainer) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "A new Kit for Android is ready (${update.release.tag.removePrefix("android-v")}).",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = { kit.dismissUpdate() }) { Text("Later") }
                TextButton(onClick = { kit.installUpdate() }) { Text("Update") }
            }
        }
        is UpdateState.Downloading -> LinearProgressIndicator(progress = { update.progress }, modifier = Modifier.fillMaxWidth())
        is UpdateState.Failed -> Surface(color = MaterialTheme.colorScheme.surfaceContainerHigh) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(update.why, fontSize = 13.sp, modifier = Modifier.weight(1f))
                TextButton(onClick = { kit.dismissUpdate() }) { Text("OK") }
            }
        }
    }
}

// ---- the conversation ----

private sealed interface ChatRow {
    val key: String

    data class Said(val line: Line) : ChatRow {
        override val key get() = line.key
    }

    data class Divider(override val key: String, val label: String) : ChatRow
}

/** The lines with a divider wherever the day or the place changes ("TODAY · ON YOUR PHONE"). */
private fun rows(view: ChatView): List<ChatRow> {
    val out = mutableListOf<ChatRow>()
    var lastDay: LocalDate? = null
    var lastPlace: String? = null
    val today = LocalDate.now()
    for (line in view.lines) {
        val day = runCatching { OffsetDateTime.parse(line.at).atZoneSameInstant(ZoneId.systemDefault()).toLocalDate() }.getOrNull()
        val place = if (line.who == Who.DAN) place(line.channel) else lastPlace
        if ((day != null && day != lastDay) || (place != null && place != lastPlace)) {
            val dayWords = when (day ?: lastDay) {
                null -> ""
                today -> "Today"
                today.minusDays(1) -> "Yesterday"
                else -> (day ?: lastDay)!!.format(DateTimeFormatter.ofPattern("EEE d MMM"))
            }
            val label = listOfNotNull(dayWords.takeIf { it.isNotEmpty() }, place).joinToString(" · ").uppercase()
            if (label.isNotEmpty()) out += ChatRow.Divider("d-${line.key}", label)
        }
        if (day != null) lastDay = day
        if (place != null) lastPlace = place
        out += ChatRow.Said(line)
    }
    return out
}

private fun place(channel: String?): String? = when (channel) {
    "phone" -> "on your phone"
    "desk" -> "at the desk"
    "voice" -> "out loud"
    "web" -> "on the web page"
    "home" -> "in home app"
    null, "" -> null
    else -> channel.replace('_', ' ')
}

@Composable
private fun Divider(label: String) {
    Text(
        label,
        fontSize = 11.sp,
        letterSpacing = 1.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center,
        modifier = Modifier.fillMaxWidth().padding(top = 10.dp, bottom = 2.dp),
    )
}

@Composable
private fun Hint(text: String) {
    Text(
        text,
        fontSize = 12.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center,
        modifier = Modifier.fillMaxWidth().padding(8.dp),
    )
}

@Composable
private fun Typing(doing: String?) {
    Text(
        doing?.let { "Kit is $it..." } ?: "Kit is thinking...",
        fontSize = 13.sp,
        fontStyle = FontStyle.Italic,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(start = 6.dp, top = 2.dp),
    )
}

@Composable
private fun Bubble(kit: Kit, line: Line) {
    val context = LocalContext.current
    when (line.who) {
        Who.NOTE -> Hint(line.text)
        Who.ERROR -> Text(
            line.text,
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.error,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().padding(6.dp),
        )
        Who.DAN -> Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.End) {
            Surface(
                color = MaterialTheme.colorScheme.primaryContainer,
                shape = RoundedCornerShape(18.dp, 18.dp, 4.dp, 18.dp),
                modifier = Modifier
                    .widthIn(max = 300.dp)
                    .pointerInput(line.key) { detectTapGestures(onLongPress = { copy(context, line.text) }) },
            ) {
                Text(
                    line.text,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 9.dp),
                )
            }
            val note = when (line.sending) {
                Sending.SENDING -> "sending..."
                Sending.WAITING -> "◷ waiting to send"
                Sending.FAILED -> "Didn't send: ${line.problem}. Tap to try again."
                Sending.DONE -> when (place(line.channel)) {
                    null, "on your phone" -> null
                    else -> place(line.channel)
                }
            }
            if (note != null) {
                Text(
                    note,
                    fontSize = 11.sp,
                    color = if (line.sending == Sending.FAILED) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .padding(top = 2.dp, end = 6.dp)
                        .then(
                            if (line.sending == Sending.FAILED && line.outgoing != null) {
                                Modifier.clickable { kit.conversation.retry(line.outgoing!!) }
                            } else {
                                Modifier
                            },
                        ),
                )
            }
        }
        Who.KIT -> Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.Start) {
            Surface(
                color = MaterialTheme.colorScheme.surfaceContainerHigh,
                shape = RoundedCornerShape(18.dp, 18.dp, 18.dp, 4.dp),
                modifier = Modifier
                    .widthIn(max = 320.dp)
                    .pointerInput(line.key) {
                        detectTapGestures(onLongPress = { copy(context, listOf(line.text, line.detail).filter { it.isNotBlank() }.joinToString("\n\n")) })
                    },
            ) {
                Column(Modifier.padding(horizontal = 14.dp, vertical = 9.dp)) {
                    MarkdownText(line.text, MaterialTheme.colorScheme.onSurface)
                    if (line.detail.isNotBlank()) {
                        HorizontalDivider(Modifier.padding(vertical = 8.dp), color = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f))
                        MarkdownText(line.detail, MaterialTheme.colorScheme.onSurface)
                    }
                }
            }
            if (line.cloud) {
                Text(
                    "with Claude's help",
                    fontSize = 11.sp,
                    color = KitColours.Claude,
                    modifier = Modifier.padding(top = 2.dp, start = 6.dp),
                )
            }
        }
    }
}

private fun copy(context: Context, text: String) {
    val clipboard = context.getSystemService(ClipboardManager::class.java) ?: return
    clipboard.setPrimaryClip(ClipData.newPlainText("Kit", text))
    Toast.makeText(context, "Copied", Toast.LENGTH_SHORT).show()
}

// ---- talking ----

@Composable
private fun InputBar(kit: Kit, reach: Reach, sent: () -> Unit) {
    var text by remember { mutableStateOf("") }
    val online = reach == Reach.Online
    // Text shared to Kit from another app lands in the box.
    val draft by kit.draft.collectAsStateWithLifecycle()
    LaunchedEffect(draft) {
        draft?.let {
            text = if (text.isBlank()) it else "$text\n$it"
            kit.draft.value = null
        }
    }
    Surface(color = MaterialTheme.colorScheme.surfaceContainer) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                placeholder = { Text(if (online) "Say something to Kit..." else "This waits until Kit's back...") },
                maxLines = 5,
                shape = RoundedCornerShape(22.dp),
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.size(6.dp))
            IconButton(
                onClick = {
                    kit.conversation.send(text)
                    text = ""
                    sent()
                },
                enabled = text.isNotBlank(),
            ) {
                Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Send", tint = if (text.isNotBlank()) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline)
            }
        }
    }
}
