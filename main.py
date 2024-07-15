import discord
from discord.ext import commands
from datetime import datetime, timedelta

bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

# Dictionary to store join times
join_times = {}
# Dictionary to store total time spent
total_times = {}

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    print(f'Intents configured: {bot.intents}')

@bot.event
async def on_voice_state_update(member, before, after):
    # Check if the user has joined a voice channel
    if before.channel is None and after.channel is not None:
        join_times[member.id] = datetime.utcnow()
        print(f"{member.name} joined {after.channel.name} at {join_times[member.id]}")

    # Check if the user has left a voice channel
    elif before.channel is not None and after.channel is None:
        if member.id in join_times:
            join_time = join_times.pop(member.id)
            time_spent = datetime.utcnow() - join_time
            if member.id not in total_times:
                total_times[member.id] = timedelta()
            total_times[member.id] += time_spent
            print(f"{member.name} left {before.channel.name} after {time_spent}")

@bot.command(name='time_spent')
async def time_spent(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author
    if member.id in total_times:
        time_spent = total_times[member.id]
        await ctx.send(f"{member.name} has spent {time_spent} in voice channels.")
    else:
        await ctx.send(f"{member.name} has not spent any time in voice channels.")

@bot.command(name='hello')
async def hello(ctx):
    print("hello")
    await ctx.send("Hello!")

# Run the bot
bot.run('') #add your discord secret here
