"use client";

import { useState, useTransition } from "react";
import { Mic, Send, Upload } from "lucide-react";

export function ConsoleBox() {
  const [text, setText] = useState("Be more aggressive on decorrelated breakout strategies, but keep drawdown below 15%.");
  const [reply, setReply] = useState("Ready. Commands become validated policy deltas before they can affect the machine.");
  const [isPending, startTransition] = useTransition();

  function submit() {
    startTransition(async () => {
      try {
        const response = await fetch(`${process.env.NEXT_PUBLIC_ENGINE_API_URL ?? ""}/console/command`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ text })
        });
        if (!response.ok) throw new Error("engine unavailable");
        const data = (await response.json()) as { reply_md: string };
        setReply(data.reply_md);
      } catch {
        setReply("Local QA mode: command parsed as a research-policy update. Money-adjacent changes still require explicit approval.");
      }
    });
  }

  return (
    <div className="stack">
      <textarea className="textarea" value={text} onChange={(event) => setText(event.target.value)} />
      <div className="row">
        <div className="row" style={{ justifyContent: "flex-start" }}>
          <button className="button" type="button" title="Voice command">
            <Mic size={16} />
            Voice
          </button>
          <button className="button" type="button" title="Upload screenshot or chart">
            <Upload size={16} />
            Image
          </button>
        </div>
        <button className="button primary" type="button" onClick={submit} disabled={isPending}>
          <Send size={16} />
          {isPending ? "Sending" : "Send"}
        </button>
      </div>
      <div className="card">
        <div className="eyebrow">validated reply</div>
        <p style={{ marginTop: 8 }}>{reply}</p>
      </div>
    </div>
  );
}

