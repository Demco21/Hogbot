# Constants
KEY_SUFFIX_VOICE = '_voice'
KEY_SUFFIX_MUTE = '_mute'
KEY_SUFFIX_DEAFEN = '_deafen'
KEY_SUFFIX_STREAM = '_stream'
VALID_ARG_TYPES = ['voice', 'muted', 'deafened', 'streaming']
SUFFIXES = {
    VALID_ARG_TYPES[0]: KEY_SUFFIX_VOICE,
    VALID_ARG_TYPES[1]: KEY_SUFFIX_MUTE,
    VALID_ARG_TYPES[2]: KEY_SUFFIX_DEAFEN,
    VALID_ARG_TYPES[3]: KEY_SUFFIX_STREAM
}
DAY_OVERRIDES = {
    "monday": "🍺 Monday Beers",
    "tuesday": "🍺 Tuesday Beers",
    "wednesday": "🍺 Wednesday Beers",
    "thursday": "🍺 Thursday Beers",
    "friday": "🍺 Friday Beers",
    "saturday": "🍺 Saturday Beers",
    "sunday": "🍺 Sunday Beers"
}
TIME_DATA_FILE = "data/persistence_data.json"
NFL_SCHEDULE_FILE = "data/nfl_game_dump_2025.json"
WINNER_PHRASES_FILE = "data/winner_phrases.json"
YAHOO_TOKEN_FILE = "data/yahoo_token.json"

# Commands
THISWEEK_COMMAND = 'thisweek'
LIFETIME_COMMAND = 'lifetime'
DUMP_COMMAND = 'dump'

from enum import Enum

class GameSource(Enum):
    SLOTS = "slots"
    CEE_LO = "cee_lo"
    RIDE_THE_BUS = "ride_the_bus"
    LOAN = "loan"
    BEG = "beg"
    MY_WALLET = "my_wallet"

class UpdateType(Enum):
    INIT_BALANCE = "init_balance"
    BET_PLACED = "bet_placed"
    BET_WON = "bet_won"
    BET_LOST = "bet_lost"
    BEG = "beg"