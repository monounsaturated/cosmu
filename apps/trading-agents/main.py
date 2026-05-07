"""
TradingAgents FastAPI wrapper.
Exposes the TauricResearch/TradingAgents multi-agent pipeline as HTTP endpoints.
"""
import os
import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Cosmu TradingAgents Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

RESULTS_DIR = Path(os.environ.get("TRADINGAGENTS_RESULTS_DIR", Path.home() / ".tradingagents" / "logs"))


class AnalyzeRequest(BaseModel):
    ticker: str
    date: Optional[str] = None
    llm_provider: str = "openai"
    deep_think_llm: str = "gpt-4o-mini"
    quick_think_llm: str = "gpt-4o-mini"
    analysts: list[str] = ["market", "social", "news", "fundamentals"]
    max_debate_rounds: int = 1
    max_risk_discuss_rounds: int = 1


class AnalyzeResponse(BaseModel):
    ticker: str
    date: str
    decision: str
    market_report: Optional[str] = None
    sentiment_report: Optional[str] = None
    news_report: Optional[str] = None
    fundamentals_report: Optional[str] = None
    investment_plan: Optional[str] = None
    trader_decision: Optional[str] = None
    final_decision: Optional[str] = None
    status: str = "completed"


# In-memory store for running analyses
_running: dict[str, dict] = {}
_results: dict[str, AnalyzeResponse] = {}


def _run_analysis_sync(request_id: str, req: AnalyzeRequest) -> None:
    """Run the TradingAgents pipeline synchronously (called in a thread)."""
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.default_config import DEFAULT_CONFIG

        config = DEFAULT_CONFIG.copy()
        config["llm_provider"] = req.llm_provider
        config["deep_think_llm"] = req.deep_think_llm
        config["quick_think_llm"] = req.quick_think_llm
        config["max_debate_rounds"] = req.max_debate_rounds
        config["max_risk_discuss_rounds"] = req.max_risk_discuss_rounds

        analyst_map = {
            "market": "Market Analyst",
            "social": "Social Media Analyst",
            "news": "News Analyst",
            "fundamentals": "Fundamentals Analyst",
        }
        selected = [analyst_map[a] for a in req.analysts if a in analyst_map]

        ta = TradingAgentsGraph(debug=False, config=config, selected_analysts=selected)

        trade_date = req.date or datetime.now().strftime("%Y-%m-%d")
        final_state, decision = ta.propagate(req.ticker, trade_date)

        _results[request_id] = AnalyzeResponse(
            ticker=req.ticker,
            date=trade_date,
            decision=decision,
            market_report=final_state.get("market_report"),
            sentiment_report=final_state.get("sentiment_report"),
            news_report=final_state.get("news_report"),
            fundamentals_report=final_state.get("fundamentals_report"),
            investment_plan=final_state.get("investment_plan"),
            trader_decision=final_state.get("trader_investment_decision"),
            final_decision=final_state.get("final_trade_decision"),
            status="completed",
        )
    except Exception as e:
        _results[request_id] = AnalyzeResponse(
            ticker=req.ticker,
            date=req.date or datetime.now().strftime("%Y-%m-%d"),
            decision="error",
            final_decision=str(e),
            status="error",
        )
    finally:
        _running.pop(request_id, None)


@app.get("/health")
def health():
    return {"status": "ok", "service": "trading-agents"}


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    request_id = f"{req.ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if request_id in _running:
        return {"request_id": request_id, "status": "already_running"}

    _running[request_id] = {"ticker": req.ticker, "started": datetime.now().isoformat()}

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_analysis_sync, request_id, req)

    return {"request_id": request_id, "status": "started"}


@app.get("/status/{request_id}")
def get_status(request_id: str):
    if request_id in _results:
        return _results[request_id]
    if request_id in _running:
        return {"request_id": request_id, "status": "running", **_running[request_id]}
    raise HTTPException(status_code=404, detail="Analysis not found")


@app.get("/results")
def list_results():
    return [
        {"request_id": rid, "ticker": r.ticker, "date": r.date, "decision": r.decision, "status": r.status}
        for rid, r in sorted(_results.items(), reverse=True)
    ]


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("TRADING_AGENTS_PORT", "8100"))
    uvicorn.run(app, host="0.0.0.0", port=port)
