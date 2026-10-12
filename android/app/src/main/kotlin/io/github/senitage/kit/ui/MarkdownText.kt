package io.github.senitage.kit.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.senitage.kit.core.Markdown

/** Kit's words with their markdown: bold, lists, code and links you can tap. */
@Composable
fun MarkdownText(text: String, colour: Color, modifier: Modifier = Modifier) {
    val blocks = remember(text) { Markdown.blocks(text) }
    val link = MaterialTheme.colorScheme.primary
    val codeBack = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.08f)
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (block in blocks) {
            when (block) {
                is Markdown.Block.Paragraph -> Text(styled(block.parts, link, codeBack), color = colour)
                is Markdown.Block.Heading -> Text(
                    styled(block.parts, link, codeBack),
                    color = colour,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = if (block.level <= 2) 17.sp else 15.sp,
                )
                is Markdown.Block.Item -> Row(Modifier.padding(start = (12 * block.depth).dp)) {
                    Text(block.marker, color = colour, modifier = Modifier.width(if (block.marker == "•") 14.dp else 22.dp))
                    Text(styled(block.parts, link, codeBack), color = colour)
                }
                is Markdown.Block.Quote -> Text(
                    styled(block.parts, link, codeBack),
                    color = colour.copy(alpha = 0.8f),
                    fontStyle = FontStyle.Italic,
                    modifier = Modifier.padding(start = 8.dp),
                )
                is Markdown.Block.Code -> Text(
                    block.text,
                    color = colour,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 13.sp,
                    softWrap = false,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(8.dp))
                        .background(codeBack)
                        .horizontalScroll(rememberScrollState())
                        .padding(10.dp),
                )
            }
        }
    }
}

private fun styled(parts: List<Markdown.Inline>, link: Color, codeBack: Color): AnnotatedString = buildAnnotatedString {
    fun add(items: List<Markdown.Inline>) {
        for (part in items) {
            when (part) {
                is Markdown.Inline.Text -> append(part.text)
                is Markdown.Inline.Bold -> withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { add(part.parts) }
                is Markdown.Inline.Italic -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { add(part.parts) }
                is Markdown.Inline.Code -> withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = codeBack)) {
                    append(part.text)
                }
                is Markdown.Inline.Link -> withLink(
                    LinkAnnotation.Url(
                        part.url,
                        TextLinkStyles(SpanStyle(color = link, textDecoration = TextDecoration.Underline)),
                    ),
                ) { append(part.text) }
            }
        }
    }
    add(parts)
}
