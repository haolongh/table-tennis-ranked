import argparse
from core.match_processor import MatchProcessor

class TableTennisCLI:
    def __init__(self):
        self.processor = MatchProcessor()
        self.parser = argparse.ArgumentParser(
            description='Table Tennis Ranking System'
        )
        self._setup_commands()

    def _setup_commands(self):
        subparsers = self.parser.add_subparsers(dest='command')

        # Add Player
        add_parser = subparsers.add_parser('add-player', help='Register new player')
        add_parser.add_argument('name', type=str, help='Player name')

        # Record Match
        match_parser = subparsers.add_parser('record-match', help='Log a new match')
        match_parser.add_argument('player1', type=int, help='Player 1 ID')
        match_parser.add_argument('player2', type=int, help='Player 2 ID')
        match_parser.add_argument('score1', type=int, help='Player 1 score')
        match_parser.add_argument('score2', type=int, help='Player 2 score')

        # Show Ladder
        subparsers.add_parser('ladder', help='Display current rankings')

        # Head-to-Head
        h2h_parser = subparsers.add_parser('h2h', help='Show head-to-head stats')
        h2h_parser.add_argument('player1', type=int, help='First player ID')
        h2h_parser.add_argument('player2', type=int, help='Second player ID')


         # Remove Player
        remove_parser = subparsers.add_parser('remove-player', 
                                        help='Delete a player from the system')
        remove_parser.add_argument('player_id', type=int, help='ID of player to remove')
    
        # Match History
        history_parser = subparsers.add_parser('match-history',
                                        help='View match history - omit ID for recent matches')
        history_parser.add_argument('player_id', nargs='?', type=int, default=None,  # Fix order here
                                help='(Optional) Player ID for specific history')
        
        #delete matches
        delete_parser = subparsers.add_parser('delete-match', 
                                            help='Delete a match by ID')
        delete_parser.add_argument('match_id', type=int, 
                                help='ID of the match to delete')
        
        #sudo rm -rf nuke
        clear_parser = subparsers.add_parser('clearalldata', 
                                   help='Delete ALL players, matches, and rankings')
        
        # In _setup_commands():
        wlt_parser = subparsers.add_parser('wlt', help='Display win/loss table sorted by win percentage')

        stats_parser = subparsers.add_parser('player-stats', help='Show detailed player statistics')
        stats_parser.add_argument('player_id', type=int, help='Player ID to show stats for')



    def run(self):
        args = self.parser.parse_args()
        
        if args.command == 'add-player':
            player = self.processor.add_player(args.name)
            print(f"Created Player {player.player_id}: {player.name}")
            
        elif args.command == 'record-match':
            match = self.processor.record_match(args.player1, args.player2, 
                                               args.score1, args.score2)
            print(f"Recorded Match {match.match_id}")
            
        elif args.command == 'ladder':
            ladder = self.processor.get_ladder()
            print("\nCurrent Rankings:")
            for idx, player in enumerate(ladder, 1):
                print(f"{idx}. {player.name} (Rating: {player.mu:.1f} ±{player.sigma:.1f})")
                
        elif args.command == 'h2h':
            stats = self.processor.get_head_to_head(args.player1, args.player2)
            
            # Get player names
            player1_name = self._get_player_name(args.player1)
            player2_name = self._get_player_name(args.player2)
            
            print(f"\nHead-to-Head: {player1_name} vs {player2_name}")
            print(f"Total Matches: {stats['total_matches']}")
            print(f"Wins {player1_name}: {stats['wins_player1']}")
            print(f"Wins {player2_name}: {stats['wins_player2']}")

        elif args.command == 'remove-player':
            self.processor.remove_player(args.player_id)
            print(f"Removed player ID {args.player_id} and associated matches")
        
        elif args.command == 'match-history':
            history = self.processor.get_match_history(args.player_id)
            player_name = self._get_player_name(args.player_id)
        
            print(f"\nMatch History for {player_name} (ID: {args.player_id})")
            print("-" * 60)
            for match in history:
                outcome = "WON" if match['is_win'] else "LOST"
                print(f"{match['date']} | {match['player1']} {match['score1']}-{match['score2']} {match['player2']} ({outcome})") 

        elif args.command == 'match-history':
            if args.player_id is not None:
                # Player-specific history
                try:
                    history = self.processor.get_match_history(args.player_id)
                    player_name = self._get_player_name(args.player_id)
                    
                    print(f"\nMatch History for {player_name} (ID: {args.player_id})")
                    print("-" * 60)
                    for match in history:
                        outcome = "WON" if match['is_win'] else "LOST"
                        print(f"{match['date']} | {match['player1']} {match['score1']}-{match['score2']} {match['player2']} ({outcome})")
                except Exception as e:
                    print(f"Error: {str(e)}")
            else:
                # Show recent matches
                matches = self.processor.get_recent_matches()
                if not matches:
                    print("\nNo matches recorded yet")
                    return
                    
                print("\nLast 10 Recent Matches")
                print("-" * 40)
                for match in matches:
                    print(f"{match['date']} | {match['player1']} {match['score1']}-{match['score2']} {match['player2']}")

        elif args.command == 'delete-match':
            confirm = input(f"WARNING: Deleting match {args.match_id} will recalculate all subsequent ratings. Continue? (y/N) ")
            if confirm.lower() != 'y':
                print("Cancelled.")
                return
            
            try:
                self.processor.delete_match(args.match_id)
                print(f"Deleted match {args.match_id} and recalculated ratings")
            except Exception as e:
                print(f"Error: {str(e)}")
        
        elif args.command == 'wlt':
            table = self.processor.get_win_loss_table()
            print("\nWin/Loss Table:")
            print(f"{'Player':<20} {'MP':<6} {'W':<6} {'L':<6} {'Win%':<6}")
            print("-" * 45)
            for entry in table:
                print(f"{entry['name']:<20} {entry['played']:<6} {entry['wins']:<6} {entry['losses']:<6} {entry['win_pct']:<6.1f}")

        elif args.command == 'clearalldata':
            confirm = input("⚠️  WARNING: This will PERMANENTLY DELETE ALL DATA! Type 'DELETE' to confirm: ")
            if confirm.strip().upper() == 'DELETE':
                self.processor.clear_all_data()
                print("Successfully erased all data. Database is now empty.")
            else:
                print("Clear operation cancelled.")

        elif args.command == 'player-stats':
            try:
                stats = self.processor.get_player_stats(args.player_id)
                p = stats['player']
                
                print(f"\nPlayer Statistics: {p.name} (ID: {p.player_id})")
                print(f"Current Rating: {p.mu:.1f} ±{p.sigma:.1f}")
                print(f"Peak Rating:    {stats['peak_rating']:.1f}")
                print(f"Matches Played: {stats['total_matches']}")
                print(f"W/L Record:     {stats['wins']}-{stats['losses']}")
                print(f"Win Percentage: {(stats['wins']/stats['total_matches']*100 if stats['total_matches'] > 0 else 0):.1f}%")
                print(f"\nNemesis:       {stats['nemesis']['name']} ({stats['nemesis']['rate']*100:.1f}% win rate)")
                print(f"Victim:        {stats['victim']['name']} ({stats['victim']['rate']*100:.1f}% win rate)")
            except Exception as e:
                print(f"Error: {str(e)}")

    def _get_player_name(self, player_id: int) -> str:
        """Get player name safely"""
        try:
            with self.processor.db_handler.connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT name FROM players WHERE player_id = ?', (player_id,))
                result = cursor.fetchone()
                return result[0] if result else "Unknown Player"
        except Exception:
            return "Unknown Player"


if __name__ == '__main__':
    TableTennisCLI().run()