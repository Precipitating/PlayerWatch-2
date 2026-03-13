import random
import subprocess
import json
from player import Player
from database import VIDEO_TRANSITIONS, VIDEO_CONFIG


def get_video_size(path):
    result = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v:0",
        path
    ], capture_output=True, text=True)
    s = json.loads(result.stdout)["streams"][0]
    return int(s["width"]), int(s["height"])


class Clipper:
    def __init__(self):
        self.parts = []
        self.segments = []
        self.video_out = "[outv]"
        self.inputs = []
        self.mappings = []
        self.has_transitions = False

    def add_offsets_to_segments(self, player_events):
        for event in player_events:
            start = max(0, event["start"] - VIDEO_CONFIG["start_offset"])
            end = event["end"]
            self.segments.append((start, end))
        self.merge_segments()

    def merge_segments(self):
        sorted_segs = sorted(self.segments, key=lambda x: x[0])
        merged = [sorted_segs[0]]
        for start, end in sorted_segs[1:]:
            prev_start, prev_end = merged[-1]
            if start <= prev_end:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))
        self.segments = merged

    # 1. Trim
    def trim_clips(self):
        for i, (start, end) in enumerate(self.segments):
            self.parts.append(f"[0:v]trim={start}:{end},setpts=PTS-STARTPTS[v{i}]")

    # 2. Transitions
    def apply_transitions(self, player: Player):
        n = len(self.segments)
        td = VIDEO_CONFIG["transition_time"]

        if n == 0:
            return

        if n == 1:
            self.parts.append(f"[v0]concat=n=1:v=1:a=0[outv]")
            return

        durations = [end - start for start, end in self.segments]

        valid = all(d > td * 2 for d in durations)

        if not valid or not player.chosen_transition:
            concat_in = "".join(f"[v{i}]" for i in range(n))
            self.parts.append(f"{concat_in}concat=n={n}:v=1:a=0[outv]")
            return

        self.has_transitions = True
        td = VIDEO_CONFIG["transition_time"]
        prev = "v0"
        for i in range(1, n):
            # This is the key formula from the SO post
            offset = sum(durations[:i]) - (i * td)
            offset = max(0, offset)

            out_label = f"xf{i}" if i < n - 1 else "outv"
            transition = (
                player.chosen_transition
                if player.chosen_transition != "random"
                else random.choice([t for t in VIDEO_TRANSITIONS if t != "random"])
            )
            self.parts.append(
                f"[{prev}][v{i}]xfade=transition={transition}"
                f":duration={td}:offset={offset}[{out_label}]"
            )
            prev = f"xf{i}"


    # 3. Watermark filter
    def define_watermark(self, video_path: str):
        watermark_path = VIDEO_CONFIG["watermark_path"]
        if watermark_path:
            vid_w, vid_h = get_video_size(video_path)
            wm_ratio = 0.1
            wm_padding = int(vid_h * 0.03)
            wm_width = int(vid_w * wm_ratio)

            self.parts.append(
                f"[2:v]scale={wm_width}:-1,format=yuva420p[wm_scaled];"
                f"{self.video_out}[wm_scaled]overlay=(W-w)/2:(H-h-{wm_padding})[wmv]"
            )
            self.video_out = "[wmv]"

    # 4. Audio
    def apply_custom_audio(self, audio_path, video_path):
        n = len(self.segments)

        if audio_path:
            self.inputs = ["-i", video_path, "-stream_loop", "-1", "-i", audio_path]
            self.mappings = ["-map", self.video_out, "-map", "1:a", "-shortest"]
            return

        # Trim audio segments
        for i, (start, end) in enumerate(self.segments):
            self.parts.append(f"[0:a]atrim={start}:{end},asetpts=PTS-STARTPTS[a{i}]")

        if self.has_transitions and n > 1:
            # Crossfade audio to match video xfade
            td = VIDEO_CONFIG["transition_time"]
            prev = "a0"
            for i in range(1, n):
                out_label = f"ax{i}" if i < n - 1 else "outa"
                self.parts.append(
                    f"[{prev}][a{i}]acrossfade=d={td}[{out_label}]"
                )
                prev = f"ax{i}"
        else:
            a_concat = "".join(f"[a{i}]" for i in range(n))
            self.parts.append(f"{a_concat}concat=n={n}:v=0:a=1[outa]")

        self.inputs = ["-i", video_path]
        self.mappings = ["-map", self.video_out, "-map", "[outa]"]

    # 5. Watermark input
    def apply_watermark(self):
        watermark_path = VIDEO_CONFIG["watermark_path"]
        if watermark_path:
            wm_index = len([x for x in self.inputs if x == "-i"])
            self.inputs.extend(["-i", watermark_path])
            self.parts = [p.replace("[2:v]", f"[{wm_index}:v]") for p in self.parts]

    # 6. Build
    def build_final_cmd(self, output_file: str):
        return [
            "ffmpeg", "-y", *self.inputs,
            "-filter_complex", ";".join(self.parts),
            *self.mappings,
            "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-crf", "23", "-c:a", "aac",
            output_file
        ]