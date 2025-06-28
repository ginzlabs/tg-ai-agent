import os
import sys
import requests
from dotenv import load_dotenv

# Load .env from the root directory (two levels up from utils)
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
print(f"Loading .env from: {env_path}")
print(f"Current working directory: {os.getcwd()}")
load_dotenv(env_path, override=True)  # Added override=True to force reload

# # Debug print all relevant environment variables
# print("\nEnvironment variables after loading:")
# print(f"TELEGRAM_BOT_TOKEN: {'Set' if os.getenv('TELEGRAM_BOT_TOKEN') else 'Not set'}")
# print(f"OUR_SECRET_TOKEN: {'Set' if os.getenv('OUR_SECRET_TOKEN') else 'Not set'}")
# print(f"TGAGENT_WEBHOOK_URL: {'Set' if os.getenv('TGAGENT_WEBHOOK_URL') else 'Not set'}\n")

def register_webhook_url(webhook_url: str):
    """
    Registers the webhook URL with Telegram by calling the Bot API directly
    using the requests library. Requires TELEGRAM_BOT_TOKEN, OUR_SECRET_TOKEN,
    and TG_WEBHOOK_URL to be set in the environment.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    secret_token = os.getenv("OUR_SECRET_TOKEN")

    # Debug print all relevant environment variables
    # print(bot_token)
    # print(secret_token)
    # print(webhook_url)
    
    if not bot_token:
        raise EnvironmentError("Environment variable TELEGRAM_BOT_TOKEN not found.")
    if not secret_token:
        raise EnvironmentError("Environment variable OUR_SECRET_TOKEN not found.")
    if not webhook_url:
        raise EnvironmentError("Environment variable TG_WEBHOOK_URL not found.")

    # Telegram Bot API endpoint for setting a webhook
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    # Telegram expects the secret token as secret_token parameter.
    payload = {"url": webhook_url, "secret_token": secret_token}
    
    response = requests.post(url, data=payload)
    return response.json()

if __name__ == "__main__":
    webhook_url = os.getenv("TGAGENT_WEBHOOK_URL")
    try:
        result = register_webhook_url(webhook_url)
        print("Webhook registration result:", result)
    except Exception as e:
        print("Error registering webhook:", e)
        sys.exit(1)

