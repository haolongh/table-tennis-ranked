from dataclasses import dataclass
from datetime import datetime

@dataclass
class Player:
    player_id: int
    name: str
    mu: float
    sigma: float
    last_updated: datetime

@dataclass
class Match:
    match_id: int
    player1_id: int
    player2_id: int
    player1_score: int
    player2_score: int
    timestamp: datetime