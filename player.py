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
        self.start_event_type = None
        self.success = None
        self.first_half_output = None,
        self.second_half_output =  None,
