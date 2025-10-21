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

def get_json(path, params=None):
    url = f"{API_BASE}/{path}"
    headers = get_api_headers()
    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    return r.json()

def _fetch_target_progress(target: dict, obj: dict) -> dict:
    """Fetch current tick and objective-period progress for a specific target"""
    try:
        target_type = target.get("type", "").lower()
        system = target.get("system") or obj.get("system")
        faction = target.get("faction") or obj.get("faction")
        
        # Get objective date range for overall calculation
        start_date = obj.get("startdate")
        end_date = obj.get("enddate")
        
        # Map target types to API endpoints and data extraction
        if target_type == "space_cz":
            # Fetch space CZ data for current tick
            data_ct = get_json("syntheticcz-summary", params={"period": "ct", "system_name": system})
            total_ct = sum(row.get("cz_count", 0) for row in (data_ct or []) if row.get("starsystem") == system)
            
            # Fetch data for objective period
            params_obj = {"system_name": system}
            if start_date and end_date:
                params_obj["start_date"] = start_date
                params_obj["end_date"] = end_date
            else:
                params_obj["period"] = "all"
            data_obj = get_json("syntheticcz-summary", params=params_obj)
            total_obj = sum(row.get("cz_count", 0) for row in (data_obj or []) if row.get("starsystem") == system)
            
            return {"total": total_ct, "total_objective": total_obj, "label": "CZs completed"}
        
        elif target_type == "ground_cz":
            # Fetch ground CZ data for current tick
            data_ct = get_json("syntheticgroundcz-summary", params={"period": "ct", "system_name": system})
            total_ct = sum(row.get("cz_count", 0) for row in (data_ct or []) if row.get("starsystem") == system)
            
            # Fetch data for objective period
            params_obj = {"system_name": system}
            if start_date and end_date:
                params_obj["start_date"] = start_date
                params_obj["end_date"] = end_date
            else:
                params_obj["period"] = "all"
            data_obj = get_json("syntheticgroundcz-summary", params=params_obj)
            total_obj = sum(row.get("cz_count", 0) for row in (data_obj or []) if row.get("starsystem") == system)
            
            return {"total": total_ct, "total_objective": total_obj, "label": "Ground CZs completed"}
        
        elif target_type == "bv":
            # Fetch bounty vouchers
            data_ct = get_json("summary/bounty-vouchers", params={"period": "ct", "system_name": system})
            total_ct = sum(row.get("bounty_vouchers", 0) for row in (data_ct or []))
            
            params_obj = {"system_name": system}
            if start_date and end_date:
                params_obj["start_date"] = start_date
                params_obj["end_date"] = end_date
            else:
                params_obj["period"] = "all"
            data_obj = get_json("summary/bounty-vouchers", params=params_obj)
            total_obj = sum(row.get("bounty_vouchers", 0) for row in (data_obj or []))
            
            return {"total": total_ct, "total_objective": total_obj, "label": "CR in bounties"}
        
        elif target_type == "cb":
            # Fetch combat bonds
            data_ct = get_json("summary/combat-bonds", params={"period": "ct", "system_name": system})
            total_ct = sum(row.get("combat_bonds", 0) for row in (data_ct or []))
            
            params_obj = {"system_name": system}
            if start_date and end_date:
                params_obj["start_date"] = start_date
                params_obj["end_date"] = end_date
            else:
                params_obj["period"] = "all"
            data_obj = get_json("summary/combat-bonds", params=params_obj)
            total_obj = sum(row.get("combat_bonds", 0) for row in (data_obj or []))
            
            return {"total": total_ct, "total_objective": total_obj, "label": "CR in bonds"}
        
        elif target_type == "inf":
            # Fetch influence data
            data_ct = get_json("summary/influence-by-faction", params={"period": "ct", "system_name": system})
            total_ct = sum(row.get("influence", 0) for row in (data_ct or []) if row.get("faction_name") == faction)
            
            params_obj = {"system_name": system}
            if start_date and end_date:
                params_obj["start_date"] = start_date
                params_obj["end_date"] = end_date
            else:
                params_obj["period"] = "all"
            data_obj = get_json("summary/influence-by-faction", params=params_obj)
            total_obj = sum(row.get("influence", 0) for row in (data_obj or []) if row.get("faction_name") == faction)
            
            return {"total": total_ct, "total_objective": total_obj, "label": "INF gained"}
        
        elif target_type == "expl":
            # Fetch exploration data
            data_ct = get_json("summary/exploration-sales", params={"period": "ct", "system_name": system})
            total_ct = sum(row.get("total_exploration_sales", 0) for row in (data_ct or []))
            
            params_obj = {"system_name": system}
            if start_date and end_date:
                params_obj["start_date"] = start_date
                params_obj["end_date"] = end_date
            else:
                params_obj["period"] = "all"
            data_obj = get_json("summary/exploration-sales", params=params_obj)
            total_obj = sum(row.get("total_exploration_sales", 0) for row in (data_obj or []))
            
            return {"total": total_ct, "total_objective": total_obj, "label": "CR in exploration"}
        
        elif target_type == "trade_prof":
            # Fetch trade profit data
            data_ct = get_json("summary/market-events", params={"period": "ct", "system_name": system})
            total_ct = sum(row.get("total_profit", 0) for row in (data_ct or []))
            
            params_obj = {"system_name": system}
            if start_date and end_date:
                params_obj["start_date"] = start_date
                params_obj["end_date"] = end_date
            else:
                params_obj["period"] = "all"
            data_obj = get_json("summary/market-events", params=params_obj)
            total_obj = sum(row.get("total_profit", 0) for row in (data_obj or []))
            
            return {"total": total_ct, "total_objective": total_obj, "label": "CR profit"}
        
        elif target_type == "mission_fail":
            # Fetch mission failures
            data_ct = get_json("summary/missions-failed", params={"period": "ct", "system_name": system})
            total_ct = len(data_ct or [])
            
            params_obj = {"system_name": system}
            if start_date and end_date:
                params_obj["start_date"] = start_date
                params_obj["end_date"] = end_date
            else:
                params_obj["period"] = "all"
            data_obj = get_json("summary/missions-failed", params=params_obj)
            total_obj = len(data_obj or [])
            
            return {"total": total_ct, "total_objective": total_obj, "label": "missions failed"}
        
        return {"total": 0, "total_objective": 0, "label": ""}
    except Exception as e:
        # Silently fail and return 0 to avoid breaking the UI
        return {"total": 0, "total_objective": 0, "label": ""}

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
        
        # Try to get user's current system for distance calculation
        current_system = None
        user_coords = None
        discord_id = str(interaction.user.id)
        
        try:
            location_response = requests.get(
                f'{API_BASE}cmdr_system',
                headers=headers,
                params={"discord_id": discord_id},
                timeout=10
            )
            if location_response.status_code == 200:
                location_data = location_response.json()
                current_system = location_data.get('current_system')
        except:
            pass  # Silently fail if we can't get location
        
        # If we have a current system, fetch coordinates from EDSM
        system_coords = {}
        if current_system:
            # Collect all system names (current + objectives)
            system_names = [current_system]
            for obj in active_objectives:
                obj_system = obj.get('system')
                if obj_system and obj_system not in system_names:
                    system_names.append(obj_system)
            
            # Batch fetch coordinates from EDSM
            try:
                edsm_params = [('systemName[]', name) for name in system_names]
                edsm_params.append(('showCoordinates', '1'))
                
                edsm_response = requests.get(
                    'https://www.edsm.net/api-v1/systems',
                    params=edsm_params,
                    timeout=10
                )
                if edsm_response.status_code == 200:
                    edsm_data = edsm_response.json()
                    for system in edsm_data:
                        name = system.get('name')
                        coords = system.get('coords')
                        if name and coords:
                            system_coords[name] = coords
                    
                    # Get user's coordinates
                    user_coords = system_coords.get(current_system)
            except:
                pass  # Silently fail if EDSM is unavailable
        
        # Calculate distances and add to objectives
        objectives_with_distance = []
        for obj in active_objectives:
            obj_system = obj.get('system')
            distance = None
            
            if user_coords and obj_system in system_coords:
                obj_coords = system_coords[obj_system]
                distance = calculate_distance(user_coords, obj_coords)
            
            objectives_with_distance.append({
                'objective': obj,
                'distance': distance
            })
        
        # Sort by distance if available, otherwise by priority
        if user_coords:
            objectives_with_distance.sort(key=lambda x: (x['distance'] is None, x['distance'] if x['distance'] is not None else float('inf')))
        else:
            objectives_with_distance.sort(key=lambda x: int(x['objective'].get('priority', 0)), reverse=True)
        
        # Create embed
        title = "⚒️ Current CIU Objectives"
        if filter_value != "all":
            title += f" - {filter_value.capitalize()}"
        
        description = "_From each according to their ability, to each according to their needs_"
        if current_system and user_coords:
            description += f"\n📍 Your location: **{current_system}**"
        elif current_system:
            description += f"\n⚠️ Could not fetch coordinates for distance calculation"
        else:
            description += f"\n💡 Use `/linkcmdr` to see distances from your location"
        description += "\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
            
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.red()
        )
        
        for item in objectives_with_distance[:5]:  # Show top 5
            obj = item['objective']
            distance = item['distance']
            
            priority = "⭐" * min(int(obj.get('priority', 0)), 5)
            title_text = obj.get('title', 'Unnamed')
            system = obj.get('system', 'N/A')
            faction = obj.get('faction', 'N/A')
            description = obj.get('description', '')
            
            # Build field name with distance
            field_name = f"{priority} {title_text}"
            if distance is not None:
                field_name += f" [{distance:.2f} Ly]"
            
            # Build target summary
            targets = obj.get('targets', [])
            target_summary = []
            for target in targets:
                t_type = target.get('type', '').upper()
                icon = get_target_icon(t_type)
                target_overall = target.get('targetoverall', 0)
                              
                # Fetch current tick and objective period progress
                progress_data = _fetch_target_progress(target, obj)
                current_total = progress_data.get("total", 0)
                objective_total = progress_data.get("total_objective", 0)
              
                if target_overall > 0:
                    # Calculate percentages
                    percent_ct = (current_total / target_overall * 100) if target_overall > 0 else 0
                    
                    # Build progress string showing both metrics
                    progress_str = f"This Tick: **{current_total:,} / {target_overall:,}** ({percent_ct:.1f}%). *{objective_total} completed since {target.get('start_time', 'mission start')}*"

                    target_summary.append(f"{icon} {t_type}\n{progress_str}")

            # Build the value content with proper formatting
            value_parts = []

            if description:
                # Trim any extra whitespace/newlines and wrap in italics
                value_parts.append(f"_{description.strip()}_")

            value_parts.append(f"**System:** {system}\n**Faction:** {faction}")

            if target_summary:
                value_parts.append("**Targets:**\n" + "\n".join(target_summary))

            # Join all parts with proper spacing and add a separator
            value = "\n".join(value_parts)
            
            embed.add_field(
                name=field_name,
                value=f"{value}\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
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
        
        # Try to get user's current system for distance calculation
        current_system = None
        user_coords = None
        discord_id = str(interaction.user.id)
        
        try:
            location_response = requests.get(
                f'{API_BASE}cmdr_system',
                headers=headers,
                params={"discord_id": discord_id},
                timeout=10
            )
            if location_response.status_code == 200:
                location_data = location_response.json()
                current_system = location_data.get('current_system')
        except:
            pass  # Silently fail if we can't get location
        
        # If we have a current system, fetch coordinates from EDSM
        system_coords = {}
        if current_system:
            # Collect all system names (current + colonies)
            system_names = [current_system]
            for colony in colonies_list:
                colony_system = colony.get('starsystem')
                if colony_system and colony_system not in system_names:
                    system_names.append(colony_system)
            
            # Batch fetch coordinates from EDSM
            try:
                edsm_params = [('systemName[]', name) for name in system_names]
                edsm_params.append(('showCoordinates', '1'))
                
                edsm_response = requests.get(
                    'https://www.edsm.net/api-v1/systems',
                    params=edsm_params,
                    timeout=10
                )
                if edsm_response.status_code == 200:
                    edsm_data = edsm_response.json()
                    for system in edsm_data:
                        name = system.get('name')
                        coords = system.get('coords')
                        if name and coords:
                            system_coords[name] = coords
                    
                    # Get user's coordinates
                    user_coords = system_coords.get(current_system)
            except:
                pass  # Silently fail if EDSM is unavailable
        
        # Calculate distances and add to colonies
        colonies_with_distance = []
        for colony in colonies_list:
            colony_system = colony.get('starsystem')
            distance = None
            
            if user_coords and colony_system in system_coords:
                colony_coords = system_coords[colony_system]
                distance = calculate_distance(user_coords, colony_coords)
            
            colonies_with_distance.append({
                'colony': colony,
                'distance': distance
            })
        
        # Sort by distance if available, otherwise by priority
        if user_coords:
            colonies_with_distance.sort(key=lambda x: (x['distance'] is None, x['distance'] if x['distance'] is not None else float('inf')))
        else:
            colonies_with_distance.sort(key=lambda x: int(x['colony'].get('priority', 0)), reverse=True)
        
        # Create embed
        embed_title = "🌍 Colonisation Goals"
        embed_desc = "Use SrvSurvey to track your help!"
        
        if current_system and user_coords:
            embed_desc += f"\n📍 Your location: **{current_system}**"
        elif current_system:
            embed_desc += f"\n⚠️ Could not fetch coordinates for distance calculation"
        else:
            embed_desc += f"\n💡 Use `/linkcmdr` to see distances from your location"
        
        embed = discord.Embed(
            title=embed_title,
            description=embed_desc,
            color=discord.Color.gold()
        )
        
        for item in colonies_with_distance[:5]:
            colony = item['colony']
            distance = item['distance']
            
            priority = "⭐" * min(colony.get('priority', 0), 5)
            system = colony.get('starsystem', 'Unknown')
            cmdr = colony.get('cmdr', 'N/A')
            raven_url = colony.get('ravenurl', '')
            
            # Build field name with distance
            field_name = f"{priority} {system}"
            if distance is not None:
                field_name += f" [{distance:.2f} Ly]"
            
            value = f"**Commander:** {cmdr}\n"
            if raven_url:
                value += f"[🔗 View on Raven Colonial]({raven_url})"
            
            embed.add_field(
                name=field_name,
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
def calculate_distance(coords1, coords2):
    """Calculate Euclidean distance between two coordinate sets in 3D space"""
    import math
    dx = coords2['x'] - coords1['x']
    dy = coords2['y'] - coords1['y']
    dz = coords2['z'] - coords1['z']
    return math.sqrt(dx*dx + dy*dy + dz*dz)

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
                    f"❌ You don't have a user account yet. Please login into the dashboard at https://dashboard.sinistra-ciu.space",
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


@bot.tree.command(name="help", description="Show all available bot commands")
async def help_command(interaction: discord.Interaction):
    """Show little helper for setup and how to work with Sinistra"""
    await interaction.response.defer()
    
    embed = discord.Embed(
        title="⚒️ Welcome to Sinistra Bot!",
        description="Your companion for CIU operations in Elite Dangerous",
        color=discord.Color.red()
    )
    
    # Getting Started
    embed.add_field(
        name="⚒️ Getting Started",
        value=(
            "1. Follow the instructions in #work to set up EDMC and BGSTally!\n"
            "2. **Visit the dashboard to automatically create a user**: [CIU Dashboard](https://dashboard.sinistra-ciu.space)"
            "3. **Link your commander**: Use `/linkcmdr <your_cmdr_name>`\n"
            "4. **Verify it works**: Use `/wheream` to check your location\n"
            "5. **Explore commands**: Use `/list` to see all available commands\n"
        ),
        inline=False
    )
    
    # What you can do
    embed.add_field(
        name="⚒️ What Can You Do?",
        value=(
            "• View current objectives and colonies with distances\n"
            "• Check your commander's location in-game\n"
            "• Calculate distances between systems\n"
            "• Filter objectives by activity type (fight, haul, explore)"
        ),
        inline=False
    )
    
    # Important Note
    embed.add_field(
        name="⚠️ Important",
        value=(
            "Make sure you're running EDMC and BGSTally! Follow the instructions pinned in #work"
        ),
        inline=False
    )
    
    embed.set_footer(text="From each according to their ability, to each according to their needs")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="list", description="Quick reference of all commands")
async def list_command(interaction: discord.Interaction):
    """Show a concise list of all available commands"""
    await interaction.response.defer()
    
    commands_text = """
**📋 Objectives**
• `/goals` - Current CIU objectives
• `/fight` - Combat objectives
• `/haul` - Trade objectives
• `/explore` - Exploration objectives
• `/colonies` - Colonization goals

**🧑‍🚀 Commander**
• `/linkcmdr <name>` - Link your commander
• `/wheream` - Your current location
• `/dist <sys1> [sys2]` - Distance calculator

**ℹ️ Help**
• `/help` - Detailed help
• `/list` - This list
    """
    
    embed = discord.Embed(
        title="⚡ Quick Command Reference",
        description=commands_text,
        color=discord.Color.gold()
    )
    
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="dist", description="Calculate distance between two systems")
@app_commands.describe(
    system1="First system name",
    system2="Second system name (leave empty to use your current location)"
)
async def distance(interaction: discord.Interaction, system1: str, system2: str = None):
    """Calculate the distance between two systems"""
    await interaction.response.defer()
    
    try:
        headers = get_api_headers()
        
        # If system2 is not provided, try to get user's current system
        if not system2:
            discord_id = str(interaction.user.id)
            try:
                location_response = requests.get(
                    f'{API_BASE}cmdr_system',
                    headers=headers,
                    params={"discord_id": discord_id},
                    timeout=10
                )
                if location_response.status_code == 200:
                    location_data = location_response.json()
                    system2 = location_data.get('current_system')
                    if not system2:
                        await interaction.followup.send(
                            "❌ No second system provided and you don't have a current location. "
                            "Either provide two system names or link your commander with `/linkcmdr`.",
                            ephemeral=True
                        )
                        return
                else:
                    await interaction.followup.send(
                        "❌ No second system provided and couldn't fetch your current location. "
                        "Please provide both system names or link your commander with `/linkcmdr`.",
                        ephemeral=True
                    )
                    return
            except:
                await interaction.followup.send(
                    "❌ No second system provided and couldn't fetch your current location.",
                    ephemeral=True
                )
                return
        
        # Fetch coordinates from EDSM for both systems
        system_names = [system1, system2]
        edsm_params = [('systemName[]', name) for name in system_names]
        edsm_params.append(('showCoordinates', '1'))
        
        edsm_response = requests.get(
            'https://www.edsm.net/api-v1/systems',
            params=edsm_params,
            timeout=10
        )
        
        if edsm_response.status_code != 200:
            await interaction.followup.send("❌ Failed to fetch system data from EDSM.")
            return
        
        edsm_data = edsm_response.json()
        
        # Build a dict of system coordinates
        system_coords = {}
        for system in edsm_data:
            name = system.get('name')
            coords = system.get('coords')
            if name and coords:
                system_coords[name] = coords
        
        # Check if we have coordinates for both systems
        coords1 = system_coords.get(system1)
        coords2 = system_coords.get(system2)
        
        if not coords1:
            await interaction.followup.send(
                f"❌ System **{system1}** not found or has no coordinates in EDSM.",
                ephemeral=True
            )
            return
        
        if not coords2:
            await interaction.followup.send(
                f"❌ System **{system2}** not found or has no coordinates in EDSM.",
                ephemeral=True
            )
            return
        
        # Calculate distance
        distance = calculate_distance(coords1, coords2)
        
        # Create embed with result
        embed = discord.Embed(
            title="📏 Distance Calculator",
            color=discord.Color.green()
        )
        
        embed.add_field(name="From", value=f"**{system1}**", inline=True)
        embed.add_field(name="To", value=f"**{system2}**", inline=True)
        embed.add_field(name="Distance", value=f"**{distance:.2f} Ly**", inline=False)
        
        # Add coordinates in footer for reference
        embed.set_footer(text=f"{system1}: ({coords1['x']:.2f}, {coords1['y']:.2f}, {coords1['z']:.2f}) | "
                             f"{system2}: ({coords2['x']:.2f}, {coords2['y']:.2f}, {coords2['z']:.2f})")
        
        await interaction.followup.send(embed=embed)
        
    except requests.RequestException as e:
        await interaction.followup.send(f"❌ Error connecting to EDSM: {str(e)}")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}")


# Run the bot
if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    if not TOKEN:
        print("❌ Error: DISCORD_BOT_TOKEN not found in environment!")
        exit(1)
    
    bot.run(TOKEN)