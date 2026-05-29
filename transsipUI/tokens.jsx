// tokens.jsx — themes (CSS vars) + line-stroke Icon set + shared helpers
// All surfaces consume CSS custom properties so swapping `t-cobalt` / `t-ember`
// / `t-mint` on an ancestor reskins the whole tree.

const { useState, useEffect, useRef } = React;

// ── Theme registry ───────────────────────────────────────────────────────
// Cobalt is the chosen direction. Two modes: dark (default) + light.
const THEMES = [
  {
    id: "cobalt",
    name: "Cobalt · Dark",
    blurb: "Indigo accent · cool neutral · Inter — primary mode",
  },
  {
    id: "cobalt-light",
    name: "Cobalt · Light",
    blurb: "Same palette inverted for daytime / high-ambient setups",
  },
];

// ── Icon set ─────────────────────────────────────────────────────────────
// Line-stroke icons, 16×16 viewBox, 1.5px stroke, round caps & joins.
// Replaces every emoji in the original Qt code (⚙ 🔊 ⧉ × etc).
const ICON_PATHS = {
  settings: (
    <g>
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.5v1.7M8 12.8v1.7M2.2 8h1.7M12.1 8h1.7M3.9 3.9l1.2 1.2M10.9 10.9l1.2 1.2M3.9 12.1l1.2-1.2M10.9 5.1l1.2-1.2" />
    </g>
  ),
  volume: (
    <g>
      <path d="M3 6h2l3-2.5v9L5 10H3z" />
      <path d="M10.5 5.5a3.5 3.5 0 0 1 0 5" />
      <path d="M12.5 3.5a6 6 0 0 1 0 9" />
    </g>
  ),
  "volume-mute": (
    <g>
      <path d="M3 6h2l3-2.5v9L5 10H3z" />
      <path d="M10 6l3 3M13 6l-3 3" />
    </g>
  ),
  copy: (
    <g>
      <rect x="5" y="5" width="8" height="8" rx="1.3" />
      <path d="M3 11V4a1.3 1.3 0 0 1 1.3-1.3H11" />
    </g>
  ),
  check: <path d="M3 8.5l3 3 7-7" />,
  close: <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />,
  pin: (
    <g>
      <path d="M8 1.8l-2 4-3 1 3.5 3.5L3 14l4.2-3.5L10.7 14l-1-3 3.5-3.5-3-1z" />
    </g>
  ),
  chevron: <path d="M4 6l4 4 4-4" />,
  "chevron-right": <path d="M6 4l4 4-4 4" />,
  refresh: (
    <g>
      <path d="M13.5 8a5.5 5.5 0 1 1-1.7-4" />
      <path d="M13.5 2v3.5h-3.5" />
    </g>
  ),
  plus: <path d="M8 3v10M3 8h10" />,
  minus: <path d="M3 8h10" />,
  trash: (
    <g>
      <path d="M2.5 4h11M5.5 4V2.7A.7.7 0 0 1 6.2 2h3.6a.7.7 0 0 1 .7.7V4M4 4l.7 9a.7.7 0 0 0 .7.7h5.2a.7.7 0 0 0 .7-.7L12 4" />
      <path d="M6.5 7v4M9.5 7v4" />
    </g>
  ),
  crop: (
    <g>
      <path d="M4 2v9.3a.7.7 0 0 0 .7.7H14" />
      <path d="M2 4h9.3a.7.7 0 0 1 .7.7V14" />
    </g>
  ),
  fullscreen: (
    <g>
      <path d="M2 5V3a1 1 0 0 1 1-1h2" />
      <path d="M14 5V3a1 1 0 0 0-1-1h-2" />
      <path d="M2 11v2a1 1 0 0 0 1 1h2" />
      <path d="M14 11v2a1 1 0 0 1-1 1h-2" />
    </g>
  ),
  subtitles: (
    <g>
      <rect x="1.8" y="3.5" width="12.4" height="9" rx="1.3" />
      <path d="M4 8h3M8 8h4M4 10.5h2M7 10.5h5" />
    </g>
  ),
  keyboard: (
    <g>
      <rect x="1.5" y="4" width="13" height="8" rx="1.3" />
      <path d="M4 7h.01M6.5 7h.01M9 7h.01M11.5 7h.01M4 9.5h.01M6.5 9.5h3M12 9.5h.01" />
    </g>
  ),
  globe: (
    <g>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M2 8h12M8 1.8c2 2 2 10.4 0 12.4M8 1.8c-2 2-2 10.4 0 12.4" />
    </g>
  ),
  info: (
    <g>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M8 7.5v3.5M8 5.2v.3" />
    </g>
  ),
  alert: (
    <g>
      <path d="M8 2L1.5 13.5h13z" />
      <path d="M8 6.5v3M8 11.5v.3" />
    </g>
  ),
  power: (
    <g>
      <path d="M5 3.5a5.5 5.5 0 1 0 6 0" />
      <path d="M8 1.5v6" />
    </g>
  ),
  search: (
    <g>
      <circle cx="7" cy="7" r="4.2" />
      <path d="M10 10l3.2 3.2" />
    </g>
  ),
  edit: (
    <g>
      <path d="M11.5 2.5l2 2L5 13l-3 1 1-3z" />
    </g>
  ),
  spinner: null, // rendered separately as animated SVG
  eye: (
    <g>
      <path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" />
      <circle cx="8" cy="8" r="1.8" />
    </g>
  ),
  cached: (
    <g>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M5 8l2.2 2.2L11.5 6" />
    </g>
  ),
  brain: (
    <g>
      <path d="M5.5 3.5A2 2 0 0 0 4 7v2a2 2 0 0 0 1.5 2.5v1A1.5 1.5 0 0 0 7 14V3a1.5 1.5 0 0 0-1.5-1.5A2 2 0 0 0 5.5 3.5z" />
      <path d="M10.5 3.5A2 2 0 0 1 12 7v2a2 2 0 0 1-1.5 2.5v1A1.5 1.5 0 0 1 9 14V3a1.5 1.5 0 0 1 1.5-1.5A2 2 0 0 1 10.5 3.5z" />
    </g>
  ),
  link: (
    <g>
      <path d="M6.5 9.5l3-3M7 4.5l.8-.8a2.5 2.5 0 0 1 3.5 3.5l-.8.8M9 11.5l-.8.8a2.5 2.5 0 0 1-3.5-3.5l.8-.8" />
    </g>
  ),
  "external": (
    <g>
      <path d="M9 3h4v4M13 3l-6 6" />
      <path d="M11 9.5V12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h2.5" />
    </g>
  ),
  mail: (
    <g>
      <rect x="2" y="3.5" width="12" height="9" rx="1.3" />
      <path d="M2.5 4.5l5.5 4 5.5-4" />
    </g>
  ),
  clipboard: (
    <g>
      <rect x="3.5" y="3" width="9" height="11" rx="1.2" />
      <path d="M6 3V2.3A.8.8 0 0 1 6.8 1.5h2.4a.8.8 0 0 1 .8.8V3" />
    </g>
  ),
  play: <path d="M5 3.5l7 4.5-7 4.5z" />,
  arrow: <path d="M2.5 8h11M9.5 4l4 4-4 4" />,
  monitor: (
    <g>
      <rect x="1.8" y="2.8" width="12.4" height="8.4" rx="1.2" />
      <path d="M5.5 14h5M8 11.2V14" />
    </g>
  ),
  download: (
    <g>
      <path d="M8 2v8M5 7l3 3 3-3" />
      <path d="M2.5 12.5h11" />
    </g>
  ),
  user: (
    <g>
      <circle cx="8" cy="5.5" r="2.8" />
      <path d="M2.8 13.5a5.2 5.2 0 0 1 10.4 0" />
    </g>
  ),
};

function Icon({ name, size = 16, stroke = 1.5, color, style, className = "" }) {
  if (name === "spinner") {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 16 16"
        fill="none"
        style={{ color: color || "currentColor", ...style }}
        className={className}
      >
        <circle
          cx="8"
          cy="8"
          r="6"
          stroke="currentColor"
          strokeWidth={stroke}
          strokeOpacity="0.18"
        />
        <path
          d="M14 8a6 6 0 0 0-6-6"
          stroke="currentColor"
          strokeWidth={stroke}
          strokeLinecap="round"
          style={{ transformOrigin: "8px 8px", animation: "ts-spin 0.9s linear infinite" }}
        />
      </svg>
    );
  }
  const path = ICON_PATHS[name];
  if (!path) return null;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ color: color || "currentColor", flexShrink: 0, ...style }}
      className={className}
    >
      {path}
    </svg>
  );
}

// ── Mock screen content for region/overlay backdrops ─────────────────────
// A realistic-looking dark "article being read" so the overlays land on
// believable source text. Pure CSS — no images.

function MockBrowserBackdrop({ children }) {
  return (
    <div className="mock-browser">
      <div className="mock-browser-chrome">
        <div className="mock-traffic">
          <span /><span /><span />
        </div>
        <div className="mock-url">
          <Icon name="globe" size={12} />
          <span>tech-blog.jp/ai-translation-future</span>
        </div>
        <div style={{ width: 56 }} />
      </div>
      <div className="mock-browser-body">
        <article className="mock-article">
          <div className="mock-eyebrow">AI · 機械学習</div>
          <h1 className="mock-h1">AI翻訳の未来について</h1>
          <p className="mock-lede">
            OCRと大規模言語モデルの組み合わせは、画面上のあらゆるテキストを瞬時に
            理解できる新しい体験を生み出している。
          </p>
          <p className="mock-body">
            近年、画像認識と自然言語処理の技術が急速に発展し、スクリーン上の文字を
            リアルタイムで翻訳することが可能になった。これは語学学習者だけでなく、
            ゲーム実況者やマンガ読者にも大きな影響を与えている。
          </p>
          <p className="mock-body">
            特に注目すべきは、文脈を理解した翻訳の精度向上である。
          </p>
        </article>
        {children}
      </div>
    </div>
  );
}

// Export to global scope so other Babel files can use these.
Object.assign(window, { THEMES, Icon, MockBrowserBackdrop });
