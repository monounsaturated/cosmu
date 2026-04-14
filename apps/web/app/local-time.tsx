"use client";

import { useEffect, useState } from "react";

type LocalTimeProps = {
  value: string;
  mode?: "datetime" | "date";
};

export function LocalTime({ value, mode = "datetime" }: LocalTimeProps) {
  const [text, setText] = useState("—");

  useEffect(() => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      setText("—");
      return;
    }
    if (mode === "date") {
      setText(date.toLocaleDateString());
      return;
    }
    setText(date.toLocaleString());
  }, [mode, value]);

  return <span>{text}</span>;
}
