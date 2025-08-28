def send_message(bot_token: str, chat_id: str, message: str) -> None:
    import requests

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message
    }

    response = requests.post(url, json=payload)
    response.raise_for_status()  # Raise an error for bad responses
