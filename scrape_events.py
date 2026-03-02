from bs4 import BeautifulSoup
from selenium import webdriver
import re
import click
import json
from tkinter import Tk, filedialog
import os
import subprocess
VIDEO_CONFIG =  {
    "path": None,
    "start_offset": None
}


def browse_video():
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)  # <-- Force to front
    root.update()                       # <-- Process the attribute change

    file_path = filedialog.askopenfilename(
        parent=root,                    # <-- Attach to root
        title="Select a football clip",
        filetypes=[
            ("Common Video Files", "*.mp4 *.mkv *.mov *.avi *.webm"),
            ("All files", "*.*")
        ]
    )

    root.destroy()
    return file_path


def validate_whoscored_link(ctx, param, value):
    pattern = r"^https://www\.whoscored\.com/matches/\d+/live/.*$"
    if not re.match(pattern, value):
        raise click.BadParameter(
            "Must be https://www.whoscored.com/matches/<id>/live/..."
        )
    return value



def get_video():
    video = browse_video()
    if not video:
        click.secho("Can't find video", fg="red")
        return
    VIDEO_CONFIG["path"] = video


def get_start_offset():
    val = click.prompt(text=click.style("Seconds before action occurs offset", bold= True, fg="green"), type=click.IntRange(min=0))
    VIDEO_CONFIG["start_offset"] = val





@click.command()
@click.option("--link",
              prompt=click.style("Enter WhoScored link (must be a live link!)",
              bold = True,
              fg = "cyan"),
              help= "The WhoScored match link",
              callback = validate_whoscored_link)
def load_up_site(link):
    click.secho("Select FULL match video", fg="green", bold = True)

    # store video path via tkinter
    get_video()

    # supply start time offset before action occurs
    get_start_offset()

    click.secho("Loading site...", fg="green", bold = True)
    driver = webdriver.Chrome()
    driver.get(link)
    parse_site(driver)





def parse_site(driver):
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    element = soup.select_one('script:-soup-contains("matchCentreData")')

    if not element:
        click.secho(message="Can't find matchCentreData from link", fg="red")
        return

    click.secho("Site loaded and looks correct, starting parse...", fg="green", bold=True)
    match_dict = json.loads(element.text.split("matchCentreData: ")[1].split(",\n")[0])

    match_event = match_dict['events']

    # dict: {name} : {playerId}
    player_map = match_dict['playerIdNameDictionary']

    # display names available to use
    click.secho("Input the player ID you want to make a compilation of", fg="yellow")
    for id, name in player_map.items():
        click.secho(message= f"{id}. {name}", fg="green")

    # validate player id
    player_id = pick_player(player_map)

    # start storing the player's events
    player_events = get_events(player_id, match_event)

    # ffmpeg clipping
    start_clipping(player_events, VIDEO_CONFIG["start_offset"])



def get_events(player_id, match_event):
    player_id = int(player_id)
    events = []
    start = None
    start_event_type = None
    success = None
    period = None
    last_seconds = None
    first_half_finish_time = None
    second_half_offset = None

    MAX_CLIP_DURATION = 10
    MIN_CLIP_DURATION = 3

    def clamp_end(start, end):
        duration = end - start
        if duration > MAX_CLIP_DURATION:
            return start + MAX_CLIP_DURATION
        if duration < MIN_CLIP_DURATION:
            return start + MIN_CLIP_DURATION
        return end

    def save_event(end):
        nonlocal start, start_event_type, success, period
        events.append({
            "start": start,
            "end": clamp_end(start, end),
            "type": start_event_type,
            "outcome": success,
            "period": period
        })
        start = None
        start_event_type = None
        success = None
        period = None

    for event in match_event:
        player_id_int = event.get("playerId")
        minute = event.get("expandedMinute", 0)
        second = event.get("second", 0)
        current_period = event.get("period", {}).get("displayName")
        current_event_type = event.get("type", {}).get("displayName")

        # First half finish time
        if current_period == "FirstHalf" and current_event_type == "End" and first_half_finish_time is None:
            first_half_finish_time = (minute * 60) + second

        # Second half offset calculation
        if current_period == "SecondHalf" and current_event_type == "Start" and second_half_offset is None:
            second_half_offset = ((minute * 60) + second) - first_half_finish_time

        # Skip until we have timing info for second half
        if current_period == "SecondHalf" and second_half_offset is None:
            continue

        # Calculate total seconds
        if current_period == "SecondHalf":
            total_seconds = ((minute * 60) + second) - second_half_offset
        else:
            total_seconds = (minute * 60) + second

        last_seconds = total_seconds

        # No player — close open clip
        if not player_id_int:
            if start:
                save_event(total_seconds)
            continue

        if player_id_int == player_id:
            # Period changed — close previous clip
            if start and current_period != period:
                save_event(total_seconds)

            # Player still has possession — keep clip going
            if start:
                continue

            # Start new clip
            start = total_seconds
            start_event_type = current_event_type
            success = event['outcomeType']['displayName']
            period = current_period
        else:
            # Another player — close open clip
            if start is None:
                continue
            save_event(total_seconds)

    # Don't lose last event
    if start is not None:
        save_event(last_seconds)

    return events

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

def start_clipping(player_events, startOffset):
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    output_file = os.path.join(desktop, f"compilation.mp4")

    # Build segments with offset applied
    segments = []
    for event in player_events:
        start = max(0, event["start"] - startOffset)
        end = event["end"] + startOffset
        segments.append((start, end))
        print(event)

    # Merge overlapping segments
    segments = merge_segments(segments)

    filter_parts = []
    concat_inputs = ""
    for i, (start, end) in enumerate(segments):
        filter_parts.append(
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];"
            f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];"
        )
        concat_inputs += f"[v{i}][a{i}]"

    n = len(segments)
    filter_complex = "".join(filter_parts) + f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]"

    subprocess.run([
        "ffmpeg",
        "-i", VIDEO_CONFIG["path"],
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-crf", "23",
        "-c:a", "aac",
        "-y",
        output_file
    ])
    print(f"Saved to: {output_file}")



def pick_player(player_map):
    chosen_id = click.prompt("Pick Player ID", type=str)
    print(VIDEO_CONFIG["path"])

    while not player_map.get(chosen_id):
        chosen_id = click.prompt("Wrong player ID, try again", type=str)

    return chosen_id


























