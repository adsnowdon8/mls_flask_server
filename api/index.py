import json
import os
import psycopg2
import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify

load_dotenv(".flaskenv")

from flask_cors import CORS
from consts import MLS_TRADE_RULES, document_prefix_prompt


MLS_ROSTER_URL = "https://stats-api.mlssoccer.com/players/seasons/MLS-SEA-0001KA/clubs/{}?per_page=100"
MLS_CLUBS_BY_IDS_URL = "https://sportapi.mlssoccer.com/api/clubs/bySportecIds/{}"

# initialize flask app
app = Flask(__name__)

# Enable CORS only for specific domains (React app running on localhost:3000)
# this lets you send requests to your own computer from your own computer i guess
# CORS(app, resources={r"/google": {"origins": "https://mlspal.vercel.app/"}})
CORS(app)

@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"

@app.route('/profile')
def my_profile():
    response_body = {
        "name": "Gagato",
        "about": "Hello! I'm a full stack developer that loves python and javascript"
    }
    return jsonify(response_body)

MLS_GOALS_URL = "https://sportapi.mlssoccer.com/api/stats/players/competition/MLS-COM-000001/season/MLS-SEA-0001KA/order/goals/desc?pageSize=100&page={}"

def get_db():
    return psycopg2.connect(os.environ.get("DATABASE_URL"))

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_stats (
            player_id TEXT PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            team TEXT,
            goals INTEGER,
            assists INTEGER,
            shots INTEGER,
            games_started INTEGER,
            fetched_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def init_roster_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_roster (
            player_id TEXT PRIMARY KEY,
            shirt_number TEXT,
            position TEXT,
            birth_date DATE,
            nationality TEXT
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


def migrate_db():
    conn = get_db()
    cur = conn.cursor()
    # Add minutes to player_stats if not already there
    cur.execute("""
        ALTER TABLE player_stats
        ADD COLUMN IF NOT EXISTS minutes INTEGER
    """)
    # Remove legacy age column from player_roster if it exists
    cur.execute("""
        ALTER TABLE player_roster
        DROP COLUMN IF EXISTS age
    """)
    conn.commit()
    cur.close()
    conn.close()


init_db()
init_roster_db()
migrate_db()



@app.route('/stats/goals', methods=['GET'])
def get_goals_leaders():
    all_players = []
    page = 1
    while True:
        response = requests.get(MLS_GOALS_URL.format(page))
        batch = response.json()
        if not batch:
            break
        all_players.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    conn = get_db()
    cur = conn.cursor()
    for p in all_players:
        cur.execute("""
            INSERT INTO player_stats (player_id, first_name, last_name, team, goals, assists, shots, games_started, minutes, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (player_id) DO UPDATE SET
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                team = EXCLUDED.team,
                goals = EXCLUDED.goals,
                assists = EXCLUDED.assists,
                shots = EXCLUDED.shots,
                games_started = EXCLUDED.games_started,
                minutes = EXCLUDED.minutes,
                fetched_at = NOW()
        """, (
            p.get("player_id"),
            p.get("player_first_name"),
            p.get("player_last_name"),
            p.get("team_short_name"),
            p.get("goals"),
            p.get("assists"),
            p.get("shots_at_goal_sum"),
            p.get("game_started"),
            p.get("normalized_player_minutes")
        ))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(all_players)

@app.route('/stats/roster', methods=['GET'])
def get_roster():
    club_ids = [
        'MLS-CLU-000001', 'MLS-CLU-000002', 'MLS-CLU-000003', 'MLS-CLU-000004',
        'MLS-CLU-000005', 'MLS-CLU-000006', 'MLS-CLU-000007', 'MLS-CLU-000008',
        'MLS-CLU-000009', 'MLS-CLU-00000A', 'MLS-CLU-00000B', 'MLS-CLU-00000C',
        'MLS-CLU-00000D', 'MLS-CLU-00000E', 'MLS-CLU-00000F', 'MLS-CLU-00000G',
        'MLS-CLU-00000H', 'MLS-CLU-00000I', 'MLS-CLU-00000J', 'MLS-CLU-00000K',
        'MLS-CLU-00000L', 'MLS-CLU-00000M', 'MLS-CLU-00000N', 'MLS-CLU-00000O',
        'MLS-CLU-00000P', 'MLS-CLU-00000Q', 'MLS-CLU-00000R', 'MLS-CLU-00000S',
        'MLS-CLU-000065', 'MLS-CLU-00001L',
    ]
    
    ids_param = ",".join(club_ids)
    clubs_response = requests.get(MLS_CLUBS_BY_IDS_URL.format(ids_param))
    clubs = clubs_response.json()
    conn = get_db()
    cur = conn.cursor()
    
    for club in clubs:
        club_id = club['sportecId']
        roster_response = requests.get(MLS_ROSTER_URL.format(club_id))
        # if not roster_response.ok or not roster_response.text.strip():
        #     continue
        try:
            players = roster_response.json()['players']
        except Exception:
            print('no players in ', club)
            continue

        print(f"Fetching club {club_id}...")

        for p in players:
            cur.execute("""
                INSERT INTO player_roster (player_id, shirt_number, position, birth_date, nationality)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (player_id) DO UPDATE SET
                    shirt_number = EXCLUDED.shirt_number,
                    position = EXCLUDED.position,
                    birth_date = EXCLUDED.birth_date,
                    nationality = EXCLUDED.nationality
            """, (
                p.get("player_id"),       # verify field name from API response
                p.get("shirt_number"),    # verify field name
                p.get("playing_position_english"),      
                p.get("birth_date"),      # e.g. "1995-03-22"
                p.get("nationality_english"),     # verify field name
            ))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "ok"})


@app.route('/players', methods=['GET'])
def get_players():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            s.player_id, s.first_name, s.last_name, s.team,
            s.goals, s.assists, s.shots, s.games_started, s.minutes,
            r.shirt_number, r.position,
            DATE_PART('year', AGE(r.birth_date)) AS age,
            r.nationality
        FROM player_stats s
        LEFT JOIN player_roster r ON s.player_id = r.player_id
        ORDER BY s.goals DESC
    """)
    rows = cur.fetchall()
    print(len(rows), ' players')
    cur.close()
    conn.close()
    players = [
        {
            "player_id": row[0],
            "first_name": row[1],
            "last_name": row[2],
            "team": row[3],
            "goals": row[4],
            "assists": row[5],
            "shots": row[6],
            "games_started": row[7],
            "minutes": row[8],
            "shirt_number": row[9],
            "position": row[10],
            "age": row[11],
            "nationality": row[12],
        }
        for row in rows
    ]
    return jsonify(players)


# if __name__ == "__main__":
#     app.run(debug=True, port=8080)  # Use debug=True for better error messages during development

