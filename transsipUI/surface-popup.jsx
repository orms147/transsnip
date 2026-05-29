// surface-popup.jsx — FloatingPopup redesign
// One component, four states: learning (EN+IPA furigana) · translated (clean)
// · loading · error. Reads CSS vars from a theme ancestor.

const POPUP_W = 460;

// IPA sample data — keyed off the English source so each render is
// deterministic. Real Qt app pulls these from CMU dict via eng-to-ipa.
const IPA_MAP = {
  The: "ðə", quick: "kwɪk", brown: "braʊn", fox: "fɒks",
  jumps: "dʒʌmps", over: "ˈoʊvər", the: "ðə", lazy: "ˈleɪzi",
  dog: "dɔɡ",
};

function tokenizeForIPA(text) {
  // Split on whitespace, preserve spaces as their own tokens so the source
  // and IPA rows can use matching token positions (em-dash placeholder for
  // words with no known IPA — same trick as the Python renderer).
  return text.split(/(\s+)/).filter(Boolean).map((tok, i) => {
    if (/^\s+$/.test(tok)) return { type: "space", t: tok, k: i };
    // Strip trailing punctuation for IPA lookup but keep it on display.
    const m = tok.match(/^([^\s.,!?;:]*)(.*)$/);
    const word = m ? m[1] : tok;
    const trail = m ? m[2] : "";
    const ipa = IPA_MAP[word] || IPA_MAP[word.toLowerCase()];
    return { type: "word", t: tok, word, trail, ipa, k: i };
  });
}

function LangChip({ code, name }) {
  return (
    <div className="lang-chip">
      <span className="lang-chip-code">{code}</span>
      {name ? <span className="lang-chip-name">{name}</span> : null}
    </div>
  );
}

function PopupHeader({ status, hasVoice, provider, cached }) {
  return (
    <div className="popup-header">
      <div className="popup-brand">
        <AppGlyph size={14} />
        <span className="popup-brand-name">TransSnip</span>
      </div>

      <div className="popup-drag" aria-hidden />

      <div className="popup-status-area">
        {status === "ocr" && (
          <div className="popup-status">
            <Icon name="spinner" size={11} />
            <span>Đang OCR…</span>
          </div>
        )}
        {status === "translating" && (
          <div className="popup-status">
            <Icon name="spinner" size={11} />
            <span>Đang dịch…</span>
          </div>
        )}
        {status === "done" && (
          <div className="popup-status popup-status--done">
            <span className="popup-provider">{provider}</span>
            {cached && (
              <span className="popup-cache">
                <Icon name="cached" size={10} />
                cached
              </span>
            )}
          </div>
        )}
        {status === "error" && (
          <div className="popup-status popup-status--error">
            <Icon name="alert" size={11} />
            <span>error</span>
          </div>
        )}
      </div>

      <div className="popup-actions">
        {hasVoice && (
          <button className="popup-iconbtn popup-iconbtn--accent" title="Play pronunciation">
            <Icon name="volume" size={14} />
          </button>
        )}
        <button className="popup-iconbtn" title="Copy translation">
          <Icon name="copy" size={14} />
        </button>
        <button className="popup-iconbtn" title="Pin (always on top)">
          <Icon name="pin" size={14} />
        </button>
        <button className="popup-iconbtn" title="Settings">
          <Icon name="settings" size={14} />
        </button>
        <div className="popup-divider" />
        <button className="popup-iconbtn popup-iconbtn--close" title="Close (Esc)">
          <Icon name="close" size={14} />
        </button>
      </div>
    </div>
  );
}

function PhoneticSource({ text }) {
  const tokens = tokenizeForIPA(text);
  return (
    <div className="phonetic-source">
      <div className="phonetic-row phonetic-row--words">
        {tokens.map((tok) => {
          if (tok.type === "space") return <span key={tok.k}>{tok.t}</span>;
          return (
            <a key={tok.k} className="phonetic-word" href={`#speak:${tok.word}`} title={`Phát âm: ${tok.word}`}>
              {tok.t}
            </a>
          );
        })}
      </div>
      <div className="phonetic-row phonetic-row--ipa">
        {tokens.map((tok) => {
          if (tok.type === "space") return <span key={tok.k}>{tok.t}</span>;
          if (tok.ipa) {
            return (
              <a key={tok.k} className="phonetic-ipa" href={`#speak:${tok.word}`}>
                /{tok.ipa}/{tok.trail ? <span className="phonetic-trail">{tok.trail}</span> : null}
              </a>
            );
          }
          return (
            <span key={tok.k} className="phonetic-dash">—</span>
          );
        })}
      </div>
    </div>
  );
}

function FloatingPopup({ state = "learning" }) {
  if (state === "loading") {
    return (
      <div className="popup" style={{ width: POPUP_W, minHeight: 180 }}>
        <PopupHeader status="ocr" />
        <div className="popup-body popup-body--loading">
          <div className="popup-skeleton-line" style={{ width: "85%" }} />
          <div className="popup-skeleton-line" style={{ width: "60%" }} />
          <div className="popup-skeleton-line popup-skeleton-line--accent" style={{ width: "75%" }} />
          <div className="popup-skeleton-line popup-skeleton-line--accent" style={{ width: "50%" }} />
        </div>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="popup" style={{ width: POPUP_W }}>
        <PopupHeader status="error" />
        <div className="popup-body">
          <div className="popup-error">
            <div className="popup-error-icon">
              <Icon name="alert" size={18} />
            </div>
            <div className="popup-error-text">
              <div className="popup-error-title">Không thể dịch</div>
              <div className="popup-error-msg">
                <span className="mono">Anthropic API · 429</span> · Rate limit
                exceeded. Đổi provider trong Settings hoặc thử lại sau.
              </div>
              <div className="popup-error-actions">
                <button className="popup-btn-soft">Đổi provider</button>
                <button className="popup-btn-soft">Thử lại</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (state === "ja-vi") {
    return (
      <div className="popup" style={{ width: POPUP_W }}>
        <PopupHeader status="done" provider="gemini · 1.5-flash" cached />
        <div className="popup-body">
          <div className="popup-section">
            <LangChip code="JA" name="日本語" />
            <div className="popup-source popup-source--plain">
              今日は天気がいいですね。散歩に行きましょう。
            </div>
          </div>

          <div className="popup-divider-h" />

          <div className="popup-section">
            <LangChip code="VI" name="Tiếng Việt" />
            <div className="popup-translation">
              Hôm nay thời tiết đẹp nhỉ. Cùng đi dạo nào.
            </div>
          </div>
        </div>
      </div>
    );
  }

  // learning — English source with IPA furigana
  return (
    <div className="popup" style={{ width: POPUP_W }}>
      <PopupHeader status="done" hasVoice provider="claude · sonnet-4" />
      <div className="popup-body">
        <div className="popup-section">
          <div className="popup-section-head">
            <LangChip code="EN" name="English" />
            <span className="popup-learning-tag">Learning mode</span>
          </div>
          <PhoneticSource text="The quick brown fox jumps over the lazy dog." />
        </div>

        <div className="popup-divider-h" />

        <div className="popup-section">
          <LangChip code="VI" name="Tiếng Việt" />
          <div className="popup-translation">
            Con cáo nâu nhanh nhẹn nhảy qua con chó lười biếng.
          </div>
        </div>

        <div className="popup-footer-hint">
          <kbd>Esc</kbd> đóng · <kbd>Ctrl</kbd>+<kbd>C</kbd> copy translation · click vào từ để nghe phát âm
        </div>
      </div>
    </div>
  );
}

// Tiny app glyph used in headers — same composition as the full app icon
// but at chrome-size. Crop marks + chevron indicating translation direction.
function AppGlyph({ size = 14, accent }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      style={{ flexShrink: 0 }}
    >
      <path
        d="M2.5 4.5V3a.7.7 0 0 1 .7-.7H4.5M11.5 2.3H13a.7.7 0 0 1 .7.7v1.5M13.7 11.5V13a.7.7 0 0 1-.7.7h-1.5M4.5 13.7H3a.7.7 0 0 1-.7-.7v-1.5"
        stroke={accent || "var(--accent)"}
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M6 8h4M8.5 6.5L10 8l-1.5 1.5"
        stroke="var(--text-1)"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

Object.assign(window, { FloatingPopup, AppGlyph, LangChip });

// ── Pinned compact popup (280×80) ─────────────────────────────────────────
function PinnedPopup({ state = "filled" }) {
  if (state === "empty") {
    return (
      <div className="pinned pinned--empty">
        <AppGlyph size={14} />
        <div className="pinned-empty-text">
          <span className="pinned-empty-title">TransSnip ready</span>
          <span className="pinned-empty-hint"><kbd>Alt</kbd>+<kbd>T</kbd> để dịch</span>
        </div>
        <span className="pinned-dot" title="Ready" />
      </div>
    );
  }
  const hover = state === "hover";
  return (
    <div className={`pinned ${hover ? "is-hover" : ""}`}>
      <div className="pinned-left">
        <AppGlyph size={14} />
        <span className="pinned-chip"><span className="mono">JA</span><Icon name="chevron-right" size={8} /><span className="mono">VI</span></span>
      </div>
      <div className="pinned-text">Hôm nay thời tiết đẹp nhỉ. Cùng đi dạo nào.</div>
      <div className="pinned-actions">
        <button className="pinned-iconbtn" title="Unpin"><Icon name="pin" size={11} /></button>
        <button className="pinned-iconbtn pinned-iconbtn--close" title="Close"><Icon name="close" size={11} /></button>
      </div>
      {hover ? <div className="pinned-expand-hint">Click để mở lại</div> : null}
    </div>
  );
}

// Transition diagram: full popup → pinned → click to expand
function PinnedTransition() {
  return (
    <div className="pintrans">
      <div className="pintrans-frame">
        <div className="pintrans-mini pintrans-mini--full">
          <div className="pintrans-mini-bar"><span /><span className="pintrans-mini-bar-grow" /><span className="pintrans-mini-pin" /></div>
          <div className="pintrans-mini-body">
            <span className="pintrans-mini-line" style={{ width: "70%" }} />
            <span className="pintrans-mini-line pintrans-mini-line--accent" style={{ width: "90%" }} />
            <span className="pintrans-mini-line pintrans-mini-line--accent" style={{ width: "60%" }} />
          </div>
        </div>
        <div className="pintrans-cap">Popup đầy đủ</div>
      </div>

      <div className="pintrans-arrow"><Icon name="arrow" size={18} /><span className="pintrans-arrow-label">Pin</span></div>

      <div className="pintrans-frame">
        <div className="pintrans-mini pintrans-mini--pinned">
          <span className="pintrans-mini-glyph" />
          <span className="pintrans-mini-line" style={{ flex: 1, width: "auto" }} />
        </div>
        <div className="pintrans-cap">Thu nhỏ · góc phải</div>
      </div>

      <div className="pintrans-arrow"><Icon name="arrow" size={18} /><span className="pintrans-arrow-label">Click</span></div>

      <div className="pintrans-frame">
        <div className="pintrans-mini pintrans-mini--full is-restore">
          <div className="pintrans-mini-bar"><span /><span className="pintrans-mini-bar-grow" /><span className="pintrans-mini-pin" /></div>
          <div className="pintrans-mini-body">
            <span className="pintrans-mini-line" style={{ width: "70%" }} />
            <span className="pintrans-mini-line pintrans-mini-line--accent" style={{ width: "90%" }} />
            <span className="pintrans-mini-line pintrans-mini-line--accent" style={{ width: "60%" }} />
          </div>
        </div>
        <div className="pintrans-cap">Mở lại đầy đủ</div>
      </div>
    </div>
  );
}

Object.assign(window, { PinnedPopup, PinnedTransition });
