# Deribit options-inefficiency substrate: a keyless forward-only logger (logger.py + sink.py over deribit_client.py)
# that hoards OUR-OWN top-of-book, and a "camper" inefficiency scanner (scanner.py + campers.py) whose candidates
# only become real opportunities after the FillabilityModel (fillability.py) re-prices them at the executable touch
# with Deribit's maker==taker fee (fees.py). Forward-only, append-only, PIT, propose-only — no order ever placed.
# See README.md for which inefficiency classes a non-latency maker can realistically capture vs the mid-price mirages.

from __future__ import annotations

from cosmu.options.campers import (
    PutCallParityCamper,
    VerticalArbCamper,
    VolRiskPremiumCamper,
    default_campers,
)
from cosmu.options.chain import ChainSnapshot, OptionQuote, parse_book_summary, parse_instrument
from cosmu.options.deribit_client import DeribitClient
from cosmu.options.fees import DeribitOptionFees
from cosmu.options.fillability import FillabilityModel, FillVerdict
from cosmu.options.logger import DeribitOptionsLogger, PollResult
from cosmu.options.scanner import Camper, Candidate, Leg, Opportunity, run_scan
from cosmu.options.sink import LocalJsonlSink, snapshot_to_rows

__all__ = [
    "DeribitClient",
    "ChainSnapshot",
    "OptionQuote",
    "parse_book_summary",
    "parse_instrument",
    "DeribitOptionsLogger",
    "PollResult",
    "LocalJsonlSink",
    "snapshot_to_rows",
    "DeribitOptionFees",
    "FillabilityModel",
    "FillVerdict",
    "Candidate",
    "Camper",
    "Leg",
    "Opportunity",
    "run_scan",
    "PutCallParityCamper",
    "VerticalArbCamper",
    "VolRiskPremiumCamper",
    "default_campers",
]
