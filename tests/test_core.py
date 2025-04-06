import sqlite3
import unittest
from datetime import datetime
from database.db_handler import DatabaseHandler
from core.match_processor import MatchProcessor

class TestCore(unittest.TestCase):
    def setUp(self):
        # Use shared in-memory database
        self.processor = MatchProcessor(
            db_name='file:testing?mode=memory&cache=shared'
        )
        # Force table creation
        with self.processor.db_handler.connection() as conn:
            pass

    def tearDown(self):
        # Clear data but keep tables
        with self.processor.db_handler.connection() as conn:
            conn.execute('DELETE FROM players')
            conn.execute('DELETE FROM matches')
            conn.execute('DELETE FROM matchups')

    def test_new_player_creation(self):
        """Test creating a new player"""
        player = self.processor.add_player("Test Player")
        self.assertEqual(player.name, "Test Player")
        self.assertAlmostEqual(player.mu, 25.0, delta=0.1)
        self.assertAlmostEqual(player.sigma, 8.333, delta=0.1)

        # Verify database entry
        with self.processor.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM players')
            results = cursor.fetchall()
            self.assertEqual(len(results), 1)

    def test_match_processing(self):
        """Test recording and processing a match"""
        p1 = self.processor.add_player("Player 1")
        p2 = self.processor.add_player("Player 2")
        
        # Record match with valid scores
        match = self.processor.record_match(p1.player_id, p2.player_id, 21, 19)
        self.assertEqual(match.player1_score, 21)
        self.assertEqual(match.player2_score, 19)

        # Verify rating updates
        with self.processor.db_handler.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT mu FROM players WHERE player_id = ?', (p1.player_id,))
            updated_mu = cursor.fetchone()[0]
            self.assertNotEqual(updated_mu, 25.0)

        # Verify matchup stats
        with self.processor.db_handler.connection() as conn:
            cursor = conn.cursor()
            a, b = sorted((p1.player_id, p2.player_id))
            cursor.execute('SELECT wins_a, wins_b FROM matchups WHERE player_a_id = ? AND player_b_id = ?', (a, b))
            row = cursor.fetchone()
            self.assertEqual(row[0], 1)  # wins_a
            self.assertEqual(row[1], 0)  # wins_b

if __name__ == '__main__':
    unittest.main()