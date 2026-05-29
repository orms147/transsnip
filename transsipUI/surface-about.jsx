// surface-about.jsx — About dialog (3 internal tabs) + License sheet
// 480×600 frameless modal.

function AboutHead() {
  return (
    <div className="about-head">
      <div className="about-icon"><AppIconLarge size={84} /></div>
      <div className="about-wordmark">
        <span className="about-name">TransSnip</span>
        <span className="about-version mono">v0.2.0-mvp</span>
      </div>
      <div className="about-tagline">Screen translation cho Windows · Made with ♥ in Vietnam</div>
    </div>
  );
}

function AboutTabs({ active }) {
  const tabs = [
    { id: "info", label: "Thông tin" },
    { id: "ack", label: "Acknowledgements" },
    { id: "author", label: "Tác giả" },
  ];
  return (
    <div className="about-tabs">
      {tabs.map((t) => (
        <button key={t.id} className={`about-tab ${t.id === active ? "is-active" : ""}`}>{t.label}</button>
      ))}
    </div>
  );
}

function AboutInfo() {
  const rows = [
    { k: "License", v: "MIT" },
    { k: "Build", v: "cobalt-dark · Nov 2025" },
    { k: "Engine", v: "Qt 6.7 · Python 3.12" },
    { k: "Repo", v: "github.com/orms147/transsnip", link: true },
  ];
  return (
    <div className="about-pane">
      <div className="about-info-grid">
        {rows.map((r) => (
          <div key={r.k} className="about-info-row">
            <span className="about-info-key mono">{r.k}</span>
            <span className="about-info-val mono">
              {r.v}
              {r.link ? <Icon name="external" size={12} className="about-info-link" /> : null}
            </span>
          </div>
        ))}
      </div>
      <div className="about-update">
        <button className="btn btn-soft"><Icon name="refresh" size={12} />Kiểm tra cập nhật</button>
        <span className="about-update-meta">Đã kiểm tra 2 giờ trước · mới nhất</span>
      </div>
    </div>
  );
}

function AboutAck() {
  const items = [
    { name: "RapidOCR", blurb: "ONNX OCR fallback" },
    { name: "winsdk", blurb: "Windows OCR binding" },
    { name: "eng-to-ipa", blurb: "CMU phonetic dictionary" },
    { name: "edge-tts", blurb: "Microsoft Edge TTS streaming" },
    { name: "PySide6", blurb: "Qt for Python" },
    { name: "mss", blurb: "fast multi-monitor capture" },
  ];
  return (
    <div className="about-pane">
      <div className="about-ack-list">
        {items.map((it) => (
          <div key={it.name} className="about-ack-row">
            <span className="about-ack-dot" />
            <span className="about-ack-name mono">{it.name}</span>
            <span className="about-ack-blurb">{it.blurb}</span>
          </div>
        ))}
      </div>
      <div className="about-ack-foot">Chi tiết license trong <span className="mono">LICENSE.md</span></div>
    </div>
  );
}

function AboutAuthor() {
  return (
    <div className="about-pane about-pane--author">
      <div className="about-avatar"><Icon name="user" size={34} /></div>
      <div className="about-author-name">orms147</div>
      <a className="about-author-handle"><Icon name="link" size={12} />github.com/orms147</a>
      <div className="about-author-line">Made for ĐATN ITSS in Japanese · ITSS K67 HUST</div>
      <div className="about-social">
        <button className="about-social-btn" title="GitHub"><Icon name="link" size={15} /></button>
        <button className="about-social-btn" title="Email"><Icon name="mail" size={15} /></button>
      </div>
    </div>
  );
}

function AboutDialog({ aboutTab = "info" }) {
  return (
    <div className="about">
      <AboutHead />
      <AboutTabs active={aboutTab} />
      <div className="about-body">
        {aboutTab === "info" ? <AboutInfo /> : null}
        {aboutTab === "ack" ? <AboutAck /> : null}
        {aboutTab === "author" ? <AboutAuthor /> : null}
      </div>
      <div className="about-footer">
        <a className="link about-footer-link">Run onboarding again</a>
        <button className="btn btn-primary">Đóng</button>
      </div>
    </div>
  );
}

// License sheet — MIT text + dependency licenses
function LicenseSheet() {
  const deps = [
    ["RapidOCR", "Apache-2.0"],
    ["winsdk", "MIT"],
    ["eng-to-ipa", "MIT"],
    ["edge-tts", "GPL-3.0"],
    ["PySide6", "LGPL-3.0"],
    ["mss", "MIT"],
  ];
  return (
    <div className="license">
      <div className="license-head">
        <Icon name="info" size={15} />
        <span className="license-title">LICENSE.md</span>
        <span className="license-badge mono">MIT</span>
      </div>
      <div className="license-body">
        <pre className="license-text mono">{`MIT License

Copyright (c) 2025 orms147

Permission is hereby granted, free of charge, to any
person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the
Software without restriction, including without
limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies…`}</pre>
        <div className="license-deps">
          <div className="license-deps-head">Third-party licenses</div>
          {deps.map(([name, lic]) => (
            <div key={name} className="license-dep">
              <span className="mono">{name}</span>
              <span className="license-dep-lic mono">{lic}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="about-footer">
        <span className="settings-footer-hint">6 dependencies</span>
        <button className="btn btn-primary">Đóng</button>
      </div>
    </div>
  );
}

Object.assign(window, { AboutDialog, LicenseSheet });
