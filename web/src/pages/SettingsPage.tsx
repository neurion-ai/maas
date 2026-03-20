type ThemeMode = "light" | "dark";

export function SettingsPage({
  theme,
  onThemeChange,
}: {
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
}) {
  return (
    <section className="codex-page">
      <header className="codex-page__header">
        <div>
          <span className="codex-kicker">Settings</span>
          <h1>Application settings</h1>
          <p>Global preferences belong here instead of being stranded inside the shell.</p>
        </div>
      </header>

      <section className="codex-panel codex-settings-panel">
        <div className="codex-panel__header">
          <div>
            <span className="codex-kicker">Appearance</span>
            <h2>Theme</h2>
            <p>Choose how MAAS should look across the whole app.</p>
          </div>
        </div>

        <div className="codex-settings-options">
          <button
            type="button"
            className={`codex-settings-option ${theme === "dark" ? "is-active" : ""}`}
            onClick={() => onThemeChange("dark")}
          >
            <strong>Dark</strong>
            <span>Default matte workspace for dense operational work.</span>
          </button>

          <button
            type="button"
            className={`codex-settings-option ${theme === "light" ? "is-active" : ""}`}
            onClick={() => onThemeChange("light")}
          >
            <strong>Light</strong>
            <span>Brighter mode for long reading and review sessions.</span>
          </button>
        </div>
      </section>
    </section>
  );
}
