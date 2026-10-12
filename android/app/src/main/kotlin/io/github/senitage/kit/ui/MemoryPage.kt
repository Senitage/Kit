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
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.senitage.kit.Kit
import io.github.senitage.kit.core.Item
import io.github.senitage.kit.core.KitError
import io.github.senitage.kit.core.Thing
import kotlinx.coroutines.launch

/** The kinds of fact Kit keeps (kit.memory.FACT_KINDS). */
private val FACT_KINDS = listOf("about", "preference", "project", "place", "person", "plan", "now", "other")

private enum class Shelf(val label: String) { FACTS("Facts"), THINGS("Things"), DAYS("Days") }

/**
 * Kit's memory: search it the way he does, teach him something, see and pin or
 * forget what he knows, the things in his register and his day summaries. Mirrors
 * the desk app's Memory page (kit.memory, kit.knowledge, kit.things).
 */
@Composable
fun MemoryPage(kit: Kit) {
    val scope = rememberCoroutineScope()
    val name = kit.name
    var words by remember { mutableStateOf("") }
    var hits by remember { mutableStateOf<List<Item>?>(null) }
    var wordsOnly by remember { mutableStateOf(false) }
    var shelf by remember { mutableStateOf(Shelf.FACTS) }
    var facts by remember { mutableStateOf<List<Item>>(emptyList()) }
    var things by remember { mutableStateOf<List<Thing>>(emptyList()) }
    var days by remember { mutableStateOf<List<Item>>(emptyList()) }
    var problem by remember { mutableStateOf<String?>(null) }
    var teaching by remember { mutableStateOf(false) }
    var forgetting by remember { mutableStateOf<Item?>(null) }
    var opened by remember { mutableStateOf<Long?>(null) }
    var info by remember { mutableStateOf<String?>(null) }

    suspend fun load() {
        val client = kit.conversation.client ?: return
        try {
            when (shelf) {
                Shelf.FACTS -> facts = client.facts()
                Shelf.THINGS -> things = client.things()
                Shelf.DAYS -> days = client.days()
            }
            problem = null
        } catch (e: KitError) {
            problem = "Couldn't ask $name just now."
        }
    }
    LaunchedEffect(shelf) { load() }

    fun search() {
        val client = kit.conversation.client ?: return
        val q = words.trim()
        if (q.isEmpty()) {
            hits = null
            return
        }
        scope.launch {
            try {
                val answer = client.search(q)
                hits = answer.hits
                wordsOnly = answer.wordsOnly
            } catch (e: KitError) {
                problem = "Couldn't search just now."
            }
        }
    }

    LazyColumn(
        Modifier.fillMaxSize().statusBarsPadding(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item { Text("Memory", fontSize = 22.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(vertical = 4.dp)) }
        item {
            OutlinedTextField(
                value = words,
                onValueChange = { words = it },
                placeholder = { Text("Search what $name remembers") },
                singleLine = true,
                trailingIcon = { IconButton(onClick = { search() }) { Icon(Icons.Filled.Search, contentDescription = "Search") } },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { search() }),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        problem?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
        info?.let { item { Text(it, fontSize = 13.sp, color = MaterialTheme.colorScheme.primary) } }
        hits?.let { found ->
            item {
                Text(
                    when {
                        found.isEmpty() -> "Nothing came to mind for that."
                        wordsOnly -> "By words only (his embeddings are off):"
                        else -> "What came to mind:"
                    },
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            items(found, key = { "hit-${it.id}" }) { hit -> Hit(hit) }
        }
        item {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Shelf.entries.forEach { s ->
                    FilterChip(selected = s == shelf, onClick = { shelf = s }, label = { Text(s.label) })
                }
                FilterChip(selected = teaching, onClick = { teaching = !teaching }, label = { Text("Teach him something") })
            }
        }
        if (teaching) {
            item {
                Teach(name, FACT_KINDS) { text, kind, pinned ->
                    scope.launch {
                        val client = kit.conversation.client ?: return@launch
                        try {
                            val learned = client.teach(text, kind, pinned)
                            info = when (learned.decision) {
                                "new" -> "$name learned that."
                                "update" -> "$name updated what he knew."
                                "same" -> "$name already knew that."
                                else -> "$name took that in (${learned.decision})."
                            }
                            teaching = false
                            shelf = Shelf.FACTS
                            load()
                        } catch (e: KitError) {
                            problem = e.message ?: "Couldn't teach him just now."
                        }
                    }
                }
            }
        }
        when (shelf) {
            Shelf.FACTS -> {
                if (facts.isEmpty()) item { Text("Nothing taught yet. Tell him things in the chat, or teach him here.", fontSize = 13.sp) }
                items(facts.sortedByDescending { it.pinned }, key = { "fact-${it.id}" }) { fact ->
                    Fact(
                        fact,
                        onPin = {
                            scope.launch {
                                runCatching { kit.conversation.client?.pinFact(fact.id, !fact.pinned) }
                                load()
                            }
                        },
                        onForget = { forgetting = fact },
                    )
                }
            }
            Shelf.THINGS -> {
                if (things.isEmpty()) item { Text("No things in his register yet.", fontSize = 13.sp) }
                items(things, key = { "thing-${it.id}" }) { thing ->
                    ThingCard(thing, open = opened == thing.id) { opened = if (opened == thing.id) null else thing.id }
                }
            }
            Shelf.DAYS -> {
                if (days.isEmpty()) item { Text("No days written up yet.", fontSize = 13.sp) }
                items(days, key = { "day-${it.id}" }) { day ->
                    DayCard(day, open = opened == day.id) { opened = if (opened == day.id) null else day.id }
                }
            }
        }
        item { Spacer(Modifier.height(24.dp)) }
    }

    forgetting?.let { fact ->
        AlertDialog(
            onDismissRequest = { forgetting = null },
            title = { Text("Forget this?") },
            text = { Text(fact.text) },
            confirmButton = {
                TextButton(onClick = {
                    forgetting = null
                    scope.launch {
                        runCatching { kit.conversation.client?.forgetFact(fact.id) }
                        load()
                    }
                }) { Text("Forget") }
            },
            dismissButton = { TextButton(onClick = { forgetting = null }) { Text("Keep") } },
        )
    }
}

@Composable
private fun Hit(hit: Item) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Column(Modifier.padding(12.dp)) {
            val where = listOfNotNull(hit.source.replace('_', ' '), hit.kind.takeIf { it.isNotEmpty() }, hit.day).joinToString(" · ")
            Text(where, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (hit.title.isNotEmpty() && hit.title != hit.text) Text(hit.title, fontWeight = FontWeight.Medium, fontSize = 14.sp)
            Text(hit.text, fontSize = 14.sp, maxLines = 6)
        }
    }
}

@Composable
private fun Fact(fact: Item, onPin: () -> Unit, onForget: () -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
        Row(Modifier.padding(start = 12.dp, top = 6.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(fact.kind + if (fact.pinned) " · always" else "", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(fact.text, fontSize = 14.sp)
            }
            IconButton(onClick = onPin) {
                Icon(
                    Icons.Filled.Star,
                    contentDescription = if (fact.pinned) "Stop always keeping this in mind" else "Always keep this in mind",
                    tint = if (fact.pinned) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline,
                )
            }
            IconButton(onClick = onForget) { Icon(Icons.Filled.Delete, contentDescription = "Forget") }
        }
    }
}

@Composable
private fun Teach(name: String, kinds: List<String>, onTeach: (String, String, Boolean) -> Unit) {
    var text by remember { mutableStateOf("") }
    var kind by remember { mutableStateOf("other") }
    var pinned by remember { mutableStateOf(false) }
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerHigh)) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                placeholder = { Text("Something $name should know") },
                maxLines = 4,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                kinds.forEach { k -> FilterChip(selected = k == kind, onClick = { kind = k }, label = { Text(k) }) }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(checked = pinned, onCheckedChange = { pinned = it }, enabled = kind != "now")
                Text("Always keep in mind", fontSize = 13.sp, modifier = Modifier.padding(start = 8.dp).weight(1f))
                TextButton(onClick = { onTeach(text.trim(), kind, pinned && kind != "now") }, enabled = text.isNotBlank()) { Text("Teach") }
            }
        }
    }
}

@Composable
private fun ThingCard(thing: Thing, open: Boolean, onToggle: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
        modifier = Modifier.clickable(onClick = onToggle),
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(thing.name + if (thing.suggested) " (his guess)" else "", fontWeight = FontWeight.Medium, fontSize = 14.sp)
            Text(thing.kind + if (thing.aliases.isNotEmpty()) " · also " + thing.aliases.joinToString(", ") else "", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (open) {
                if (thing.about.isNotEmpty()) Text(thing.about, fontSize = 14.sp, modifier = Modifier.padding(top = 4.dp))
                thing.links.forEach { Text("${it.system}: ${it.target}", fontSize = 12.sp, modifier = Modifier.padding(top = 2.dp)) }
            }
        }
    }
}

@Composable
private fun DayCard(day: Item, open: Boolean, onToggle: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
        modifier = Modifier.clickable(onClick = onToggle),
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(day.day ?: day.title, fontWeight = FontWeight.Medium, fontSize = 14.sp)
            Text(day.text, fontSize = 14.sp, maxLines = if (open) Int.MAX_VALUE else 2)
        }
    }
}
