# Hogbot

Simple Discord bot to monitor how long people spend in Discord voice channels, and time spent muted, deafened, or streaming. Hogbot will on a weekly basis (every sunday morning) report to a designated channel how long each memeber has spent in a voice channel. The top memeber will receive a designated role of Chancellor.

## Getting Started

### Prerequisites

You need to have Python installed. You can download it from [here](https://www.python.org/downloads/).

### Installation

Install the required packages using pip:

```shell
pip install -r requirements.txt
```

### Set up environment file
create a file named `.env` and add the following keys:<br>
`ENV=` where values can be `_DEV` or `_PROD`<br>
`DISCORD_TOKEN_DEV=` value of your dev discord token<br>
`DISCORD_TOKEN_PROD=` value of your prod discord token<br>
`AFK_CHANNEL_ID=` ID value of your AFK channel so timers know to stop for this channel<br>
`ANNOUNCEMENTS_CHANNEL_ID=` ID value of the channel you'd like for Hogbot to push automated messages to<br>
`CHANCELLOR_ROLE_ID=` ID value of the Chancellor role which Hogbot will give to the memeber who spent the most time in voice channels this week<br>
`HOGBOT_USER_ID=` ID of Hogbot itself<br>
`HOGBOT_SERVER_ID=` ID of the server<br>
`CHANGE_CHANNEL_ID=` ID of the beers channel<br>
`NFL_SCHEDULE_CHANNEL_ID=` ID of the nfl schedule channel<br>
`FANTASY_FOOTBALL_CHANNEL_ID=` ID of the fantasy football channel<br>
`ADMIN_USER_ID=` ID of the server admin<br>
`YAHOO_CLIENT_ID=` ID of the yahoo client token for fantasy football<br>
`YAHOO_CLIENT_SECRET=` Secret for yahoo client API<br>
`YAHOO_LEAGUE_KEY=` Yahoo Fantasy football league key<br><br>
Emoji ID's for NFL team emoji<br>
`GIANTS_EMOJI_ID=`<br>
`JETS_EMOJI_ID=`<br>
`BILLS_EMOJI_ID=`<br>
`PATRIOTS_EMOJI_ID=`<br>
`DOLPHINS_EMOJI_ID=`<br>
`RAVENS_EMOJI_ID=`<br>
`BENGALS_EMOJI_ID=`<br>
`BROWNS_EMOJI_ID=`<br>
`STEELERS_EMOJI_ID=`<br>
`TITANS_EMOJI_ID=`<br>
`COLTS_EMOJI_ID=`<br>
`TEXANS_EMOJI_ID=`<br>
`JAGUARS_EMOJI_ID=`<br>
`CHIEFS_EMOJI_ID=`<br>
`BRONCOS_EMOJI_ID=`<br>
`CHARGERS_EMOJI_ID=`<br>
`RAIDERS_EMOJI_ID=`<br>
`EAGLES_EMOJI_ID=`<br>
`COWBOYS_EMOJI_ID=`<br>
`COMMANDERS_EMOJI_ID=`<br>
`PACKERS_EMOJI_ID=`<br>
`BEARS_EMOJI_ID=`<br>
`VIKINGS_EMOJI_ID=`<br>
`LIONS_EMOJI_ID=`<br>
`FALCONS_EMOJI_ID=`<br>
`SAINTS_EMOJI_ID=`<br>
`BUCCANEERS_EMOJI_ID=`<br>
`PANTHERS_EMOJI_ID=`<br>
`NINERS_EMOJI_ID=`<br>
`SEAHAWKS_EMOJI_ID=`<br>
`RAMS_EMOJI_ID=`<br>
`CARDINALS_EMOJI_ID=`<br>

## Running the bot
### Run the bot locally
```shell
py ./main.py
```

### Running on AWS

1. switch to the root user
```shell
sudo su
```
2. Run the bot in the background use nohup (recommended)
```shell
nohup python3 -u main.py &
```
3. You can also run the bot directly using python3 (optional)
```shell
python3 main.py
```
4. Check the log output
```shell
tail -f nohup.out
```
5. Check the running processes
```shell
ps aux | grep python3
```
6. To kill a process where `[PID]` is the process ID you can find from the output of step 5
```shell
kill [PID]
```

## Commands
While the bot is running you can enter the following commands into a discord text channel
```shell
!thisweek [type]
```
```shell
!lifetime [type]
```
### Arguments
* [type] (optional): The type of event to get times for. Valid values are:
    * voice - Time spent in voice channels.
    * muted - Time spent muted in voice channels.
    * deafened - Time spent deafened in voice channels.
    * streaming - Time spent streaming in voice channels.
    * username of the member for which times will be listed for.
    * If blank, defaults to voice.