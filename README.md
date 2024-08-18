# Hogbot

Simple Discord bot to monitor how long people spend in Discord voice channels, and time spent muted, deafened, or streaming. Hogbot will on a weekly basis (every sunday morning) report to a designated channel how long each memeber has spent in a voice channel. The top memeber will receive a designated role of Chancellor.

## Getting Started

### Prerequisites

You need to have Python installed. You can download it from [here](https://www.python.org/downloads/).

### Installation

Install the required packages using pip:

```shell
pip install discord
```
```shell
pip install python-dotenv
```
```shell
pip install apscheduler
```

### Set up environment file
create a file named `.env` and add the following keys:<br>
1. `ENV=` where values can be `_DEV` or `_PROD`<br>
2. `DISCORD_TOKEN_DEV=` value of your dev discord token<br>
3. `DISCORD_TOKEN_PROD=` value of your prod discord token<br>
4. `AFK_CHANNEL_ID=` ID value of your AFK channel so timers know to stop for this channel<br>
5. `HOGBOT_CHANNEL_ID=` ID value of the channel you'd like for Hogbot to push automated messages to<br>
5. `CHANCELLOR_ROLE_ID=` ID value of the Chancellor role which Hogbot will give to the memeber who spent the most time in voice channels this week<br>
6. `HOGBOT_USER_ID=` ID of Hogbot itself
7. `HOGBOT_SERVER_ID=` ID of the server

## Running the bot
### Run the bot locally
```shell
py ./hogbot.py
```

### Running on AWS

1. switch to the root user
```shell
sudo su
```
2. Run the bot in the background use nohup (recommended)
```shell
nohup python3 -u hogbot.py &
```
3. You can also run the bot directly using python3 (optional)
```shell
python3 hogbot.py
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