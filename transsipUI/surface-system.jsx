// surface-system.jsx — Tray menu · Toast notification · App icon set

function TrayMenu() {
  const items = [
    { kind: "header" },
    { kind: "item", icon: "crop", label: "Region translate", kbd: ["Alt", "T"] },
    { kind: "item", icon: "fullscreen", label: "Fullscreen translate", kbd: ["Alt", "F"] },
    {
      kind: "item",
      icon: "subtitles",
      label: "Video subtitle",
      kbd: ["Alt", "V"],
      muted: true,
      tag: "Phase 2",
    },
    { kind: "sep" },
    { kind: "item", icon: "globe", label: "Provider", value: "claude · sonnet-4", caret: true },
    { kind: "item", icon: "brain", label: "Preset", value: "gaming", caret: true },
    { kind: "sep" },
    { kind: "item", icon: "settings", label: "Settings…", kbd: ["Ctrl", ","] },
    { kind: "item", icon: "info", label: "About TransSnip" },
    { kind: "sep" },
    { kind: "item", icon: "power", label: "Quit", danger: true },
  ];
  return (
    <div className="tray-context">
      <div className="tray-taskbar" aria-hidden>
        <div className="tray-taskbar-spacer" />
        <div className="tray-taskbar-icons">
          <span className="tray-taskbar-icon" />
          <span className="tray-taskbar-icon" />
          <span className="tray-taskbar-icon tray-taskbar-icon--active">
            <AppGlyph size={11} />
          </span>
          <span className="tray-taskbar-icon" />
          <span className="tray-taskbar-time mono">14:32</span>
        </div>
      </div>

      <div className="tray-menu">
        {items.map((item, i) => {
          if (item.kind === "sep") return <div key={i} className="tray-sep" />;
          if (item.kind === "header") {
            return (
              <div key={i} className="tray-header">
                <AppGlyph size={14} />
                <div className="tray-header-text">
                  <div className="tray-header-name">TransSnip</div>
                  <div className="tray-header-desc">JA <Icon name="chevron-right" size={9} /> VI · claude</div>
                </div>
                <div className="tray-header-dot" title="Ready" />
              </div>
            );
          }
          return (
            <button
              key={i}
              className={`tray-item ${item.muted ? "is-muted" : ""} ${item.danger ? "is-danger" : ""}`}
            >
              <span className="tray-item-icon">
                <Icon name={item.icon} size={13} />
              </span>
              <span className="tray-item-label">
                {item.label}
                {item.tag ? <span className="tray-item-tag">{item.tag}</span> : null}
              </span>
              {item.value ? <span className="tray-item-value mono">{item.value}</span> : null}
              {item.caret ? <Icon name="chevron-right" size={10} className="tray-item-caret" /> : null}
              {item.kbd ? (
                <span className="tray-item-kbd">
                  {item.kbd.map((k, j) => (
                    <kbd key={j}>{k}</kbd>
                  ))}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ToastStack() {
  return (
    <div className="toast-stack">
      <div className="toast toast--success">
        <div className="toast-icon"><Icon name="check" size={14} /></div>
        <div className="toast-body">
          <div className="toast-title">Settings đã lưu</div>
          <div className="toast-desc">Provider: claude · Target: Tiếng Việt · 5 presets</div>
        </div>
        <button className="toast-close"><Icon name="close" size={11} /></button>
        <div className="toast-progress" />
      </div>

      <div className="toast">
        <div className="toast-icon"><Icon name="info" size={14} /></div>
        <div className="toast-body">
          <div className="toast-title">Đang OCR + dịch toàn màn hình…</div>
          <div className="toast-desc">12 blocks · Windows OCR → claude</div>
        </div>
        <button className="toast-close"><Icon name="close" size={11} /></button>
      </div>

      <div className="toast toast--warn">
        <div className="toast-icon"><Icon name="alert" size={14} /></div>
        <div className="toast-body">
          <div className="toast-title">Hotkey trùng</div>
          <div className="toast-desc">
            <span className="mono">Alt+T</span> đang gán cho 2 action. Đổi 1 trong Settings → Hotkeys.
          </div>
        </div>
        <button className="toast-close"><Icon name="close" size={11} /></button>
      </div>
    </div>
  );
}

// App icon / wordmark. Composition: crop brackets (selection) + chevron pointing
// right (translation direction). Themed by accent. Shown at 4 sizes.
function AppIconShowcase() {
  return (
    <div className="appicon-showcase">
      <div className="appicon-stage">
        <AppIconLarge size={144} />
        <div className="appicon-wordmark">
          <div className="appicon-name">TransSnip</div>
          <div className="appicon-tag">Screen translation · v0.2</div>
        </div>
      </div>
      <div className="appicon-row">
        <div className="appicon-cell">
          <AppIconLarge size={64} />
          <span className="appicon-size mono">64</span>
        </div>
        <div className="appicon-cell">
          <AppIconLarge size={32} />
          <span className="appicon-size mono">32</span>
        </div>
        <div className="appicon-cell">
          <AppIconLarge size={20} />
          <span className="appicon-size mono">20</span>
        </div>
        <div className="appicon-cell">
          <div className="appicon-mono">
            <AppIconMono size={20} />
          </div>
          <span className="appicon-size mono">tray</span>
        </div>
      </div>
    </div>
  );
}

function AppIconLarge({ size = 144 }) {
  // Rounded square tile with crop-brackets + chevron mark.
  const r = size * 0.22;
  return (
    <svg width={size} height={size} viewBox="0 0 144 144" className="appicon-svg">
      <defs>
        <linearGradient id={`icon-bg-${size}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="var(--bg-2)" />
          <stop offset="100%" stopColor="var(--bg-1)" />
        </linearGradient>
      </defs>
      <rect
        x="2"
        y="2"
        width="140"
        height="140"
        rx={r}
        fill={`url(#icon-bg-${size})`}
        stroke="var(--border-2)"
        strokeWidth="1"
      />
      {/* Crop brackets — selection metaphor */}
      <path
        d="M30 50V36a6 6 0 0 1 6-6h14M114 50V36a6 6 0 0 0-6-6H94M114 94v14a6 6 0 0 1-6 6H94M30 94v14a6 6 0 0 0 6 6h14"
        stroke="var(--accent)"
        strokeWidth="6"
        strokeLinecap="round"
        fill="none"
      />
      {/* Inner chevron — translation direction */}
      <path
        d="M58 72h28M78 60l10 12-10 12"
        stroke="var(--text-1)"
        strokeWidth="7"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

function AppIconMono({ size = 16 }) {
  // Monochrome tray version — single color stroke, no fill tile.
  return (
    <svg width={size} height={size} viewBox="0 0 16 16">
      <path
        d="M2.5 4.5V3a.7.7 0 0 1 .7-.7H4.5M11.5 2.3H13a.7.7 0 0 1 .7.7v1.5M13.7 11.5V13a.7.7 0 0 1-.7.7h-1.5M4.5 13.7H3a.7.7 0 0 1-.7-.7v-1.5"
        stroke="var(--text-1)"
        strokeWidth="1.6"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M6 8h4M8.5 6.5L10 8l-1.5 1.5"
        stroke="var(--accent)"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

Object.assign(window, { TrayMenu, ToastStack, AppIconShowcase, AppIconLarge, AppIconMono });
