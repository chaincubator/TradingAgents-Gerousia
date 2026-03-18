from enum import Enum
from typing import List, Optional, Dict
from pydantic import BaseModel


class AnalystType(str, Enum):
    MARKET = "market"
    MARKET_4H = "market_4h"
    SOCIAL = "social"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"
