# core/prediction_model.py
import math
from trueskill import TrueSkill, Rating
from database.db_handler import DatabaseHandler
from datetime import datetime, timedelta
from core.models import Player

# Configuration
FORM_LOOKBACK_GAMES = 5  # Recent matches for momentum analysis
MODEL_A_WEIGHT = 0.5     # Weight for historical model
MODEL_B_WEIGHT = 0.5     # Weight for TrueSkill model

class EnhancedPredictor:
    def __init__(self, db_name='rankings.db'):
        self.db_handler = DatabaseHandler(db_name)
        self.trueskill_env = TrueSkill()

    # --------------------------
    # Core Prediction Method
    # --------------------------
    def predict_win_probability(self, player1_id: int, player2_id: int) -> dict:
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            
            try:
                # Get base player data
                p1 = self._get_player(player1_id, cursor)
                p2 = self._get_player(player2_id, cursor)
            except ValueError as e:
                raise e

            # Model A: Historical Analysis
            try:
                model_a = self._historical_model(p1.player_id, p2.player_id, cursor)
            except:
                model_a = 0.5  # Fallback if historical data missing

            # Model B: TrueSkill Analysis
            model_b = self._trueskill_model(p1, p2)

            # Blend predictions
            # Blend predictions
            blended = (MODEL_A_WEIGHT * model_a) + (MODEL_B_WEIGHT * model_b)
            blended = max(0.0, min(1.0, blended))  # Fixed line

            return {
                'player1_id': p1.player_id,
                'player1_name': p1.name,
                'player2_id': p2.player_id,
                'player2_name': p2.name,
                'model_a': model_a,
                'model_b': model_b,
                'final_prediction': blended,
                'model_weights': {'historical': MODEL_A_WEIGHT, 'trueskill': MODEL_B_WEIGHT}
            }

    # --------------------------
    # Historical Model (Model A)
    # --------------------------
    def _historical_model(self, p1_id: int, p2_id: int, cursor) -> float:
        """Combines gross WR, momentum, and head-to-head stats"""
        components = {
            'gross': self._get_gross_win_rate(p1_id, p2_id, cursor),
            'momentum': self._get_momentum(p1_id, p2_id, cursor),
            'h2h': self._get_h2h_win_rate(p1_id, p2_id, cursor)
        }
        
        # Weighted average (adjust weights as needed)
        return (
            0.4 * components['h2h'] +
            0.4 * components['momentum'] +
            0.2 * components['gross']
        )

    def _get_gross_win_rate(self, p1_id: int, p2_id: int, cursor) -> float:
        """Overall win rate comparison"""
        p1_wr = self._calculate_win_rate(p1_id, cursor)
        p2_wr = self._calculate_win_rate(p2_id, cursor)
        
        if p1_wr + p2_wr == 0:
            return 0.5
        return p1_wr / (p1_wr + p2_wr)

    def _get_momentum(self, p1_id: int, p2_id: int, cursor) -> float:
        """Recent performance comparison (last N games)"""
        p1_momentum = self._calculate_recent_win_rate(p1_id, cursor)
        p2_momentum = self._calculate_recent_win_rate(p2_id, cursor)
        
        if p1_momentum + p2_momentum == 0:
            return 0.5
        return p1_momentum / (p1_momentum + p2_momentum)

    def _get_h2h_win_rate(self, p1_id: int, p2_id: int, cursor) -> float:
        """Head-to-head win rate between these players"""
        cursor.execute('''
            SELECT COUNT(*),
                SUM(CASE WHEN (player1_id = ? AND player1_score > player2_score) OR
                            (player2_id = ? AND player2_score > player1_score)
                        THEN 1 ELSE 0 END)
            FROM matches
            WHERE (player1_id = ? AND player2_id = ?)
               OR (player2_id = ? AND player1_id = ?)
        ''', (p1_id, p1_id, p1_id, p2_id, p1_id, p2_id))
        
        total, wins = cursor.fetchone()
        return wins / total if total > 0 else 0.5

    # --------------------------
    # TrueSkill Model (Model B)
    # --------------------------
    def _trueskill_model(self, p1: Player, p2: Player) -> float:
        """Pure TrueSkill prediction"""
        delta_mu = p1.mu - p2.mu
        sum_sigma = p1.sigma**2 + p2.sigma**2
        beta_sq = self.trueskill_env.beta**2
        denominator = math.sqrt(2 * beta_sq + sum_sigma)

        if abs(denominator) < 1e-9:
            return 0.5
        return 1 / (1 + math.exp(-delta_mu / denominator))

    # --------------------------
    # Helper Methods
    # --------------------------
    def _calculate_win_rate(self, player_id: int, cursor) -> float:
        """Overall win rate for a single player"""
        cursor.execute('''
            SELECT COUNT(*),
                SUM(CASE WHEN (player1_id = ? AND player1_score > player2_score) OR
                            (player2_id = ? AND player2_score > player1_score)
                        THEN 1 ELSE 0 END)
            FROM matches
            WHERE player1_id = ? OR player2_id = ?
        ''', (player_id, player_id, player_id, player_id))
        
        total, wins = cursor.fetchone()
        return wins / total if total > 0 else 0.0

    def _calculate_recent_win_rate(self, player_id: int, cursor) -> float:
        """Win rate in last N matches"""
        cursor.execute('''
            SELECT player1_score, player2_score 
            FROM matches
            WHERE player1_id = ? OR player2_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (player_id, player_id, FORM_LOOKBACK_GAMES))
        
        wins = 0
        for score1, score2 in cursor.fetchall():
            if (score1 > score2 and player_id == score1) or (score2 > score1 and player_id == score2):
                wins += 1
        return wins / FORM_LOOKBACK_GAMES if FORM_LOOKBACK_GAMES > 0 else 0.0

    def _get_player(self, player_id: int, cursor) -> Player:
        """Fetch player with error handling"""
        cursor.execute('''
            SELECT player_id, name, mu, sigma 
            FROM players 
            WHERE player_id = ?
        ''', (player_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Player {player_id} not found")
        return Player(player_id=row[0], name=row[1], mu=row[2], sigma=row[3], last_updated=datetime.now())