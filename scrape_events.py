from bs4 import BeautifulSoup
from selenium import webdriver
import re
import click
import json
from tkinter import Tk, filedialog
import os
import subprocess
import cv2
import questionary
from player import Player
from concurrent.futures import ThreadPoolExecutor
import sqlite3
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



def file_picker(file_types):
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


def validate_whoscored_link(ctx, param, value):
    pattern = r"^https://www\.whoscored\.com/matches/\d+/live(?:/.*)?$"
    if not re.match(pattern, value):
        raise click.BadParameter(
            "Must be https://www.whoscored.com/matches/<id>/live/..."
        )

    VIDEO_CONFIG["match_id"] = re.search(r"/matches/(\d+)", value).group(1)
    return value



def get_video(type: object) -> bool:
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



""" Supply a custom audio if required"""
def get_audio():
    require_custom_audio = questionary.select("Use custom audio?", choices=["Yes", "No"]).ask()

    if require_custom_audio == "Yes":
        audio_path = file_picker("*.mp3 *.wav *.aac *.m4a *.flac *.ogg *.opus *.wma *.aiff *.alac")
        if audio_path:
            VIDEO_CONFIG["audio_path"] = audio_path
            return True

    return False




""" Determine if we want to clip succesful actions by the player or only unsucessful ones"""
def choose_action_conclusion():
    selected = questionary.select(
        "Successful/unsuccessful actions only or include both?",
        choices=["Both", "Successful","Unsuccessful"],
        use_arrow_keys=True
    ).ask()

    if selected == "Both": return


    VIDEO_CONFIG["action_conclusion"] = selected



""" Apply an offset before action occurs"""
def get_start_offset():
    VIDEO_CONFIG["start_offset"] = click.prompt(text=click.style("Seconds before action occurs offset", bold= True, fg="green"), type=click.IntRange(min=0))


"""The main function for displaying and processing CLI options"""
@click.command()
@click.option("--link",
              prompt=click.style("Enter WhoScored link (must be a live link!)",
              bold = True,
              fg = "cyan"),
              help= "The WhoScored match link",
              callback = validate_whoscored_link)
def start_program(link):
    """ Input both video halves"""
    click.secho("Select first half video", fg="green", bold = True)
    first_half_valid = get_video(1)
    if not first_half_valid : return

    click.secho("Select second half video", fg="green", bold=True)
    second_half_valid = get_video(2)
    if not first_half_valid: return

    """Custom audio option"""
    custom_audio = get_audio()



    """ Sync video with match time (if required) """
    needs_calibration = click.confirm("Do the videos need calibrating? (video time matches match time?)", default=True)
    if needs_calibration:
        calibrate_halves()

    get_start_offset()

    choose_action_conclusion()

    """ Get match info via selenium"""
    click.secho("Loading site...", fg="green", bold = True)
    match_dict, match_info = parse_site()


    if match_dict is None or match_info is None:
        print("match_dict or match_info is None, aborting")
        return

    """ Choose players to create a compilation of"""
    initialize_player_class(match_dict)

    if not VIDEO_CONFIG["players_list"]:
        print("Didn't select a player! aborting")
        return

    """ Go through players_list and start the compilation creation"""
    start_pipeline(match_info)






"""Show frame from video and let user manually input the match time."""
def get_match_time_manual(video_path, seek_minute):

    vid = cv2.VideoCapture(video_path)
    cv2.namedWindow("Preview", cv2.WINDOW_AUTOSIZE)
    cv2.setWindowProperty("Preview", cv2.WND_PROP_TOPMOST, 1)
    vid.set(cv2.CAP_PROP_POS_MSEC, seek_minute * 60_000)
    success, image = vid.read()
    vid.release()

    if not success:
        click.secho("Failed to read frame", fg="red")
        return None

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


""" Determine offset to sync the video with match time and apply to timestamps later"""
def calibrate_halves():
    """Calibrate both halves by showing a frame and asking for match time."""
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


def parse_site():

    # check if exists first and use that data instead
    try:
        with open(os.path.join(VIDEO_CONFIG["cwd"], "FootballMatchData", f"{VIDEO_CONFIG["match_id"]}.json"), encoding="utf-8") as f:
            click.secho("Match data already exists, using!", fg="yellow")
            match_dict = json.load(f)
            match_event = match_dict['events']
            return match_dict, match_event
    except FileNotFoundError:
        pass


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


    # save to a folder called "match_data" so we can skip the parse process if reran
    save_path = os.path.join(VIDEO_CONFIG["cwd"],"FootballMatchData")
    os.makedirs(save_path, exist_ok=True)
    with open(os.path.join(save_path, f"{VIDEO_CONFIG["match_id"]}.json"), "w", encoding="utf-8") as f:
        json.dump(match_dict, f)

    return match_dict, match_event


def combine_videos(file1, file2, output_file):

    if file1 is None or file2 is None:
        print("No point combining, one half is missing. Potentially no actions in one half.")
        return

    """Concatenate two video files into one."""
    cmd = [
        "ffmpeg",
        "-i", file1,
        "-i", file2
    ]

    if VIDEO_CONFIG["audio_path"]:
        cmd += [
            "-stream_loop", "-1",
            "-i", VIDEO_CONFIG["audio_path"],
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[outv]",
            "-map", "[outv]",
            "-map", "2:a",
            "-shortest"
        ]
    else:
        cmd += [
            "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]",
            "-map", "[outv]",
            "-map", "[outa]"
        ]

    cmd += [
        "-c:v", "libx264",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-y",
        output_file
    ]

    subprocess.run(cmd)

    print(f"Combined to: {output_file}")


""" Determines if current event is succesful or not """
def event_is_action_conclusion(event_conclusion):
    if event_conclusion is None: return False

    return event_conclusion == VIDEO_CONFIG["action_conclusion"]

""" The main function that stores clipping ranges via timestamps provided by WhoScored"""
def get_events(match_event, players_list):

    MAX_CLIP_DURATION = 10
    MIN_CLIP_DURATION = 2

    def clamp_end(start, end):
        duration = end - start
        if duration > MAX_CLIP_DURATION:
            return start + MAX_CLIP_DURATION
        if duration < MIN_CLIP_DURATION:
            return start + MIN_CLIP_DURATION
        return end

    def save_event(playerClass, end, period):
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

    """ NOTE: We shouldn't redo this per player due to inefficiencies, do it inside the loop instead """
    for event in match_event:
        current_player_id = event.get("playerId")
        current_player_id = str(current_player_id)
        minute = event.get("minute", 0)
        second = event.get("second", 0)
        current_period = event.get("period", {}).get("displayName")
        current_event_type = event.get("type", {}).get("displayName")

        # Calculate total seconds
        # Not using expandedMinute (which includes added time)
        # due to weird sync issues at this moment, hence why -45
        # is negated in the second half

        total_seconds = (minute * 60) + second if current_period == "FirstHalf" else ((minute - 45) * 60) + second

        for event in match_event:
            current_player_id = str(event.get("playerId", ""))
            minute = event.get("minute", 0)
            second = event.get("second", 0)
            current_period = event.get("period", {}).get("displayName")
            current_event_type = event.get("type", {}).get("displayName")

            total_seconds = (minute * 60) + second if current_period == "FirstHalf" else ((minute - 45) * 60) + second

            for playerId, playerClass in players_list.items():
                # No player event — close any open clip
                if not current_player_id:
                    if playerClass.current_start is not None:
                        save_event(playerClass, total_seconds, current_period)
                    continue

                if current_player_id == playerId:
                    # Action conclusion filter
                    if VIDEO_CONFIG["action_conclusion"] is not None:
                        outcome = event.get("outcomeType", {}).get("displayName")
                        if not event_is_action_conclusion(outcome):
                            continue

                    if playerClass.current_start is not None:
                        # Player still on the ball — extend clip, update outcome
                        playerClass.success = event['outcomeType']['displayName']
                    else:
                        # Start new clip
                        playerClass.current_start = total_seconds
                        playerClass.start_event_type = current_event_type
                        playerClass.success = event['outcomeType']['displayName']
                else:
                    # Different player touched the ball — close open clip
                    if playerClass.current_start is not None:
                        save_event(playerClass, total_seconds, current_period)

        # Close any remaining open clips
        for playerId, playerClass in players_list.items():
            if playerClass.current_start is not None:
                save_event(playerClass, playerClass.current_start + MIN_CLIP_DURATION, current_period)





""" Handle ffmpeg time overlap when cropping """
def merge_segments(segments):
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



""" Use player events timestamps and clip + concatenate them together via ffmpeg
 player - target player class (holds their event data etc)
 player_events - target player events (first half or second half)
"""
def start_clipping(player, player_events):
    if not player_events:
        print(f"{player.name} has no events in this half ")
        return
    period = player_events[0]['period']
    audio_path = VIDEO_CONFIG.get("audio_path")

    output_folder = os.path.join(VIDEO_CONFIG["cwd"], player.name)
    os.makedirs(output_folder, exist_ok=True)
    output_file = os.path.join(output_folder, f"{VIDEO_CONFIG["match_id"]}_{player.name}_{period}_comp.mp4")

    # get input video path depending on period
    video_path = VIDEO_CONFIG["first_half_path"] if period == "FirstHalf" else VIDEO_CONFIG["second_half_path"]

    # create output path  depending on period
    setattr(player,"first_half_output" if period == "FirstHalf" else "second_half_output", output_file)

    segments = []
    for event in player_events:
        start = max(0, event["start"] - VIDEO_CONFIG["start_offset"])
        end = event["end"] + (VIDEO_CONFIG["start_offset"] * 0.5)
        segments.append((start, end))

    segments = merge_segments(segments)
    n = len(segments)

    parts = []
    for i, (start, end) in enumerate(segments):
        parts.append(f"[0:v]trim={start}:{end},setpts=PTS-STARTPTS[v{i}]")

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

    subprocess.run(cmd)

    print(f"Saved to: {output_file}")


""" Initialize a player class """
""" match_dict - parsed data from WhoScored, used to get player mapping data """
def initialize_player_class(match_dict):
    player_dict = match_dict["playerIdNameDictionary"]
    player_array =  [{"name": name, "value": key} for key, name in player_dict.items()]

    selected = questionary.checkbox(
        message="Select the player's you want to make a compilation of (press enter when done):",
        choices= player_array
    ).ask()

    """ Initialize player class for each selected player """
    for id in selected:
        name = player_dict[id]
        print(f'Initializing player {name} with id {id}')
        new_player = Player(name, id)
        VIDEO_CONFIG["players_list"][id] = new_player


""" Start creating clips from time frames"""
""" player - The player class of a specified player """
def process_player(player):
    # Clip first and second half
    start_clipping(player, player.first_half_events)
    start_clipping(player, player.second_half_events)

    # Combine the clips into full video
    output_path = os.path.join(
        VIDEO_CONFIG["cwd"],
        player.name,
        f"{VIDEO_CONFIG["match_id"]}_{player.name}_full_comp.mp4"
    )
    combine_videos(player.first_half_output, player.second_half_output, output_path)

""" Start going through the process to create the compilation"""
""" match_info - The full events data of the match """
def start_pipeline(match_info):
    players_list = VIDEO_CONFIG["players_list"]
    get_events(match_info, players_list)

    num_threads = os.cpu_count() or 4  # default to 4 if detection fails
    with ThreadPoolExecutor(max_workers=num_threads) as executor:  # adjust max_workers as needed
        executor.map(process_player, players_list.values())


























