import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

type LiveTransport = "websocket" | "sse" | "polling";

interface LivePulseContextValue {
  pulse: number;
  transport: LiveTransport;
  connected: boolean;
}

const LivePulseContext = createContext<LivePulseContextValue | null>(null);

function buildLiveWebsocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/api/live/ws`;
}

export function LivePulseProvider({ children }: { children: ReactNode }) {
  const [pulse, setPulse] = useState(0);
  const [transport, setTransport] = useState<LiveTransport>("polling");
  const [connected, setConnected] = useState(false);

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

    function stopPollingFallback() {
      if (timer == null) {
        return;
      }
      window.clearInterval(timer);
      timer = null;
    }

    function clearSseSource() {
      source?.close();
      source = null;
    }

    function clearWebsocket() {
      socket?.close();
      socket = null;
    }

    function connectWebsocket() {
      if (cancelled || socket || source) {
        return;
      }
      try {
        setTransport("websocket");
        setConnected(false);
        socket = new WebSocket(buildLiveWebsocketUrl());
        socket.onopen = () => {
          if (cancelled) {
            return;
          }
          stopPollingFallback();
          setTransport("websocket");
          setConnected(true);
        };
        socket.onmessage = bumpPulse;
        socket.onerror = () => {
          socket?.close();
        };
        socket.onclose = () => {
          socket = null;
          if (!cancelled) {
            startSseFallback();
          }
        };
      } catch {
        socket = null;
        startSseFallback();
      }
    }

    function startPollingFallback() {
      if (cancelled || timer != null || socket || source) {
        return;
      }
      setTransport("polling");
      setConnected(false);
      timer = window.setInterval(() => {
        bumpPulse();
        connectWebsocket();
      }, 15000);
    }

    function startSseFallback() {
      if (cancelled || source) {
        return;
      }
      try {
        setTransport("sse");
        setConnected(false);
        source = new EventSource("/api/live/stream");
        source.onopen = () => {
          if (cancelled) {
            return;
          }
          stopPollingFallback();
          setTransport("sse");
          setConnected(true);
        };
        source.addEventListener("dashboard", bumpPulse);
        source.onerror = () => {
          clearSseSource();
          startPollingFallback();
        };
      } catch {
        source = null;
        startPollingFallback();
      }
    }

    connectWebsocket();

    return () => {
      cancelled = true;
      clearWebsocket();
      clearSseSource();
      stopPollingFallback();
    };
  }, []);

  const value = useMemo(
    () => ({
      pulse,
      transport,
      connected,
    }),
    [connected, pulse, transport]
  );

  return <LivePulseContext.Provider value={value}>{children}</LivePulseContext.Provider>;
}

export function useLivePulse() {
  return useLiveStatus().pulse;
}

export function useLiveStatus() {
  const context = useContext(LivePulseContext);
  if (!context) {
    throw new Error("useLiveStatus must be used within a LivePulseProvider");
  }
  return context;
}
