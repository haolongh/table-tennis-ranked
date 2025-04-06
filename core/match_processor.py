# core/match_processor.py
from trueskill import Rating
from datetime import datetime
from database.db_handler import DatabaseHandler
from core.models import Player, Match
from core.trueskill_setup import TrueSkillSystem

class MatchProcessor:
    def __init__(self, db_name='rankings.db'):
        self.db_handler = DatabaseHandler(db_name)
        self.trueskill = TrueSkillSystem()

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
                (player1_id, player2_id, player1_score, player2_score)
                VALUES (?, ?, ?, ?)
            ''', (player1_id, player2_id, score1, score2))
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
        return Player(*row)

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
            
            return {
                'total_matches': result[0] if result else 0,
                'wins_player1': result[1] if result else 0,
                'wins_player2': result[2] if result else 0,
                'player1_id': a,
                'player2_id': b
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
                SELECT m.timestamp, 
                    p1.name, m.player1_score,
                    p2.name, m.player2_score
                FROM matches m
                JOIN players p1 ON m.player1_id = p1.player_id
                JOIN players p2 ON m.player2_id = p2.player_id
                ORDER BY m.timestamp DESC
                LIMIT ?
            ''', (limit,))
            return [{
                'date': row[0],
                'player1': row[1],
                'score1': row[2],
                'player2': row[3],
                'score2': row[4]
            } for row in cursor.fetchall()]
        
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