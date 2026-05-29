// surface-overlays.jsx — RegionSelector (snipping) + InlineOverlay (fullscreen translate)

function RegionSelector() {
  // Mid-drag mock: tint covers everything except a "hole" around the
  // selected paragraph. Accent border replaces the old yellow #FFC800.
  // Adds: crosshair guides, size readout, dismiss hint.
  const SEL = { left: 92, top: 178, w: 480, h: 78 };
  return (
    <MockBrowserBackdrop>
      <div className="overlay-root" data-mode="region">
        {/* 4-strip tint outside selection */}
        <div className="overlay-tint" style={{ left: 0, top: 0, right: 0, height: SEL.top }} />
        <div className="overlay-tint" style={{ left: 0, top: SEL.top + SEL.h, right: 0, bottom: 0 }} />
        <div className="overlay-tint" style={{ left: 0, top: SEL.top, width: SEL.left, height: SEL.h }} />
        <div className="overlay-tint" style={{ left: SEL.left + SEL.w, top: SEL.top, right: 0, height: SEL.h }} />

        {/* Crosshair guides at active corner */}
        <div className="overlay-guide overlay-guide--h" style={{ top: SEL.top + SEL.h, left: 0, right: 0 }} />
        <div className="overlay-guide overlay-guide--v" style={{ left: SEL.left + SEL.w, top: 0, bottom: 0 }} />

        {/* Selection box */}
        <div
          className="region-box"
          style={{ left: SEL.left, top: SEL.top, width: SEL.w, height: SEL.h }}
        >
          <span className="region-corner region-corner--tl" />
          <span className="region-corner region-corner--tr" />
          <span className="region-corner region-corner--bl" />
          <span className="region-corner region-corner--br" />
        </div>

        {/* Size readout follows cursor at bottom-right of selection */}
        <div
          className="region-readout"
          style={{ left: SEL.left + SEL.w + 8, top: SEL.top + SEL.h + 8 }}
        >
          <span className="mono">{SEL.w} × {SEL.h}</span>
          <span className="region-readout-divider" />
          <span>1.5×</span>
        </div>

        {/* Hint pinned top-center */}
        <div className="region-hint">
          <span className="region-hint-glyph"><AppGlyph size={12} /></span>
          <span>Kéo để chọn vùng cần dịch</span>
          <span className="region-hint-sep" />
          <kbd>Esc</kbd>
          <span className="region-hint-label">huỷ</span>
          <kbd>Enter</kbd>
          <span className="region-hint-label">xác nhận</span>
        </div>
      </div>
    </MockBrowserBackdrop>
  );
}

// ── InlineOverlay (fullscreen translate) ─────────────────────────────────
// Multiple translation boxes pinned over original Japanese text blocks.
// Replaces opaque-black-box style with a subtle accent border + soft backing
// so source remains contextually visible.

function InlineOverlay() {
  // Coordinates are tuned to the mock article paragraphs in the backdrop.
  const blocks = [
    {
      top: 76, left: 92, w: 220, h: 26,
      src: "AI · 機械学習",
      vi: "AI · Machine Learning",
      tag: "eyebrow",
    },
    {
      top: 110, left: 92, w: 480, h: 44,
      src: "AI翻訳の未来について",
      vi: "Về tương lai của dịch máy AI",
      tag: "heading",
    },
    {
      top: 178, left: 92, w: 480, h: 50,
      src: "OCRと大規模言語モデルの組み合わせ…",
      vi: "Sự kết hợp giữa OCR và mô hình ngôn ngữ lớn đang tạo ra một trải nghiệm mới có thể hiểu mọi văn bản trên màn hình ngay lập tức.",
      tag: "lede",
    },
    {
      top: 250, left: 92, w: 480, h: 70,
      src: "近年、画像認識と自然言語処理…",
      vi: "Những năm gần đây, công nghệ nhận dạng hình ảnh và xử lý ngôn ngữ tự nhiên phát triển nhanh chóng, giúp việc dịch văn bản trên màn hình theo thời gian thực trở nên khả thi.",
      tag: "body",
    },
  ];

  return (
    <MockBrowserBackdrop>
      <div className="overlay-root" data-mode="inline">
        <div className="overlay-tint overlay-tint--soft" style={{ inset: 0 }} />

        {/* Floating toolbar — fixed top-right */}
        <div className="overlay-toolbar">
          <div className="overlay-toolbar-brand">
            <AppGlyph size={12} />
            <span>Fullscreen translate</span>
          </div>
          <span className="overlay-toolbar-divider" />
          <div className="overlay-toolbar-chip">
            <span className="mono">JA</span>
            <Icon name="chevron-right" size={10} />
            <span className="mono">VI</span>
          </div>
          <div className="overlay-toolbar-chip overlay-toolbar-chip--muted">
            <span>claude</span>
            <span className="overlay-toolbar-pill">12 blocks</span>
          </div>
          <span className="overlay-toolbar-divider" />
          <button className="overlay-toolbar-btn" title="Toggle source">
            <Icon name="eye" size={12} />
            <span>Source</span>
          </button>
          <button className="overlay-toolbar-btn" title="Refresh">
            <Icon name="refresh" size={12} />
          </button>
          <button className="overlay-toolbar-btn overlay-toolbar-btn--close" title="Close (Esc)">
            <Icon name="close" size={12} />
          </button>
        </div>

        {blocks.map((b, i) => (
          <div
            key={i}
            className={`inline-block inline-block--${b.tag}`}
            style={{ top: b.top, left: b.left, width: b.w, minHeight: b.h }}
          >
            <span className="inline-block-num">{i + 1}</span>
            <span className="inline-block-text">{b.vi}</span>
          </div>
        ))}
      </div>
    </MockBrowserBackdrop>
  );
}

Object.assign(window, { RegionSelector, InlineOverlay });
