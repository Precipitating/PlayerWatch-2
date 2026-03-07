import sqlite3
import json
import os
import sys

VIDEO_CONFIG =  {
    "timer_timestamp_minute": 20,
    "match_id": None,
    "first_half_offset": 0,
    "second_half_offset": 0,

    "first_half_path": None,
    "second_half_path": None,
    "audio_path": None,

    "start_offset": None,
    "end_offset": None,

    "action_conclusion": None,

    "players_list": {},

    "cwd": os.path.dirname(sys.executable if getattr(sys, "frozen", False) else __file__)

}

DB_PATH = f'{VIDEO_CONFIG["cwd"]}/FootballData/match_events.db'

def get_connection() -> tuple[sqlite3.Connection, sqlite3.Cursor]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    return conn, cursor

def init_db() -> bool:
    if os.path.exists(DB_PATH):
        return True
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn, cursor = get_connection()
    cursor.execute(
    """
        CREATE TABLE IF NOT EXISTS match_events
        (
            match_id TEXT PRIMARY KEY,
            match_dict TEXT,
            player_dict TEXT,
            events TEXT
        )     
    """
    )
    return False

def add_to_db(match_id: str, match_dict: str, player_dict: str, events: str) -> None:
    conn, cursor = get_connection()
    cursor.execute("INSERT INTO match_events (match_id, match_dict, player_dict, events) VALUES (?, ?, ?, ?)", (match_id, match_dict, player_dict, events))
    conn.commit()


def get_db_dict(match_id: str, row_name: str) -> dict | None:
    """
    Load a dict from the db
    Returns:
        dict: Should be a dictionary or None
    """

    conn, cursor = get_connection()

    # whitelist columns
    if row_name not in ["match_dict", "player_dict", "events"]:
        print (f"Invalid column name: {row_name}, we'll create it")
        return None

    cursor.execute(f"SELECT {row_name} FROM match_events WHERE match_id = ?", (match_id,))
    row = cursor.fetchone()

    if row is None or row[0] is None:
        print("Player dictionary not found in database")
        return None

    return json.loads(row[0])






