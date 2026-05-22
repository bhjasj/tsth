import json
import os
import requests
from flask import Flask, request
from dotenv import load_dotenv

load_dotenv()

TOKEN         = os.getenv("DISCORD_TOKEN")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BASE_URL      = os.getenv("BASE_URL")
CLIENT_ID     = 1502467961636520046
TOKENS_FILE   = "tokens.json"

app = Flask(__name__)


def load_tokens():
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE) as f:
            return json.load(f)
    return {}


def save_tokens(store):
    with open(TOKENS_FILE, "w") as f:
        json.dump(store, f, indent=2)


@app.route("/callback")
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

    # Exchange code for tokens
    token_resp = requests.post(
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

    # Get user info
    user_resp = requests.get(
        "https://discord.com/api/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if not user_resp.ok:
        return "❌ Could not fetch Discord user info.", 500

    user_data = user_resp.json()
    user_id   = int(user_data["id"])
    username  = user_data.get("username", str(user_id))

    # Save tokens
    store = load_tokens()
    store[str(user_id)] = {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "username":      username,
    }
    save_tokens(store)
    print(f"[TOKEN] Stored tokens for {username} ({user_id})")

    # Add user to guild with role
    join_resp = requests.put(
        f"https://discord.com/api/guilds/{guild_id}/members/{user_id}",
        headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"},
        json={"access_token": access_token, "roles": [role_id]},
    )

    if join_resp.status_code == 204:
        # Already in server, assign role separately
        requests.put(
            f"https://discord.com/api/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
            headers={"Authorization": f"Bot {TOKEN}"},
        )
    elif join_resp.status_code not in (200, 201):
        print(f"[ERROR] Join failed ({join_resp.status_code}): {join_resp.text}")
        return "❌ Could not add you to the server. Contact an admin.", 500

    print(f"[VERIFY] ✅ {username} ({user_id}) → guild {guild_id}, role {role_id}")

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


if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN not set in .env")
    if not CLIENT_SECRET:
        raise ValueError("CLIENT_SECRET not set in .env")
    if not BASE_URL:
        raise ValueError("BASE_URL not set in .env")
    app.run(host="0.0.0.0", port=5000, debug=False)
