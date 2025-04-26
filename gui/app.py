DB_FILE = "../rankings.db"
import sys
import os
import sqlite3
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from database.db_handler import get_rankings, get_recent_matches
from core.match_processor import MatchProcessor
from core.prediction_model import EnhancedPredictor
processor = MatchProcessor(DB_FILE)
predictor = EnhancedPredictor(DB_FILE)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "tung-tung-tung-sahur"

@app.route("/")
def index():
    trueskill_table = get_rankings()
    wlt_table_raw = processor.get_win_loss_table()
    delta_map = {}
    current_season = processor.get_current_season()
    available_seasons = processor.get_available_seasons()

    recent_matches = processor.get_recent_matches(limit=1)
    if recent_matches:
        latest_match = recent_matches[0]
        # Get players from the latest match
        involved_players = {latest_match['player1_id'], latest_match['player2_id']}
        
        # Fetch pre-match ratings directly from ratings_history
        pre_ratings = processor.get_ratings_by_match(latest_match['match_id'])
        pre_rating_map = {r['player_id']: r['mu'] for r in pre_ratings}
        
        # Calculate deltas only for involved players
        for player in trueskill_table:
            if player['id'] in involved_players and player['id'] in pre_rating_map:
                delta = player['mu'] - pre_rating_map[player['id']]
                delta_map[player['id']] = delta
    # Build a lookup from name to (id, form)
    form_lookup = {p['name']: (p['id'], p['form']) for p in trueskill_table}

    # Inject form and ID manually based on player name
    for player in wlt_table_raw:
        form_data = form_lookup.get(player['name'])
        if form_data:
            player_id, form = form_data
            player['id'] = player_id
            player['form'] = form
        else:
            print(f"⚠️ No form data found for {player['name']}")
            player['id'] = -1  # fallback if needed
            player['form'] = []

    
    return render_template("index.html",
                           rankings=trueskill_table,
                           wlt_table=wlt_table_raw,
                           deltas=delta_map,
                           available_seasons=available_seasons,
                           current_season=current_season)


@app.route("/players")
def players():
    return render_template("players.html")

@app.route("/predict")
def predict():
    players = processor.get_all_players()

    p1_id = request.args.get("player1", type=int)
    p2_id = request.args.get("player2", type=int)

    player1 = player2 = h2h = prediction = None
    p1_history = p2_history = []

    def build_player_summary(pid):
        stats = processor.get_player_stats(pid)
        return {
            "id": stats["player"].player_id,
            "name": stats["player"].name,
            "mu": round(stats["player"].mu, 2),
            "sigma": round(stats["player"].sigma, 2),
            "played": stats["total_matches"],
            "wins": stats["wins"],
            "losses": stats["losses"],
            "form": [m["result"] for m in processor.get_player_recent_matches(pid, limit=5)]
        }

    if p1_id:
        player1 = build_player_summary(p1_id)
        p1_history = processor.get_unified_rating_history(p1_id)

    if p2_id:
        player2 = build_player_summary(p2_id)
        p2_history = processor.get_unified_rating_history(p2_id)

    if player1 and player2:
        h2h = processor.get_head_to_head(player1["id"], player2["id"])
        try:
            hist_raw = predictor.predict_win_probability(player1["id"], player2["id"])
            prediction = {
                "player1_name": hist_raw["player1_name"],
                "player2_name": hist_raw["player2_name"],
                "model_a": hist_raw["model_a"],
                "model_b": hist_raw["model_b"],
                "model_weights": hist_raw["model_weights"],
                "final_prediction": hist_raw["final_prediction"],
                "player1_win_prob": hist_raw["final_prediction"],
                "player2_win_prob": 1 - hist_raw["final_prediction"]
            }
        except Exception as e:
            print("[ERROR] Failed to generate prediction:", e)
            prediction = None  # Fail silently for now

    # ✅ Always return something
    return render_template("predict.html",
                           players=players,
                           player1=player1,
                           player2=player2,
                           h2h=h2h,
                           prediction=prediction,
                           p1_history=p1_history,
                           p2_history=p2_history)








@app.route("/matches", methods=["GET"])
def matches():
    page = int(request.args.get("page", 1))
    per_page = 10
    all_matches = get_recent_matches()
    start = (page - 1) * per_page
    end = start + per_page
    paginated_matches = all_matches[start:end]

    total_pages = (len(all_matches) + per_page - 1) // per_page
    
    # Get players for the add match modal
    players = processor.get_all_players()
    
    return render_template("matches.html",
                           matches=paginated_matches,
                           page=page,
                           total_pages=total_pages,
                           players=players)  # Pass players to the template


def get_initials(full_name):
    return ''.join([part[0].upper() for part in full_name.split()])

@app.route('/player/<int:player_id>')
def player_profile(player_id):
    try:
        # Get stats from your CLI function
        stats = processor.get_player_stats(player_id)
        rating_history = processor.get_rating_history(player_id)
        p = stats['player']  # This is already a Player object from DB
        recent_matches = processor.get_player_recent_matches(player_id, limit=5)

        print("Recent matches:", recent_matches)

        # Extract initials (same as before)
        initials = ''.join([part[0].upper() for part in p.name.split() if part])

        # Unified player object (as before)
        player = {
            "id": p.player_id,
            "name": p.name,
            "initials": initials,
            "mu": round(p.mu, 2),
            "sigma": round(p.sigma, 2),
            "last_updated": p.last_updated
        }

        # Format history for JS (labels and mu values)
        history = [
            {"match": h["match_num"], "mu": h["mu"], "sigma": h["sigma"]}
            for h in rating_history # Use the variable already fetched
        ]
        return render_template("player_profile.html", player=player, stats=stats, history=history, recent_matches=recent_matches)
    except Exception as e:
        print(f"Error loading profile for player {player_id}: {e}")
        flash(f"Could not load profile for Player ID {player_id}.", "danger")
        return redirect(url_for('index')) # Redirect to a safe page

@app.route("/submit", methods=["GET", "POST"])
def submit_match():
    print("📥 /submit route triggered:", request.method)

    if request.method == "POST":
        try:
            # Get IDs from form (they're coming in as strings)
            player1_id = int(request.form["player1"])
            player2_id = int(request.form["player2"])
            score1 = int(request.form["score1"])
            score2 = int(request.form["score2"])

            print("🎯 Submitted form:", {
                "player1_id": player1_id,
                "player2_id": player2_id,
                "score1": score1,
                "score2": score2
            })

            if player1_id == player2_id:
                flash("❌ Players must be different.", "danger")
                return redirect(url_for("matches"))  # Changed: redirect to matches

            # Call your working record_match
            match = processor.record_match(player1_id, player2_id, score1, score2)

            flash(f"✅ Match {match.match_id} recorded!", "success")
            return redirect(url_for("matches"))

        except ValueError as ve: # Catch specific errors like draws
             print(f"❌ Submission Value Error: {ve}")
             flash(f"Error: {ve}", "danger")
             return redirect(url_for("matches"))  # Changed: redirect to matches
        except Exception as e:
            print(f"❌ Error during submission: {e}")
            flash(f"An unexpected error occurred during submission.", "danger")
            return redirect(url_for("matches"))  # Changed: redirect to matches

    # For GET requests, just redirect to matches page which has the modal
    return redirect(url_for("matches"))

@app.route("/delete-match", methods=["POST"])
def delete_match():
    print("🗑️ /delete-match route triggered")
    
    try:
        match_id = int(request.form["match_id"])
        
        print(f"🎯 Attempting to delete match ID: {match_id}")
        
        # Call your existing delete_match method
        processor.delete_match(match_id)
        
        flash(f"✅ Match {match_id} deleted and ratings recalculated!", "success")
    except ValueError as ve:
        print(f"❌ Delete Value Error: {ve}")
        flash(f"Error: {ve}", "danger")
    except Exception as e:
        print(f"❌ Error during match deletion: {e}")
        flash(f"An unexpected error occurred during deletion: {e}", "danger")
    
    # Always redirect back to matches page
    return redirect(url_for("matches"))

@app.route("/weekly-wrapped")
def weekly_wrapped():
    from datetime import datetime, timedelta
    
    # Calculate date range (last Sunday to Saturday)
    today = datetime.now()
    days_since_sunday = (today.weekday() + 1) % 7  # Monday is 0
    last_sunday = today - timedelta(days=days_since_sunday)
    start_date = last_sunday.replace(hour=0, minute=0, second=0)
    end_date = start_date + timedelta(days=6, hours=23, minutes=59, seconds=59)
    
    # Get weekly summary data
    summary = processor.get_weekly_summary(start_date.isoformat(), end_date.isoformat())
    
    # Format dates for display
    date_range = f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d')}"
    
    return render_template("weekly_wrapped.html", 
                         summary=summary,
                         date_range=date_range)

@app.route("/get_season_ladder/<int:season_id>")
def get_season_ladder(season_id):
    try:
        ladder = processor.get_season_ladder(season_id)
        ladder_data = [{
            "name": p.name,
            "mu": round(p.mu, 2),
            "sigma": round(p.sigma, 2),
            "conservative": round(p.mu - 3 * p.sigma, 2)  # Add conservative rating
        } for p in ladder]
        return jsonify(ladder_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

if __name__ == "__main__":
    app.run(debug=True)
