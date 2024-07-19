# Hogpen Monitor

Simple Discord bot to monitor how long people spend in Discord voice channels, and time spent muted, deafened, or streaming.

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

### run the bot locally
```shell
py ./main.py
```

### running on AWS

1. switch to the root user

```shell
sudo su
```

2. run the bot using python3

```shell
python3 main.py
```

3. to run the bot in the background use nohup

```shell
nohup python3 -u main.py &
```

4. check the log output
```shell
tail -f nohup.out
```

5. check the running instances
```shell
ps aux | grep python3
```

6. kill an instance where `<instance>` is the instance number you can find from the output of step 5
```shell
kill <instance>
```