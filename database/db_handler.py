# database/db_handler.py
import sqlite3
import os
from contextlib import contextmanager

DB_FILE = os.path.join(os.path.dirname(__file__), '..', 'rankings.db')

class DatabaseHandler:
    def __init__(self, db_name='rankings.db'):
        self.db_name = db_name
        self.is_memory = ':memory:' in db_name or 'mode=memory' in db_name
        self._init_db()
    
    def _init_db(self):
        # Create tables immediately for persistent databases
        if not self.is_memory:
            with self.connection() as conn:
                self._create_tables(conn)
    
    def _create_tables(self, conn):
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS players (
                player_id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                mu REAL NOT NULL,
                sigma REAL NOT NULL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS matches (
                match_id INTEGER PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                player1_id INTEGER NOT NULL,
                player2_id INTEGER NOT NULL,
                player1_score INTEGER NOT NULL,
                player2_score INTEGER NOT NULL,
                season INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(player1_id) REFERENCES players(player_id) ON DELETE CASCADE,
                FOREIGN KEY(player2_id) REFERENCES players(player_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS matchups (
                player_a_id INTEGER NOT NULL,
                player_b_id INTEGER NOT NULL,
                matches_played INTEGER DEFAULT 0,
                wins_a INTEGER DEFAULT 0,
                wins_b INTEGER DEFAULT 0,
                PRIMARY KEY (player_a_id, player_b_id),
                FOREIGN KEY(player_a_id) REFERENCES players(player_id) ON DELETE CASCADE,
                FOREIGN KEY(player_b_id) REFERENCES players(player_id) ON DELETE CASCADE
            );
        
            CREATE TABLE IF NOT EXISTS ratings_history (
                history_id INTEGER PRIMARY KEY,
                player_id INTEGER NOT NULL,
                match_id INTEGER NOT NULL,
                mu REAL NOT NULL,
                sigma REAL NOT NULL,
                FOREIGN KEY(player_id) REFERENCES players(player_id),
                FOREIGN KEY(match_id) REFERENCES matches(match_id)
            );
            -- Keep existing tables from previous definition --
                           
            CREATE TABLE IF NOT EXISTS PlayerRatingHistory (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER NOT NULL,
                match_id INTEGER, -- Optional: Link to the specific match
                timestamp DATETIME NOT NULL,
                mu_after REAL NOT NULL,
                sigma_after REAL NOT NULL,
                FOREIGN KEY (player_id) REFERENCES Players (player_id) ON DELETE CASCADE
                -- Optional FOREIGN KEY (match_id) REFERENCES Matches (match_id)
            );
        ''')

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_name, uri=True)
        conn.execute("PRAGMA foreign_keys = ON")  
        try:
            if self.is_memory:
                self._create_tables(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if not self.is_memory:
                conn.close()

def get_rankings():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT player_id, name, mu, sigma
            FROM players
            ORDER BY mu DESC
        """)
        players = c.fetchall()

    return [
        {
            "id": row[0],
            "name": row[1],
            "mu": row[2],
            "sigma": row[3],
            "form": get_player_form(row[0])
        }
        for row in players
    ]

def get_recent_matches():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT
                m.match_id,
                p1.name AS player1_name,
                p2.name AS player2_name,
                m.player1_score,
                m.player2_score
            FROM matches m
            JOIN players p1 ON m.player1_id = p1.player_id
            JOIN players p2 ON m.player2_id = p2.player_id
            ORDER BY m.match_id DESC
        """)
        rows = c.fetchall()

    return [
        {
            "match_id": row[0],
            "player1": row[1],
            "player2": row[2],
            "score1": row[3],
            "score2": row[4],
        }
        for row in rows
    ]


def get_player_form(player_id, num_matches=5):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT player1_id, player2_id, player1_score, player2_score
            FROM matches
            WHERE player1_id = ? OR player2_id = ?
            ORDER BY match_id DESC
            LIMIT ?
        """, (player_id, player_id, num_matches))
        rows = c.fetchall()

    form = []
    for p1_id, p2_id, p1_score, p2_score in rows:
        if player_id == p1_id:
            won = p1_score > p2_score
        else:
            won = p2_score > p1_score
        form.append('W' if won else 'L')
    return form

