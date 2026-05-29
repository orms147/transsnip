// surface-empty.jsx — Empty states & error variants
// 1) Popup · No text found   2) Popup · Network down
// 3) Settings preset list empty (Context body)
// 4) Hotkey collision modal  5) Tray toast · API key invalid

// Shared minimal popup chrome for the two popup empty/error states.
function PopupShell({ width = 520, status, children }) {
  return (
    <div className="popup" style={{ width }}>
      <div className="popup-header">
        <div className="popup-brand">
          <AppGlyph size={14} />
          <span className="popup-brand-name">TransSnip</span>
        </div>
        <div className="popup-drag" aria-hidden />
        <div className="popup-status-area">
          {status ? <div className={`popup-status ${status.cls || ""}`}>{status.icon ? <Icon name={status.icon} size={11} /> : null}<span>{status.label}</span></div> : null}
        </div>
        <div className="popup-actions">
          <button className="popup-iconbtn" title="Copy"><Icon name="copy" size={14} /></button>
          <button className="popup-iconbtn" title="Settings"><Icon name="settings" size={14} /></button>
          <div className="popup-divider" />
          <button className="popup-iconbtn popup-iconbtn--close" title="Close (Esc)"><Icon name="close" size={14} /></button>
        </div>
      </div>
      <div className="popup-body">{children}</div>
    </div>
  );
}

// 1 · No text found
function PopupNoText() {
  return (
    <PopupShell status={{ label: "0 blocks", cls: "" }}>
      <div className="empty-state">
        <div className="empty-icon"><Icon name="eye" size={28} /></div>
        <div className="empty-title">Không tìm thấy text</div>
        <div className="empty-desc">
          Vùng đã chọn không có chữ — hoặc OCR không nhận ra. Thử lại với vùng to hơn,
          hoặc chuyển sang <b>Gemini Vision</b> (giỏi hơn với text stylized).
        </div>
        <div className="empty-actions">
          <button className="popup-btn-soft"><Icon name="refresh" size={12} />Thử lại</button>
          <button className="popup-btn-soft">Đổi provider →</button>
        </div>
      </div>
    </PopupShell>
  );
}

// 2 · Network down
function PopupNetwork() {
  return (
    <PopupShell status={{ label: "offline", cls: "popup-status--error", icon: "alert" }}>
      <div className="empty-state">
        <div className="empty-icon empty-icon--warn"><Icon name="alert" size={26} /></div>
        <div className="empty-title">Không có kết nối</div>
        <div className="empty-desc">
          Provider hiện cần internet. Thử <b>Google Translate Free</b> hoặc cài
          <span className="mono"> RapidOCR</span> cho offline.
        </div>
        <div className="empty-actions">
          <button className="popup-btn-soft"><Icon name="refresh" size={12} />Thử lại</button>
          <button className="popup-btn-soft">Chuyển sang offline</button>
        </div>
      </div>
    </PopupShell>
  );
}

// 3 · Settings preset list empty (rendered inside Context tab body)
function PresetEmpty() {
  return (
    <SettingsWindowChrome tab="context">
      <div className="preset-empty">
        <div className="preset-empty-illu">
          <Icon name="brain" size={42} />
        </div>
        <div className="empty-title empty-title--lg">Chưa có preset nào</div>
        <div className="empty-desc empty-desc--wide">
          Preset là bộ chỉ thị + glossary áp dụng cho LLM provider.
          Vd: <span className="mono">gaming</span> giữ tên skill, <span className="mono">medical</span> dùng thuật ngữ Y khoa.
        </div>
        <div className="empty-actions">
          <button className="btn btn-primary"><Icon name="plus" size={13} />Tạo preset đầu tiên</button>
          <button className="btn btn-ghost">Xem ví dụ</button>
        </div>
      </div>
    </SettingsWindowChrome>
  );
}

// 4 · Hotkey collision modal (480×280)
function HotkeyCollision() {
  return (
    <div className="collision">
      <div className="collision-icon"><Icon name="alert" size={18} /></div>
      <div className="collision-title">Phím tắt đã được dùng</div>
      <div className="collision-box">
        <kbd className="kbd-big">Alt</kbd>
        <span className="kbd-plus">+</span>
        <kbd className="kbd-big">T</kbd>
        <Icon name="arrow" size={16} className="collision-arrow" />
        <div className="collision-apps">
          <span className="collision-app"><span className="collision-app-name">Photoshop</span><span className="collision-app-ctx">Type tool</span></span>
          <span className="collision-app"><span className="collision-app-name">Discord</span><span className="collision-app-ctx">Tag user</span></span>
        </div>
      </div>
      <div className="collision-btns">
        <button className="btn btn-primary">Ghi đè (TransSnip ưu tiên)</button>
        <button className="btn">Chọn phím khác</button>
        <button className="btn btn-ghost">Huỷ</button>
      </div>
    </div>
  );
}

// 5 · Tray toast · API key invalid
function ApiKeyToast() {
  return (
    <div className="toast-stack toast-stack--single">
      <div className="toast toast--warn">
        <div className="toast-icon"><Icon name="alert" size={14} /></div>
        <div className="toast-body">
          <div className="toast-title">API key không hợp lệ</div>
          <div className="toast-desc">
            <span className="mono">claude · 401 unauthorized</span>
          </div>
          <a className="toast-action">Mở Settings → Translation</a>
        </div>
        <button className="toast-close"><Icon name="close" size={11} /></button>
        <div className="toast-progress toast-progress--warn" />
      </div>
    </div>
  );
}

Object.assign(window, { PopupNoText, PopupNetwork, PresetEmpty, HotkeyCollision, ApiKeyToast });
