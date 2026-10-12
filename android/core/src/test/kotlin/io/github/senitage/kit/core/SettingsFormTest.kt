package io.github.senitage.kit.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** The settings page against a copy of Kit's real schema (tests/test_android.py keeps it current). */
class SettingsFormTest {
    private val schema: JsonObject by lazy {
        val text = javaClass.getResource("/settings_schema.json")!!.readText()
        KitJson.parseToJsonElement(text).jsonObject
    }
    private val sections by lazy { SettingsForm.sections(schema) }

    private fun section(name: String) = sections.first { it.name == name }
    private fun field(section: String, name: String) = section(section).fields.first { it.name == name }

    @Test
    fun `every section of kit's settings is drawn, except the version`() {
        val names = sections.map { it.name }
        assertTrue("phone" in names && "persona" in names && "life" in names, names.toString())
        assertTrue("schema_version" !in names)
        assertTrue(sections.all { it.title.isNotBlank() })
        assertTrue(section("phone").description.contains("phone"), section("phone").description)
    }

    @Test
    fun `fields get their kind from the schema`() {
        val notify = field("phone", "notify")
        assertEquals(FieldKind.CHOICE, notify.kind)
        assertEquals(listOf("away", "always", "never"), notify.choices)
        assertEquals(JsonPrimitive("away"), notify.default)
        assertTrue(notify.description.contains("notification"), notify.description)

        val perHour = field("phone", "notify_per_hour")
        assertEquals(FieldKind.INT, perHour.kind)
        assertEquals(0.0, perHour.min)
        assertEquals(20.0, perHour.max)

        assertEquals(FieldKind.TEXT, field("persona", "backstory").kind)
        assertEquals(FieldKind.LINES, field("persona", "traits").kind)
        assertEquals(FieldKind.BOOL, field("cloud", "stream").kind)
        assertEquals(FieldKind.NUMBER, field("cloud", "monthly_cap_usd").kind)
        assertEquals(FieldKind.OTHER, field("persona", "examples").kind)
    }

    @Test
    fun `an optional setting is one that may be null`() {
        val anyOptional = sections.flatMap { it.fields }.filter { it.optional }
        assertTrue(anyOptional.isNotEmpty())
        assertTrue(anyOptional.all { it.kind != FieldKind.OTHER || it.choices.isEmpty() })
        val vault = field("nas", "vault")
        assertEquals(FieldKind.TEXT, vault.kind)
        assertTrue(vault.optional)
    }

    @Test
    fun `sections of named profiles are named but not drawn`() {
        assertTrue(!section("models").editable)
        assertTrue(section("phone").editable)
    }

    @Test
    fun `what's typed becomes the setting's json, or nothing when it doesn't fit`() {
        val perHour = field("phone", "notify_per_hour")
        assertEquals(JsonPrimitive(3L), SettingsForm.parse(perHour, " 3 "))
        assertNull(SettingsForm.parse(perHour, "21"))
        assertNull(SettingsForm.parse(perHour, "three"))
        assertNull(SettingsForm.parse(perHour, "2.5"))
        val notify = field("phone", "notify")
        assertEquals(JsonPrimitive("never"), SettingsForm.parse(notify, "never"))
        assertNull(SettingsForm.parse(notify, "sometimes"))
        val traits = field("persona", "traits")
        assertEquals(
            JsonArray(listOf(JsonPrimitive("kind"), JsonPrimitive("curious"))),
            SettingsForm.parse(traits, "kind\n\n curious \n"),
        )
        val enabled = field("cloud", "stream")
        assertEquals(JsonPrimitive(true), SettingsForm.parse(enabled, "on"))
        val cap = field("cloud", "monthly_cap_usd")
        assertEquals(JsonPrimitive(12.5), SettingsForm.parse(cap, "12.5"))
        val backstory = field("persona", "backstory")
        assertEquals(JsonPrimitive("A desk robot."), SettingsForm.parse(backstory, "A desk robot. "))
        assertEquals(JsonPrimitive(""), SettingsForm.parse(backstory, ""))
        val optional = sections.flatMap { it.fields }.first { it.optional && it.kind == FieldKind.TEXT }
        assertEquals(JsonNull, SettingsForm.parse(optional, " "))
    }

    @Test
    fun `values show as text and patches wrap one setting in its section`() {
        val settings = KitJson.parseToJsonElement(
            """{"phone":{"notify":"away","notify_per_hour":2},"persona":{"traits":["kind","curious"]},"cloud":{"stream":true,"monthly_cap_usd":40}}""",
        ).jsonObject
        assertEquals("away", SettingsForm.text(SettingsForm.value(settings, "phone", "notify")))
        assertEquals("kind\ncurious", SettingsForm.text(SettingsForm.value(settings, "persona", "traits")))
        assertEquals(listOf("kind", "curious"), SettingsForm.lines(SettingsForm.value(settings, "persona", "traits")))
        assertEquals("", SettingsForm.text(SettingsForm.value(settings, "phone", "missing")))
        assertTrue(SettingsForm.on(SettingsForm.value(settings, "cloud", "stream")))
        assertEquals(40.0, SettingsForm.number(SettingsForm.value(settings, "cloud", "monthly_cap_usd")))
        assertEquals(
            """{"phone":{"notify":"never"}}""",
            SettingsForm.patch("phone", "notify", JsonPrimitive("never")).toString(),
        )
        assertNotNull(SettingsForm.value(settings, "phone", "notify_per_hour"))
    }
}
