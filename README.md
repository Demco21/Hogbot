# HogBot 🐗🏈  

A custom Discord bot that brings together **fantasy football automation** and **community fun**.  
HogBot tracks time spent in Discord voice channels, appoints a weekly “Chancellor,” posts **NFL schedules**, updates **Yahoo Fantasy Football matchups/standings**, and automates channel naming.  

---

## ⚙️ Features  

- **Voice Activity Tracking**  
  - Tracks time spent in voice, muted, deafened, and streaming.  
  - Weekly leaderboards posted automatically.  
  - Appoints a weekly **Chancellor** with a special Discord role.  

- **Fantasy Football Integration**  
  - Yahoo Fantasy Football OAuth2 setup.  
  - Posts weekly **matchups**, **standings**, and **winner announcements**.  
  - Supports periodic updates every few minutes.  

- **NFL Schedule Support**  
  - Fetches and posts weekly NFL schedules from ESPN.  
  - Automatically updates ongoing game states.  

- **Community Automation**  
  - Renames designated channels based on the day.  
  - Schedules routine data dumps for persistence.  
  - Rotating file-based logging with backups.  

- **Casino**
  - Casino games including Ride The Bus, Slots, and Cee Lo

---

## 📂 Project Structure  

```
.
├── main.py                  # Bot entrypoint and scheduler
├── cogs/                    # Command definitions
│   ├── time_cog.py          # Voice tracking commands
│   ├── admin_cog.py         # Admin commands
├── services/                # Core bot services
│   ├── time_service.py      # Voice activity tracking
│   ├── persistence_service.py # Service for dumping and restoring persistent data
│   ├── channel_change_service.py # Channel renamer
│   ├── chancellor_service.py     # Chancellor role logic
│   ├── nfl_service.py       # NFL schedules/weeks
│   ├── espn_service.py      # ESPN API integration
│   ├── yahoo_ff_service.py  # Yahoo Fantasy API integration
│   ├── gamble_service.py    # Global service for casino games
│   ├── ride_the_bus_service.py # Service for playing Ride The Bus casino game
│   ├── slots_service.py     # Service for playing slots casino game
│   ├── cee_lo_service.py    # Service for playing Cee Lo casino game
├── data/                    # Logs and persistent data
│   └── hogbot.log           # Rotating log file
```

---

## 🚀 Getting Started  

### Prerequisites  
- Python 3.9+  
- Discord bot token  
- Yahoo Fantasy Football API credentials  
- ESPN (public API access)  

### Installation  
```bash
git clone https://github.com/Demco21/hogbot.git
cd hogbot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Environment Setup  
Create a `.env` file in the root with:  
```env
ENV=_DEV or _PROD
DISCORD_TOKEN_DEV=your_dev_token
DISCORD_TOKEN_PROD=your_prod_token
AFK_CHANNEL_ID=
ANNOUNCEMENTS_CHANNEL_ID=
CHANCELLOR_ROLE_ID=
HOGBOT_USER_ID=
HOGBOT_SERVER_ID=
CHANGE_CHANNEL_ID=
CASINO_CHANNEL_ID=
ADMIN_USER_ID=
NFL_SCHEDULE_CHANNEL_ID=
FANTASY_FOOTBALL_CHANNEL_ID=
ADMIN_USER_ID=
YAHOO_CLIENT_ID=
YAHOO_CLIENT_SECRET=
YAHOO_LEAGUE_KEY=
GIANTS_EMOJI_ID=
JETS_EMOJI_ID=
BILLS_EMOJI_ID=
PATRIOTS_EMOJI_ID=
DOLPHINS_EMOJI_ID=
RAVENS_EMOJI_ID=
BENGALS_EMOJI_ID=
BROWNS_EMOJI_ID=
STEELERS_EMOJI_ID=
TITANS_EMOJI_ID=
COLTS_EMOJI_ID=
TEXANS_EMOJI_ID=
JAGUARS_EMOJI_ID=
CHIEFS_EMOJI_ID=
BRONCOS_EMOJI_ID=
CHARGERS_EMOJI_ID=
RAIDERS_EMOJI_ID=
EAGLES_EMOJI_ID=
COWBOYS_EMOJI_ID=
COMMANDERS_EMOJI_ID=
PACKERS_EMOJI_ID=
BEARS_EMOJI_ID=
VIKINGS_EMOJI_ID=
LIONS_EMOJI_ID=
FALCONS_EMOJI_ID=
SAINTS_EMOJI_ID=
BUCCANEERS_EMOJI_ID=
PANTHERS_EMOJI_ID=
NINERS_EMOJI_ID=
SEAHAWKS_EMOJI_ID=
RAMS_EMOJI_ID=
CARDINALS_EMOJI_ID=
```
---

## 📝 Running  

### Locally  
```bash
py ./main.py
```

### On AWS (background service)  
```bash
sudo su
nohup python3 -u main.py &
tail -f nohup.out
ps aux | grep python3
kill [PID]
```

---

## 📜 Commands  

### Voice Tracking  
- `!thisweek [voice|muted|deafened|streaming|username]`  
- `!lifetime [voice|muted|deafened|streaming|username]`  
- `!dump` (admin only, forces data dump)

### Yahoo Fantasy (Admin Only)
- `!auth` – authorize Yahoo Fantasy
- `!matchups` / `!matchupsupd`  
- `!standings` / `!standingsupd`  

### NFL / ESPN (Admin Only)
- `!nfldump` (refresh full schedule)
- `!games` – post current week  
- `!gamesupd` – update schedule  

---

## ⏰ Scheduled Jobs  

- **NFL**: Post Tuesday mornings, update every 15 minutes.  
- **Yahoo Fantasy**: Post standings/matchups Tuesday mornings, update every 5 minutes.  
- **Chancellor**: Appointed weekly on Sunday mornings.  
- **Channel Rename**: Midnight rename.  
- **Data Dump**: Hourly persistence.