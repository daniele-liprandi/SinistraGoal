import discord
from discord import app_commands
from discord.ext import commands
import requests
import os
from datetime import datetime
import logging

# Bot setup
intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)

API_BASE = os.getenv('API_BASE', '')
API_KEY = os.getenv('API_KEY', '')
API_VERSION = os.getenv('API_VERSION', '1.6.0')

def get_api_headers():
    """Return headers required by the Flask API (apikey + apiversion).

    The backend expects headers named 'apikey' and 'apiversion' (lowercase).
    """
    headers = {}
    if API_KEY:
        headers["apikey"] = str(API_KEY)
    # Always include a sane apiversion to satisfy the backend validator
    headers["apiversion"] = str(API_VERSION)
    return headers


def _mask_key(k: str) -> str:
    if not k:
        return "(none)"
    if len(k) <= 8:
        return k
    return f"{k[:4]}...{k[-4:]}"

@bot.event
async def on_ready():
    print(f'🚀 {bot.user} is now online and ready!')
    print(f'📡 Connected to {len(bot.guilds)} server(s)')
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f'✅ Synced {len(synced)} slash command(s)')
    except Exception as e:
        print(f'❌ Failed to sync commands: {e}')

# Helper function to fetch and display goals
async def show_goals_helper(interaction: discord.Interaction, filter_value: str = "all"):
    """Shared logic for displaying goals"""
    try:
        # Fetch objectives from backend
        headers = get_api_headers()
        logging.info(f"Requesting {API_BASE}objectives headers={_mask_key(headers.get('apikey',''))} apiversion={headers.get('apiversion')}")
        response = requests.get(
            f'{API_BASE}objectives',
            headers=headers,
            params={'active': 'true'},
            timeout=10
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            # Include backend response body for easier debugging
            body = response.text if response is not None else ''
            await interaction.followup.send(f"❌ Backend returned HTTP {response.status_code}: {body}")
            return
        objectives = response.json()
        
        # Filter active objectives
        active_objectives = [
            obj for obj in objectives
            if is_active(obj)
        ]
        
        if not active_objectives:
            await interaction.followup.send("📭 No active objectives at the moment, Comrade!")
            return
        
        # Filter by type if specified
        if filter_value != "all":
            filtered = filter_by_type(active_objectives, filter_value)
            if not filtered:
                await interaction.followup.send(f"❌ No {filter_value} objectives found!")
                return
            active_objectives = filtered
        
        # Sort by priority
        active_objectives.sort(key=lambda x: int(x.get('priority', 0)), reverse=True)
        
        # Create embed
        title = "⚒️ Current CIU Objectives"
        if filter_value != "all":
            title += f" - {filter_value.capitalize()}"
            
        embed = discord.Embed(
            title=title,
            description="From each according to their ability, to each according to their needs",
            color=discord.Color.red()
        )
        
        for obj in active_objectives[:5]:  # Show top 5
            priority = "⭐" * min(int(obj.get('priority', 0)), 5)
            title_text = obj.get('title', 'Unnamed')
            system = obj.get('system', 'N/A')
            faction = obj.get('faction', 'N/A')
            
            # Build target summary
            targets = obj.get('targets', [])
            target_summary = []
            for target in targets[:3]:  # Show first 3 targets
                t_type = target.get('type', '').upper()
                icon = get_target_icon(t_type)
                target_overall = target.get('targetoverall', 0)
                if target_overall > 0:
                    target_summary.append(f"{icon} {t_type}: {target_overall:,}")
            
            value = f"**System:** {system}\n**Faction:** {faction}\n"
            if target_summary:
                value += "**Targets:**\n" + "\n".join(target_summary)
            
            embed.add_field(
                name=f"{priority} {title_text}",
                value=value,
                inline=False
            )
        
        embed.set_footer(text="Use /colonies for colonization goals")
        await interaction.followup.send(embed=embed)
        
    except requests.RequestException as e:
        await interaction.followup.send(f"❌ Error connecting to backend: {str(e)}")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}")

@bot.tree.command(name="goals", description="Show current objectives")
@app_commands.describe(
    goal_type="Filter by activity type (fighting, hauling, colonizing)"
)
@app_commands.choices(goal_type=[
    app_commands.Choice(name="All", value="all"),
    app_commands.Choice(name="Fight", value="fight"),
    app_commands.Choice(name="Haul", value="haul"),
    app_commands.Choice(name="Explore", value="explore")
])
async def goals(interaction: discord.Interaction, goal_type: app_commands.Choice[str] = None):
    """Show current objectives"""
    await interaction.response.defer()
    filter_value = goal_type.value if goal_type else "all"
    await show_goals_helper(interaction, filter_value)

@bot.tree.command(name="colonies", description="Show priority colonization goals")
async def colonies(interaction: discord.Interaction):
    """Show priority colonization goals"""
    await interaction.response.defer()
    
    try:
        headers = get_api_headers()
        logging.info(f"Requesting {API_BASE}colonies/priority headers={_mask_key(headers.get('apikey',''))} apiversion={headers.get('apiversion')}")
        response = requests.get(
            f'{API_BASE}colonies/priority',
            headers=headers,
            timeout=10
        )
        try:
            response.raise_for_status()
        except requests.HTTPError:
            body = response.text if response is not None else ''
            await interaction.followup.send(f"❌ Backend returned HTTP {response.status_code}: {body}")
            return
        colonies_list = response.json()
        
        if not colonies_list:
            await interaction.followup.send("📭 No priority colonies at the moment!")
            return
        
        embed = discord.Embed(
            title="🌍 Colonisation Goals",
            description="Use SrvSurvey to track your help!",
            color=discord.Color.gold()
        )
        
        for colony in colonies_list[:5]:
            priority = "⭐" * min(colony.get('priority', 0), 5)
            system = colony.get('starsystem', 'Unknown')
            cmdr = colony.get('cmdr', 'N/A')
            raven_url = colony.get('ravenurl', '')
            
            value = f"**Commander:** {cmdr}\n"
            if raven_url:
                value += f"[🔗 View on Raven Colonial]({raven_url})"
            
            embed.add_field(
                name=f"{priority} {system}",
                value=value,
                inline=False
            )
        
        await interaction.followup.send(embed=embed)
        
    except requests.RequestException as e:
        await interaction.followup.send(f"❌ Error connecting to backend: {str(e)}")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}")

@bot.tree.command(name="fight", description="Show combat objectives")
async def fighting(interaction: discord.Interaction):
    """Show combat-related objectives"""
    await interaction.response.defer()
    await show_goals_helper(interaction, "fight")

@bot.tree.command(name="haul", description="Show trade/hauling objectives")
async def hauling(interaction: discord.Interaction):
    """Show trade/hauling objectives"""
    await interaction.response.defer()
    await show_goals_helper(interaction, "haul")

@bot.tree.command(name="explore", description="Show exploration/travelling objectives")
async def exploring(interaction: discord.Interaction):
    """Show exploration objectives"""
    await interaction.response.defer()
    await show_goals_helper(interaction, "explore")

# Helper functions
def is_active(obj):
    """Check if objective is currently active"""
    try:
        if obj.get('enddate'):
            end = datetime.fromisoformat(obj['enddate'].replace('Z', ''))
            return end > datetime.utcnow()
        return True
    except:
        return True

def filter_by_type(objectives, goal_type):
    """Filter objectives by activity type"""
    type_map = {
        'fight': ['space_cz', 'ground_cz', 'cb', 'bv', 'murder'],
        'haul': ['trade_prof', 'bm_prof'],
        'explore': ['expl', 'inf', 'visit']
    }
    
    target_types = type_map.get(goal_type, [])
    if not target_types:
        return objectives
    
    filtered = []
    for obj in objectives:
        for target in obj.get('targets', []):
            if target.get('type', '').lower() in target_types:
                filtered.append(obj)
                break
    return filtered

def get_target_icon(target_type):
    """Return emoji for target type"""
    icons = {
        'SPACE_CZ': '🚀',
        'GROUND_CZ': '⚔️',
        'CB': '🎯',
        'BV': '💰',
        'INF': '📈',
        'EXPL': '🔭',
        'TRADE_PROF': '📦',
        'VISIT': '🛸',
        'MURDER': '💀',
        'MISSION_FAIL': '❌'
    }
    return icons.get(target_type, '🎯')

@bot.tree.command(name="linkcmdr", description="Link your Elite Dangerous commander name to your Discord account")
@app_commands.describe(cmdr_name="Your Elite Dangerous commander name")
async def link_cmdr(interaction: discord.Interaction, cmdr_name: str):
    """Link a commander name to the user's Discord account"""
    await interaction.response.defer(ephemeral=True)
    
    try:
        headers = get_api_headers()
        discord_id = str(interaction.user.id)
        
        # Call the backend to link the cmdr
        response = requests.post(
            f'{API_BASE}link_cmdr',
            headers=headers,
            json={
                "discord_id": discord_id,
                "cmdr_name": cmdr_name
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            await interaction.followup.send(
                f"✅ Successfully linked CMDR **{cmdr_name}** to your account!",
                ephemeral=True
            )
        elif response.status_code == 404:
            error_data = response.json()
            error_msg = error_data.get('error', 'Unknown error')
            
            if 'User not found' in error_msg:
                await interaction.followup.send(
                    f"❌ You don't have a user account yet. Please verify with the bot first using `/verify` or contact an admin.",
                    ephemeral=True
                )
            elif 'Cmdr' in error_msg and 'not found' in error_msg:
                await interaction.followup.send(
                    f"❌ Commander **{cmdr_name}** not found in the database. Make sure the name is spelled correctly and that you've uploaded EDDN data.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"❌ Error: {error_msg}", ephemeral=True)
        else:
            error_data = response.json()
            await interaction.followup.send(
                f"❌ Error linking commander: {error_data.get('error', 'Unknown error')}",
                ephemeral=True
            )
            
    except requests.RequestException as e:
        await interaction.followup.send(
            f"❌ Error connecting to backend: {str(e)}",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(
            f"❌ Error: {str(e)}",
            ephemeral=True
        )


@bot.tree.command(name="wheream", description="Show your current Elite Dangerous location")
async def where_am_i(interaction: discord.Interaction):
    """Show the user's current system based on their last FSDJump"""
    await interaction.response.defer()
    
    try:
        headers = get_api_headers()
        discord_id = str(interaction.user.id)
        
        # Call the backend to get current system
        response = requests.get(
            f'{API_BASE}cmdr_system',
            headers=headers,
            params={"discord_id": discord_id},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            cmdr_name = data.get('cmdr_name')
            current_system = data.get('current_system')
            timestamp = data.get('timestamp')
            
            embed = discord.Embed(
                title="📍 Current Location",
                color=discord.Color.blue()
            )
            
            embed.add_field(name="Commander", value=cmdr_name, inline=False)
            
            if current_system:
                embed.add_field(name="System", value=current_system, inline=False)
                if timestamp:
                    embed.add_field(name="Last Jump", value=timestamp, inline=False)
            else:
                embed.add_field(
                    name="System", 
                    value="No FSDJump data available", 
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
        elif response.status_code == 404:
            error_data = response.json()
            error_msg = error_data.get('error', 'Unknown error')
            
            if 'No cmdr linked' in error_msg:
                await interaction.followup.send(
                    f"❌ You haven't linked a commander yet. Use `/linkcmdr <name>` to link your commander.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"❌ Error: {error_msg}",
                    ephemeral=True
                )
        else:
            error_data = response.json()
            await interaction.followup.send(
                f"❌ Error fetching location: {error_data.get('error', 'Unknown error')}",
                ephemeral=True
            )
            
    except requests.RequestException as e:
        await interaction.followup.send(f"❌ Error connecting to backend: {str(e)}")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}")


# Run the bot
if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    if not TOKEN:
        print("❌ Error: DISCORD_BOT_TOKEN not found in environment!")
        exit(1)
    
    bot.run(TOKEN)