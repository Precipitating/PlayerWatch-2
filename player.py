import click
import questionary
from utility import file_picker
from database import ACTION_TYPES, VIDEO_TRANSITIONS




class Player:
    """
    Stores player information and most importantly, the events
    """

    def __init__(self, player_name, player_id):
        self.name = player_name
        self.id = player_id
        self.first_half_events = []
        self.second_half_events = []
        self.current_start = None
        self.current_end = None
        self.current_period = None
        self.start_event_type = None
        self.success = None
        self.first_half_output = None
        self.second_half_output =  None
        self.custom_audio = None
        self.action_conclusion = None
        self.filtered_events = None
        self.end_offset = 0
        self.manual_end = None
        self.chosen_transition = None

    def get_audio(self) -> None:
        """
       Determine if we want to use custom audio via
       questionary select input
        """
        require_custom_audio = questionary.select(f"Use custom audio for {self.name}?", choices=["Yes", "No"]).ask()

        if require_custom_audio == "Yes":
            audio_path = file_picker("*.mp3 *.wav *.aac *.m4a *.flac *.ogg *.opus *.wma *.aiff *.alac")
            if audio_path:
                self.custom_audio = audio_path



    def event_is_action_conclusion(self, current_action_conclusion: str) -> bool:
        """
        Simple helper to return if the event's conclusion is succesful or not, and checks if it
        matches the player's setting of only wanting succesful actions (or not)

        Args:
            current_action_conclusion (str): Either Successful or Unsuccessful, should be the current event's conclusion
        """
        return current_action_conclusion == self.action_conclusion


    def get_transition(self):

        use_transition = questionary.select("Use a video transition effect?", choices=["Yes", "No"]).ask()

        if use_transition == "Yes":
            self.chosen_transition = questionary.select(message= "Select video transition to apply per action", choices = VIDEO_TRANSITIONS).ask()




    def get_end_offset(self):
        """ Apply an end offset after action made (in seconds)"""
        self.end_offset = click.prompt("Enter an end offset after each action occurs (s)", type= int)


    def auto_end_detection_option(self):
        """ Give the ability for the user to only apply a fixed offset (seconds) after an action occurs,
            or detect when another player initiates an action before ending the clip
        """
        manual_end = questionary.select("Auto clip end detection or fixed end offset?", choices=["Auto detect", "Manual Offset"]).ask()

        self.manual_end = True if manual_end == "Manual Offset" else False





    def choose_action_conclusion(self) -> None:
        """
        Determine if we want to clip successful/unsuccessful actions via
        questionary select input

        """

        selected = questionary.select(
            f"Successful/unsuccessful actions only or include both? for {self.name}",
            choices=["Both", "Successful", "Unsuccessful"],
            use_arrow_keys=True
        ).ask()

        if selected == "Both": return

        self.action_conclusion = selected

    def filter_events(self):
        """
        Checkbox to select specific actions to filter for the chosen player
        """
        filter_actions = questionary.select(f"Filter specific actions for {self.name}?", ["Yes", "No"]).ask()

        if filter_actions == "No":
            return

        select_actions = questionary.checkbox(message="Select actions to filter",
                                              choices=ACTION_TYPES,
                                              validate=lambda choice: True if len(
                                                  choice) > 0 else "Select atleast one option").ask()

        if select_actions:
            self.filtered_events = select_actions

