from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Dict, Optional

from datetime import datetime, timedelta


class RecordOwnner(Enum):
    CLOUDFLARE = auto()
    AZURE = auto()
    GOOGLE = auto()

@dataclass
class DNSRecord:
    name: str
    rtype: str
    ttl: int
    values: List[str]
    owner: RecordOwnner
    proxy: bool
    observed_at: datetime 

