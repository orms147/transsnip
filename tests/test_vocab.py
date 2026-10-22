from transsnip.learning.vocab import VocabEntry, VocabStore, schedule

DAY = 86_400


def test_sm2_intervals_grow_and_lapse_resets():
    e = VocabEntry("实习")
    e = schedule(e, "good", now=0)
    assert e.interval_days == 1 and e.due_at == DAY
    e = schedule(e, "good", now=DAY)
    assert e.interval_days == 3
    e = schedule(e, "good", now=4 * DAY)
    assert e.interval_days == 7.5               # 3 × ease 2.5
    lapsed = schedule(e, "again", now=12 * DAY)
    assert lapsed.reps == 0 and lapsed.lapses == 1 and lapsed.ease < e.ease
    assert lapsed.due_at == 12 * DAY + 600      # back in this session


def test_easy_jumps_further_than_hard():
    base = schedule(schedule(VocabEntry("x"), "good", 0), "good", DAY)
    easy = schedule(base, "easy", 4 * DAY).interval_days
    assert easy > schedule(base, "hard", 4 * DAY).interval_days


def test_store_add_due_answer_export(tmp_path):
    s = VocabStore(tmp_path / "v.sqlite3")
    assert s.add(VocabEntry("实习", pinyin="shíxí", hanviet="thực tập", meaning="thực tập",
                            example="实习不久", example_vi="Thực tập chưa lâu"))
    assert not s.add(VocabEntry("实习", meaning="ignored"))     # keeps history, no dup
    assert s.contains("实习") and len(s.all()) == 1
    (due,) = s.due()
    after = s.answer(due, "good")
    assert s.due(now=after.due_at - 1) == []
    out = tmp_path / "anki.txt"
    assert s.export_anki_tsv(out) == 1
    text = out.read_text(encoding="utf-8")
    assert text.startswith("#separator:tab") and "实习\t" in text and "thực tập" in text
    s.remove("实习")
    assert s.all() == []
