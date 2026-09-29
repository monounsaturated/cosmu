"use client";

// intent: every scenario at a glance. Click a card → it opens in the studio at the top of the page.

import { IDEAS, STOCK_PLATFORMS, CRYPTO_PLATFORMS, holdWords, pct, pickIdea, randomWords, results } from "@/lib/showcase";
import { Icon } from "./icon";

export function Gallery() {
  return (
    <div className="gallery">
      {IDEAS.map((idea) => {
        const r = results(idea, (idea.crypto ? CRYPTO_PLATFORMS : STOCK_PLATFORMS)[0]);
        const n = idea.trades.length;
        return (
          <button key={idea.key} className="g-card" onClick={() => pickIdea(idea.key)} type="button">
            <div className="g-top">
              <span className="g-icon"><Icon name={idea.icon} size={17} /></span>
              <span className="g-tag">{idea.spike ? `${n} spikes` : `${n} events`} · {holdWords(idea.hold_days)}</span>
            </div>
            <div className="g-q">{idea.q}</div>
            <div className="g-num">
              <b className={r.avg >= 0 ? "up" : "dn"}>{pct(r.avg)}</b>
              <span>vs {pct(r.randomMonth)} {randomWords(idea.hold_days).replace("Any random", "random")}</span>
            </div>
            <div className="g-stats">
              <span>{r.wins}/{n} made money</span>
              <span>Beats {Math.round(idea.beats_random * 100)}% of random timing</span>
            </div>
            <span className="g-open">Open <Icon name="arrow" size={13} /></span>
          </button>
        );
      })}
    </div>
  );
}
