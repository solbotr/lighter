"""
LighterBot VPS Heartbeat — sends Telegram status every 10 minutes.
Runs as a standalone Windows Scheduled Task on the VPS.
Zero dependency on Antigravity or the user's laptop.
"""
import os, sys, time, json, requests, subprocess

ENV_PATH = r"C:\LighterBot\.env"

def load_env(path):
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as e:
        print(f"[ENV] Failed to load .env: {e}")
    return env

env = load_env(ENV_PATH)

TG_TOKEN    = env.get("TELEGRAM_TOKEN", "")
CHAT_ID     = env.get("ADMIN_CHAT_ID", "") or env.get("TELEGRAM_CHAT_ID", "")
ACCT_IDX    = env.get("ACCOUNT_INDEX", "737649")
LIGHTER_URL = env.get("LIGHTER_API_URL", "https://mainnet.zklighter.elliot.ai")

def fetch_positions():
    try:
        url = f"{LIGHTER_URL}/api/v1/account_details?account_index={ACCT_IDX}"
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            data = r.json()
            positions = []
            collateral = 0.0
            accts = data.get("accounts", [])
            if accts:
                acct = accts[0]
                collateral = float(acct.get("collateral", 0)) / 1e6
                for pos in acct.get("positions", []):
                    size = float(pos.get("size", 0))
                    if abs(size) > 1e-9:
                        positions.append({
                            "market_index": pos.get("market_index"),
                            "size": size,
                        })
            return collateral, positions
    except Exception as e:
        print(f"[FETCH] Error: {e}")
    return None, []

def get_bot_pid_and_mem():
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-Process python -EA SilentlyContinue | "
             "Select-Object Id,@{N='MB';E={[math]::Round($_.WS/1MB,1)}} | ConvertTo-Json"],
            capture_output=True, text=True, timeout=10
        )
        raw = result.stdout.strip()
        if not raw:
            return None, 0
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        if data:
            biggest = max(data, key=lambda x: x.get("MB", 0))
            return biggest.get("Id"), biggest.get("MB", 0)
    except Exception:
        pass
    return None, 0

def tg_send(text):
    if not TG_TOKEN or not CHAT_ID:
        print("[TG] No token/chat_id configured")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=8
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[TG] Send error: {e}")
        return False

def main():
    collateral, positions = fetch_positions()
    pid, mem_mb = get_bot_pid_and_mem()

    bot_status = "🟢 RUNNING" if pid else "🔴 DOWN — CHECK IMMEDIATELY"
    mem_str    = f"{mem_mb} MB" if pid else "N/A"
    collat_str = f"${collateral:,.2f} USDC" if collateral is not None else "⚠️ Fetch Error"
    pos_count  = len(positions)

    pos_lines = ""
    for p in positions[:8]:
        side = "🟢 LONG" if p["size"] > 0 else "🔴 SHORT"
        pos_lines += f"  • Mkt #{p['market_index']} | {side} | {abs(p['size']):.4f}\n"
    if not pos_lines:
        pos_lines = "  <i>No open positions</i>\n"

    now_utc = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    msg = (
        f"🤖 <b>LighterBot Heartbeat</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 <b>Time:</b> <code>{now_utc}</code>\n"
        f"⚡ <b>Bot:</b> {bot_status}\n"
        f"🧠 <b>RAM:</b> <code>{mem_str}</code> (PID {pid})\n"
        f"💰 <b>Margin:</b> <code>{collat_str}</code>\n"
        f"📊 <b>Positions:</b> <code>{pos_count} open</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{pos_lines}"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>⚙️ Auto-ping every 10 min from VPS — no laptop needed</i>"
    )

    ok = tg_send(msg)
    status = "✅ delivered" if ok else "❌ failed"
    print(f"[HEARTBEAT] TG {status} | pos={pos_count} | margin={collat_str} | ram={mem_str}")

if __name__ == "__main__":
    main()
