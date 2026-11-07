package io.github.orms147.transsnip.translate

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TranslatorTest {

    private class FakeCompleter(private val reply: (system: String) -> String) : Completer {
        val systems = mutableListOf<String>()
        override fun complete(system: String, user: String): String {
            systems += system
            return reply(system)
        }
    }

    @Test
    fun detectsScripts() {
        assertEquals("zh-Hans", LangDetect.detect("让你唱歌爆炸好听"))
        assertEquals("ja", LangDetect.detect("これはテストです"))
        assertEquals("ko", LangDetect.detect("안녕하세요"))
        assertEquals("en", LangDetect.detect("Hello world"))
        // A Vietnamese sentence keeping one Chinese name is still Latin text.
        assertEquals("en", LangDetect.detect("Công ty Tencent (腾讯) vừa phát hành mô hình mới"))
    }

    @Test
    fun promptMatchesDesktop() {
        val p = Prompts.systemPrompt("vi", "zh-Hans")
        assertTrue(p.startsWith("You are a professional translator. Translate the user's text into Vietnamese."))
        assertTrue(p.endsWith("The source is Simplified Chinese."))
        assertEquals("Translate into Vietnamese:\n\nhi", Prompts.userTurn("hi", "vi"))
    }

    @Test
    fun emptyReplyFallsBackToMinimalPrompt() {
        val fake = FakeCompleter { if ("Output ONLY" in it) "" else "Khiến bạn hát hay đến nổ tung!" }
        val r = Translator(fake).translate("让你唱歌爆炸好听", "vi")
        assertEquals("Khiến bạn hát hay đến nổ tung!", r.translation)
        assertEquals("zh-Hans", r.sourceLang)
        assertFalse("Output ONLY" in fake.systems[1])
    }

    @Test
    fun untranslatedReplyIsRetried() {
        var n = 0
        val fake = FakeCompleter { if (n++ == 0) "让你唱歌爆炸好听" else "Hát hay" }
        assertEquals("Hát hay", Translator(fake).translate("让你唱歌爆炸好听", "vi").translation)
    }

    @Test(expected = TranslationException::class)
    fun emptyFromBothPromptsFails() {
        Translator(FakeCompleter { "" }).translate("你好", "vi")
    }
}
