# database/db_handler.py
import sqlite3
from contextlib import contextmanager

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
                FOREIGN KEY(player1_id) REFERENCES players(player_id) ON DELETE CASCADE,
                FOREIGN KEY(player2_id) REFERENCES players(player_id) ON DELETE CASCADE
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