import sqlite3
import json
import os
import questionary

VIDEO_CONFIG =  {
    "timer_timestamp_minute": 20,
    "match_id": None,
    "first_half_offset": 0,
    "second_half_offset": 0,

    "first_half_path": None,
    "second_half_path": None,

    "start_offset": None,
    "end_offset": None,

    "watermark_path": None,

    "players_list": {},

}

ACTION_TYPES = [
    questionary.Choice("-----------------General Player Events-----------------", disabled="-"),
    "Aerial",
    "BallRecovery",
    "BallTouch",
    "BlockedPass",
    "Card",
    "Challenge",
    "Clearance",
    "Dispossessed",
    "Error",
    "Foul",
    "Interception",
    "Pass",
    "ShieldBallOpp",
    "Tackle",
    "TakeOn",
    "CornerAwarded",
    "Goal",
    "MissedShots",
    "OffsideGiven",
    "OffsidePass",
    "OffsideProvoked",
    "SavedShot",

    questionary.Choice("-----------------Goalkeeper-----------------", disabled="-"),
    # Goalkeeper Only
    "Claim",
    "KeeperPickup",
    "KeeperSweeper",
    "PenaltyFaced",
    "Punch",
    "Save",
    "Smother",

    questionary.Choice("-----------------Match Events-----------------", disabled="-"),
    # Admin / Match Events
    "SubstitutionOff",
    "SubstitutionOn",
]

VIDEO_TRANSITIONS = [
    "random",
    "fade",
    "wipeleft",
    "wiperight",
    "wipeup",
    "wipedown",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "circlecrop",
    "rectcrop",
    "distance",
    "fadeblack",
    "fadewhite",
    "radial",
    "smoothleft",
    "smoothright",
    "smoothup",
    "smoothdown",
    "circleopen",
    "circleclose",
    "vertopen",
    "vertclose",
    "horzopen",
    "horzclose",
    "dissolve",
    "pixelize",
    "diagtl",
    "diagtr",
    "diagbl",
    "diagbr",
    "hlslice",
    "hrslice",
    "vuslice",
    "vdslice",
    "hblur",
    "fadegrays",
    "wipetl",
    "wipetr",
    "wipebl",
    "wipebr",
    "squeezeh",
    "squeezev",
    "zoomin",
    "fadefast",
    "fadeslow"
]

DB_PATH = os.path.join("FootballData", "match_events.db")

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    return conn

def init_db() -> bool:
    if os.path.exists(DB_PATH):
        return True
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    with get_connection() as conn:
        conn.execute(
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
    with get_connection() as conn:
        conn.execute("INSERT INTO match_events (match_id, match_dict, player_dict, events) VALUES (?, ?, ?, ?)", (match_id, match_dict, player_dict, events))


def get_db_dict(match_id: str, row_name: str) -> dict | None:
    """
    Load a dict from the db
    Returns:
        dict: Should be a dictionary or None
    """
    # whitelist columns
    if row_name not in ["match_dict", "player_dict", "events"]:
        print (f"Invalid column name: {row_name}, we'll create it")
        return None

    with get_connection() as conn:
        row = conn.execute(f"SELECT {row_name} FROM match_events WHERE match_id = ?", (match_id,)).fetchone()

    if row is None or row[row_name] is None:
        print("Player dictionary not found in database")
        return None


    return json.loads(row[row_name])






