# intent: a small library of realistic community-style Pine strategies used to exercise + demo the translator; inputs: none; outputs: named pine source snippets; invariants: each must translate to a valid StrategySpec (asserted in tests).

from __future__ import annotations

PINE_SAMPLES: dict[str, str] = {
    "RSI oversold reversion": """//@version=5
strategy("RSI Oversold Reversion", overlay=true)
rsiLen = input.int(14, "RSI Length")
oversold = input.int(30, "Oversold")
rsiVal = ta.rsi(close, rsiLen)
longCondition = ta.crossover(rsiVal, oversold)
if longCondition
    strategy.entry("Long", strategy.long)
strategy.exit("Exit", "Long", stop=0.04, limit=0.10)
""",
    "MACD momentum": """//@version=5
strategy("MACD Momentum", overlay=false)
[macdLine, signalLine, _] = ta.macd(close, 12, 26, 9)
longCondition = ta.crossover(macdLine, signalLine)
strategy.entry("L", strategy.long, when=longCondition)
strategy.exit("X", stop=0.05, limit=0.12)
""",
    "Golden cross trend": """//@version=5
strategy("Golden Cross", overlay=true)
fastLen = input.int(50)
slowLen = input.int(200)
fast = ta.sma(close, fastLen)
slow = ta.sma(close, slowLen)
longCondition = ta.crossover(fast, slow)
strategy.entry("Long", strategy.long, when=longCondition)
strategy.exit("Exit", stop=0.08, limit=0.2)
""",
    "Bollinger breakout": """//@version=5
strategy("Bollinger Breakout", overlay=true)
length = input.int(20)
mult = input.float(2.0)
basis = ta.sma(close, length)
dev = mult * ta.stdev(close, length)
upper = basis + dev
longCondition = close > upper
strategy.entry("L", strategy.long, when=longCondition)
strategy.exit("X", stop=0.05, limit=0.15)
""",
    "ADX trend filter": """//@version=5
strategy("ADX Trend", overlay=true)
adxLen = input.int(14)
adxVal = ta.adx(adxLen)
rsiVal = ta.rsi(close, 14)
longCondition = adxVal > 25 and rsiVal > 50
strategy.entry("L", strategy.long, when=longCondition)
strategy.exit("X", stop=0.06, limit=0.14)
""",
}
