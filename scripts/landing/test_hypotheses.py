# intent: guard the three promises the landing page makes about its method, on synthetic prices (no network):
#   1) no hindsight: the buy is at the close of the first session STRICTLY AFTER the news day;
#   2) costs: every trade pays the round-trip cost;
#   3) fair baseline: random entry dates are drawn from the same stretch of time as the events.
# usage: python3 -m unittest -q test_hypotheses   (from scripts/landing)
import unittest
from datetime import date, timedelta

import hypotheses as hx


def business_days(n, start=date(2021, 1, 4)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self._px, self._hyp = dict(hx.PX), dict(hx.HYP)

    def tearDown(self):
        hx.PX.clear(); hx.PX.update(self._px)
        hx.HYP.clear(); hx.HYP.update(self._hyp)

    def test_buys_strictly_after_the_news_day(self):
        days = business_days(60)
        hx.PX["TST"] = (days, [100.0 + i for i in range(60)])
        hx.HYP["t_after"] = {"q": "t", "events": [(days[10], "TST", "news on a trading day")]}
        trade = hx.run("t_after", h=5, draws=10)["trades"][0]
        self.assertEqual(trade["fill"], days[11])  # never the news day's own close
        self.assertGreater(trade["fill"], trade["news"])

    def test_every_trade_pays_the_round_trip_cost(self):
        days = business_days(60)
        hx.PX["TST"] = (days, [100.0] * 60)  # flat prices: the only return is the cost
        hx.HYP["t_cost"] = {"q": "t", "events": [(days[10], "TST", "x"), (days[30], "TST", "y")]}
        r = hx.run("t_cost", h=5, draws=10)
        for t in r["trades"]:
            self.assertAlmostEqual(t["ret"], -hx.DEFAULT_COST, places=6)

    def test_random_baseline_comes_from_the_same_period(self):
        # first 500 sessions rise 1%/day, the next 500 are flat; events sit deep in the flat part,
        # so an honest same-period baseline must be flat too (a whole-history baseline would not be).
        days = business_days(1000)
        prices = [100.0 * 1.01 ** min(i, 500) for i in range(1000)]
        hx.PX["TST"] = (days, prices)
        hx.HYP["t_window"] = {"q": "t", "events": [(days[i], "TST", "e") for i in (700, 740, 780)]}
        r = hx.run("t_window", h=5, draws=500)
        self.assertAlmostEqual(r["rand_mean"], -hx.DEFAULT_COST, places=6)


if __name__ == "__main__":
    unittest.main()
