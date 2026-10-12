package io.github.senitage.kit.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/**
 * One thing in Kit's knowledge index (kit.knowledge.Item): a fact, a day summary, a
 * page of his notebook, a search hit.
 */
@Serializable
data class Item(
    val id: Long = 0,
    val source: String = "",
    val kind: String = "",
    val title: String = "",
    val text: String = "",
    val day: String? = null,
    val created: String = "",
    val updated: String = "",
    val pinned: Boolean = false,
    val meta: JsonObject? = null,
    val similarity: Double? = null,
    @SerialName("word_match") val wordMatch: Boolean? = null,
)

/** What came of teaching him something (`POST /api/memory/facts`). */
@Serializable
data class Learned(val decision: String = "", val id: Long? = null, val replaced: String? = null)

@Serializable
data class SearchAnswer(
    @SerialName("words_only") val wordsOnly: Boolean = false,
    val hits: List<Item> = emptyList(),
)

@Serializable
data class ThingLink(val system: String = "", val target: String = "")

/** Something in the register of things (kit.things): a person, a car, a project... */
@Serializable
data class Thing(
    val id: Long = 0,
    val name: String = "",
    val kind: String = "",
    val aliases: List<String> = emptyList(),
    val links: List<ThingLink> = emptyList(),
    val about: String = "",
    val suggested: Boolean = false,
    val line: String = "",
)

/** `/api/life/notebook`: the parts the phone shows. */
@Serializable
data class Notebook(
    val sheet: Item? = null,
    val dan: Item? = null,
    val quirks: List<String> = emptyList(),
    val wants: List<Item> = emptyList(),
    val threads: List<Item> = emptyList(),
    val thoughts: List<Item> = emptyList(),
    val opinions: List<Item> = emptyList(),
    val moments: List<Item> = emptyList(),
    val journal: List<Item> = emptyList(),
)

/** `/api/settings`: the settings in force, and a problem with the file if any. */
@Serializable
data class SettingsAnswer(val settings: JsonObject = JsonObject(emptyMap()), val problem: String? = null)

/** `/api/spend/summary`: cloud spend this month against the cap. */
@Serializable
data class Spend(
    @SerialName("month_usd") val monthUsd: Double = 0.0,
    @SerialName("cap_usd") val capUsd: Double = 0.0,
)
