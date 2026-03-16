import { useEffect, useState } from "react";

export function useLivePulse() {
  const [pulse, setPulse] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;
    let socket: WebSocket | null = null;
    let timer: number | null = null;

    function bumpPulse() {
      if (!cancelled) {
        setPulse((current) => current + 1);
      }
    }

    function startPollingFallback() {
      if (timer != null) {
        return;
      }
      timer = window.setInterval(bumpPulse, 15000);
    }

    function startSseFallback() {
      if (cancelled || source) {
        return;
      }
      try {
        source = new EventSource("/api/live/stream");
        source.addEventListener("dashboard", bumpPulse);
        source.onerror = () => {
          source?.close();
          source = null;
          startPollingFallback();
        };
      } catch {
        source = null;
        startPollingFallback();
      }
    }

    try {
      socket = new WebSocket(`${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/api/live/ws`);
      socket.onmessage = bumpPulse;
      socket.onerror = () => {
        socket?.close();
      };
      socket.onclose = () => {
        socket = null;
        startSseFallback();
      };
    } catch {
      socket = null;
      startSseFallback();
    }

    return () => {
      cancelled = true;
      socket?.close();
      source?.close();
      if (timer != null) {
        window.clearInterval(timer);
      }
    };
  }, []);

  return pulse;
}
