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


def get_api_error(response_data: dict, default: str = 'Unknown error') -> str:
    """Extract error message from API response. Handles both Flask format
    {'error': '...'} and Effect format {'message': '...', '_tag': '...'}."""
    return response_data.get('error') or response_data.get('message') or default


def _mask_key(k: str) -> str:
    if not k:
        return "(none)"
    if len(k) <= 8:
        return k
    return f"{k[:4]}...{k[-4:]}"

def get_json(path, params=None):
    # Strip trailing slash from API_BASE to avoid double slashes
    base = API_BASE.rstrip('/') if API_BASE else ''
    url = f"{base}/{path}"
    headers = get_api_headers()
    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    return r.json()

def _get_progress_from_backend(target: dict) -> dict:
    """
    Extract progress data from the backend's progressDetail.

    The backend now calculates progress server-side and returns it in progressDetail.
    This includes:
    - overallProgress: Total progress across all CMDRs for the objective period
    - cmdrProgress: Per-CMDR breakdown

    Returns dict with 'total_objective' (progress for objective period).
    For current tick progress, fetch objectives with ?period=ct separately.
    """
    try:
        progress_detail = target.get("progressDetail", {})
        if not progress_detail:
            # Fallback to simple progress field if progressDetail not available
            return {"total_objective": target.get("progress", 0)}

        return {
            "total_objective": progress_detail.get("overallProgress", 0),
            "cmdr_count": len(progress_detail.get("cmdrProgress", [])),
            "percentage": progress_detail.get("overallPercentage", 0)
        }
    except Exception as e:
        logging.error(f"_get_progress_from_backend error: {e}")
        return {"total_objective": 0, "cmdr_count": 0, "percentage": 0}

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
        # The backend now calculates progress server-side based on objective dates
        headers = get_api_headers()
        logging.info(f"Requesting {API_BASE}objectives headers={_mask_key(headers.get('apikey',''))} apiversion={headers.get('apiversion')}")

        # Fetch objectives with their date-based progress (uses startdate/enddate)
        # Use /objectives endpoint (not /api/objectives) to get progressDetail
        objectives_url = API_BASE.replace('/api/', '/').rstrip('/') + '/objectives'
        response = requests.get(
            objectives_url,
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

        # Also fetch current tick progress for "This Tick" display
        response_ct = requests.get(
            objectives_url,
            headers=headers,
            params={'active': 'true', 'period': 'ct'},
            timeout=10
        )
        response_ct.raise_for_status()
        objectives_ct = response_ct.json()

        # Build a map of current tick progress by objective ID + target type
        ct_progress_map = {}
        for obj_ct in objectives_ct:
            obj_id = obj_ct.get('id')
            for target_ct in obj_ct.get('targets', []):
                key = (obj_id, target_ct.get('type'))
                ct_progress_map[key] = target_ct.get('progressDetail', {}).get('overallProgress', 0)
        
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
        
        # Create embeds - one per objective with color-coding
        embeds = []
        is_first_embed = True
        
        for item in objectives_with_distance[:5]:  # Show top 5
            obj = item['objective']
            distance = item['distance']
            
            priority = "⭐" * min(int(obj.get('priority', 0)), 5)
            title_text = obj.get('title', 'Unnamed')
            system = obj.get('system', 'N/A')
            faction = obj.get('faction', 'N/A')
            obj_desc = obj.get('description', '')
            
            # Build field name with distance
            field_name = f"{priority} {title_text}"
            if distance is not None:
                field_name += f" [{distance:.2f} Ly]"
            
            # Build target summary
            targets = obj.get('targets', [])
            target_summary = []
            obj_id = obj.get('id')
            for target in targets:
                t_type = target.get('type', '').upper()
                icon = get_target_icon(t_type)
                target_overall = target.get('targetoverall', 0)

                # Get objective period progress from backend's progressDetail
                progress_data = _get_progress_from_backend(target)
                objective_total = progress_data.get("total_objective", 0)

                # Get current tick progress from the ct_progress_map
                ct_key = (obj_id, target.get('type'))
                current_total = ct_progress_map.get(ct_key, 0)

                if target_overall > 0:
                    # Calculate percentages
                    percent_ct = (current_total / target_overall * 100) if target_overall > 0 else 0

                    # Format the start date for display
                    start_date = obj.get('startdate', '')
                    if start_date:
                        try:
                            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                            start_display = start_dt.strftime('%b %d')
                        except:
                            start_display = 'mission start'
                    else:
                        start_display = 'mission start'

                    # Build progress string showing both metrics
                    progress_str = f"This Tick: **{_fmt_credits(current_total)} / {_fmt_credits(target_overall)}** ({percent_ct:.1f}%)\n*{_fmt_credits(objective_total)} completed since {start_display}*"

                    target_summary.append(f"{icon} {t_type}\n{progress_str}")

            # Build the value content with proper formatting
            # Build critical info first (system, faction, targets)
            critical_info = f"**System:** {system}\n**Faction:** {faction}"
            if target_summary:
                critical_info += "\n**Targets:**\n" + "\n".join(target_summary)

            # Calculate available space for description
            truncation_notice = "\n*(description truncated)*"
            max_total_length = 1024
            critical_length = len(critical_info)
            available_for_desc = max_total_length - critical_length - len(truncation_notice) - 2  # -2 for \n\n separator

            # Build value with description handling
            if obj_desc:
                desc_text = obj_desc.strip()
                if len(desc_text) > available_for_desc and available_for_desc > 50:
                    # Truncate description to fit
                    desc_text = desc_text[:available_for_desc - 3] + "..."
                    value = f"_{desc_text}_\n\n{critical_info}"
                elif available_for_desc <= 50:
                    # Not enough space for description, skip it
                    value = critical_info
                else:
                    # Description fits
                    value = f"_{desc_text}_\n\n{critical_info}"
            else:
                value = critical_info

            # Final safety check: if somehow still too long, truncate from end
            if len(value) > max_total_length:
                value = value[:max_total_length - 17] + "\n*(truncated)*"
            
            # Get color based on objective type
            obj_color = get_objective_color(obj)
            
            # Create description for this embed
            if is_first_embed:
                description = "_From each according to their ability, to each according to their needs_"
                if current_system and user_coords:
                    description += f"\n📍 Your location: **{current_system}**"
                elif current_system:
                    description += f"\n⚠️ Could not fetch coordinates for distance calculation"
                else:
                    description += f"\n💡 Use `/linkcmdr` to see distances from your location"
                description += "\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
                is_first_embed = False
            else:
                description = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
            
            # Create embed for this objective
            title = "⚒️ Current CIU Objectives"
            if filter_value != "all":
                title += f" - {filter_value.capitalize()}"
            
            embed = discord.Embed(
                title=title,
                description=description,
                color=obj_color
            )
            
            embed.add_field(
                name=field_name,
                value=value,
                inline=False
            )
            
            embed.set_footer(text="Use /colonies for colonization goals")
            embeds.append(embed)
        
        await send_chunked_embeds(interaction, embeds)
        
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

def get_objective_color(obj: dict) -> discord.Color:
    """Get embed color based on objective type"""
    targets = obj.get('targets', [])
    if not targets:
        return discord.Color.greyple()
    
    # Get the primary target type
    primary_type = targets[0].get('type', '').lower()
    
    color_map = {
        'space_cz': discord.Color.blue(),      # Combat - blue
        'ground_cz': discord.Color.blue(),     # Combat - blue
        'cb': discord.Color.orange(),          # Combat bonds - orange
        'bv': discord.Color.gold(),            # Bounty vouchers - gold
        'trade_prof': discord.Color.green(),   # Trade - green
        'expl': discord.Color.purple(),        # Exploration - purple
        'inf': discord.Color.red(),            # Influence - red
        'mission_fail': discord.Color.greyple(),
        'murder': discord.Color.dark_red(),
        'visit': discord.Color.blurple()
    }
    
    return color_map.get(primary_type, discord.Color.greyple())

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

def truncate_field_value(value: str, max_length: int = 1024) -> tuple[str, bool]:
    """Truncate a field value to Discord's character limit.
    
    Returns: (truncated_value, was_truncated)
    """
    if len(value) <= max_length:
        return value, False
    
    # Truncate and add ellipsis
    truncated = value[:max_length - 4] + "..."
    return truncated, True

async def send_chunked_embeds(interaction: discord.Interaction, embeds: list):
    """Send embeds, chunking them if necessary to respect Discord limits.
    
    Discord has limits:
    - 10 embeds per message
    - 25 fields per embed
    - 1024 characters per field value
    - 2048 characters per field name
    """
    if not embeds:
        return
    
    # Discord allows up to 10 embeds per message
    if len(embeds) <= 10:
        await interaction.followup.send(embeds=embeds)
    else:
        # Send in chunks of 10
        for i in range(0, len(embeds), 10):
            chunk = embeds[i:i+10]
            await interaction.followup.send(embeds=chunk)

OFFICER_ROLE = os.getenv('OFFICER_ROLE', 'Comrade [Veteran]')

TARGET_TYPES_LIST = [
    {"value": "visit",       "label": "Visit"},
    {"value": "inf",         "label": "Influence"},
    {"value": "bv",          "label": "Bounty Vouchers"},
    {"value": "cb",          "label": "Combat Bonds"},
    {"value": "expl",        "label": "Exploration"},
    {"value": "trade_prof",  "label": "Trade Profit"},
    {"value": "ground_cz",   "label": "Ground CZ"},
    {"value": "space_cz",    "label": "Space CZ"},
    {"value": "murder",      "label": "Murder"},
    {"value": "mission_fail","label": "Mission Fail"},
]
VALID_TARGET_TYPES = {t["value"] for t in TARGET_TYPES_LIST}


def _objectives_base_url() -> str:
    base = API_BASE.rstrip('/') if API_BASE else ''
    return base.replace('/api/', '/').rstrip('/') + '/objectives'


def _fetch_objective_targets(objective_id: int) -> list:
    """Return the current targets list for an objective, ready for the update payload."""
    headers = get_api_headers()
    response = requests.get(_objectives_base_url(), headers=headers, timeout=10)
    response.raise_for_status()
    all_objectives = response.json()
    obj = next((o for o in all_objectives if o.get('id') == objective_id), None)
    if obj is None:
        raise ValueError(f"Objective {objective_id} not found")
    return [
        {
            "type": t.get("type", ""),
            "station": t.get("station", ""),
            "system": t.get("system", ""),
            "faction": t.get("faction", ""),
            "progress": 0,
            "targetindividual": t.get("targetindividual", 0),
            "targetoverall": t.get("targetoverall", 0),
            "settlements": [],
        }
        for t in obj.get("targets", [])
    ]


def has_officer_role(member: discord.Member) -> bool:
    """Check if the member has the required role to create/manage objectives."""
    return any(role.name == OFFICER_ROLE for role in member.roles)


class AddTargetView(discord.ui.View):
    """Persistent button shown after objective creation / target addition."""

    def __init__(self, objective_id: int, objective_title: str):
        super().__init__(timeout=600)
        self.objective_id = objective_id
        self.objective_title = objective_title

    @discord.ui.button(label="Add Target", style=discord.ButtonStyle.primary, emoji="➕")
    async def add_target(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = CreateTargetModal(objective_id=self.objective_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"✅ Objective **{self.objective_title}** setup complete.",
            view=self,
        )
        self.stop()


class CreateTargetModal(discord.ui.Modal, title="Add Target"):
    """Modal for adding a target to an existing objective."""

    target_type = discord.ui.TextInput(
        label="Type",
        placeholder="visit | inf | bv | cb | expl | trade_prof | ground_cz | space_cz | murder | mission_fail",
        required=True,
        max_length=20,
    )
    target_overall = discord.ui.TextInput(
        label="Target Overall (total for the whole group)",
        placeholder="e.g. 5000000",
        required=True,
        max_length=20,
    )
    target_individual = discord.ui.TextInput(
        label="Target Individual (per CMDR, 0 = none)",
        placeholder="e.g. 500000",
        required=False,
        max_length=20,
    )
    system_override = discord.ui.TextInput(
        label="System Override",
        placeholder="Leave empty to use the objective's system",
        required=False,
        max_length=100,
    )
    faction_override = discord.ui.TextInput(
        label="Faction Override",
        placeholder="Leave empty to use the objective's faction",
        required=False,
        max_length=100,
    )

    def __init__(self, objective_id: int):
        super().__init__()
        self.objective_id = objective_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        type_value = self.target_type.value.strip().lower()
        if type_value not in VALID_TARGET_TYPES:
            valid_str = ", ".join(sorted(VALID_TARGET_TYPES))
            await interaction.followup.send(
                f"❌ Invalid type `{type_value}`.\nValid types: {valid_str}",
                ephemeral=True,
            )
            return

        try:
            overall = int(self.target_overall.value.strip().replace(",", "").replace(".", ""))
        except ValueError:
            await interaction.followup.send("❌ Target Overall must be a whole number.", ephemeral=True)
            return

        individual = 0
        if self.target_individual.value.strip():
            try:
                individual = int(self.target_individual.value.strip().replace(",", "").replace(".", ""))
            except ValueError:
                individual = 0

        try:
            headers = get_api_headers()
            existing_targets = _fetch_objective_targets(self.objective_id)

            new_target = {
                "type": type_value,
                "station": "",
                "system": self.system_override.value.strip(),
                "faction": self.faction_override.value.strip(),
                "progress": 0,
                "targetindividual": individual,
                "targetoverall": overall,
                "settlements": [],
            }
            existing_targets.append(new_target)

            update_url = f"{_objectives_base_url()}/{self.objective_id}"
            update_response = requests.post(
                update_url,
                headers=headers,
                json={"targets": existing_targets},
                timeout=10,
            )

            if update_response.status_code in (200, 201):
                type_label = next(
                    (t["label"] for t in TARGET_TYPES_LIST if t["value"] == type_value),
                    type_value,
                )
                view = AddTargetView(objective_id=self.objective_id, objective_title=f"#{self.objective_id}")
                await interaction.followup.send(
                    f"✅ Target **{type_label}** added (overall: {overall:,}, individual: {individual:,}).\n"
                    f"Add another target or click **Done** when finished.",
                    view=view,
                    ephemeral=True,
                )
            else:
                try:
                    error_msg = update_response.json().get('error', f'HTTP {update_response.status_code}')
                except Exception:
                    error_msg = f'HTTP {update_response.status_code}'
                await interaction.followup.send(f"❌ Failed to add target: {error_msg}", ephemeral=True)

        except ValueError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
        except requests.RequestException as e:
            await interaction.followup.send(f"❌ Error connecting to backend: {e}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ An error occurred: {error}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ An error occurred: {error}", ephemeral=True)


class CreateObjectiveModal(discord.ui.Modal, title="Create New Objective"):
    """Modal for creating a new BGS objective."""

    obj_title = discord.ui.TextInput(
        label="Title",
        placeholder="Enter objective title",
        required=True,
        max_length=200,
    )
    system = discord.ui.TextInput(
        label="System",
        placeholder="Star system (optional)",
        required=False,
        max_length=100,
    )
    faction = discord.ui.TextInput(
        label="Faction",
        placeholder="Faction name (optional)",
        required=False,
        max_length=100,
    )
    description = discord.ui.TextInput(
        label="Description",
        placeholder="Objective description (optional)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )
    end_date = discord.ui.TextInput(
        label="End Date (YYYY-MM-DD, optional)",
        placeholder="e.g. 2026-03-01",
        required=False,
        max_length=10,
    )

    def __init__(self, obj_type: str = "recon", priority: int = 1):
        super().__init__()
        self.obj_type = obj_type
        self.priority = priority

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            headers = get_api_headers()
            objectives_url = _objectives_base_url()

            payload = {
                "title": self.obj_title.value,
                "type": self.obj_type,
                "priority": self.priority,
                "targets": [],
            }
            if self.system.value:
                payload["system"] = self.system.value
            if self.faction.value:
                payload["faction"] = self.faction.value
            if self.description.value:
                payload["description"] = self.description.value
            if self.end_date.value:
                payload["enddate"] = self.end_date.value

            response = requests.post(objectives_url, headers=headers, json=payload, timeout=10)

            if response.status_code in (200, 201):
                data = response.json()
                obj_id = data.get('id', '?')
                view = AddTargetView(objective_id=obj_id, objective_title=self.obj_title.value)
                await interaction.followup.send(
                    f"✅ Objective **{self.obj_title.value}** created! (ID: {obj_id})\n"
                    f"Add targets using the button below, or visit the dashboard.",
                    view=view,
                    ephemeral=True,
                )
            else:
                try:
                    error_msg = response.json().get('error', f'HTTP {response.status_code}')
                except Exception:
                    error_msg = f'HTTP {response.status_code}: {response.text}'
                await interaction.followup.send(f"❌ Failed to create objective: {error_msg}", ephemeral=True)

        except requests.RequestException as e:
            await interaction.followup.send(f"❌ Error connecting to backend: {e}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ An error occurred: {error}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ An error occurred: {error}", ephemeral=True)


@bot.tree.command(name="create_objective", description="Create a new BGS objective (Veterans only)")
@app_commands.describe(
    obj_type="Type of objective",
    priority="Priority level (1 = lowest, 5 = highest)",
)
@app_commands.choices(
    obj_type=[
        app_commands.Choice(name="Recon", value="recon"),
        app_commands.Choice(name="Win War", value="win_war"),
        app_commands.Choice(name="Draw War", value="draw_war"),
        app_commands.Choice(name="Win Election", value="win_election"),
        app_commands.Choice(name="Draw Election", value="draw_election"),
        app_commands.Choice(name="Boost Influence", value="boost"),
        app_commands.Choice(name="Expand", value="expand"),
        app_commands.Choice(name="Reduce Influence", value="reduce"),
        app_commands.Choice(name="Retreat", value="retreat"),
        app_commands.Choice(name="Equalise", value="equalise"),
    ],
    priority=[
        app_commands.Choice(name="1 - Lowest", value="1"),
        app_commands.Choice(name="2", value="2"),
        app_commands.Choice(name="3", value="3"),
        app_commands.Choice(name="4", value="4"),
        app_commands.Choice(name="5 - Highest", value="5"),
    ],
)
async def create_objective(
    interaction: discord.Interaction,
    obj_type: app_commands.Choice[str] = None,
    priority: app_commands.Choice[str] = None,
):
    """Create a new BGS objective via a modal form."""
    if not has_officer_role(interaction.user):
        await interaction.response.send_message(
            "❌ Only Veterans can create objectives. Ask an officer if you'd like to suggest one!",
            ephemeral=True,
        )
        return

    type_value = obj_type.value if obj_type else "recon"
    priority_value = int(priority.value) if priority else 1

    modal = CreateObjectiveModal(obj_type=type_value, priority=priority_value)
    await interaction.response.send_modal(modal)


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
            error_msg = get_api_error(error_data)

            if 'User not found' in error_msg:
                await interaction.followup.send(
                    f"❌ You don't have a user account yet. Please login into the dashboard at https://dashboard.sinistra-ciu.space",
                    ephemeral=True
                )
            elif 'Cmdr' in error_msg and 'not found' in error_msg:
                await interaction.followup.send(
                    f"❌ Commander **{cmdr_name}** not found in the database. Run /synccmdrs to add them. If it is still not working, make sure the name is spelled correctly and that you've used BGSTally.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"❌ Error: {error_msg}", ephemeral=True)
        else:
            error_data = response.json()
            await interaction.followup.send(
                f"❌ Error linking commander: {get_api_error(error_data)}",
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
            error_msg = get_api_error(error_data)

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
                f"❌ Error fetching location: {get_api_error(error_data)}",
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
• `/create_objective` - Create a new objective (Veterans only)

**🧑‍🚀 Commander**
• `/linkcmdr <name>` - Link your commander
• `/wheream` - Your current location
• `/dist <sys1> [sys2]` - Distance calculator

**📊 Reports**
• `/ticksummary <period>` - BGS tick summary (ct/lt)
• `/synccmdrs` - Force adding new commanders to the cmdr list
• `/nexttick` - Show next BGS tick prediction

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


@bot.tree.command(name="ticksummary", description="Generate a BGS tick summary report")
@app_commands.describe(
    period="Time period for the summary (ct = current tick, lt = last tick)"
)
@app_commands.choices(period=[
    app_commands.Choice(name="Current Tick", value="ct"),
    app_commands.Choice(name="Last Tick", value="lt")
])
async def tick_summary(interaction: discord.Interaction, period: app_commands.Choice[str]):
    """Trigger a daily tick summary to be posted in Discord"""
    await interaction.response.defer()
    
    try:
        headers = get_api_headers()
        
        # Call the backend API to trigger the summary
        response = requests.post(
            f'{API_BASE}summary/discord/tick',
            headers=headers,
            params={"period": period.value},
            timeout=30
        )
        
        if response.status_code == 200:
            period_label = "Current Tick" if period.value == "ct" else "Last Tick"
            await interaction.followup.send(
                f"✅ Successfully triggered **{period_label}** summary! Check the BGS channel.",
                ephemeral=True
            )
        else:
            error_data = response.json() if response.headers.get('content-type') == 'application/json' else {}
            error_msg = error_data.get('error', f'HTTP {response.status_code}')
            await interaction.followup.send(
                f"❌ Failed to trigger summary: {error_msg}",
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


@bot.tree.command(name="synccmdrs", description="Force add new commanders to the cmdr list")
async def sync_cmdrs(interaction: discord.Interaction):
    """Manually trigger adding commanders from events only (no Inara lookups)"""
    await interaction.response.defer()
    
    try:
        headers = get_api_headers()
        
        # Call the backend API to trigger the cmdr sync (no Inara lookups)
        response = requests.post(
            f'{API_BASE}sync/cmdrs?inara=false',
            headers=headers,
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            summary = data.get('summary', 'Sync completed')
            await interaction.followup.send(
                f"✅ **Cmdr Sync Complete**\n{summary}",
                ephemeral=True
            )
        else:
            error_data = response.json() if response.headers.get('content-type') == 'application/json' else {}
            error_msg = error_data.get('error', f'HTTP {response.status_code}')
            await interaction.followup.send(
                f"❌ Failed to sync commanders: {error_msg}",
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


@bot.tree.command(name="nexttick", description="Show when the next BGS tick is expected")
async def next_tick(interaction: discord.Interaction):
    """Show the last BGS tick time and predict when the next one will occur"""
    await interaction.response.defer()
    
    try:
        # Fetch tick data directly from Zoy's service
        response = requests.get("http://tick.infomancer.uk/galtick.json", timeout=10)
        response.raise_for_status()
        
        data = response.json()
        last_tick_str = data.get("lastGalaxyTick")
        
        if not last_tick_str:
            await interaction.followup.send("❌ Unable to fetch tick data from the service.")
            return
        
        # Parse the last tick time
        from datetime import timedelta
        last_tick_time = datetime.fromisoformat(last_tick_str.replace('Z', '+00:00'))
        
        # Calculate time since last tick
        now = datetime.now(last_tick_time.tzinfo)
        time_since_tick = now - last_tick_time
        
        # BGS ticks occur approximately every 24 hours (can vary slightly)
        # Predict next tick (24 hours from last tick)
        expected_next_tick = last_tick_time + timedelta(hours=24)
        time_until_next = expected_next_tick - now
        
        # Format times
        hours_since = int(time_since_tick.total_seconds() // 3600)
        minutes_since = int((time_since_tick.total_seconds() % 3600) // 60)
        
        hours_until = int(time_until_next.total_seconds() // 3600)
        minutes_until = int((time_until_next.total_seconds() % 3600) // 60)
        
        # Create embed
        embed = discord.Embed(
            title="⏰ When is the next tick?",
            color=discord.Color.blue()
        )
        
        # Last tick info
        last_tick_formatted = last_tick_time.strftime("%Y-%m-%d %H:%M:%S UTC")
        embed.add_field(
            name="🕐 Last Tick",
            value=f"**{last_tick_formatted}**\n_{hours_since}h {minutes_since}m ago_",
            inline=False
        )
        
        # Next tick prediction
        next_tick_formatted = expected_next_tick.strftime("%Y-%m-%d %H:%M:%S UTC")
        if time_until_next.total_seconds() > 0:
            embed.add_field(
                name="🔮 Expected Next Tick",
                value=f"**{next_tick_formatted}**\n_in approximately {hours_until}h {minutes_until}m_",
                inline=False
            )
        else:
            # Tick is overdue
            embed.add_field(
                name="🔮 Expected Next Tick",
                value=f"**Overdue!**\n_Expected around {next_tick_formatted}_\n_({abs(hours_until)}h {abs(minutes_until)}m overdue)_",
                inline=False
            )
        
        embed.set_footer(text="⚠️ Tick times can vary by ±30 minutes | Data from tick.infomancer.uk")
        
        await interaction.followup.send(embed=embed)
        
    except requests.RequestException as e:
        await interaction.followup.send(f"❌ Error fetching tick data: {str(e)}")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}")


# ──────────────────────────────────────────────────────────────────────────────
# /buckets — BGS activity bucket status
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_credits(value: float) -> str:
    """Format a credit value as a human-readable string (1.5M, 400K …)."""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return str(int(value))


def _pips(pts: int, max_pts: int = 10, filled: str = "◆", empty: str = "◇") -> str:
    """Return a pip string like ◆◆◆◇◇◇◇◇◇◇."""
    n = max(0, min(pts, max_pts))
    return filled * n + empty * (max_pts - n)


def _bucket_line(emoji: str, label: str, bucket: dict, next_label: str) -> str:
    """Single embed line for one BGS bucket."""
    pts = bucket.get("pts", 0)
    remaining = bucket.get("remaining", 0)
    pip_str = _pips(pts)
    line = f"{emoji} **{label}**  `{pip_str}`  **{pts}**"
    if remaining > 0:
        line += f"  ·  _{next_label} to next_"
    elif pts >= 10:
        line += "  ·  ✅ **CAPPED**"
    return line


def _neg_bucket_line(emoji: str, label: str, bucket: dict) -> str:
    """Single embed line for a negative BGS bucket."""
    pts = bucket.get("pts", 0)
    remaining = bucket.get("remaining", 0)
    pip_str = _pips(pts, filled="◈", empty="◇")
    line = f"{emoji} **{label}**  `{pip_str}`  **{pts}**"
    if pts > 0:
        line += f"  ·  _{remaining} more = next point_"
    return line


def _buckets_embed(entry: dict, system: str, faction: str) -> discord.Embed:
    """Build a Discord embed for a single buckets entry."""
    buckets = entry.get("buckets", {})
    capped_pts = entry.get("cappedPts", 0)
    pct_cap = entry.get("pctCap", 0)

    # Colour: green if high cap, gold if mid, orange if low
    if capped_pts >= 7:
        color = discord.Color.green()
    elif capped_pts >= 4:
        color = discord.Color.gold()
    else:
        color = discord.Color.orange()

    influence = entry.get("currentInfluence")
    period_label = entry.get("period", "—")
    inf_str = f"  ·  Influence: **{influence:.1f}%**" if influence is not None else ""
    description = f"📍 **{system}**  ·  {period_label}{inf_str}"

    embed = discord.Embed(
        title=f"🎯 BGS Prediction — {faction}",
        description=description,
        color=color,
    )

    # ── Positive buckets ──────────────────────────────────────────────────────
    missions    = buckets.get("missions",    {})
    exploration = buckets.get("exploration", {})
    trade       = buckets.get("trade",       {})
    bounty      = buckets.get("bounty",      {})

    positive_lines = [
        _bucket_line("📈", "Missions",    missions,    f"+{missions.get('remaining', 0)} pluses"),
        _bucket_line("🔭", "Exploration", exploration, f"{_fmt_credits(exploration.get('remaining', 0))} cr"),
        _bucket_line("🛒", "Trade",       trade,       f"{_fmt_credits(trade.get('remaining', 0))} cr"),
        _bucket_line("💰", "Bounty",      bounty,      f"{_fmt_credits(bounty.get('remaining', 0))} cr"),
    ]
    embed.add_field(name="⬆️ Positive Buckets", value="\n".join(positive_lines), inline=False)

    # ── Negative buckets ──────────────────────────────────────────────────────
    mission_fail = buckets.get("missionFail", {})
    murder       = buckets.get("murder",      {})

    negative_lines = [
        _neg_bucket_line("❌", "Mission Fails", mission_fail),
        _neg_bucket_line("💀", "Murder",        murder),
    ]
    embed.add_field(name="⬇️ Negative Buckets", value="\n".join(negative_lines), inline=False)

    # ── Net result ────────────────────────────────────────────────────────────
    net_pts   = entry.get("netPts", 0)
    total_pos = entry.get("totalPositivePts", 0)
    total_neg = entry.get("totalNegativePts", 0)

    net_pip_str = _pips(capped_pts)
    result_lines = [
        f"`{net_pip_str}`  **{capped_pts}/10**  ({pct_cap:.0f}% cap)",
        f"Raw: **+{total_pos}** pos  ·  **−{total_neg}** neg  =  **{net_pts}** net",
    ]

    predicted_change = entry.get("predictedInfluenceChange")
    predicted_inf    = entry.get("predictedInfluence")
    if predicted_change is not None:
        sign = "+" if predicted_change >= 0 else ""
        change_str = f"{sign}{predicted_change:.2f}%"
        if predicted_inf is not None:
            result_lines.append(f"Predicted: **{change_str}** → {predicted_inf:.1f}%")
        else:
            result_lines.append(f"Predicted: **{change_str}**")

    embed.add_field(name="📊 Net Result", value="\n".join(result_lines), inline=False)

    # Footer: population + faction count
    footer_parts = []
    pop       = entry.get("population")
    fac_count = entry.get("factionCount")
    max_swing = entry.get("maxSwing")
    if pop is not None:
        footer_parts.append(f"Pop: {pop:,}")
    if fac_count is not None:
        footer_parts.append(f"Factions: {fac_count}")
    if max_swing is not None:
        footer_parts.append(f"Max swing: {max_swing:.2f}%")
    if footer_parts:
        embed.set_footer(text="  ·  ".join(footer_parts))

    return embed


@bot.tree.command(name="buckets", description="Show BGS activity bucket status for a faction in a system")
@app_commands.describe(
    system="Star system name (e.g. Sol)",
    faction="Faction name",
    period="Tick period to check (default: current tick)",
)
@app_commands.choices(period=[
    app_commands.Choice(name="Current Tick", value="ct"),
    app_commands.Choice(name="Last Tick",    value="lt"),
])
async def buckets_command(
    interaction: discord.Interaction,
    system: str,
    faction: str,
    period: app_commands.Choice[str] = None,
):
    """Show BGS bucket breakdown for a given faction/system."""
    await interaction.response.defer()

    period_value = period.value if period else "ct"

    try:
        data = get_json("buckets", params={"period": period_value, "system": system})
    except requests.HTTPError as e:
        await interaction.followup.send(f"❌ API error: {e}")
        return
    except Exception as e:
        await interaction.followup.send(f"❌ Error fetching buckets data: {e}")
        return

    buckets_list = data.get("buckets", [])

    # Case-insensitive faction match
    entry = next(
        (b for b in buckets_list if b["faction"].lower() == faction.lower()),
        None,
    )

    if entry is None:
        available = [b["faction"] for b in buckets_list]
        hint = (
            f"\nObjectives in **{system}** cover: {', '.join(available)}"
            if available
            else f"\nNo objective found for **{system}** — is it tracked?"
        )
        await interaction.followup.send(
            f"❌ No buckets data for **{faction}** in **{system}** "
            f"(period: `{period_value}`).{hint}"
        )
        return

    await interaction.followup.send(embed=_buckets_embed(entry, system, faction))


# Run the bot
if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    if not TOKEN:
        print("❌ Error: DISCORD_BOT_TOKEN not found in environment!")
        exit(1)
    
    bot.run(TOKEN)