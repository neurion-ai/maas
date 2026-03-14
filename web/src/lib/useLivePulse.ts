import { useEffect, useState } from "react";

export function useLivePulse() {
  const [pulse, setPulse] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;

    function bumpPulse() {
      if (!cancelled) {
        setPulse((current) => current + 1);
      }
    }

    try {
      source = new EventSource("/api/live/stream");
      source.addEventListener("dashboard", bumpPulse);
      source.onerror = () => {
        source?.close();
      };
    } catch {
      source = null;
    }

    const timer = window.setInterval(bumpPulse, 15000);

    return () => {
      cancelled = true;
      source?.close();
      window.clearInterval(timer);
    };
  }, []);

  return pulse;
}
