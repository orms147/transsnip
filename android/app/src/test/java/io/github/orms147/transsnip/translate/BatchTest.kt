package io.github.orms147.transsnip.translate

import io.github.orms147.transsnip.screen.Ocr
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BatchTest {

    @Test
    fun parsesNumberedLines() {
        val m = BatchTranslator.parse("[1] Trọng tài: Không điểm\n[2] Tôi còn cơ hội thứ hai\nghi chú lạc\n3. Điểm tuyệt đối")
        assertEquals(mapOf(0 to "Trọng tài: Không điểm", 1 to "Tôi còn cơ hội thứ hai", 2 to "Điểm tuyệt đối"), m)
    }

    @Test
    fun streamsLinesAsTheyComplete() {
        val reply = "[1] Trọng tài\n[2] Tuyển thủ\n[3] Điểm tối đa"
        val seen = mutableListOf<Int>()
        val fake = object : Completer {
            override fun complete(system: String, user: String) = reply
            override fun stream(system: String, user: String, onText: (String) -> Unit): String {
                // chunked like SSE deltas
                reply.chunked(5).runningReduce { a, b -> a + b }.forEach(onText)
                return reply
            }
        }
        val out = arrayOfNulls<String>(3)
        BatchTranslator(fake).translate(listOf("裁判", "选手", "满分"), "vi") { i, t -> out[i] = t; seen += i }
        assertEquals(listOf("Trọng tài", "Tuyển thủ", "Điểm tối đa"), out.toList())
        assertEquals(listOf(0, 1, 2), seen)
    }

    @Test
    fun missingLineIsRetriedAlone() {
        val fake = Completer { _, user ->
            if (user.contains("[1]")) "[1] Trọng tài" else "Tuyển thủ"
        }
        val out = arrayOfNulls<String>(2)
        BatchTranslator(fake).translate(listOf("裁判", "选手"), "vi") { i, t -> out[i] = t }
        assertEquals(listOf("Trọng tài", "Tuyển thủ"), out.toList())
    }

    @Test
    fun skipsWhatNeedsNoTranslation() {
        assertFalse(Prompts.needsTranslation("12:18", "vi"))
        assertFalse(Prompts.needsTranslation("962", "vi"))
        assertFalse(Prompts.needsTranslation("Trọng tài: Điểm tuyệt đối", "vi"))
        assertTrue(Prompts.needsTranslation("裁判：零分", "vi"))
        assertTrue(Prompts.needsTranslation("Translate", "vi"))
        assertTrue(Prompts.needsTranslation("好", "vi"))
        assertFalse(Prompts.needsTranslation("Translate", "en"))
    }

    @Test
    fun hyMt2StartsWithTheMinimalPrompt() {
        val systems = mutableListOf<String>()
        val fake = Completer { s, _ -> systems += s; "Hát hay" }
        Translator.forModel(fake, "tencent/hy-mt2-30b-a3b").translate("让你唱歌爆炸好听", "vi")
        assertEquals(1, systems.size)
        assertFalse("Output ONLY" in systems[0])
    }

    @Test
    fun ocrLinesJoinPerScript() {
        assertEquals("我还有第二次机会", Ocr.joinLines(listOf("我还有第", "二次机会")))
        assertEquals("the second chance", Ocr.joinLines(listOf("the second", "chance")))
    }
}
