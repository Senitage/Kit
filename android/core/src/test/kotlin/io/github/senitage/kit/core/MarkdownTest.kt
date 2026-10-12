package io.github.senitage.kit.core

import io.github.senitage.kit.core.Markdown.Block
import io.github.senitage.kit.core.Markdown.Inline
import kotlin.test.Test
import kotlin.test.assertEquals

class MarkdownTest {
    @Test
    fun `inline styles`() {
        assertEquals(
            listOf(Inline.Text("a "), Inline.Bold(listOf(Inline.Text("big"))), Inline.Text(" and "), Inline.Italic(listOf(Inline.Text("small"))), Inline.Text(" "), Inline.Code("x = 1")),
            Markdown.inline("a **big** and *small* `x = 1`"),
        )
        assertEquals(listOf(Inline.Link("the docs", "https://example.com/a")), Markdown.inline("[the docs](https://example.com/a)"))
        assertEquals(
            listOf(Inline.Text("see "), Inline.Link("https://example.com/x", "https://example.com/x"), Inline.Text(".")),
            Markdown.inline("see https://example.com/x."),
        )
        assertEquals(listOf(Inline.Text("snake_case_name stays")), Markdown.inline("snake_case_name stays"))
        assertEquals(listOf(Inline.Text("2 * 3 * 4")), Markdown.inline("2 * 3 * 4"))
    }

    @Test
    fun `blocks`() {
        val text = "# Plan\n\nFirst line\nsecond line\n\n- one\n  - two\n1. three\n> quoted\n```py\nprint(1)\n```"
        val blocks = Markdown.blocks(text)
        assertEquals(Block.Heading(1, listOf(Inline.Text("Plan"))), blocks[0])
        assertEquals(Block.Paragraph(listOf(Inline.Text("First line\nsecond line"))), blocks[1])
        assertEquals(Block.Item("•", 0, listOf(Inline.Text("one"))), blocks[2])
        assertEquals(Block.Item("•", 1, listOf(Inline.Text("two"))), blocks[3])
        assertEquals(Block.Item("1.", 0, listOf(Inline.Text("three"))), blocks[4])
        assertEquals(Block.Quote(listOf(Inline.Text("quoted"))), blocks[5])
        assertEquals(Block.Code("print(1)", "py"), blocks[6])
        assertEquals(7, blocks.size)
    }
}
