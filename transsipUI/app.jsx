// app.jsx — assemble DesignCanvas with 3 theme sections × 8 surfaces each

function ThemedFrame({ theme, children, padding = 24, fill = true }) {
  // Each artboard wraps content in a theme container so CSS vars cascade.
  return (
    <div className={`t-${theme} themed-frame ${fill ? "themed-frame--fill" : ""}`} style={{ padding }}>
      {children}
    </div>
  );
}

function PopupArtboard({ theme, state, hint }) {
  return (
    <ThemedFrame theme={theme} padding={0}>
      <div className="artboard-stage popup-stage">
        <div className="artboard-stage-bg" />
        <div className="popup-shadow-wrap">
          <FloatingPopup state={state} />
        </div>
        {hint ? <div className="artboard-hint">{hint}</div> : null}
      </div>
    </ThemedFrame>
  );
}

function FullscreenArtboard({ theme, mode }) {
  return (
    <ThemedFrame theme={theme} padding={0}>
      <div className="artboard-stage fullscreen-stage">
        {mode === "region" ? <RegionSelector /> : <InlineOverlay />}
      </div>
    </ThemedFrame>
  );
}

function SettingsArtboard({ theme, tab }) {
  return (
    <ThemedFrame theme={theme} padding={28}>
      <SettingsWindow tab={tab} />
    </ThemedFrame>
  );
}

function SystemArtboard({ theme, kind }) {
  return (
    <ThemedFrame theme={theme} padding={kind === "icon" ? 36 : 24}>
      {kind === "tray" ? <TrayMenu /> : null}
      {kind === "toast" ? <ToastStack /> : null}
      {kind === "icon" ? <AppIconShowcase /> : null}
    </ThemedFrame>
  );
}

// Generic stage for floating modals/widgets centered on the grid backdrop.
function StageArtboard({ theme, shadow = false, children }) {
  return (
    <ThemedFrame theme={theme} padding={0}>
      <div className="artboard-stage popup-stage">
        <div className="artboard-stage-bg" />
        <div className={shadow ? "popup-shadow-wrap" : "stage-center"}>{children}</div>
      </div>
    </ThemedFrame>
  );
}

// Full-bleed window surface (settings window fills the frame).
function WindowArtboard({ theme, children }) {
  return (
    <ThemedFrame theme={theme} padding={28}>{children}</ThemedFrame>
  );
}

function ThemeSection({ theme }) {
  const meta = THEMES.find((t) => t.id === theme);
  return (
    <DCSection
      id={`section-${theme}`}
      title={`Direction · ${meta.name}`}
      subtitle={meta.blurb}
    >
      <DCArtboard id={`${theme}-popup-learn`} label="FloatingPopup · Learning mode (EN → VI)" width={640} height={560}>
        <PopupArtboard theme={theme} state="learning" hint="English source · IPA furigana · TTS available" />
      </DCArtboard>

      <DCArtboard id={`${theme}-popup-ja`} label="FloatingPopup · Translated (JA → VI · cached)" width={640} height={400}>
        <PopupArtboard theme={theme} state="ja-vi" hint="Non-Latin source · plain mode" />
      </DCArtboard>

      <DCArtboard id={`${theme}-popup-loading`} label="FloatingPopup · Loading" width={640} height={360}>
        <PopupArtboard theme={theme} state="loading" hint="OCR pipeline in progress" />
      </DCArtboard>

      <DCArtboard id={`${theme}-popup-error`} label="FloatingPopup · Error recovery" width={640} height={360}>
        <PopupArtboard theme={theme} state="error" hint="Provider failure with inline actions" />
      </DCArtboard>

      <DCArtboard id={`${theme}-region`} label="RegionSelector · mid-drag" width={960} height={560}>
        <FullscreenArtboard theme={theme} mode="region" />
      </DCArtboard>

      <DCArtboard id={`${theme}-overlay`} label="InlineOverlay · fullscreen translate (12 blocks)" width={960} height={560}>
        <FullscreenArtboard theme={theme} mode="overlay" />
      </DCArtboard>

      <DCArtboard id={`${theme}-settings-t`} label="Settings · Translation tab" width={820} height={680}>
        <SettingsArtboard theme={theme} tab="translation" />
      </DCArtboard>

      <DCArtboard id={`${theme}-settings-c`} label="Settings · Context preset (master-detail)" width={820} height={680}>
        <SettingsArtboard theme={theme} tab="context" />
      </DCArtboard>

      <DCArtboard id={`${theme}-settings-h`} label="Settings · Hotkeys" width={820} height={680}>
        <SettingsArtboard theme={theme} tab="hotkeys" />
      </DCArtboard>

      <DCArtboard id={`${theme}-tray`} label="Tray menu (right-click)" width={420} height={520}>
        <SystemArtboard theme={theme} kind="tray" />
      </DCArtboard>

      <DCArtboard id={`${theme}-toast`} label="Toast notifications" width={420} height={520}>
        <SystemArtboard theme={theme} kind="toast" />
      </DCArtboard>

      <DCArtboard id={`${theme}-icon`} label="App icon · wordmark" width={520} height={520}>
        <SystemArtboard theme={theme} kind="icon" />
      </DCArtboard>
    </DCSection>
  );
}

const THEME_ROW = [
  { id: "cobalt", tag: "Dark" },
  { id: "cobalt-light", tag: "Light" },
];

// ── Prompt 1 · Onboarding wizard ──────────────────────────────────────────
function OnboardingSection() {
  const steps = [
    { n: 1, name: "Welcome" },
    { n: 2, name: "Provider" },
    { n: 3, name: "Ngôn ngữ" },
    { n: 4, name: "Hotkey" },
    { n: 5, name: "Ready" },
  ];
  return (
    <DCSection id="onboarding" title="Onboarding · First-run wizard" subtitle="720×520 frameless · runs once · dark + light">
      {THEME_ROW.map((t) => [
        ...steps.map((s) => (
          <DCArtboard key={`${t.id}-onb-${s.n}`} id={`${t.id}-onb-${s.n}`} label={`${t.tag} · Step ${s.n} · ${s.name}`} width={784} height={596}>
            <StageArtboard theme={t.id}><OnboardingModal step={s.n} /></StageArtboard>
          </DCArtboard>
        )),
        <DCArtboard key={`${t.id}-onb-confirm`} id={`${t.id}-onb-confirm`} label={`${t.tag} · Esc confirm`} width={520} height={400}>
          <StageArtboard theme={t.id}><OnboardingConfirm /></StageArtboard>
        </DCArtboard>,
      ])}
    </DCSection>
  );
}

// ── Prompt 2 · Settings Display + Voice tabs ──────────────────────────────
function SettingsTabsSection() {
  return (
    <DCSection id="settings-tabs" title="Settings · Display + Voice tabs" subtitle="New tabs in SettingsWindow · dark + light">
      {THEME_ROW.map((t) => [
        <DCArtboard key={`${t.id}-set-display`} id={`${t.id}-set-display`} label={`${t.tag} · Display tab`} width={820} height={700}>
          <WindowArtboard theme={t.id}><SettingsWindow tab="display" /></WindowArtboard>
        </DCArtboard>,
        <DCArtboard key={`${t.id}-set-voice`} id={`${t.id}-set-voice`} label={`${t.tag} · Voice tab`} width={820} height={700}>
          <WindowArtboard theme={t.id}><SettingsWindow tab="voice" /></WindowArtboard>
        </DCArtboard>,
      ])}
    </DCSection>
  );
}

// ── Prompt 3 · Empty states + error variants ──────────────────────────────
function EmptyStatesSection() {
  return (
    <DCSection id="empty-states" title="Empty states & error variants" subtitle="No-text · network · empty preset · collision · invalid key">
      {THEME_ROW.map((t) => [
        <DCArtboard key={`${t.id}-empty-notext`} id={`${t.id}-empty-notext`} label={`${t.tag} · Popup · No text found`} width={620} height={360}>
          <StageArtboard theme={t.id} shadow><PopupNoText /></StageArtboard>
        </DCArtboard>,
        <DCArtboard key={`${t.id}-empty-network`} id={`${t.id}-empty-network`} label={`${t.tag} · Popup · Network down`} width={620} height={360}>
          <StageArtboard theme={t.id} shadow><PopupNetwork /></StageArtboard>
        </DCArtboard>,
        <DCArtboard key={`${t.id}-empty-preset`} id={`${t.id}-empty-preset`} label={`${t.tag} · Settings · Empty preset list`} width={820} height={700}>
          <WindowArtboard theme={t.id}><PresetEmpty /></WindowArtboard>
        </DCArtboard>,
        <DCArtboard key={`${t.id}-empty-collision`} id={`${t.id}-empty-collision`} label={`${t.tag} · Hotkey collision`} width={580} height={360}>
          <StageArtboard theme={t.id}><HotkeyCollision /></StageArtboard>
        </DCArtboard>,
        <DCArtboard key={`${t.id}-empty-toast`} id={`${t.id}-empty-toast`} label={`${t.tag} · Toast · API key invalid`} width={480} height={280}>
          <ThemedFrame theme={t.id} padding={0}>
            <div className="artboard-stage popup-stage"><div className="artboard-stage-bg" /><ApiKeyToast /></div>
          </ThemedFrame>
        </DCArtboard>,
      ])}
    </DCSection>
  );
}

// ── Prompt 4 · About dialog + License sheet ───────────────────────────────
function AboutSection() {
  const tabs = [
    { id: "info", name: "Thông tin" },
    { id: "ack", name: "Acknowledgements" },
    { id: "author", name: "Tác giả" },
  ];
  return (
    <DCSection id="about" title="About dialog + License" subtitle="480×600 modal · 3 internal tabs · dark + light">
      {THEME_ROW.map((t) => [
        ...tabs.map((tb) => (
          <DCArtboard key={`${t.id}-about-${tb.id}`} id={`${t.id}-about-${tb.id}`} label={`${t.tag} · About · ${tb.name}`} width={560} height={684}>
            <StageArtboard theme={t.id}><AboutDialog aboutTab={tb.id} /></StageArtboard>
          </DCArtboard>
        )),
        <DCArtboard key={`${t.id}-license`} id={`${t.id}-license`} label={`${t.tag} · License sheet`} width={560} height={684}>
          <StageArtboard theme={t.id}><LicenseSheet /></StageArtboard>
        </DCArtboard>,
      ])}
    </DCSection>
  );
}

// ── Prompt 5 · Pinned compact popup ───────────────────────────────────────
function PinnedSection() {
  return (
    <DCSection id="pinned" title="Pinned compact popup" subtitle="280×80 always-on-top widget · transition · empty">
      {THEME_ROW.map((t) => [
        <DCArtboard key={`${t.id}-pin`} id={`${t.id}-pin`} label={`${t.tag} · Pinned · resting`} width={400} height={220}>
          <StageArtboard theme={t.id}><PinnedPopup state="filled" /></StageArtboard>
        </DCArtboard>,
        <DCArtboard key={`${t.id}-pin-hover`} id={`${t.id}-pin-hover`} label={`${t.tag} · Pinned · hover`} width={400} height={220}>
          <StageArtboard theme={t.id}><PinnedPopup state="hover" /></StageArtboard>
        </DCArtboard>,
        <DCArtboard key={`${t.id}-pin-empty`} id={`${t.id}-pin-empty`} label={`${t.tag} · Pinned · empty / ready`} width={400} height={200}>
          <StageArtboard theme={t.id}><PinnedPopup state="empty" /></StageArtboard>
        </DCArtboard>,
        <DCArtboard key={`${t.id}-pin-trans`} id={`${t.id}-pin-trans`} label={`${t.tag} · Transition · full → pinned → expand`} width={760} height={260}>
          <ThemedFrame theme={t.id} padding={0}>
            <div className="artboard-stage popup-stage"><div className="artboard-stage-bg" /><PinnedTransition /></div>
          </ThemedFrame>
        </DCArtboard>,
      ])}
    </DCSection>
  );
}

function App() {
  return (
    <DesignCanvas>
      <ThemeSection theme="cobalt" />
      <ThemeSection theme="cobalt-light" />
      <OnboardingSection />
      <SettingsTabsSection />
      <EmptyStatesSection />
      <AboutSection />
      <PinnedSection />
    </DesignCanvas>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
