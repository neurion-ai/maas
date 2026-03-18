const TASK_FOCUS_STORAGE_KEY = "maas:focused-task";

export function setPendingTaskFocus(taskId: string | null) {
  if (!taskId) {
    window.localStorage.removeItem(TASK_FOCUS_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(TASK_FOCUS_STORAGE_KEY, taskId);
}

export function consumePendingTaskFocus() {
  const taskId = window.localStorage.getItem(TASK_FOCUS_STORAGE_KEY);
  if (taskId) {
    window.localStorage.removeItem(TASK_FOCUS_STORAGE_KEY);
  }
  return taskId;
}
