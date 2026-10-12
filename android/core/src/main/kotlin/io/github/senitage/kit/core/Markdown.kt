package io.github.senitage.kit.core

/**
 * Just enough markdown for Kit's replies and their written detail: paragraphs,
 * headings, lists, quotes, code blocks, and bold, italic, code and links inside
 * a line. The app turns these into styled text.
 */
object Markdown {
    sealed interface Inline {
        data class Text(val text: String) : Inline

        data class Bold(val parts: List<Inline>) : Inline

        data class Italic(val parts: List<Inline>) : Inline

        data class Code(val text: String) : Inline

        data class Link(val text: String, val url: String) : Inline
    }

    sealed interface Block {
        data class Paragraph(val parts: List<Inline>) : Block

        data class Heading(val level: Int, val parts: List<Inline>) : Block

        data class Item(val marker: String, val depth: Int, val parts: List<Inline>) : Block

        data class Quote(val parts: List<Inline>) : Block

        data class Code(val text: String, val language: String) : Block
    }

    private val BULLET = Regex("^(\\s*)[-*+]\\s+(.*)$")
    private val NUMBERED = Regex("^(\\s*)(\\d{1,3})[.)]\\s+(.*)$")
    private val HEADING = Regex("^(#{1,6})\\s+(.*)$")
    private val URL = Regex("https?://[^\\s<>()]+[^\\s<>().,;:!?'\"]")

    fun blocks(text: String): List<Block> {
        val out = mutableListOf<Block>()
        val paragraph = mutableListOf<String>()
        fun flush() {
            if (paragraph.isNotEmpty()) {
                out += Block.Paragraph(inline(paragraph.joinToString("\n")))
                paragraph.clear()
            }
        }
        val lines = text.replace("\r\n", "\n").split('\n')
        var i = 0
        while (i < lines.size) {
            val line = lines[i]
            val trimmed = line.trim()
            if (trimmed.startsWith("```")) {
                flush()
                val language = trimmed.removePrefix("```").trim()
                val code = mutableListOf<String>()
                i++
                while (i < lines.size && !lines[i].trim().startsWith("```")) {
                    code += lines[i]
                    i++
                }
                out += Block.Code(code.joinToString("\n"), language)
                i++
                continue
            }
            val heading = HEADING.matchEntire(trimmed)
            val bullet = BULLET.matchEntire(line)
            val numbered = NUMBERED.matchEntire(line)
            when {
                trimmed.isEmpty() -> flush()
                heading != null -> {
                    flush()
                    out += Block.Heading(heading.groupValues[1].length, inline(heading.groupValues[2]))
                }
                bullet != null -> {
                    flush()
                    out += Block.Item("•", depth(bullet.groupValues[1]), inline(bullet.groupValues[2]))
                }
                numbered != null -> {
                    flush()
                    out += Block.Item("${numbered.groupValues[2]}.", depth(numbered.groupValues[1]), inline(numbered.groupValues[3]))
                }
                trimmed.startsWith(">") -> {
                    flush()
                    out += Block.Quote(inline(trimmed.removePrefix(">").trim()))
                }
                else -> paragraph += line
            }
            i++
        }
        flush()
        return out
    }

    private fun depth(indent: String): Int = indent.replace("\t", "    ").length / 2

    fun inline(text: String): List<Inline> {
        val out = mutableListOf<Inline>()
        val plain = StringBuilder()
        fun flush() {
            if (plain.isNotEmpty()) {
                out += links(plain.toString())
                plain.clear()
            }
        }
        var i = 0
        while (i < text.length) {
            val c = text[i]
            when {
                c == '\\' && i + 1 < text.length && text[i + 1] in "\\`*_[]()#" -> {
                    plain.append(text[i + 1])
                    i += 2
                    continue
                }
                c == '`' -> {
                    val end = text.indexOf('`', i + 1)
                    if (end > i) {
                        flush()
                        out += Inline.Code(text.substring(i + 1, end))
                        i = end + 1
                        continue
                    }
                }
                text.startsWith("**", i) || text.startsWith("__", i) -> {
                    val mark = text.substring(i, i + 2)
                    val end = text.indexOf(mark, i + 2)
                    if (end > i + 2) {
                        flush()
                        out += Inline.Bold(inline(text.substring(i + 2, end)))
                        i = end + 2
                        continue
                    }
                }
                (c == '*' || c == '_') && i + 1 < text.length && !text[i + 1].isWhitespace() &&
                    (c == '*' || i == 0 || !text[i - 1].isLetterOrDigit()) -> {
                    val end = closing(text, c, i + 1)
                    if (end > i + 1) {
                        flush()
                        out += Inline.Italic(inline(text.substring(i + 1, end)))
                        i = end + 1
                        continue
                    }
                }
                c == '[' -> {
                    val close = text.indexOf("](", i + 1)
                    val end = if (close > i) text.indexOf(')', close + 2) else -1
                    if (close > i && end > close) {
                        val url = text.substring(close + 2, end).trim()
                        if (url.startsWith("http://") || url.startsWith("https://")) {
                            flush()
                            out += Inline.Link(text.substring(i + 1, close), url)
                            i = end + 1
                            continue
                        }
                    }
                }
            }
            plain.append(c)
            i++
        }
        flush()
        return out
    }

    /** Where a single `*` or `_` emphasis closes, or -1. */
    private fun closing(text: String, mark: Char, from: Int): Int {
        var j = from
        while (j < text.length) {
            val at = text.indexOf(mark, j)
            if (at < 0) return -1
            val doubled = at + 1 < text.length && text[at + 1] == mark
            val before = text[at - 1]
            val after = text.getOrNull(at + 1)
            val wordEnd = mark == '*' || after == null || !after.isLetterOrDigit()
            if (!doubled && !before.isWhitespace() && wordEnd) return at
            j = at + if (doubled) 2 else 1
        }
        return -1
    }

    /** Bare web addresses in plain text become links. */
    private fun links(text: String): List<Inline> {
        val out = mutableListOf<Inline>()
        var last = 0
        for (m in URL.findAll(text)) {
            if (m.range.first > last) out += Inline.Text(text.substring(last, m.range.first))
            out += Inline.Link(m.value, m.value)
            last = m.range.last + 1
        }
        if (last < text.length) out += Inline.Text(text.substring(last))
        return out
    }

    /** The words without markup, for a notification or a copy. */
    fun plain(parts: List<Inline>): String = parts.joinToString("") {
        when (it) {
            is Inline.Text -> it.text
            is Inline.Bold -> plain(it.parts)
            is Inline.Italic -> plain(it.parts)
            is Inline.Code -> it.text
            is Inline.Link -> it.text
        }
    }
}
