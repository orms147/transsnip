package io.github.orms147.transsnip.zh

import org.junit.Assert.assertEquals
import org.junit.Test

class ZhTest {

    @Test
    fun marksTones() {
        assertEquals("zhǎng", Pinyin.mark("zhang3"))
        assertEquals("nǚ", Pinyin.mark("nv3"))
        assertEquals("lǜ", Pinyin.mark("lv4"))
        assertEquals("dōu", Pinyin.mark("dou1"))
        assertEquals("guǐ", Pinyin.mark("gui3"))
        assertEquals("de", Pinyin.mark("de5"))
    }

    @Test
    fun syllableTone() {
        assertEquals(3, Syllable('长', "zhang3").tone)
        assertEquals(5, Syllable('的', "de5").tone)
        assertEquals(0, Syllable('，', "").tone)
    }

    @Test
    fun sentenceAtPicksTheWordsSentence() {
        val t = "美国时间10月21日，公司发布了模型。CEO写道：从零开始！他向Wired解释了原因"
        val i = t.indexOf("从零")
        assertEquals("CEO写道：从零开始！", ZhDict.sentenceAt(t, i, i + 2))
        assertEquals("美国时间10月21日，公司发布了模型。", ZhDict.sentenceAt(t, 0, 2))
        val w = t.indexOf("Wired")
        assertEquals("他向Wired解释了原因", ZhDict.sentenceAt(t, w, w + 5))
    }

    @Test
    fun parsesUsageJsonInsideFences() {
        val raw = """```json
            {"meaning_here": "thời gian", "explanation": "Danh từ.",
             "grammar": ["花时间 + V"], "examples": [{"zh": "我没有时间。", "pinyin": "Wǒ méiyǒu shíjiān.", "vi": "Tôi không có thời gian."}],
             "collocations": ["时间表"], "confusables": [{"word": "时候", "difference": "thời điểm"}]}
            ```"""
        val n = Usage.parse(raw)
        assertEquals("thời gian", n.meaningHere)
        assertEquals("我没有时间。", n.examples.single().first)
        assertEquals("时候" to "thời điểm", n.confusables.single())
    }
}
