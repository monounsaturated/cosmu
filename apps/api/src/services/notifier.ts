// module: Fire-and-forget Slack notifications.
import { env } from "../env.js";

const postToSlack = async (text: string) => {
  if (!env.SLACK_WEBHOOK_URL) {
    return;
  }

  await fetch(env.SLACK_WEBHOOK_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text })
  });
};

export const notifySlack = async (text: string) => {
  try {
    await postToSlack(text);
  } catch (error) {
    console.error("Slack notification failed", error);
  }
};
