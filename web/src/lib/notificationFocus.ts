const NOTIFICATION_FOCUS_STORAGE_KEY = "maas:focused-notification";

export function setPendingNotificationFocus(notificationDigestId: string | null) {
  if (!notificationDigestId) {
    window.localStorage.removeItem(NOTIFICATION_FOCUS_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(NOTIFICATION_FOCUS_STORAGE_KEY, notificationDigestId);
}

export function consumePendingNotificationFocus() {
  const notificationDigestId = window.localStorage.getItem(NOTIFICATION_FOCUS_STORAGE_KEY);
  if (notificationDigestId) {
    window.localStorage.removeItem(NOTIFICATION_FOCUS_STORAGE_KEY);
  }
  return notificationDigestId;
}
