const RUN_FOCUS_STORAGE_KEY = "maas:focused-run";

export function setPendingRunFocus(sessionId: string | null) {
  if (!sessionId) {
    window.localStorage.removeItem(RUN_FOCUS_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(RUN_FOCUS_STORAGE_KEY, sessionId);
}

export function consumePendingRunFocus() {
  const sessionId = window.localStorage.getItem(RUN_FOCUS_STORAGE_KEY);
  if (sessionId) {
    window.localStorage.removeItem(RUN_FOCUS_STORAGE_KEY);
  }
  return sessionId;
}
