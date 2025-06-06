# core/match_processor.py
import math
from trueskill import Rating, TrueSkill
from datetime import datetime
from database.db_handler import DatabaseHandler
from core.models import Player, Match
from core.trueskill_setup import TrueSkillSystem

class MatchProcessor:
    def __init__(self, db_name='rankings.db'):
        self.db_handler = DatabaseHandler(db_name)
        self.trueskill = TrueSkillSystem()
        self.trueskill_env = TrueSkill()

    def add_player(self, name: str) -> Player:
        rating = self.trueskill.create_rating()
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO players (name, mu, sigma)
                VALUES (?, ?, ?)
            ''', (name, rating.mu, rating.sigma))
            
            return Player(
                player_id=cursor.lastrowid,
                name=name,
                mu=rating.mu,
                sigma=rating.sigma,
                last_updated=datetime.now()
            )

    def record_match(self, player1_id: int, player2_id: int, 
                    score1: int, score2: int) -> Match:
        if score1 == score2:
            raise ValueError("Draws are not allowed")

        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            
            # Get current ratings first
            p1 = self._get_player(player1_id, cursor)
            p2 = self._get_player(player2_id, cursor)

            # Create the match record
            cursor.execute('''
                INSERT INTO matches 
                (player1_id, player2_id, player1_score, player2_score, season)
                VALUES (?, ?, ?, ?, ?)
            ''', (player1_id, player2_id, score1, score2, self._get_current_season(cursor)))
            match_id = cursor.lastrowid

            # Store historical ratings
            cursor.execute('''
                INSERT INTO ratings_history (player_id, match_id, mu, sigma)
                VALUES (?, ?, ?, ?)
            ''', (player1_id, match_id, p1.mu, p1.sigma))
            cursor.execute('''
                INSERT INTO ratings_history (player_id, match_id, mu, sigma)
                VALUES (?, ?, ?, ?)
            ''', (player2_id, match_id, p2.mu, p2.sigma))

            # Process ratings update
            winner = 1 if score1 > score2 else 2
            new_p1, new_p2 = self.trueskill.rate_match(
                Rating(p1.mu, p1.sigma),
                Rating(p2.mu, p2.sigma),
                winner
            )

            # Update player ratings
            cursor.execute('''
                UPDATE players 
                SET mu = ?, sigma = ?, last_updated = ?
                WHERE player_id = ?
            ''', (new_p1.mu, new_p1.sigma, datetime.now(), player1_id))
            cursor.execute('''
                UPDATE players 
                SET mu = ?, sigma = ?, last_updated = ?
                WHERE player_id = ?
            ''', (new_p2.mu, new_p2.sigma, datetime.now(), player2_id))

            # Update matchup stats
            self._update_matchup_stats(player1_id, player2_id, winner, cursor)
            
            return Match(
                match_id=match_id,
                player1_id=player1_id,
                player2_id=player2_id,
                player1_score=score1,
                player2_score=score2,
                timestamp=datetime.now()
            )

    def delete_match(self, match_id: int):
        """Delete match and restore ratings"""
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            
            # 1. Get full match details including scores
            cursor.execute('''
                SELECT player1_id, player2_id, player1_score, player2_score 
                FROM matches WHERE match_id = ?
            ''', (match_id,))
            match_data = cursor.fetchone()
            if not match_data:
                raise ValueError(f"Match {match_id} not found")
                
            p1_id, p2_id, score1, score2 = match_data

            # 2. Determine original winner and matchup order
            original_winner = 1 if score1 > score2 else 2
            a, b = sorted((p1_id, p2_id))
            is_reversed = p1_id != a

            # 3. Update matchups table
            # Calculate which wins to decrement
            if original_winner == 1:
                decrement_wins_a = 1 if not is_reversed else 0
                decrement_wins_b = 1 if is_reversed else 0
            else:
                decrement_wins_a = 1 if is_reversed else 0
                decrement_wins_b = 1 if not is_reversed else 0

            # Update or delete the matchup record
            cursor.execute('''
                UPDATE matchups 
                SET matches_played = matches_played - 1,
                    wins_a = wins_a - ?,
                    wins_b = wins_b - ?
                WHERE player_a_id = ? AND player_b_id = ?
            ''', (decrement_wins_a, decrement_wins_b, a, b))

            # Cleanup if no matches left
            cursor.execute('''
                DELETE FROM matchups 
                WHERE player_a_id = ? AND player_b_id = ? 
                AND matches_played <= 0
            ''', (a, b))

            # 4. Proceed with original deletion logic
            cursor.execute('DELETE FROM ratings_history WHERE match_id = ?', (match_id,))
            cursor.execute('DELETE FROM matches WHERE match_id = ?', (match_id,))


            # Restore player ratings
            cursor.execute('SELECT mu, sigma FROM players WHERE player_id = ?', (p1_id,))
            p1_mu, p1_sigma = cursor.fetchone()
            cursor.execute('SELECT mu, sigma FROM players WHERE player_id = ?', (p2_id,))
            p2_mu, p2_sigma = cursor.fetchone()

            cursor.execute('''
                UPDATE players 
                SET mu = ?, sigma = ?
                WHERE player_id = ?
            ''', (p1_mu, p1_sigma, p1_id))
            cursor.execute('''
                UPDATE players 
                SET mu = ?, sigma = ?
                WHERE player_id = ?
            ''', (p2_mu, p2_sigma, p2_id))

            # Recalculate subsequent matches
            self._recalculate_all_ratings(conn)

    def _recalculate_all_ratings(self, conn):
        """Full ratings recalculation from scratch"""
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE players 
            SET mu = 25.0, 
                sigma = 8.333,
                last_updated = datetime('now')
        ''')
        
        cursor.execute('''
            SELECT match_id, player1_id, player2_id, player1_score, player2_score
            FROM matches 
            ORDER BY timestamp ASC
        ''')
        
        for match in cursor.fetchall():
            match_id, p1_id, p2_id, score1, score2 = match
            
            p1 = self._get_player(p1_id, cursor)
            p2 = self._get_player(p2_id, cursor)
            
            winner = 1 if score1 > score2 else 2
            new_p1, new_p2 = self.trueskill.rate_match(
                Rating(p1.mu, p1.sigma),
                Rating(p2.mu, p2.sigma),
                winner
            )
            
            cursor.execute('''
                UPDATE players 
                SET mu = ?, sigma = ?
                WHERE player_id = ?
            ''', (new_p1.mu, new_p1.sigma, p1_id))
            cursor.execute('''
                UPDATE players 
                SET mu = ?, sigma = ?
                WHERE player_id = ?
            ''', (new_p2.mu, new_p2.sigma, p2_id))

    def _get_player(self, player_id: int, cursor) -> Player:
        cursor.execute('''
            SELECT player_id, name, mu, sigma, last_updated
            FROM players WHERE player_id = ?
        ''', (player_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Player {player_id} not found")
        return Player(player_id=row[0], name=row[1], mu=row[2], sigma=row[3], last_updated=row[4])

    def _update_matchup_stats(self, p1_id: int, p2_id: int, winner: int, cursor):
        a, b = sorted((p1_id, p2_id))
        is_reversed = p1_id != a
        
        cursor.execute('''
            INSERT INTO matchups (player_a_id, player_b_id, matches_played, wins_a, wins_b)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(player_a_id, player_b_id) DO UPDATE SET
                matches_played = matches_played + 1,
                wins_a = wins_a + excluded.wins_a,
                wins_b = wins_b + excluded.wins_b
        ''', (
            a, b,
            (1 if (winner == 1 and not is_reversed) or (winner == 2 and is_reversed) else 0),
            (1 if (winner == 2 and not is_reversed) or (winner == 1 and is_reversed) else 0)
        ))

    def get_ladder(self) -> list[Player]:
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT player_id, name, mu, sigma, last_updated 
                FROM players 
                ORDER BY (mu - 3*sigma) DESC
            ''')
            return [Player(*row) for row in cursor.fetchall()]

    def get_head_to_head(self, player1_id: int, player2_id: int) -> dict:
        a, b = sorted((player1_id, player2_id))
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT matches_played, wins_a, wins_b 
                FROM matchups 
                WHERE player_a_id = ? AND player_b_id = ?
            ''', (a, b))
            result = cursor.fetchone()

            total_matches = result[0] if result else 0
            wins_a = result[1] if result else 0
            wins_b = result[2] if result else 0

            # Remap wins to match the order user selected
            if player1_id == a:
                wins_player1 = wins_a
                wins_player2 = wins_b
            else:
                wins_player1 = wins_b
                wins_player2 = wins_a

            return {
                'total_matches': total_matches,
                'wins_player1': wins_player1,
                'wins_player2': wins_player2,
                'player1_id': player1_id,
                'player2_id': player2_id
            }

        
    def remove_player(self, player_id: int):
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM players WHERE player_id = ?', (player_id,))

    def get_match_history(self, player_id: int) -> list[dict]:
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.timestamp, 
                    p1.player_id, p1.name, m.player1_score,
                    p2.player_id, p2.name, m.player2_score
                FROM matches m
                JOIN players p1 ON m.player1_id = p1.player_id
                JOIN players p2 ON m.player2_id = p2.player_id
                WHERE m.player1_id = ? OR m.player2_id = ?
                ORDER BY m.timestamp DESC
            ''', (player_id, player_id))
            rows = cursor.fetchall()

        return [{
            'date': row[0],
            'player1_id': row[1],
            'player1': row[2],
            'score1': row[3],
            'player2_id': row[4],
            'player2': row[5],
            'score2': row[6],
            'is_win': (row[3] > row[6]) if (row[1] == player_id) else (row[6] > row[3])
        } for row in rows]

    def get_recent_matches(self, limit=10) -> list[dict]:
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.match_id, m.timestamp,
                    p1.player_id, p1.name, m.player1_score,
                    p2.player_id, p2.name, m.player2_score
                FROM matches m
                JOIN players p1 ON m.player1_id = p1.player_id
                JOIN players p2 ON m.player2_id = p2.player_id
                ORDER BY m.timestamp DESC
                LIMIT ?
            ''', (limit,))
            return [{
                'match_id': row[0],
                'date': row[1],
                'player1_id': row[2],
                'player1': row[3],
                'score1': row[4],
                'player2_id': row[5],
                'player2': row[6],
                'score2': row[7]
            } for row in cursor.fetchall()]

    def get_ratings_by_match(self, match_id: int) -> list[dict]:
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT player_id, mu
                FROM ratings_history
                WHERE match_id = ?
            ''', (match_id,))
            return [{'player_id': row[0], 'mu': row[1]} for row in cursor.fetchall()]
        
    def get_win_loss_table(self) -> list[dict]:
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    p.player_id,
                    p.name,
                    COUNT(m.match_id) AS matches_played,
                    SUM(CASE 
                        WHEN (m.player1_id = p.player_id AND m.player1_score > m.player2_score) OR 
                            (m.player2_id = p.player_id AND m.player2_score > m.player1_score) 
                        THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE 
                        WHEN (m.player1_id = p.player_id AND m.player1_score < m.player2_score) OR 
                            (m.player2_id = p.player_id AND m.player2_score < m.player1_score) 
                        THEN 1 ELSE 0 END) AS losses
                FROM players p
                LEFT JOIN matches m 
                    ON p.player_id = m.player1_id OR p.player_id = m.player2_id
                GROUP BY p.player_id, p.name
            ''')
            
            table = []
            for row in cursor.fetchall():
                player_id, name, played, wins, losses = row
                win_pct = (wins / played * 100) if played > 0 else 0.0
                table.append({
                    'name': name,
                    'played': played,
                    'wins': wins,
                    'losses': losses,
                    'win_pct': round(win_pct, 1)
                })
            
            # Sort by win percentage (descending), then wins, then played
            return sorted(table, key=lambda x: (-x['win_pct'], -x['wins'], -x['played']))
        
    def clear_all_data(self):
        """Delete ALL data from the database"""
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            # Order matters due to foreign key constraints
            cursor.execute('DELETE FROM ratings_history')
            cursor.execute('DELETE FROM matches')
            cursor.execute('DELETE FROM matchups')
            cursor.execute('DELETE FROM players')
            conn.commit()

    def get_player_stats(self, player_id: int) -> dict:
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            
            # Basic player info
            player = self._get_player(player_id, cursor)
            
            # Peak rating
            cursor.execute('''
                SELECT MAX(mu) FROM ratings_history 
                WHERE player_id = ?
            ''', (player_id,))
            peak_rating = cursor.fetchone()[0] or player.mu

            # Match statistics
            cursor.execute('''
                SELECT 
                    COUNT(*) AS total_matches,
                    SUM(CASE 
                        WHEN (player1_id = ? AND player1_score > player2_score) OR
                            (player2_id = ? AND player2_score > player1_score)
                        THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE 
                        WHEN (player1_id = ? AND player1_score < player2_score) OR
                            (player2_id = ? AND player2_score < player1_score)
                        THEN 1 ELSE 0 END) AS losses
                FROM matches
                WHERE player1_id = ? OR player2_id = ?
            ''', (player_id, player_id, player_id, player_id, player_id, player_id))
            total, wins, losses = cursor.fetchone()
            total = total or 0
            wins = wins or 0
            losses = losses or 0

            # Opponent analysis
            cursor.execute('''
                SELECT 
                    CASE WHEN m.player1_id = ? THEN m.player2_id ELSE m.player1_id END AS opponent_id,
                    COUNT(*) AS matches,
                    SUM(CASE 
                        WHEN (m.player1_id = ? AND m.player1_score > m.player2_score) OR
                            (m.player2_id = ? AND m.player2_score > m.player1_score)
                        THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE 
                        WHEN (m.player1_id = ? AND m.player1_score < m.player2_score) OR
                            (m.player2_id = ? AND m.player2_score < m.player1_score)
                        THEN 1 ELSE 0 END) AS losses
                FROM matches m
                WHERE ? IN (m.player1_id, m.player2_id)
                GROUP BY opponent_id
            ''', (player_id, player_id, player_id, player_id, player_id, player_id))
            
            opponents = []
            for row in cursor.fetchall():
                opp_id, matches, w, l = row
                cursor.execute('SELECT name FROM players WHERE player_id = ?', (opp_id,))
                name = cursor.fetchone()[0]
                win_rate = w / matches if matches > 0 else 0
                opponents.append({
                    'id': opp_id,
                    'name': name,
                    'matches': matches,
                    'wins': w,
                    'losses': l,
                    'win_rate': win_rate
                })

            # Find Victim and Nemesis
            def sort_key(x):
                return (-x['win_rate'], -x['matches'], x['name'])

            sorted_opponents = sorted(opponents, key=sort_key)
            victim = self._process_opponent_group(sorted_opponents)
            nemesis = self._process_opponent_group(sorted(opponents, key=lambda x: (x['win_rate'], -x['matches'])))

            return {
                'player': player,
                'peak_rating': peak_rating,
                'total_matches': total,
                'wins': wins,
                'losses': losses,
                'victim': victim,
                'nemesis': nemesis
            }

    def _process_opponent_group(self, opponents):
        """Helper to handle ties in opponent rankings"""
        if not opponents:
            return {'name': 'N/A', 'rate': 0.0}
        
        # Find the top entry
        top = opponents[0]
        
        # Find all tied opponents
        tied = [o for o in opponents if 
            o['win_rate'] == top['win_rate'] and
            o['matches'] == top['matches']]
        
        if len(tied) > 1:
            # Format tied names
            names = ", ".join([o['name'] for o in tied[:3]])
            if len(tied) > 3:
                names += f" (+{len(tied)-3} more)"
            return {'name': f"Tied between {names}", 'rate': top['win_rate']}
        
        return {'name': top['name'], 'rate': top['win_rate']}
    
    def get_rating_history(self, player_id: int) -> list[dict]:
        """Get historical ratings with match sequence numbers"""
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            
            # Get initial rating
            cursor.execute('''
                SELECT mu, sigma, last_updated 
                FROM players 
                WHERE player_id = ?
            ''', (player_id,))
            initial = cursor.fetchone()
            if not initial:
                raise ValueError(f"Player {player_id} not found")
            
            history = [{
                'mu': initial[0],
                'sigma': initial[1],
                'match_num': 0,
                'timestamp': datetime.fromisoformat(initial[2])
            }]

            # Get match-based ratings
            cursor.execute('''
                SELECT rh.mu, rh.sigma, m.timestamp 
                FROM ratings_history rh
                JOIN matches m ON rh.match_id = m.match_id
                WHERE rh.player_id = ?
                ORDER BY m.timestamp ASC
            ''', (player_id,))
            
            for idx, row in enumerate(cursor.fetchall(), start=1):
                history.append({
                    'mu': row[0],
                    'sigma': row[1],
                    'match_num': idx,
                    'timestamp': datetime.fromisoformat(row[2])
                })
                
            return history
    
    def get_unified_rating_history(self, player_id: int) -> list[dict]:
        """Get player's ratings aligned with global match sequence"""
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            
            # Get all matches in chronological order
            cursor.execute('''
                SELECT match_id, timestamp 
                FROM matches 
                ORDER BY timestamp ASC
            ''')
            all_matches = [row[0] for row in cursor.fetchall()]
            
            # Get player's rating changes with match IDs
            cursor.execute('''
                SELECT rh.mu, rh.sigma, m.match_id, m.timestamp
                FROM ratings_history rh
                JOIN matches m ON rh.match_id = m.match_id
                WHERE rh.player_id = ?
                ORDER BY m.timestamp ASC
            ''', (player_id,))
            player_changes = {row[2]: (row[0], row[1]) for row in cursor.fetchall()}
            
            # Get initial rating
            cursor.execute('SELECT mu, sigma FROM players WHERE player_id = ?', (player_id,))
            current_mu, current_sigma = cursor.fetchone()
            
            # Build unified timeline
            history = []
            for global_match_num, match_id in enumerate(all_matches, start=1):
                if match_id in player_changes:
                    current_mu, current_sigma = player_changes[match_id]
                history.append({
                    'global_match_num': global_match_num,
                    'mu': current_mu,
                    'sigma': current_sigma
                })
                
            return history
        
    def predict_win_probability(self, player1_id: int, player2_id: int) -> dict:
        """
        Predicts the win probability between two players based on their current ratings.
        """
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            try:
                player1 = self._get_player(player1_id, cursor)
                player2 = self._get_player(player2_id, cursor)
            except ValueError as e:
                raise e # Re-raise the error if a player isn't found

        # Use the formula based on TrueSkill principles
        # delta_mu = mu1 - mu2
        # denom = sqrt(2 * beta^2 + sigma1^2 + sigma2^2)
        # probability = cdf(delta_mu / denom) where cdf is the cumulative distribution function of a standard normal distribution
        # Alternatively, the formula from bayesian.py uses an equivalent logistic function: 1 / (1 + exp(-delta_mu / denominator))

        delta_mu = player1.mu - player2.mu
        sum_sigma_sq = player1.sigma**2 + player2.sigma**2
        beta_sq = self.trueskill_env.beta**2 # Access beta from the TrueSkill instance

        denominator = math.sqrt(2 * beta_sq + sum_sigma_sq)

        if denominator == 0:
             # Avoid division by zero; implies absolute certainty (rare)
             # If delta_mu > 0, p1 wins; if < 0, p2 wins; if == 0, it's a 50/50 toss-up theoretically
             prob_p1_wins = 0.5 if delta_mu == 0 else (1.0 if delta_mu > 0 else 0.0)
        else:
            # Using the logistic function approach equivalent to CDF for win probability
            prob_p1_wins = 1 / (1 + math.exp(-delta_mu / denominator))


        prob_p2_wins = 1.0 - prob_p1_wins

        return {
            'player1_id': player1_id,
            'player1_name': player1.name,
            'player1_win_prob': prob_p1_wins,
            'player2_id': player2_id,
            'player2_name': player2.name,
            'player2_win_prob': prob_p2_wins
        }

    def get_player_recent_matches(self, player_id: int, limit: int = 5) -> list[dict]:
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.player1_id, p1.name, m.player1_score,
                    m.player2_id, p2.name, m.player2_score,
                    m.timestamp
                FROM matches m
                JOIN players p1 ON m.player1_id = p1.player_id
                JOIN players p2 ON m.player2_id = p2.player_id
                WHERE m.player1_id = ? OR m.player2_id = ?
                ORDER BY m.timestamp DESC
                LIMIT ?
            ''', (player_id, player_id, limit))
            
            result = []
            for row in cursor.fetchall():
                p1_id, p1_name, s1, p2_id, p2_name, s2, timestamp = row

                if p1_id == player_id:
                    opponent = p2_name
                    is_win = s1 > s2
                else:
                    opponent = p1_name
                    is_win = s2 > s1

                result.append({
                    'opponent': opponent,
                    'result': 'W' if is_win else 'L',
                    'timestamp': timestamp  # Optional: use later for dates
                })

            return result
        
    def get_all_players(self):
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT player_id, name FROM players ORDER BY name")
            return [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]

    def get_player_id_by_name(self, name: str) -> int:
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT player_id FROM players WHERE name = ?', (name,))
            result = cursor.fetchone()
            if not result:
                raise ValueError(f"No player found with name: {name}")
            return result[0]
        
    def get_weekly_summary(self, start_date, end_date):
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            player_stats = []

            # Highest Climber and Biggest Thrower
            cursor.execute('SELECT player_id, name FROM players')
            players = cursor.fetchall()
            climbers = []
            for (player_id, name) in players:
                # Get initial rating (before first match of the week)
                cursor.execute('''
                    SELECT rh.mu FROM ratings_history rh
                    JOIN matches m ON rh.match_id = m.match_id
                    WHERE rh.player_id = ? AND m.timestamp >= ? AND m.timestamp <= ?
                    ORDER BY m.timestamp ASC LIMIT 1
                ''', (player_id, start_date, end_date))
                initial_mu = cursor.fetchone()
                cursor.execute('SELECT mu FROM players WHERE player_id = ?', (player_id,))
                final_mu = cursor.fetchone()[0]
                delta = final_mu - (initial_mu[0] if initial_mu else final_mu)
                climbers.append((player_id, name, delta))

            # Sort climbers
            climbers_sorted = sorted(climbers, key=lambda x: x[2], reverse=True)
            highest_climber = climbers_sorted[0] if climbers_sorted else None
            biggest_thrower = climbers_sorted[-1] if climbers_sorted else None

            # Win Rates
            win_rates = []
            for (player_id, name) in players:
                cursor.execute('''
                    SELECT 
                        SUM(CASE WHEN (player1_id = ? AND player1_score > player2_score) OR
                                        (player2_id = ? AND player2_score > player1_score)
                                THEN 1 ELSE 0 END) AS wins,
                        COUNT(*) AS total
                    FROM matches
                    WHERE (player1_id = ? OR player2_id = ?) AND timestamp BETWEEN ? AND ?
                ''', (player_id, player_id, player_id, player_id, start_date, end_date))
                wins, total = cursor.fetchone()
                win_rate = (wins / total) if total > 0 else 0.0
                win_rates.append((name, win_rate))

            win_rates_sorted = sorted(win_rates, key=lambda x: x[1], reverse=True)
            highest_win = win_rates_sorted[0] if win_rates_sorted else None
            lowest_win = win_rates_sorted[-1] if win_rates_sorted else None

            # Most Frequent Match
            cursor.execute('''
                    SELECT player1_id, player2_id, COUNT(*) as cnt
                    FROM matches
                    WHERE timestamp BETWEEN ? AND ?
                    GROUP BY player1_id, player2_id
                    ORDER BY cnt DESC LIMIT 1
                ''', (start_date, end_date))
            frequent_match = cursor.fetchone()
            
            if frequent_match:
                p1, p2, count = frequent_match
                cursor.execute('SELECT name FROM players WHERE player_id IN (?, ?)', (p1, p2))
                names = cursor.fetchall()
                p1_name, p2_name = names[0][0], names[1][0]
                
                # Get wins THIS WEEK for this matchup
                # In MatchProcessor.get_weekly_summary() method:
                # In MatchProcessor.get_weekly_summary():
                cursor.execute('''
                    SELECT 
                        SUM(CASE 
                            WHEN (player1_id = ? AND player1_score > player2_score) OR 
                                (player2_id = ? AND player2_score > player1_score) 
                            THEN 1 ELSE 0 END) AS wins_p1,
                        SUM(CASE 
                            WHEN (player1_id = ? AND player1_score > player2_score) OR 
                                (player2_id = ? AND player2_score > player1_score) 
                            THEN 1 ELSE 0 END) AS wins_p2
                    FROM matches
                    WHERE (
                        (player1_id = ? AND player2_id = ?) OR 
                        (player2_id = ? AND player1_id = ?)
                    ) AND timestamp BETWEEN ? AND ?
                ''', (
                    p1, p1,  # Wins for Luka (p1)
                    p2, p2,  # Wins for Alex (p2)
                    p1, p2,  # Matches where p1 is player1 and p2 is player2
                    p1, p2,  # Matches where p2 is player1 and p1 is player2
                    start_date, end_date
                ))
                wins_p1, wins_p2 = cursor.fetchone()
            else:
                p1_name = p2_name = count = wins_p1 = wins_p2 = None


            return {
                'highest_climber': highest_climber,
                'biggest_thrower': biggest_thrower,
                'highest_win_rate': highest_win,  # Directly return the tuple
                'lowest_win_rate': lowest_win,    # Directly return the tuple
                'most_frequent_match': (p1_name, p2_name, count, wins_p2, wins_p1)
            }
        
    def _get_current_season(self, cursor) -> int:
        cursor.execute('SELECT value FROM system_settings WHERE key = ?', ('current_season',))
        row = cursor.fetchone()
        if row:
            return int(row[0])
        else:
            cursor.execute('INSERT INTO system_settings (key, value) VALUES (?, ?)', ('current_season', 2))
            return 2

    def get_season_ladder(self, season_id: int) -> list[Player]:
        """Generate ladder for a specific season by reprocessing its matches"""
        from trueskill import Rating, rate_1vs1
        
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            # Get all matches in the season
            cursor.execute('''
                SELECT player1_id, player2_id, player1_score, player2_score
                FROM matches
                WHERE season = ?
                ORDER BY timestamp ASC
            ''', (season_id,))
            matches = cursor.fetchall()
            
            # Initialize player ratings
            cursor.execute('SELECT player_id FROM players')
            players = {row[0]: Rating() for row in cursor.fetchall()}
            
            # Process each match
            for p1_id, p2_id, s1, s2 in matches:
                winner = 1 if s1 > s2 else 2
                if winner == 1:
                    new_p1, new_p2 = rate_1vs1(players[p1_id], players[p2_id])
                else:
                    new_p2, new_p1 = rate_1vs1(players[p2_id], players[p1_id])
                players[p1_id] = new_p1
                players[p2_id] = new_p2
            
            # Convert to Player objects sorted by TrueSkill
            ladder = []
            for player_id in players:
                cursor.execute('SELECT name FROM players WHERE player_id = ?', (player_id,))
                name = cursor.fetchone()[0]
                mu = players[player_id].mu
                sigma = players[player_id].sigma
                ladder.append(Player(player_id, name, mu, sigma, datetime.now()))
            
            # Sort by TrueSkill mean minus 3*sigma
            ladder.sort(key=lambda p: (p.mu - 3*p.sigma), reverse=True)
            return ladder
        
    # In MatchProcessor class
    def get_current_season(self) -> int:
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM system_settings WHERE key = "current_season"')
            row = cursor.fetchone()
            return int(row[0]) if row else 1

    def get_available_seasons(self) -> list[int]:
        with self.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT season FROM matches ORDER BY season DESC')
            seasons = [row[0] for row in cursor.fetchall()]
            # Ensure season 1 exists even if no matches
            if not seasons:
                return [1]
            return seasons + [1] if 1 not in seasons else seasons
