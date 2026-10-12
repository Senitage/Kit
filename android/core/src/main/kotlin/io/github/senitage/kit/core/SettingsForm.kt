package io.github.senitage.kit.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray

/** The kinds of setting the phone can edit, and one it only names. */
enum class FieldKind { BOOL, INT, NUMBER, TEXT, CHOICE, LINES, OTHER }

data class SettingsField(
    val name: String,
    val title: String,
    val description: String,
    val kind: FieldKind,
    val choices: List<String> = emptyList(),
    val min: Double? = null,
    val max: Double? = null,
    val optional: Boolean = false,
    val default: JsonElement? = null,
) {
    val editable: Boolean get() = kind != FieldKind.OTHER
}

data class SettingsSection(
    val name: String,
    val title: String,
    val description: String,
    val fields: List<SettingsField>,
) {
    /** A section the app can't draw (models, voice engines: tables of profiles). */
    val editable: Boolean get() = fields.any { it.editable }
}

/**
 * Kit's settings screen, drawn from his settings schema (`/api/settings/schema`, a
 * JSON Schema from pydantic), so a new setting on the brain shows up on the phone
 * without an update. Sections of named profiles (models, voice engines) are named
 * but left to the settings page on the PC.
 */
object SettingsForm {
    fun sections(schema: JsonObject): List<SettingsSection> {
        val properties = schema["properties"] as? JsonObject ?: return emptyList()
        return properties.mapNotNull { (name, node) ->
            if (name == "schema_version") return@mapNotNull null
            val resolved = resolve(schema, node as? JsonObject ?: return@mapNotNull null)
            val fields = (resolved["properties"] as? JsonObject)?.map { (fieldName, fieldNode) ->
                field(fieldName, resolve(schema, fieldNode as? JsonObject ?: JsonObject(emptyMap())), schema)
            } ?: emptyList()
            SettingsSection(
                name,
                resolved.str("title") ?: name,
                resolved.str("description") ?: (node as? JsonObject)?.str("description") ?: "",
                fields,
            )
        }
    }

    /** Follow a `$ref` to its definition, keeping the description written at the use. */
    fun resolve(schema: JsonObject, node: JsonObject): JsonObject {
        val ref = node.str("\$ref") ?: return node
        val name = ref.substringAfterLast('/')
        val defs = schema["\$defs"] as? JsonObject
        val found = defs?.get(name) as? JsonObject ?: return node
        val extra = node.filterKeys { it != "\$ref" }
        return JsonObject(found + extra)
    }

    fun field(name: String, node: JsonObject, schema: JsonObject): SettingsField {
        var optional = false
        var shape = node
        // `str | None`: anyOf [{type: string}, {type: null}]
        (node["anyOf"] as? JsonArray)?.let { options ->
            val real = options.filterIsInstance<JsonObject>().filter { it.str("type") != "null" }
            optional = real.size < options.size
            if (real.size == 1) shape = JsonObject(resolve(schema, real[0]) + node.filterKeys { it != "anyOf" })
        }
        val title = node.str("title") ?: name.replace('_', ' ').replaceFirstChar(Char::uppercase)
        val description = node.str("description") ?: ""
        val default = node["default"]
        val choices = (shape["enum"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull } ?: emptyList()
        val kind = when {
            choices.isNotEmpty() -> FieldKind.CHOICE
            shape.str("type") == "boolean" -> FieldKind.BOOL
            shape.str("type") == "integer" -> FieldKind.INT
            shape.str("type") == "number" -> FieldKind.NUMBER
            shape.str("type") == "string" -> FieldKind.TEXT
            shape.str("type") == "array" && (shape["items"] as? JsonObject)?.str("type") == "string" -> FieldKind.LINES
            else -> FieldKind.OTHER
        }
        return SettingsField(
            name,
            title,
            description,
            kind,
            choices,
            shape.num("minimum"),
            shape.num("maximum"),
            optional,
            default,
        )
    }

    /** A setting's value as the screen shows it in a text box. */
    fun text(value: JsonElement?): String = when (value) {
        null, JsonNull -> ""
        is JsonPrimitive -> value.contentOrNull ?: ""
        is JsonArray -> value.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.joinToString("\n")
        else -> value.toString()
    }

    /**
     * What was typed, as the setting's JSON, or null when it doesn't fit (a word in a
     * number box, a number outside its range). An empty box means unset for an
     * optional setting, and nothing for the rest.
     */
    fun parse(field: SettingsField, typed: String): JsonElement? {
        val text = typed.trim()
        return when (field.kind) {
            FieldKind.BOOL -> when (text.lowercase()) {
                "true", "on", "yes" -> JsonPrimitive(true)
                "false", "off", "no" -> JsonPrimitive(false)
                else -> null
            }
            FieldKind.INT -> text.toLongOrNull()?.takeIf { inRange(field, it.toDouble()) }?.let { JsonPrimitive(it) }
            FieldKind.NUMBER -> text.toDoubleOrNull()?.takeIf { inRange(field, it) }?.let { JsonPrimitive(it) }
            FieldKind.CHOICE -> text.takeIf { it in field.choices }?.let { JsonPrimitive(it) }
            FieldKind.TEXT -> if (text.isEmpty() && field.optional) JsonNull else JsonPrimitive(typed.trimEnd())
            FieldKind.LINES -> JsonArray(typed.lines().map { it.trim() }.filter { it.isNotEmpty() }.map { JsonPrimitive(it) })
            FieldKind.OTHER -> null
        }
    }

    private fun inRange(field: SettingsField, value: Double): Boolean =
        (field.min == null || value >= field.min) && (field.max == null || value <= field.max)

    /** The patch `PATCH /api/settings` takes: the one setting, inside its section. */
    fun patch(section: String, field: String, value: JsonElement): JsonObject =
        JsonObject(mapOf(section to JsonObject(mapOf(field to value))))

    /** The value of one setting in the settings in force. */
    fun value(settings: JsonObject, section: String, field: String): JsonElement? =
        (settings[section] as? JsonObject)?.get(field)

    /** A bool setting's value, for a switch. */
    fun on(value: JsonElement?): Boolean = (value as? JsonPrimitive)?.booleanOrNull ?: false

    /** A list setting's lines (persona traits, rules). */
    fun lines(value: JsonElement?): List<String> =
        runCatching { value?.jsonArray?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull } }.getOrNull() ?: emptyList()

    /** A number setting's value, for a slider. */
    fun number(value: JsonElement?): Double? = (value as? JsonPrimitive)?.doubleOrNull
}
