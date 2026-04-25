"use client";

import { useState, useEffect } from "react";

export function KillSwitch() {
  const [isOn, setIsOn] = useState<boolean | null>(null);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    fetch("/api/settings/kill-switch")
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (data) setIsOn(data.isOn ?? false);
      })
      .catch(() => {});
  }, []);

  const toggle = async () => {
    if (isOn === null || toggling) return;
    const newState = !isOn;
    setToggling(true);
    try {
      const res = await fetch("/api/settings/kill-switch", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled: newState })
      });
      if (res.ok) {
        setIsOn(newState);
      }
    } catch {
      // silent
    } finally {
      setToggling(false);
    }
  };

  if (isOn === null) return null;

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={toggling}
      style={{
        background: isOn ? "#7f1d1d" : "#14532d",
        color: isOn ? "#fca5a5" : "#86efac",
        border: isOn ? "1px solid #dc2626" : "1px solid #22c55e",
        borderRadius: "6px",
        padding: "6px 14px",
        fontSize: "12px",
        fontWeight: 600,
        cursor: toggling ? "wait" : "pointer",
        opacity: toggling ? 0.6 : 1
      }}
    >
      {isOn ? "KILL SWITCH: ON" : "Kill Switch: Off"}
    </button>
  );
}
