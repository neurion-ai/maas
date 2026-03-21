type ThemeMode = "light" | "dark";

export function SettingsPage({
  theme,
  onThemeChange,
  desktopNotificationsEnabled,
  notificationPermission,
  notice,
  onToggleDesktopNotifications,
  onRequestDesktopNotifications,
}: {
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
  desktopNotificationsEnabled: boolean;
  notificationPermission: NotificationPermission;
  notice: string | null;
  onToggleDesktopNotifications: () => void;
  onRequestDesktopNotifications: () => void;
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

      {notice ? <div className="codex-banner">{notice}</div> : null}

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

      <section className="codex-panel codex-settings-panel">
        <div className="codex-panel__header">
          <div>
            <span className="codex-kicker">Notifications</span>
            <h2>Async operator loop</h2>
            <p>Let MAAS raise browser notifications when new review or failure pressure appears.</p>
          </div>
        </div>

        <div className="codex-settings-options">
          <button
            type="button"
            className={`codex-settings-option ${desktopNotificationsEnabled ? "is-active" : ""}`}
            onClick={onToggleDesktopNotifications}
          >
            <strong>{desktopNotificationsEnabled ? "Desktop notifications on" : "Desktop notifications off"}</strong>
            <span>
              Permission: {notificationPermission}. Use this for review queue and suspect-run alerts without staring at the UI.
            </span>
          </button>
          {notificationPermission !== "granted" ? (
            <button type="button" className="codex-settings-option" onClick={onRequestDesktopNotifications}>
              <strong>Request browser permission</strong>
              <span>Grant browser permission before enabling desktop alerts.</span>
            </button>
          ) : null}
        </div>
      </section>
    </section>
  );
}
