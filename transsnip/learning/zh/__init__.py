"""Chinese study aids: segmentation, pinyin, Hán-Việt, dictionary, strokes.

Everything here is offline. Heavy pieces (jieba's dictionary, the SQLite
dictionary, stroke data) load lazily on first use — `warm_up()` pre-loads
them off the GUI thread so the first Chinese snip isn't slower than the rest.
"""
