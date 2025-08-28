# remindarr Project

remindarr is a FastAPI application that functions as a Telegram bot for sending reminder notifications. This project allows users to send messages to a specified Telegram chat through a simple API endpoint.

## Project Structure

```
remindarr
├── app
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   └── services
│       └── telegram.py
├── requirements.txt
├── .env
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Setup Instructions

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd remindarr
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   Create a `.env` file in the root directory and add your Telegram bot token and chat ID:
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```

5. **Run the application:**
   You can run the FastAPI application using:
   ```bash
   uvicorn app.main:app --reload
   ```

6. **Using Docker:**
   To build and run the application using Docker, use the following commands:
   ```bash
   docker-compose up --build
   ```

## Usage

Once the application is running, you can send a test notification by accessing the following endpoint:

```
GET /test-notification
```

This will trigger a message saying "hi" to your specified Telegram chat.

## License

This project is licensed under the MIT License.