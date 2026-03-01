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
    click.secho("Select video", fg="green", bold = True)

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


def get_first_half_duration(match_events):
    last = 0
    for event in match_events:
        if event.get("period", {}).get("displayName") == "FirstHalf":
            t = event.get("minute", 0) * 60 + event.get("second", 0)
            last = max(last, t)
    return last

def get_events(player_id, match_event):
    player_id = int(player_id)
    events = []
    start = None
    event_type = None
    success = None
    period = None
    last_seconds = None

    first_half_duration = get_first_half_duration(match_event)

    for event in match_event:
        player_id_int = event.get("playerId")

        # CHANGE THIS BLOCK
        minute = event.get("minute", 0)
        second = event.get("second", 0)
        current_period = event.get("period", {}).get("displayName")

        if current_period == "SecondHalf":
            total_seconds = first_half_duration + ((minute - 45) * 60) + second
        else:
            total_seconds = (minute * 60) + second

        last_seconds = total_seconds

        if not player_id_int:
            if start:
                events.append({
                    "start": start,
                    "end": total_seconds,
                    "type": event_type,
                    "outcome": success,
                    "period": period
                })
                start = None
                event_type = None
                success = None
                period = None
            continue

        if player_id_int == player_id:
            print(f"{minute} min, {second} secs during {current_period}")
            if start and current_period != period:
                events.append({
                    "start": start,
                    "end": total_seconds,
                    "type": event_type,
                    "outcome": success,
                    "period": period
                })
                start = None

            if start:
                continue

            start = total_seconds
            event_type = event['type']['displayName']
            success = event['outcomeType']['displayName']
            period = current_period
        else:
            if start is None:
                continue

            events.append({
                "start": start,
                "end": total_seconds,
                "type": event_type,
                "outcome": success,
                "period": period
            })
            start = None
            event_type = None
            success = None
            period = None

    if start is not None:
        events.append({
            "start": start,
            "end": last_seconds,
            "type": event_type,
            "outcome": success,
            "period": period
        })

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
    output_file = os.path.join(desktop, "highlights.mp4")

    # Build segments with offset applied
    segments = []
    for event in player_events:
        start = max(0, event["start"] - startOffset)
        end = event["end"]
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


























