package io.github.senitage.kit.ui

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
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.senitage.kit.Kit
import io.github.senitage.kit.core.Item
import io.github.senitage.kit.core.KitError
import io.github.senitage.kit.core.Later
import io.github.senitage.kit.core.LifeState
import io.github.senitage.kit.core.Notebook
import kotlinx.coroutines.launch
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/**
 * Kit himself: how he's feeling and why, what he's up to and has done today,
 * what's on his mind and what he means to bring up, his quirks and his notebook.
 * Pull down to look again. Mirrors the desk app's Kit page (kit.life).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KitPage(kit: Kit) {
    val life by kit.life.collectAsStateWithLifecycle()
    val hello by kit.hello.collectAsStateWithLifecycle()
    val quietUntil by kit.quietUntil.collectAsStateWithLifecycle()
    val phoneLine by kit.senses.line.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var notebook by remember { mutableStateOf<Notebook?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    var problem by remember { mutableStateOf<String?>(null) }
    val name = hello?.name ?: "Kit"

    suspend fun load() {
        val client = kit.conversation.client ?: return
        refreshing = true
        try {
            notebook = client.notebook()
            kit.refreshLife()
            problem = null
        } catch (e: KitError) {
            problem = "Couldn't ask $name just now."
        }
        refreshing = false
    }
    LaunchedEffect(Unit) { load() }

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = { scope.launch { load() } }, modifier = Modifier.fillMaxSize()) {
        LazyColumn(
            Modifier.fillMaxSize().statusBarsPadding(),
            contentPadding = PaddingValues(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item { Text(name, fontSize = 22.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(vertical = 4.dp)) }
            problem?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
            item { HowHeIs(life, quietUntil, name, onQuiet = { minutes -> scope.launch { kit.quiet(minutes) } }) }
            life?.let { l ->
                if (l.doing != null || l.didToday.isNotEmpty()) item { Section("What he's up to") { Doing(l) } }
                if (l.thinking != null || l.curiousAbout?.isNotEmpty() == true || l.wants.isNotEmpty() || l.later.isNotEmpty() || l.threads.isNotEmpty()) {
                    item { Section("On his mind") { OnHisMind(l) } }
                }
                if (l.quirks.isNotEmpty()) item { Section("His quirks") { l.quirks.forEach { Bullet(it) } } }
            }
            if (phoneLine.isNotEmpty()) item { Section("What this phone tells him") { Text(phoneLine, fontSize = 14.sp) } }
            notebook?.let { nb ->
                nb.sheet?.let { item { Section("Who he thinks he is") { Text(it.text, fontSize = 14.sp) } } }
                nb.dan?.let { item { Section("What he's noticed about you") { Text(it.text, fontSize = 14.sp) } } }
                if (nb.journal.isNotEmpty()) item { Section("His journal") { Entries(nb.journal.take(5)) } }
                if (nb.moments.isNotEmpty()) item { Section("Moments he kept") { Entries(nb.moments.take(5)) } }
                if (nb.opinions.isNotEmpty()) item { Section("Opinions") { Entries(nb.opinions.take(8)) } }
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

@Composable
private fun HowHeIs(life: LifeState?, quietUntil: String?, name: String, onQuiet: (Int) -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            if (life == null) {
                Text("Catching up with $name...", color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                val feeling = life.feeling?.takeIf { it.name.isNotEmpty() }
                Text(
                    feeling?.name?.replaceFirstChar(Char::uppercase) ?: life.mood.replaceFirstChar(Char::uppercase),
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Medium,
                )
                feeling?.why?.takeIf { it.isNotEmpty() }?.let { Text(it, fontSize = 14.sp) }
                life.alsoFeeling?.takeIf { it.name.isNotEmpty() }?.let {
                    Text("Also a bit ${it.name}: ${it.why}", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (life.presence.isNotEmpty()) {
                    Text(life.presence.replaceFirstChar(Char::uppercase), fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                life.energy?.let { energy ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Energy", fontSize = 13.sp, modifier = Modifier.padding(end = 8.dp))
                        LinearProgressIndicator(progress = { energy.toFloat().coerceIn(0f, 1f) }, modifier = Modifier.weight(1f))
                    }
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 4.dp)) {
                Text(
                    if (quietUntil != null) "Keeping quiet until ${clock(quietUntil)}." else "He'll speak up when he has something.",
                    fontSize = 13.sp,
                    modifier = Modifier.weight(1f),
                )
                OutlinedButton(onClick = { onQuiet(if (quietUntil != null) 0 else 60) }) {
                    Text(if (quietUntil != null) "Let him speak" else "Quiet for an hour")
                }
            }
        }
    }
}

@Composable
private fun Doing(life: LifeState) {
    life.doing?.let { Text("Now: $it", fontSize = 14.sp) }
    life.didToday.asReversed().take(8).forEach { Bullet(it) }
}

@Composable
private fun OnHisMind(life: LifeState) {
    life.thinking?.takeIf { it.isNotEmpty() }?.let { Text(it, fontSize = 14.sp, fontStyle = FontStyle.Italic) }
    life.curiousAbout?.takeIf { it.isNotEmpty() }?.let { Text("Curious about $it", fontSize = 14.sp) }
    if (life.wants.isNotEmpty()) {
        Label("Wants to bring up")
        life.wants.forEach { Bullet(it) }
    }
    if (life.later.isNotEmpty()) {
        Label("Saving for later")
        life.later.forEach { LaterLine(it) }
    }
    if (life.threads.isNotEmpty()) {
        Label("Following up")
        life.threads.forEach { LaterLine(it) }
    }
}

@Composable
private fun LaterLine(later: Later) {
    val after = later.after?.let { " (after ${clock(it)})" } ?: ""
    Bullet(later.text + after + if (later.due) " · due" else "")
}

@Composable
private fun Entries(items: List<Item>) {
    items.forEach { item ->
        Column(Modifier.padding(vertical = 3.dp)) {
            val day = item.day ?: item.created.take(10)
            if (day.isNotEmpty()) Text(day, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(item.text, fontSize = 14.sp)
        }
    }
}

@Composable
fun Section(title: String, content: @Composable () -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Column(Modifier.padding(14.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, modifier = Modifier.padding(bottom = 2.dp))
            content()
        }
    }
}

@Composable
fun Label(text: String) {
    Text(text, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
}

@Composable
fun Bullet(text: String) {
    Row {
        Text("•  ", fontSize = 14.sp)
        Text(text, fontSize = 14.sp)
    }
}

/** "10:30 am" from a time Kit gives (ISO, with or without the zone). */
fun clock(at: String): String =
    runCatching { LocalDateTime.parse(at.take(16)).format(DateTimeFormatter.ofPattern("h:mm a")) }.getOrDefault(at)

