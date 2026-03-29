const AGENT_FOCUS_STORAGE_KEY = "maas:focused-agent";

export function setPendingAgentFocus(agentId: string | null) {
  if (!agentId) {
    window.localStorage.removeItem(AGENT_FOCUS_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(AGENT_FOCUS_STORAGE_KEY, agentId);
}

export function consumePendingAgentFocus() {
  const agentId = window.localStorage.getItem(AGENT_FOCUS_STORAGE_KEY);
  if (agentId) {
    window.localStorage.removeItem(AGENT_FOCUS_STORAGE_KEY);
  }
  return agentId;
}
