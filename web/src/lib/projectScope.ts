const PROJECT_SCOPE_STORAGE_KEY = "maas:selected-project-id";
const PROJECT_SCOPE_EVENT = "maas:project-scope-changed";

export function getSelectedProjectId(): string | null {
  return window.localStorage.getItem(PROJECT_SCOPE_STORAGE_KEY);
}

export function setSelectedProjectId(projectId: string | null) {
  if (projectId) {
    window.localStorage.setItem(PROJECT_SCOPE_STORAGE_KEY, projectId);
  } else {
    window.localStorage.removeItem(PROJECT_SCOPE_STORAGE_KEY);
  }
  window.dispatchEvent(new CustomEvent(PROJECT_SCOPE_EVENT, { detail: projectId }));
}

export function subscribeProjectScope(listener: (projectId: string | null) => void) {
  function handleProjectScopeChange(event: Event) {
    const customEvent = event as CustomEvent<string | null>;
    listener(customEvent.detail ?? getSelectedProjectId());
  }

  function handleStorage(event: StorageEvent) {
    if (event.key === PROJECT_SCOPE_STORAGE_KEY) {
      listener(event.newValue);
    }
  }

  window.addEventListener(PROJECT_SCOPE_EVENT, handleProjectScopeChange);
  window.addEventListener("storage", handleStorage);
  return () => {
    window.removeEventListener(PROJECT_SCOPE_EVENT, handleProjectScopeChange);
    window.removeEventListener("storage", handleStorage);
  };
}

export function appendProjectScope(path: string, projectId = getSelectedProjectId()) {
  if (!projectId) {
    return path;
  }
  const url = new URL(path, window.location.origin);
  url.searchParams.set("project_id", projectId);
  return `${url.pathname}${url.search}`;
}
