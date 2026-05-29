// surface-settings.jsx — SettingsWindow with 3 tabs (Translation / Context / Hotkeys)
// Tabs stay horizontal at the top per the user's preference.

function SettingsWindowChrome({ tab, children }) {
  return (
    <div className="settings-window">
      <div className="settings-titlebar">
        <div className="settings-titlebar-left">
          <AppGlyph size={13} />
          <span className="settings-title">TransSnip · Settings</span>
        </div>
        <div className="settings-titlebar-right">
          <button className="settings-titlebar-btn" title="Minimize">
            <svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 5h6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
          </button>
          <button className="settings-titlebar-btn" title="Maximize">
            <svg width="10" height="10" viewBox="0 0 10 10"><rect x="2" y="2" width="6" height="6" stroke="currentColor" strokeWidth="1.2" fill="none" /></svg>
          </button>
          <button className="settings-titlebar-btn settings-titlebar-btn--close" title="Close">
            <Icon name="close" size={10} />
          </button>
        </div>
      </div>

      <div className="settings-tabs">
        <button className={`settings-tab ${tab === "translation" ? "is-active" : ""}`}>
          <Icon name="globe" size={13} />
          <span>Translation</span>
        </button>
        <button className={`settings-tab ${tab === "context" ? "is-active" : ""}`}>
          <Icon name="brain" size={13} />
          <span>Context preset</span>
        </button>
        <button className={`settings-tab ${tab === "hotkeys" ? "is-active" : ""}`}>
          <Icon name="keyboard" size={13} />
          <span>Hotkeys</span>
        </button>
        <button className={`settings-tab ${tab === "display" ? "is-active" : ""}`}>
          <Icon name="eye" size={13} />
          <span>Display</span>
        </button>
        <button className={`settings-tab ${tab === "voice" ? "is-active" : ""}`}>
          <Icon name="volume" size={13} />
          <span>Voice</span>
        </button>
        <div className="settings-tab-spacer" />
        <div className="settings-search">
          <Icon name="search" size={12} />
          <input placeholder="Tìm setting…" disabled />
          <kbd>Ctrl</kbd><kbd>K</kbd>
        </div>
      </div>

      <div className="settings-body">{children}</div>

      <div className="settings-footer">
        <span className="settings-footer-hint">
          Settings được lưu vào <span className="mono">%APPDATA%\TransSnip\settings.json</span>
        </span>
        <div className="settings-footer-actions">
          <button className="btn btn-ghost">Cancel</button>
          <button className="btn btn-primary">Save</button>
        </div>
      </div>
    </div>
  );
}

// ── Reusable form atoms ──────────────────────────────────────────────────
function Field({ label, hint, children, span = 1 }) {
  return (
    <div className={`field field--span-${span}`}>
      <label className="field-label">{label}</label>
      <div className="field-control">{children}</div>
      {hint ? <div className="field-hint">{hint}</div> : null}
    </div>
  );
}

function Select({ value, items, leftIcon, mono }) {
  return (
    <div className={`select ${mono ? "select--mono" : ""}`}>
      {leftIcon ? <span className="select-left">{leftIcon}</span> : null}
      <span className="select-value">{value}</span>
      <Icon name="chevron" size={12} className="select-caret" />
    </div>
  );
}

function Input({ value, placeholder, type, suffix }) {
  return (
    <div className="input">
      <input value={value} placeholder={placeholder} type={type || "text"} readOnly />
      {suffix ? <div className="input-suffix">{suffix}</div> : null}
    </div>
  );
}

function Toggle({ on, label }) {
  return (
    <label className="toggle">
      <span className={`toggle-track ${on ? "is-on" : ""}`}>
        <span className="toggle-knob" />
      </span>
      <span className="toggle-label">{label}</span>
    </label>
  );
}

function KbdSeq({ keys }) {
  return (
    <div className="kbd-seq">
      {keys.map((k, i) => (
        <React.Fragment key={i}>
          {i > 0 ? <span className="kbd-plus">+</span> : null}
          <kbd className="kbd-key">{k}</kbd>
        </React.Fragment>
      ))}
    </div>
  );
}

// ── Slider atom (static design mock) ─────────────────────────────────────
function Slider({ pct = 50, min, max, readout, thumb }) {
  return (
    <div className="slider">
      <div className="slider-rail">
        <div className="slider-fill" style={{ width: `${pct}%` }} />
        <div className="slider-knob" style={{ left: `${pct}%` }} />
      </div>
      <div className="slider-meta">
        <span className="slider-bound mono">{min}</span>
        {readout ? <span className="slider-readout mono">{readout}</span> : null}
        <span className="slider-bound mono">{max}</span>
      </div>
      {thumb ? <div className="slider-thumb-preview">{thumb}</div> : null}
    </div>
  );
}

// ── Segmented control (icon + label) ─────────────────────────────────────
function Segmented({ options, value }) {
  return (
    <div className="segmented" role="radiogroup">
      {options.map((o) => (
        <button key={o.id} className={`segmented-opt ${o.id === value ? "is-active" : ""}`}>
          <Icon name={o.icon} size={14} />
          <span className="segmented-label">{o.label}</span>
          <span className="segmented-sub">{o.sub}</span>
        </button>
      ))}
    </div>
  );
}

// ── Theme radio card with mini popup-chrome swatch ───────────────────────
function ThemeCard({ mode, name, hint, active }) {
  return (
    <button className={`theme-card ${active ? "is-active" : ""}`}>
      <div className={`theme-swatch theme-swatch--${mode}`}>
        <div className="theme-swatch-bar">
          <span className="theme-swatch-dot" />
          <span className="theme-swatch-line" />
        </div>
        <div className="theme-swatch-body">
          <span className="theme-swatch-row" />
          <span className="theme-swatch-row theme-swatch-row--accent" />
        </div>
      </div>
      <div className="theme-card-foot">
        <span className="theme-card-name">{name}</span>
        {active ? <span className="theme-card-check"><Icon name="check" size={11} /></span> : null}
      </div>
      {hint ? <div className="theme-card-hint">{hint}</div> : null}
    </button>
  );
}

// ── Display tab ──────────────────────────────────────────────────────────
function DisplayTab() {
  const fsStyles = [
    { id: "subtle", icon: "eye", label: "Subtle border", sub: "source vẫn thấy" },
    { id: "opaque", icon: "fullscreen", label: "Opaque box", sub: "che hoàn toàn" },
    { id: "side", icon: "subtitles", label: "Side panel", sub: "dồn bên phải" },
  ];
  return (
    <div className="settings-form">
      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Theme</h3>
          <span className="settings-section-desc">
            Hệ thống dùng Windows <span className="mono">ColorPrevalence</span> + <span className="mono">WallpaperLightTheme</span> key khi chọn Tự động.
          </span>
        </div>
        <div className="theme-card-row">
          <ThemeCard mode="dark" name="Cobalt Dark" active />
          <ThemeCard mode="light" name="Cobalt Light" />
          <ThemeCard mode="auto" name="Tự động theo Windows" />
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Popup</h3>
        </div>
        <div className="settings-stack">
          <Field label="Kích thước mặc định">
            <Slider pct={42} min="380px" max="720px" readout="460 px"
              thumb={<div className="popup-size-preview"><span /><span /></div>} />
          </Field>
          <Field label="Font scale tối đa khi resize">
            <Slider pct={50} min="1.0×" max="3.0×" readout="2.0×" />
          </Field>
          <div className="toggle-row">
            <div>
              <div className="toggle-row-title">Click outside để đóng popup</div>
            </div>
            <Toggle on />
          </div>
          <div className="toggle-row">
            <div>
              <div className="toggle-row-title">Pin popup mở lại lần dịch sau</div>
            </div>
            <Toggle on={false} />
          </div>
          <div className="toggle-row">
            <div>
              <div className="toggle-row-title">Hiện footer hint trong popup</div>
              <div className="toggle-row-desc">Ẩn dòng “Esc · Ctrl+C · click vào từ” để gọn hơn.</div>
            </div>
            <Toggle on />
          </div>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Fullscreen overlay</h3>
        </div>
        <div className="settings-stack">
          <Field label="Style block">
            <Segmented options={fsStyles} value="subtle" />
          </Field>
          <div className="toggle-row">
            <div>
              <div className="toggle-row-title">Hiện numbered badges (1, 2, 3…)</div>
            </div>
            <Toggle on />
          </div>
          <div className="toggle-row">
            <div>
              <div className="toggle-row-title">Toolbar tự ẩn sau 3s</div>
            </div>
            <Toggle on={false} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Voice tab ────────────────────────────────────────────────────────────
function VoiceTab() {
  const voices = [
    { group: "US English", items: [
      { name: "Aria", id: "en-US-AriaNeural", active: true },
      { name: "Guy", id: "en-US-GuyNeural" },
    ]},
    { group: "UK English", items: [
      { name: "Sonia", id: "en-GB-SoniaNeural" },
      { name: "Ryan", id: "en-GB-RyanNeural" },
    ]},
    { group: "AU English", items: [
      { name: "Natasha", id: "en-AU-NatashaNeural" },
    ]},
  ];
  return (
    <div className="settings-form">
      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Edge TTS</h3>
          <span className="settings-section-desc">Giọng đọc Microsoft Edge — stream trực tiếp, không cần cài đặt thêm.</span>
        </div>
        <Field label="Voice">
          <div className="voice-list">
            {voices.map((g) => (
              <div key={g.group} className="voice-group">
                <div className="voice-group-head">{g.group}</div>
                {g.items.map((v) => (
                  <div key={v.id} className={`voice-row ${v.active ? "is-active" : ""}`}>
                    <span className="voice-radio"><span /></span>
                    <span className="voice-name">{v.name}</span>
                    <span className="voice-id mono">{v.id}</span>
                    <button className="voice-play" title="Nghe thử"><Icon name="play" size={11} /></button>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </Field>
        <div className="settings-grid">
          <Field label="Tốc độ">
            <Slider pct={33} min="0.5×" max="2.0×" readout="1.0×" />
          </Field>
          <Field label="Volume">
            <Slider pct={80} min="0%" max="100%" readout="80%" />
          </Field>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Tự động phát âm</h3>
        </div>
        <div className="settings-stack">
          <div className="toggle-row">
            <div>
              <div className="toggle-row-title">Phát âm tự động khi source = English</div>
              <div className="toggle-row-desc">Nguồn được đọc to ngay khi popup hiển thị bản dịch.</div>
            </div>
            <Toggle on={false} />
          </div>
          <div className="toggle-row">
            <div>
              <div className="toggle-row-title">Lưu audio đã đọc vào cache (max 100MB)</div>
              <div className="toggle-row-desc">Tránh gọi Edge TTS lại cho cùng câu — phát instant lần sau.</div>
            </div>
            <Toggle on />
          </div>
          <Field label="Cache hiện tại">
            <div className="cache-row">
              <span className="cache-readout mono">24 MB · 142 clip</span>
              <button className="btn btn-soft"><Icon name="trash" size={12} />Xoá cache</button>
            </div>
          </Field>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Phím tắt</h3>
        </div>
        <div className="settings-stack">
          <div className="kbd-readonly-row">
            <span className="kbd-readonly-label">Phát source</span>
            <span className="kbd-readonly-keys"><kbd>Space</kbd><span className="kbd-readonly-ctx">khi popup focus</span></span>
          </div>
          <div className="kbd-readonly-row">
            <span className="kbd-readonly-label">Dừng audio</span>
            <span className="kbd-readonly-keys"><kbd>Esc</kbd><span className="kbd-readonly-ctx">khi đang phát</span></span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Translation tab ──────────────────────────────────────────────────────
function TranslationTab() {
  return (
    <div className="settings-form">
      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Provider</h3>
          <span className="settings-section-desc">Chọn LLM hoặc translation service. Mỗi provider giữ API key riêng trong Windows Credential Manager.</span>
        </div>
        <div className="settings-grid">
          <Field label="Provider" span={2}>
            <Select value="Anthropic Claude" leftIcon={<Icon name="brain" size={13} />} />
          </Field>
          <Field
            label="API key"
            span={2}
            hint={<>Lấy key tại <a className="link">console.anthropic.com</a> · Lưu vào keyring sau khi Save</>}
          >
            <Input value="" placeholder="sk-ant-api03-•••••••••••••••••••••••••••" type="password" suffix={<button className="input-action"><Icon name="eye" size={12} /></button>} />
          </Field>
          <Field label="Model" span={1}>
            <Select value="claude-sonnet-4-20250514" mono />
          </Field>
          <Field label="" span={1}>
            <div className="btn-row">
              <button className="btn btn-soft"><Icon name="refresh" size={12} />Fetch</button>
              <button className="btn btn-soft btn-soft--ok"><Icon name="check" size={12} />Test</button>
            </div>
          </Field>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Ngôn ngữ</h3>
          <span className="settings-section-desc">Để Auto-detect nếu nguồn thay đổi thường xuyên — providers sẽ tự nhận dạng.</span>
        </div>
        <div className="settings-grid">
          <Field label="Nguồn (source)" span={1}>
            <Select value="Auto-detect" />
          </Field>
          <Field label="Đích (target)" span={1}>
            <Select value="Tiếng Việt · vi" />
          </Field>
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Hành vi</h3>
        </div>
        <div className="settings-stack">
          <Field label="Context preset">
            <Select value="default — translate plainly" leftIcon={<Icon name="brain" size={13} />} />
          </Field>
          <div className="toggle-row">
            <div>
              <div className="toggle-row-title">Học tiếng Anh</div>
              <div className="toggle-row-desc">Hiện phiên âm IPA + nút phát âm khi source là English.</div>
            </div>
            <Toggle on />
          </div>
          <div className="toggle-row">
            <div>
              <div className="toggle-row-title">Cache translation</div>
              <div className="toggle-row-desc">Lưu kết quả 24h để tránh gọi API lặp lại cho cùng đoạn text.</div>
            </div>
            <Toggle on />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Context preset tab ───────────────────────────────────────────────────
function ContextTab() {
  const presets = [
    { name: "default", desc: "translate plainly", active: false },
    { name: "gaming", desc: "JP→VI cho RPG, giữ tên skill", active: true },
    { name: "manga", desc: "giữ giọng nhân vật", active: false },
    { name: "programming", desc: "giữ identifier nguyên gốc", active: false },
    { name: "medical", desc: "thuật ngữ Y khoa chính xác", active: false },
  ];
  const glossary = [
    ["スキル", "kỹ năng"],
    ["魔法", "phép thuật"],
    ["ダメージ", "sát thương"],
    ["回復", "hồi phục"],
    ["クリティカル", "chí mạng"],
  ];
  return (
    <div className="settings-form settings-form--split">
      <div className="preset-list-col">
        <div className="settings-section-head settings-section-head--tight">
          <h3 className="settings-section-title">Presets</h3>
          <span className="settings-section-desc">Mỗi preset = 1 system prompt + glossary áp dụng cho provider LLM.</span>
        </div>
        <div className="preset-list">
          {presets.map((p) => (
            <div key={p.name} className={`preset-item ${p.active ? "is-active" : ""}`}>
              <div className="preset-item-main">
                <div className="preset-item-name">{p.name}</div>
                <div className="preset-item-desc">{p.desc}</div>
              </div>
              {p.active ? <span className="preset-active-dot" /> : null}
            </div>
          ))}
        </div>
        <div className="btn-row btn-row--end">
          <button className="btn btn-soft"><Icon name="plus" size={12} />Add</button>
          <button className="btn btn-soft"><Icon name="trash" size={12} />Delete</button>
        </div>
      </div>

      <div className="preset-edit-col">
        <div className="settings-grid">
          <Field label="Tên preset" span={1}>
            <Input value="gaming" />
          </Field>
          <Field label="Mô tả" span={1}>
            <Input value="JP→VI cho RPG, giữ tên skill" />
          </Field>
        </div>
        <Field label="System prompt">
          <div className="textarea">
            <pre className="textarea-content">{`You are translating Japanese RPG game dialogue
into natural, fluent Vietnamese. Keep skill names
and proper nouns in their original form. Maintain
character voice — formal NPCs stay formal, casual
party members stay casual.`}</pre>
          </div>
        </Field>
        <div className="glossary">
          <div className="glossary-head">
            <span className="field-label">Glossary</span>
            <div className="btn-row btn-row--end">
              <button className="btn btn-ghost btn-tiny"><Icon name="plus" size={11} />Thêm dòng</button>
              <button className="btn btn-ghost btn-tiny"><Icon name="minus" size={11} />Xoá</button>
            </div>
          </div>
          <div className="glossary-table">
            <div className="glossary-row glossary-row--head">
              <span>Nguồn</span>
              <span>Đích</span>
            </div>
            {glossary.map(([src, tgt], i) => (
              <div key={i} className="glossary-row">
                <span className="glossary-cell">{src}</span>
                <Icon name="chevron-right" size={10} className="glossary-arrow" />
                <span className="glossary-cell">{tgt}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Hotkeys tab ──────────────────────────────────────────────────────────
function HotkeysTab() {
  const rows = [
    {
      action: "region_translate",
      label: "Region translate",
      desc: "Snipping-tool style: chọn vùng rồi dịch",
      icon: "crop",
      keys: ["Alt", "T"],
    },
    {
      action: "fullscreen_translate",
      label: "Fullscreen translate",
      desc: "Dịch toàn bộ text trên màn hình hiện tại",
      icon: "fullscreen",
      keys: ["Alt", "F"],
    },
    {
      action: "video_subtitle_translate",
      label: "Video subtitle",
      desc: "Auto-translate vùng phụ đề real-time (Phase 2)",
      icon: "subtitles",
      keys: ["Alt", "V"],
      disabled: true,
    },
  ];
  return (
    <div className="settings-form">
      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Global hotkeys</h3>
          <span className="settings-section-desc">
            Click vào tổ hợp để gán phím mới. Để trống = tắt action đó.
            Hotkey hoạt động kể cả khi TransSnip ẩn dưới tray.
          </span>
        </div>
        <div className="hotkey-list">
          {rows.map((r) => (
            <div key={r.action} className={`hotkey-row ${r.disabled ? "is-disabled" : ""}`}>
              <div className="hotkey-icon">
                <Icon name={r.icon} size={14} />
              </div>
              <div className="hotkey-main">
                <div className="hotkey-label">{r.label}</div>
                <div className="hotkey-desc">{r.desc}</div>
              </div>
              <div className="hotkey-keys">
                <button className="hotkey-binding">
                  <KbdSeq keys={r.keys} />
                </button>
                <button className="btn btn-ghost btn-tiny" title="Reset to default">
                  <Icon name="refresh" size={11} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="settings-section">
        <div className="settings-section-head">
          <h3 className="settings-section-title">Khi popup mở</h3>
        </div>
        <div className="settings-stack">
          <div className="toggle-row">
            <div>
              <div className="toggle-row-title">Click outside để đóng popup</div>
              <div className="toggle-row-desc">Tắt nếu bạn hay click ra ngoài để copy text từ app khác.</div>
            </div>
            <Toggle on />
          </div>
          <div className="toggle-row">
            <div>
              <div className="toggle-row-title"><kbd>Esc</kbd> đóng overlay fullscreen</div>
              <div className="toggle-row-desc">Bất kỳ click nào trên overlay cũng đóng — phím Esc là tuỳ chọn.</div>
            </div>
            <Toggle on />
          </div>
        </div>
      </div>
    </div>
  );
}

function SettingsWindow({ tab = "translation" }) {
  return (
    <SettingsWindowChrome tab={tab}>
      {tab === "translation" ? <TranslationTab /> : null}
      {tab === "context" ? <ContextTab /> : null}
      {tab === "hotkeys" ? <HotkeysTab /> : null}
      {tab === "display" ? <DisplayTab /> : null}
      {tab === "voice" ? <VoiceTab /> : null}
    </SettingsWindowChrome>
  );
}

Object.assign(window, { SettingsWindow, SettingsWindowChrome, Field, Select, Input, Toggle, Slider, Segmented });
