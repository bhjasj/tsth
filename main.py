import discord
from discord.ext import commands
from discord import app_commands
import os
import json
import threading
import asyncio
import requests as http
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

TOKEN         = os.getenv("DISCORD_TOKEN")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BASE_URL      = os.getenv("BASE_URL")
API_SECRET    = os.getenv("API_SECRET")
CLIENT_ID     = 1502467961636520046
TOKENS_FILE   = "tokens.json"


# ─── Token helpers ────────────────────────────────────────────────────────────
def load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE) as f:
            return json.load(f)
    return {}


def save_tokens(store):
    with open(TOKENS_FILE, "w") as f:
        json.dump(store, f, indent=2)


def pull_user(user_id: int, guild_id: int, role_id, access_token: str):
    body = {"access_token": access_token}
    if role_id:
        body["roles"] = [role_id]
    resp = http.put(
        f"https://discord.com/api/guilds/{guild_id}/members/{user_id}",
        headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"},
        json=body,
    )
    if resp.status_code == 204:
        if role_id:
            http.put(
                f"https://discord.com/api/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
                headers={"Authorization": f"Bot {TOKEN}"},
            )
        return True, "already_member"
    if resp.status_code in (200, 201):
        return True, "joined"
    return False, f"API error {resp.status_code}: {resp.text}"


# ─── Flask ────────────────────────────────────────────────────────────────────
flask_app = Flask(__name__)


def check_secret():
    return request.headers.get("X-API-Secret") == API_SECRET


@flask_app.route("/")
def index():
    return "Bot is running!", 200


@flask_app.route("/tokens")
def get_tokens():
    if not check_secret():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_tokens())


@flask_app.route("/tokens/<user_id>")
def get_token(user_id):
    if not check_secret():
        return jsonify({"error": "Unauthorized"}), 401
    store = load_tokens()
    if user_id not in store:
        return jsonify({"error": "Not found"}), 404
    return jsonify(store[user_id])


@flask_app.route("/callback")
def callback():
    code  = request.args.get("code")
    state = request.args.get("state")

    if not code or not state:
        return "❌ Missing code or state.", 400

    try:
        guild_id_str, role_id_str = state.split(":")
        guild_id = int(guild_id_str)
        role_id  = int(role_id_str)
    except ValueError:
        return "❌ Invalid state parameter.", 400

    token_resp = http.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  f"{BASE_URL}/callback",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if not token_resp.ok:
        print(f"[ERROR] Token exchange failed: {token_resp.text}")
        return "❌ Failed to exchange code. Please try again.", 500

    token_data    = token_resp.json()
    access_token  = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not access_token:
        return "❌ No access token returned.", 500

    user_resp = http.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if not user_resp.ok:
        return "❌ Could not fetch Discord user info.", 500

    user_data = user_resp.json()
    user_id   = int(user_data["id"])
    username  = user_data.get("username", str(user_id))

    store = load_tokens()
    store[str(user_id)] = {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "username":      username,
    }
    save_tokens(store)
    print(f"[TOKEN] Stored tokens for {username} ({user_id})")

    success, msg = pull_user(user_id, guild_id, role_id, access_token)
    if not success:
        print(f"[ERROR] pull_user failed: {msg}")
        return "❌ Could not add you to the server. Contact an admin.", 500

    print(f"[VERIFY] ✅ {username} ({user_id}) → guild {guild_id}, role {role_id} ({msg})")

    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Verified!</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #23272a; color: #dcddde;
      display: flex; align-items: center; justify-content: center; min-height: 100vh;
    }
    .card {
      background: #2c2f33; border-radius: 12px; padding: 48px 40px;
      text-align: center; max-width: 420px; width: 90%;
      box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }
    .icon { font-size: 64px; margin-bottom: 16px; }
    h1 { font-size: 24px; font-weight: 700; margin-bottom: 8px; color: #fff; }
    p { font-size: 15px; color: #b9bbbe; line-height: 1.5; }
    .badge {
      display: inline-block; margin-top: 20px; background: #43b581;
      color: #fff; font-size: 13px; font-weight: 600;
      padding: 6px 16px; border-radius: 20px;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✅</div>
    <h1>You're verified!</h1>
    <p>You've been added to the server and your role has been assigned.<br>You can close this tab and head back to Discord.</p>
    <span class="badge">Verification complete</span>
  </div>
</body>
</html>
""", 200


def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ─── Discord bot ──────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, application_id=CLIENT_ID)


class VerifyView(discord.ui.View):
    def __init__(self, role_id: int, guild_id: int):
        super().__init__(timeout=None)
        self.verify_btn.custom_id = f"verify_button:{guild_id}:{role_id}"

    @discord.ui.button(
        label="✅  Verify Me",
        style=discord.ButtonStyle.success,
        custom_id="verify_button:placeholder",
    )
    async def verify_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        parts    = button.custom_id.split(":")
        guild_id = parts[1]
        role_id  = parts[2]

        oauth_url = (
            f"https://discord.com/oauth2/authorize"
            f"?client_id={CLIENT_ID}"
            f"&redirect_uri={BASE_URL}/callback"
            f"&response_type=code"
            f"&scope=identify%20guilds.join"
            f"&state={guild_id}:{role_id}"
        )

        link_view = discord.ui.View()
        link_view.add_item(discord.ui.Button(
            label="🔗 Authorize with Discord",
            style=discord.ButtonStyle.link,
            url=oauth_url,
        ))
        await interaction.response.send_message(
            "Click below to authorize and complete verification.\n"
            "You'll be redirected back automatically once done.",
            view=link_view,
            ephemeral=True,
        )


async def register_persistent_buttons():
    registered: set[str] = set()
    for guild in bot.guilds:
        for channel in guild.text_channels:
            try:
                async for message in channel.history(limit=200):
                    if message.author == guild.me:
                        for component in message.components:
                            children = getattr(component, "children", [component])
                            for child in children:
                                cid = getattr(child, "custom_id", "")
                                if cid.startswith("verify_button:") and cid not in registered:
                                    try:
                                        _, guild_id, role_id = cid.split(":")
                                        bot.add_view(VerifyView(int(role_id), int(guild_id)))
                                        registered.add(cid)
                                        print(f"[STARTUP] Re-registered button guild={guild_id} role={role_id}")
                                    except ValueError:
                                        pass
            except discord.Forbidden:
                pass


@bot.event
async def on_ready():
    print(f"✅ Bot logged in as {bot.user} ({bot.user.id})")
    await register_persistent_buttons()
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"[ERROR] Failed to sync: {e}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="Verifying members"
    ))


@bot.tree.command(name="sendverify", description="Post the verification embed.")
@app_commands.describe(role="The role to assign after the user authorizes.")
@app_commands.checks.has_permissions(manage_roles=True)
async def send_verify(interaction: discord.Interaction, role: discord.Role):
    guild = interaction.guild
    if not guild.me.guild_permissions.manage_roles:
        return await interaction.response.send_message("❌ I need the **Manage Roles** permission.", ephemeral=True)
    if guild.me.top_role <= role:
        return await interaction.response.send_message(
            f"❌ My role must be above **{role.name}** in Server Settings → Roles.", ephemeral=True)
    if not BASE_URL:
        return await interaction.response.send_message("❌ `BASE_URL` is not set.", ephemeral=True)

    embed = discord.Embed(
        title="✅  Server Verification",
        description=(
            "Welcome! To gain access to the server, click **Verify Me** below.\n\n"
            "You'll be taken to a Discord authorization page — just click **Authorize** "
            "and you'll be verified instantly."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Role you'll receive", value=role.mention, inline=False)
    embed.set_footer(text=f"{guild.name} • Role ID: {role.id}", icon_url=guild.icon.url if guild.icon else None)
    embed.timestamp = discord.utils.utcnow()

    view = VerifyView(role.id, guild.id)
    bot.add_view(view)
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message(
        f"✅ Embed sent! Users will receive **{role.name}** after authorizing.", ephemeral=True)


@send_verify.error
async def send_verify_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need **Manage Roles** to run this.", ephemeral=True)
    else:
        raise error


@bot.tree.command(name="ping", description="Pull a verified user into this server.")
@app_commands.describe(user="The user to pull.", role="Optional role to assign on join.")
@app_commands.checks.has_permissions(manage_roles=True)
async def ping(interaction: discord.Interaction, user: discord.User, role: discord.Role | None = None):
    await interaction.response.defer(ephemeral=True)

    store = load_tokens()
    if str(user.id) not in store:
        return await interaction.followup.send(
            f"❌ **{user}** has not verified through this bot yet.", ephemeral=True)

    entry        = store[str(user.id)]
    access_token = entry["access_token"]
    success, msg = pull_user(user.id, interaction.guild.id, role.id if role else None, access_token)

    if not success:
        return await interaction.followup.send(f"❌ Failed: {msg}", ephemeral=True)
    if msg == "already_member":
        role_text = f" Role **{role.name}** assigned." if role else ""
        return await interaction.followup.send(
            f"ℹ️ **{user}** is already in this server.{role_text}", ephemeral=True)

    role_text = f" and given **{role.name}**" if role else ""
    await interaction.followup.send(
        f"✅ **{user}** pulled into **{interaction.guild.name}**{role_text}!", ephemeral=True)


@ping.error
async def ping_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need **Manage Roles** to use `/ping`.", ephemeral=True)
    else:
        raise error


@bot.tree.command(name="pingall", description="Pull ALL verified users into this server.")
@app_commands.describe(role="Optional role to assign everyone on join.")
@app_commands.checks.has_permissions(administrator=True)
async def pingall(interaction: discord.Interaction, role: discord.Role | None = None):
    await interaction.response.defer(ephemeral=True)

    store = load_tokens()
    if not store:
        return await interaction.followup.send("❌ No verified users yet.", ephemeral=True)

    guild_id = interaction.guild.id
    role_id  = role.id if role else None
    joined = already = failed = 0

    for uid_str, entry in store.items():
        success, msg = pull_user(int(uid_str), guild_id, role_id, entry["access_token"])
        if success:
            if msg == "already_member":
                already += 1
            else:
                joined += 1
        else:
            failed += 1
            print(f"[PINGALL] Failed for {uid_str}: {msg}")

    role_text = f" with role **{role.name}**" if role else ""
    await interaction.followup.send(
        f"✅ Pull complete{role_text}:\n"
        f"• **{joined}** newly joined\n"
        f"• **{already}** already in server\n"
        f"• **{failed}** failed",
        ephemeral=True,
    )


@pingall.error
async def pingall_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need **Administrator** to use `/pingall`.", ephemeral=True)
    else:
        raise error


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    for var in ["DISCORD_TOKEN", "CLIENT_SECRET", "BASE_URL", "API_SECRET"]:
        if not os.getenv(var):
            raise ValueError(f"{var} not set in environment variables")

    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("🌐 Web server started")

    # Run bot (blocks until stopped)
    bot.run(TOKEN)
