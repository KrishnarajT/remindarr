# instructions for this bot, and how to make stuff like this again. 
1. register your bot with botfather. 
Step 1. Get your bot token (if you don’t have it yet)

Open Telegram → search for @BotFather.

Send /newbot.

Follow the prompts → choose a name and username (ending in _bot).

You’ll receive a token like:

1234567890:ABCDefGhIjkLmNoPQRstuVWxyz


Save it — we’ll call it BOT_TOKEN.

2. 
Step 2: Get your chat ID (3 easy options)
🟢 Option 1: Quickest (Use a simple URL)

Open this in your browser — replacing <BOT_TOKEN> with your real token:

https://api.telegram.org/bot<BOT_TOKEN>/getUpdates


Example:

https://api.telegram.org/bot1234567890:ABCdefGhijKLmnopQRstuVWxyz/getUpdates


Then send a message to your bot (like “hi”) and refresh that URL.

You’ll see a JSON response like:

{
  "ok": true,
  "result": [
    {
      "update_id": 123456789,
      "message": {
        "message_id": 1,
        "from": {
          "id": 987654321,
          "is_bot": false,
          "first_name": "Krishnaraj"
        },
        "chat": {
          "id": 987654321,
          "first_name": "Krishnaraj",
          "type": "private"
        },
        "date": 1731229324,
        "text": "hi"
      }
    }
  ]
}


👉 Your chat ID is:

987654321


That’s the value inside "chat": {"id": ...}


3. if you wanna communiate 2 way like from user to your bot, then ull need to use webhooks after hosting your app. 

`
curl -X POST \
  "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=https://remindarr.krishnarajthadesar.in/api/notifications/webhook"
`

`curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"`


# things to fix
1. check the commands some arent working. 
2. modularize and split up code properly
3. think of mcp integration here when modularizing. 
4. fix the notion api pulling thing by experimenting first and then putting that thing here. 
5. see if recurring reminders work
6. always show time in user timezone. 
7. restructure the schema to include the notion things in another table. 
8. deleting notion dbs doesnt actually work fix that
9. there has to be a way to delete the recurring tasks. 
10. list isnt working we gotta fix that, and in that list we gotta ask the user for multiple different types of listings, which could be notion, source, recurring, single, today, tomorrow, all etc. 