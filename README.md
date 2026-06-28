# Telegram-Restricted-Content-Downloader

A Telegram bot designed to streamline the process of downloading restricted and non-restricted content from Telegram groups and channels. Just copy a media link to your clipboard, and the bot will automatically add it to a download queue. Once you're ready, press enter to start downloading.

<div align="center">
  <img src="./example/screenshot.png" alt="screenshot" width="300">
</div>

## Features

📋 Clipboard Monitoring: Detects and adds Telegram media links automatically.

📥 Restricted/Non-Restricted Downloads: Supports private and public content.

⏸ Queue Management: Collects links until you press enter to download.

🔄 Reset: Clear the list anytime with r + enter.

## How it Works

Copy any Telegram media link to your clipboard.
The bot automatically detects the link and adds it to the queue.
Once ready, press 'enter' to download all queued media.

## Example Interface

![ ](/example/example.png)

# Requirements

Ensure you have Python 3.8+ installed. Install the following dependencies:

```bash
pyaes==1.6.1
pyperclip==1.9.0
pyrotgfork==2.1.35
PySocks==1.7.1
PyTgCrypto==1.2.6
python-dotenv==1.0.1
TgCrypto==1.2.5
uvloop==0.19.0
```

## Installation

### 1. Clone this repository:

```bash
git clone https://github.com/victorjalonzo/Telegram-Restricted-Content-Downloader.git
cd Telegram-Restricted-Content-Downloader
```

### 2. Install dependencies:

```bash
pip install -r requirements.txt
```

### 3. Create a .env file in the project's root directory with the following content:

```bash

#Replace it with your Telegram application credentials
API_ID="YOUR_API_ID"
API_HASH="YOUR_API_HASH"

```
Replace the placeholders with your corresponding information.
If you don't have these credentials, visit https://my.telegram.org/auth to obtain them.

## Usage

To start the bot, run the following command:
```bash
python app.py
```

## Contributions

Contributions are welcome. If you'd like to contribute, please fork the repository and create a pull request with your changes.

## License

This project is licensed under the MIT License. See the LICENSE file for details.