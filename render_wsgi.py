"""Render/Gunicorn entrypoint: serve Flask and start one scanner/poller instance."""

from app import app, bot

# Procfile runs exactly one Gunicorn worker. Starting here ensures the scanner and
# Telegram long-poll listener start under WSGI as well as during local `python app.py`.
bot.start()
