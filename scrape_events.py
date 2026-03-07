from bs4 import BeautifulSoup
from selenium import webdriver
import re
import click
import json
from tkinter import Tk, filedialog
import os
import subprocess
from typing import Any
import cv2
import questionary

import database
import player
from player import Player
from concurrent.futures import ThreadPoolExecutor
import sys

from database import VIDEO_CONFIG


def file_picker(file_types: str) -> str:
    """
    Opens a filedialog with supplied file_types
    Args:
        file_types (str): String of file types to accept when filedialog is open

    Returns:
        str: File path of the selected file

    """
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)  # <-- Force to front
    root.update()                       # <-- Process the attribute change

    file_path = filedialog.askopenfilename(
        parent=root,                    # <-- Attach to root
        title="Select a football clip",
        filetypes=[
            ("Input", file_types),
            ("All files", "*.*")
        ]
    )

    root.destroy()
    return file_path


def validate_whoscored_link(ctx: click.Context, param: click.Parameter, value: str) -> str:
    """
    Validation callback for WhoScored link, if BadParameter is raised, repeats input until correct.
    Args:
        ctx (click.Context): Click context, automatically passed in & not used.
        param (click.Parameter): Click parameter, automatically passed in & not used.
        value (str): URL provided by the user.

    Returns:
        str: The validated URL.

    Raises:
        click.BadParameter: Is raised when regex pattern does not match value.
    """
    pattern = r"^https://www\.whoscored\.com/matches/\d+/live(?:/.*)?$"
    if not re.match(pattern, value):
        raise click.BadParameter(
            "Must be https://www.whoscored.com/matches/<id>/live/..."
        )

    VIDEO_CONFIG["match_id"] = re.search(r"/matches/(\d+)", value).group(1)
    return value



def get_video(type: int) -> bool:
    """
    Opens a file browser window to look for video formats.
    Stores the paths to first_half_path or second_half_path

    Returns:
       boolean: True if path is set or else False

    """
    video = file_picker("*.mp4 *.mkv *.mov *.avi *.webm *.flv *.wmv *.mpeg *.mpg *.m4v *.ts")
    if not video:
        click.secho("Can't find video", fg="red")
        return False

    if type == 1:
        VIDEO_CONFIG["first_half_path"] = video
    elif type == 2:
        VIDEO_CONFIG["second_half_path"] = video
    else:
        click.secho("Invalid input, 1 or 2 should be used", fg="red")
        return False

    return True




def get_audio() -> bool:
    """
   Determine if we want to use custom audio via
   questionary select input

    Returns:
       boolean: True if path is set or else False
    """
    require_custom_audio = questionary.select("Use custom audio?", choices=["Yes", "No"]).ask()

    if require_custom_audio == "Yes":
        audio_path = file_picker("*.mp3 *.wav *.aac *.m4a *.flac *.ogg *.opus *.wma *.aiff *.alac")
        if audio_path:
            VIDEO_CONFIG["audio_path"] = audio_path
            return True

    return False





def choose_action_conclusion() -> None:
    """
    Determine if we want to clip succesful/unsucessful actions via
    questionary select input

    """

    selected = questionary.select(
        "Successful/unsuccessful actions only or include both?",
        choices=["Both", "Successful","Unsuccessful"],
        use_arrow_keys=True
    ).ask()

    if selected == "Both": return


    VIDEO_CONFIG["action_conclusion"] = selected


def get_start_offset():
    """ Store the offset before action occurs via user input """
    VIDEO_CONFIG["start_offset"] = click.prompt(text=click.style("Seconds before action occurs offset", bold= True, fg="green"), type=click.IntRange(min=0))



@click.command()
@click.option("--link",
              prompt=click.style("Enter WhoScored link (must be a live link!)",
              bold = True,
              fg = "cyan"),
              help= "The WhoScored match link",
              callback = validate_whoscored_link)
def start_program(link: str) -> None :

    """
    The main function that calls on program start.
    Handles user input gathering and calls the pipeline
    to begin timeline gathering and video cropping.

    Args:
        link (str): WhoScored link, must be a live link else repeats.
    """

    # Input both video halves
    click.secho("Select first half video", fg="green", bold = True)
    first_half_valid = get_video(1)
    if not first_half_valid : return

    click.secho("Select second half video", fg="green", bold=True)
    second_half_valid = get_video(2)
    if not second_half_valid: return

    # Custom audio option
    custom_audio = get_audio()

    # Sync video with match time (if required)
    needs_calibration = click.confirm("Do the videos need calibrating? (video time matches match time?)", default=True)
    if needs_calibration:
        calibrate_halves()

    # Applies a negative offset at start time before we ffmpeg crop
    get_start_offset()

    # User input to determine if we want a succcesful or unsuccesful action (or both)
    choose_action_conclusion()

    # Get match info via selenium
    click.secho("Loading site...", fg="green", bold = True)
    match_dict, match_info = parse_site(link)

    # Choose players to create a compilation of
    initialize_player_class(match_dict)

    if not VIDEO_CONFIG["players_list"]:
        print("Didn't select a player! aborting")
        return

    # Go through players_list and start the compilation creation
    start_pipeline(match_info)


def get_match_time_manual(video_path: str, seek_minute: int) -> None:

    """
    1. Display a frame of a video via video_path
    2. Go to seek_minutes into a video
    3. Wait for player input to close the image
    4. Display input with message to input the match time shown
    5. Go back to 4 if input is wrong format.

    Args:
         video_path (str): Path to input video, should be first half or second half
         seek_minute (int): Minute to go to in the video, should be VIDEO_CONFIG["timer_timestamp_minute"]

    Returns:
        int: minutes
        int: seconds

    """
    vid = cv2.VideoCapture(video_path)
    cv2.namedWindow("Preview", cv2.WINDOW_AUTOSIZE)
    cv2.setWindowProperty("Preview", cv2.WND_PROP_TOPMOST, 1)
    vid.set(cv2.CAP_PROP_POS_MSEC, seek_minute * 60_000)
    success, image = vid.read()
    vid.release()

    if not success:
        click.secho("Failed to read frame", fg="red")
        return

    # Show image
    cv2.imshow("Preview", image)
    click.secho("Look at the match clock, then press any key to close", fg="yellow")
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    # Get manual input after image is closed
    while True:
        time_input = click.prompt("Enter match time shown (MM:SS)", type=str)

        try:
            parts = time_input.split(":")
            minutes = int(parts[0])
            seconds = int(parts[1])

            if 0 <= minutes <= 120 and 0 <= seconds <= 59:
                return minutes, seconds
            else:
                click.secho("Invalid time range", fg="red")
        except (ValueError, IndexError):
            click.secho("Use format MM:SS (e.g. 45:27)", fg="red")


def calibrate_halves() -> None:
    """
    Calculate the time offset to sync match time with the unmatched video input.
    This relies on the user inputting the match time after being shown a frame
    VIDEO_CONFIG["timer_timestamp_minute"] minutes in a video.
    """

    # Calibrate both halves by showing a frame and asking for match time in both halves.
    for i in range(2):
        half = "First Half" if i == 0 else "Second Half"
        path = VIDEO_CONFIG["first_half_path"] if i == 0 else VIDEO_CONFIG["second_half_path"]

        click.secho(f"\n{half}: Look at the match clock in the image", fg="green")

        result = get_match_time_manual(path, VIDEO_CONFIG["timer_timestamp_minute"])

        if result is None:
            continue

        minutes, seconds = result
        detected_seconds = (minutes * 60) + seconds

        if i == 0:
            expected_seconds = VIDEO_CONFIG["timer_timestamp_minute"] * 60
        else:
            expected_seconds = (VIDEO_CONFIG["timer_timestamp_minute"] + 45) * 60

        offset = detected_seconds - expected_seconds

        click.secho(f"Time: {minutes:02d}:{seconds:02d}", fg="cyan")
        click.secho(f"Offset: {offset} seconds", fg="green")

        VIDEO_CONFIG["first_half_offset" if i == 0 else "second_half_offset"] = offset


def parse_site(link: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    """
    Use Beautiful Soup to web scrape WhoScored, which provides player's event data.
    Stores its data in a file to skip this step if program is reran on same match in the future.
    Args:
        link (str): Link to site
    Returns:
        tuple[dict[str, Any], list[dict[str, Any]]]:
            A tuple where:
            - match_dict - matchCentreData dictionary
            - match_event - All player events in the current match

    """
    # check if exists first and use that data instead
    exists = database.init_db()

    if exists:
        match_dict = database.get_db_dict(VIDEO_CONFIG["match_id"], "match_dict")
        match_events = database.get_db_dict(VIDEO_CONFIG["match_id"], "events")
        if not match_dict:
            print("Missing match_dict in db, we'll create it")
        if not match_events:
            print("Missing match_events in db, we'll create it")

        if match_dict and match_events:
            click.secho("Match data already exists, using!", fg="yellow")
            return match_dict, match_events






    # try:
    #     with open(os.path.join(VIDEO_CONFIG["cwd"], "FootballMatchData", f"{VIDEO_CONFIG["match_id"]}.json"), encoding="utf-8") as f:
    #         click.secho("Match data already exists, using!", fg="yellow")
    #         match_dict = json.load(f)
    #         match_event = match_dict['events']
    #         return match_dict, match_event
    # except FileNotFoundError:
    #     pass


    driver = webdriver.Chrome()
    driver.get(link)

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    element = soup.select_one('script:-soup-contains("matchCentreData")')

    if not element:
        click.secho(message="Can't find matchCentreData from link", fg="red")
        return None, None

    click.secho("Site loaded and looks correct, starting parse...", fg="green", bold=True)
    match_dict = json.loads(element.text.split("matchCentreData: ")[1].split(",\n")[0])
    match_event = match_dict['events']
    match_player_dict = match_dict["playerIdNameDictionary"]

    database.add_to_db(VIDEO_CONFIG["match_id"],
                       json.dumps(match_dict),
                       json.dumps(match_player_dict),
                       json.dumps(match_event))



    # save to a folder called "match_data" so we can skip the parse process if reran
    # save_path = os.path.join(VIDEO_CONFIG["cwd"],"FootballMatchData")
    # os.makedirs(save_path, exist_ok=True)
    # with open(os.path.join(save_path, f"{VIDEO_CONFIG["match_id"]}.json"), "w", encoding="utf-8") as f:
    #     json.dump(match_dict, f)

    return match_dict, match_event


def combine_videos(file1: str, file2: str, output_file: str) -> None:
    """
    Use Ffmpeg to combine two clips together, mainly used for combining first half and second half clips.
    Args:
        file1 (str): Path of the processed video
        file2 (str): Path of the processed video
        output_file (str): Path of the output video
    """
    # Returns early if one file input is missing, this usually means the player has
    # only has actions in one half, meaning combination is unnecessary.

    if file1 is None or file2 is None:
        print("No point combining, one half is missing. Potentially no actions in one half.")
        return

    concat_input = f"file '{file1}'\nfile '{file2}'\n"

    if VIDEO_CONFIG["audio_path"]:
        cmd = [
            "ffmpeg",
            "-f", "concat", "-safe", "0",
            "-protocol_whitelist", "file,pipe",
            "-i", "pipe:",
            "-stream_loop", "-1", "-i", VIDEO_CONFIG["audio_path"],
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v",
            "-map", "1:a",
            "-shortest",
            "-y", output_file
        ]
    else:
        cmd = [
            "ffmpeg",
            "-f", "concat", "-safe", "0",
            "-protocol_whitelist", "file,pipe",
            "-i", "pipe:",
            "-c:v", "copy",
            "-c:a", "copy",
            "-y", output_file
        ]

    subprocess.run(
        cmd,
        input=concat_input.encode(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    print(f"Combined to: {output_file}")


def event_is_action_conclusion(event_conclusion: str) -> bool    :
    """
    Simple helper to return if the event's conclusion is succesful or not, and checks if it
    matches the player's setting of only wanting succesful actions (or not)

    Args:
        event_conclusion (str): Either Successful or Unsuccesful, should be the current event's conclusion
    """
    if event_conclusion is None: return False

    return event_conclusion == VIDEO_CONFIG["action_conclusion"]


def get_events(match_event : list[dict[str, Any]], players_list: dict[str, player.Player]):
    """
    The main processing function that goes through match_event (has all match events data) and stores its timestamps
    if the event's player id key exists in player_list

    Args:
        match_event (list[dict[str, Any]]): Events data, stores all events of every player in ascending order
        players_list (dict[str, player]): Dictionary with the key of the player's id and a value of their player class
    """

    MAX_CLIP_DURATION = 10
    MIN_CLIP_DURATION = 1

    # Clamp time data within bounds within MIN_CLIP_DURATION & MAX_CLIP_DURATION
    # Mainly to prevent end getting too long if theres no events for a long time if current_start is active
    def clamp_end(start: int, end: int):
        duration = end - start
        if duration > MAX_CLIP_DURATION:
            return start + MAX_CLIP_DURATION
        if duration < MIN_CLIP_DURATION:
            return start + MIN_CLIP_DURATION
        return end

    # Save event to specified player class, depending which period it is
    def save_event(playerClass: player.Player, end: int, period: str):
        start_offset = playerClass.current_start - VIDEO_CONFIG["first_half_offset" if period == "FirstHalf" else "second_half_offset"]
        end_offset = end - VIDEO_CONFIG["first_half_offset" if period == "FirstHalf" else "second_half_offset"]

        event_data = {
            "start": start_offset,
            "end": clamp_end(start_offset, end_offset),
            "type": playerClass.start_event_type,
            "outcome": playerClass.success,
            "period": period
        }

        if period == "FirstHalf":
            playerClass.first_half_events.append(event_data)
        elif period == "SecondHalf":
            playerClass.second_half_events.append(event_data)

        playerClass.current_start = None
        playerClass.start_event_type = None
        playerClass.success = None

    # NOTE: We shouldn't rerun this loop per player due to inefficiencies, run this loop ONCE
    for event in match_event:
        # Seperate important event data into variables
        current_player_id = str(event.get("playerId", ""))
        minute = event.get("minute", 0)
        second = event.get("second", 0)
        current_period = event.get("period", {}).get("displayName")
        current_event_type = event.get("type", {}).get("displayName")

        # Calculate total seconds
        # Not using expandedMinute (which includes added time)
        # due to weird sync issues at this moment, hence why -45
        # is negated in the second half
        total_seconds = (minute * 60) + second if current_period == "FirstHalf" else ((minute - 45) * 60) + second

        for playerId, playerClass in players_list.items():
            # No player event - close any open clip
            if not current_player_id:
                if playerClass.current_start is not None:
                    save_event(playerClass, total_seconds, current_period)
                continue

            if current_player_id == playerId:
                # Action conclusion filter
                # If not None, it's either filtering Successful events or Unsuccessful
                if VIDEO_CONFIG["action_conclusion"] is not None:
                    outcome = event.get("outcomeType", {}).get("displayName")
                    if not event_is_action_conclusion(outcome):
                        continue

                if playerClass.current_start is not None:
                    # Player still on the ball - extend clip, update outcome
                    playerClass.success = event['outcomeType']['displayName']
                else:
                    # Start new clip
                    playerClass.current_start = total_seconds
                    playerClass.start_event_type = current_event_type
                    playerClass.success = event['outcomeType']['displayName']
            else:
                # Different player touched the ball or some other event - close open clip
                if playerClass.current_start is not None:
                    save_event(playerClass, total_seconds, current_period)

    # Close any remaining open clips
    for playerId, playerClass in players_list.items():
        if playerClass.current_start is not None:
            save_event(playerClass, playerClass.current_start + MIN_CLIP_DURATION, current_period)






def merge_segments(segments: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """
    Merge overlapping timeline data to create a seamless clip instead of repeatinmg clips on overlapping timeline data
    Args:
        segments (list[tuple[int,int]]): Timeline data pair start -> end. If empty, returns empty list.
    Returns:
        list[tuple[int,int]]: Processed overlapped list
    """
    if not segments:
        return []
    sorted_segs = sorted(segments, key=lambda x: x[0])
    merged = [sorted_segs[0]]
    for start, end in sorted_segs[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged



def start_clipping(player: player.Player, player_events: list[dict[str, Any]]) -> subprocess.Popen:
    """
    Use ffmpeg to crop areas of a video according to the player's class timeline data and
    combine them togeher to create a first half/second half clip

    Args:
        player (player): The player class (should have processed data already)
        player_events (list[dict[str, Any]]): The first/second half events of a specific player (inside player class)
    """

    if not player_events:
        print(f"{player.name} has no events in this half ")
        return

    period = player_events[0]['period']

    # Should be None or contain the windows path to the audio
    audio_path = VIDEO_CONFIG.get("audio_path")

    # Create output file & folder's path
    output_folder = os.path.join(VIDEO_CONFIG["cwd"], player.name)
    os.makedirs(output_folder, exist_ok=True)
    output_file = os.path.join(output_folder, f"{VIDEO_CONFIG["match_id"]}_{player.name}_{period}_comp.mp4")

    # Get input video path depending on period
    video_path = VIDEO_CONFIG["first_half_path"] if period == "FirstHalf" else VIDEO_CONFIG["second_half_path"]

    # Create output path depending on period
    setattr(player,"first_half_output" if period == "FirstHalf" else "second_half_output", output_file)

    # Add offsets to the existing player timeline data and store it in segments
    segments = []
    for event in player_events:
        start = max(0, event["start"] - VIDEO_CONFIG["start_offset"])
        end = event["end"]
        segments.append((start, end))

    segments = merge_segments(segments)
    n = len(segments)

    # Ffmpeg commands for clip trimming using segment list (timeline data)
    parts = []
    for i, (start, end) in enumerate(segments):
        parts.append(f"[0:v]trim={start}:{end},setpts=PTS-STARTPTS[v{i}]")

    # Build Ffmpeg commands
    # Replace default audio track if VIDEO_CONFIG["audio_path"] is not None
    if audio_path:
        concat_in = "".join(f"[v{i}]" for i in range(n))
        parts.append(f"{concat_in}concat=n={n}:v=1:a=0[outv]")
        cmd = [
            "ffmpeg", "-i", video_path,
            "-stream_loop", "-1", "-i", audio_path,
            "-filter_complex", ";".join(parts),
            "-map", "[outv]", "-map", "1:a",
            "-c:v", "libx264", "-crf", "23", "-c:a", "aac",
            "-shortest", "-y", output_file
        ]
    else:
    # Else keep audio data the same as original inputs
        for i, (start, end) in enumerate(segments):
            parts.append(f"[0:a]atrim={start}:{end},asetpts=PTS-STARTPTS[a{i}]")
        concat_in = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{concat_in}concat=n={n}:v=1:a=1[outv][outa]")
        cmd = [
            "ffmpeg", "-i", video_path,
            "-filter_complex", ";".join(parts),
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-crf", "23", "-c:a", "aac",
            "-y", output_file
        ]

    # Run the ffmpeg command to clip using segments data (seconds) and combine into one video
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Started clipping: {output_file}\n")
    print(f"Saved to: {output_file}\n")
    return proc



def initialize_player_class(match_dict: dict[str, str]):
    """
    Begins the process to initiate a custom player class and store into the
    VIDEO_CONFIG["players_list"][id] dictionary

    Args:
        match_dict (dict[str, str]): WhoScored matchcentredata dictionary element (via BeautifulSoup)
    """

    # Get the player's name associated to ID dictionary
    player_dict = match_dict["playerIdNameDictionary"]

    # Convert to an array
    player_array =  [{"name": name, "value": key} for key, name in player_dict.items()]

    # Ask the user to choose the players to create a compilation of
    selected = questionary.checkbox(
        message="Select the player's you want to make a compilation of (press enter when done):",
        choices= player_array
    ).ask()

    # Initialize player class for each selected player and store to VIDEO_CONFIG["players_list"]
    for id in selected:
        name = player_dict[id]
        print(f'Initializing player {name} with id {id}')
        new_player = Player(name, id)
        VIDEO_CONFIG["players_list"][id] = new_player



def process_player(player: player.Player) -> None:
    """
    Begins the process to clip processed timeline data of a specific player class

    Args:
        player (player): The custom player class that holds the timeline data of their events
    """

    procs = []
    # Clip first and second half
    if player.first_half_events:
        p1 = start_clipping(player, player.first_half_events)
        procs.append(p1)

    if player.second_half_events:
        p2 = start_clipping(player, player.second_half_events)
        procs.append(p2)

    for p in procs:
        p.wait()
        if p.returncode != 0:
            print(f"FFmpeg failed with return code {p.returncode}")

    # Combine the clips into full video
    output_path = os.path.join(
        VIDEO_CONFIG["cwd"],
        player.name,
        f'{VIDEO_CONFIG["match_id"]}_{player.name}_full_comp.mp4'
    )
    combine_videos(player.first_half_output, player.second_half_output, output_path)


def start_pipeline(match_info: list[dict[str, Any]]) -> None:
    """
    Begins the process to parse timeline data and concatenate clips together
    Use threads to speed up the process

    Args:
        match_info (list[dict[str,Any]]): The list of events that occurs during the match
    """
    players_list = VIDEO_CONFIG["players_list"]
    get_events(match_info, players_list)

    num_threads = min(os.cpu_count() or 4, len(players_list))
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        executor.map(process_player, players_list.values())

























