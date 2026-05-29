// surface-onboarding.jsx — First-run onboarding wizard (5 steps + Esc confirm)
// 720×520 frameless modal. Reuses Cobalt tokens + atoms (AppIconLarge, Icon,
// KbdSeq, Toggle, button classes). One component, switched by `step` prop.

function ProgressDots({ active, total = 4 }) {
  return (
    <div className="onb-dots" aria-label={`Bước ${active} / ${total}`}>
      {Array.from({ length: total }).map((_, i) => (
        <span key={i} className={`onb-dot ${i + 1 === active ? "is-active" : ""} ${i + 1 < active ? "is-done" : ""}`} />
      ))}
    </div>
  );
}

// ── Step 1 · Welcome ──────────────────────────────────────────────────────
function StepWelcome() {
  const features = [
    { icon: "crop", title: "Chụp & dịch", keys: ["Alt", "T"], desc: "Chụp một vùng màn hình → bản dịch hiện trong popup." },
    { icon: "fullscreen", title: "Dịch toàn màn hình", keys: ["Alt", "F"], desc: "Phủ bản dịch ngay trên text gốc, đúng vị trí." },
    { icon: "brain", title: "Học tiếng Anh", keys: null, desc: "Phiên âm IPA + nút phát âm khi nguồn là English." },
  ];
  return (
    <div className="onb-welcome">
      <div className="onb-welcome-icon">
        <AppIconLarge size={88} />
      </div>
      <h2 className="onb-title">Chào bạn 👋 TransSnip là gì?</h2>
      <p className="onb-lede">Dịch mọi text trên màn hình Windows — không cần copy, không cần đổi cửa sổ.</p>
      <div className="onb-feature-row">
        {features.map((f) => (
          <div key={f.title} className="onb-feature">
            <div className="onb-feature-icon"><Icon name={f.icon} size={18} /></div>
            <div className="onb-feature-title">{f.title}</div>
            {f.keys ? <KbdSeq keys={f.keys} /> : <span className="onb-feature-auto">tự động</span>}
            <div className="onb-feature-desc">{f.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Step 2 · Provider ─────────────────────────────────────────────────────
function StepProvider() {
  const providers = [
    { id: "claude", icon: "brain", name: "Anthropic Claude", desc: "Chất lượng cao nhất", tag: "API key · paid", active: true },
    { id: "openai", icon: "spinner", name: "OpenAI GPT", desc: "Phổ biến", tag: "API key · paid" },
    { id: "google", icon: "globe", name: "Google Translate", desc: "Free, không cần setup", tag: "Free" },
    { id: "gemini", icon: "eye", name: "Gemini Vision", desc: "OCR + dịch trong 1 call", tag: "API key · free tier" },
  ];
  return (
    <div className="onb-step">
      <h2 className="onb-title onb-title--sm">Chọn provider dịch</h2>
      <p className="onb-lede onb-lede--sm">Có thể đổi bất cứ lúc nào trong Settings → Translation.</p>
      <div className="onb-provider-grid">
        {providers.map((p) => (
          <div key={p.id} className={`onb-radio-card ${p.active ? "is-active" : ""}`}>
            <span className="onb-radio-dot"><span className="onb-radio-fill" /></span>
            <div className="onb-radio-icon"><Icon name={p.icon} size={16} /></div>
            <div className="onb-radio-main">
              <div className="onb-radio-name">{p.name}</div>
              <div className="onb-radio-desc">{p.desc}</div>
            </div>
            <span className={`onb-radio-tag ${p.tag === "Free" ? "is-free" : ""}`}>{p.tag}</span>
          </div>
        ))}
      </div>
      <div className="onb-apikey">
        <div className="onb-apikey-head">
          <span className="field-label">API key cho Anthropic Claude</span>
          <a className="link">Đăng ký lấy key tại console.anthropic.com</a>
        </div>
        <div className="onb-apikey-row">
          <div className="input">
            <input placeholder="sk-ant-api03-•••••••••••••••••••••" type="password" readOnly />
          </div>
          <button className="btn btn-soft"><Icon name="clipboard" size={13} />Dán từ clipboard</button>
        </div>
      </div>
    </div>
  );
}

// ── Step 3 · Language ─────────────────────────────────────────────────────
function OnbLangChip({ code, name, label }) {
  return (
    <button className="onb-langchip">
      <span className="onb-langchip-label">{label}</span>
      <span className="onb-langchip-code">{code}</span>
      <span className="onb-langchip-name">{name}</span>
      <Icon name="chevron" size={14} className="onb-langchip-caret" />
    </button>
  );
}

function StepLanguage() {
  const quick = [
    ["JA", "VI"], ["EN", "VI"], ["ZH", "VI"], ["KO", "VI"],
  ];
  return (
    <div className="onb-step">
      <h2 className="onb-title onb-title--sm">Bạn muốn dịch sang ngôn ngữ gì?</h2>
      <div className="onb-lang-big">
        <OnbLangChip label="Nguồn" code="JA" name="日本語" />
        <div className="onb-lang-arrow"><Icon name="arrow" size={22} /></div>
        <OnbLangChip label="Đích" code="VI" name="Tiếng Việt" />
      </div>
      <div className="onb-quickpick">
        <span className="onb-quickpick-label">Phổ biến</span>
        <div className="onb-quickpick-chips">
          {quick.map(([s, t], i) => (
            <button key={i} className={`onb-pair-chip ${i === 0 ? "is-active" : ""}`}>
              <span className="mono">{s}</span>
              <Icon name="chevron-right" size={10} />
              <span className="mono">{t}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="toggle-row">
        <div>
          <div className="toggle-row-title">Học tiếng Anh: hiện IPA + phát âm</div>
          <div className="toggle-row-desc">Tự bật khi nguồn là English — hiện phiên âm và nút đọc to.</div>
        </div>
        <Toggle on={false} />
      </div>
    </div>
  );
}

// ── Step 4 · Hotkey ───────────────────────────────────────────────────────
function StepHotkey() {
  const rows = [
    { icon: "crop", label: "Region translate", desc: "Chọn một vùng rồi dịch", keys: ["Alt", "T"] },
    { icon: "fullscreen", label: "Fullscreen translate", desc: "Dịch toàn bộ text trên màn hình", keys: ["Alt", "F"] },
    { icon: "subtitles", label: "Video subtitle", desc: "Auto-dịch phụ đề real-time (Phase 2)", keys: ["Alt", "V"], disabled: true },
  ];
  return (
    <div className="onb-step">
      <h2 className="onb-title onb-title--sm">Phím tắt</h2>
      <p className="onb-lede onb-lede--sm">Click vào tổ hợp để gán phím khác ngay tại đây.</p>
      <div className="hotkey-list">
        {rows.map((r) => (
          <div key={r.label} className={`hotkey-row ${r.disabled ? "is-disabled" : ""}`}>
            <div className="hotkey-icon"><Icon name={r.icon} size={14} /></div>
            <div className="hotkey-main">
              <div className="hotkey-label">{r.label}</div>
              <div className="hotkey-desc">{r.desc}</div>
            </div>
            <div className="hotkey-keys">
              <button className="hotkey-binding"><KbdSeq keys={r.keys} /></button>
            </div>
          </div>
        ))}
      </div>
      <div className="onb-note">
        <Icon name="info" size={13} />
        <span>Bạn có thể đổi sau trong <b>Settings → Hotkeys</b>.</span>
      </div>
    </div>
  );
}

// ── Step 5 · Ready ────────────────────────────────────────────────────────
function StepReady() {
  return (
    <div className="onb-ready">
      <div className="onb-check"><Icon name="check" size={36} /></div>
      <h2 className="onb-title">Sẵn sàng!</h2>
      <p className="onb-lede">Bấm <kbd>Alt</kbd>+<kbd>T</kbd> trên bất kỳ vùng nào để dịch.</p>
      <div className="onb-demo">
        <div className="onb-demo-tag">demo</div>
        <div className="onb-demo-screen">
          <div className="onb-demo-sel" />
          <div className="onb-demo-cursor"><Icon name="crop" size={12} /></div>
        </div>
      </div>
    </div>
  );
}

// ── Frame + footer ────────────────────────────────────────────────────────
function OnboardingModal({ step = 1 }) {
  const isReady = step === 5;
  const nav = {
    1: { next: "Bắt đầu →", back: false },
    2: { next: "Tiếp →", back: true },
    3: { next: "Tiếp →", back: true },
    4: { next: "Hoàn tất ✓", back: true },
  }[step];

  return (
    <div className="onb">
      {!isReady ? (
        <button className="onb-skip">Bỏ qua, dùng cài đặt mặc định</button>
      ) : null}

      <div className={`onb-body ${isReady ? "onb-body--center" : ""}`}>
        {step === 1 ? <StepWelcome /> : null}
        {step === 2 ? <StepProvider /> : null}
        {step === 3 ? <StepLanguage /> : null}
        {step === 4 ? <StepHotkey /> : null}
        {step === 5 ? <StepReady /> : null}
      </div>

      <div className="onb-footer">
        {!isReady ? (
          <>
            <ProgressDots active={step} total={4} />
            <div className="onb-footer-btns">
              {nav.back ? <button className="btn btn-ghost">Quay lại</button> : null}
              <button className="btn btn-primary">{nav.next}</button>
            </div>
          </>
        ) : (
          <div className="onb-footer-btns onb-footer-btns--ready">
            <button className="btn">Mở Settings để khám phá thêm</button>
            <button className="btn btn-primary">Bắt đầu dùng</button>
          </div>
        )}
      </div>
    </div>
  );
}

// Esc → confirm dialog (small modal shown over a dimmed wizard)
function OnboardingConfirm() {
  return (
    <div className="onb-confirm">
      <div className="onb-confirm-icon"><Icon name="alert" size={18} /></div>
      <div className="onb-confirm-title">Thoát onboarding?</div>
      <div className="onb-confirm-desc">
        Bạn có thể chạy lại bất cứ lúc nào từ <b>Settings → About → Run onboarding again</b>.
      </div>
      <div className="onb-confirm-btns">
        <button className="btn btn-ghost">Tiếp tục cài đặt</button>
        <button className="btn btn-primary">Thoát</button>
      </div>
    </div>
  );
}

Object.assign(window, { OnboardingModal, OnboardingConfirm });
