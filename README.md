# OrpheusDL (Customized Version)

A modular music archival tool written in Python, customized with high-performance asynchronous downloads, Apple Music integration, and automated quality repair tools.

## Key Additions & Features in this Fork

### 1. Orpheus Healer (`orpheus_healer.py`)
An automated tool designed to clean up and repair your local music library:
- **Audio Analysis Integration**: Reads CSV reports exported from **Soniq Tools**.
- **Fuzzy Quality Repair**: Detects files flagged as upsampled, transcoded, or lossy transcode (*fake lossless*).
- **Auto-Redownload**: Automatically attempts to fetch a true lossless version of the track from your active sources (Tidal, Apple Music, etc.).
- **Metadata Preserving**: Preserves the original audio file's tags (like lyrics, ratings, replaygain, track IDs, etc.) and transfers them to the new file.
- **Configurable**: Fully configured via [healer_config.toml](file:///d:/College%20Project/music/OrpheusDL-master/healer_config.toml).

### 2. Apple Music Module (`modules/applemusic`)
Allows direct, high-quality downloading from Apple Music:
- **Widevine CDM Decryption**: Integrates the `gamdl` downloader library to download and decrypt Apple Music audio files using your Widevine Device (.wvd).
- **Session Authentication**: Authenticates securely using browser cookies from [config/cookies.txt](file:///d:/College%20Project/music/OrpheusDL-master/config/cookies.txt).
- **Fuzzy Match Fallback**: Used as a fallback download source for Orpheus Healer.

### 3. Core Enhancements & Optimization
- **Asynchronous Downloading**: Replaced synchronous downloading with a highly-efficient async process (`aiohttp` + `aiofiles`) supporting connection pooling and exponential backoff.
- **Windows MAX_PATH Safety**: Automatically checks path lengths and shortens filenames to fit within Windows path length limitations (220 characters headroom), preventing OS errors.
- **Artist Parsing**: Advanced smart collaborator splitting (`Simon & Garfunkel` is preserved, while individual features/collaborations are correctly parsed and tagged).

---

## Getting Started

### Prerequisites
* Python 3.9+ (highly recommended)
* ffmpeg installed and added to your system PATH

### Installation
1. Install dependencies:
   ```shell
   pip install -r requirements.txt
   ```
2. Run the program at least once to initialize settings:
   ```shell
   python orpheus.py settings refresh
   ```
3. Configure your logins and settings inside `config/settings.json`.

---

## Usage

### 1. General Downloader
Download albums/tracks directly using a link:
```shell
python orpheus.py https://music.apple.com/us/album/...
```
Or perform a search & download:
```shell
python orpheus.py search tidal track "song name" "artist"
```

### 2. Orpheus Healer (Auto-repair library)
Configure your music directory and Soniq Tools CSV paths in `healer_config.toml`, then run:
```shell
python orpheus_healer.py
```

---

## Contributing & License
Refer to the original documentation for licensing. All personal cookie files (`config/cookies.txt`, `config/loginstorage.bin`), download outputs, and session databases are ignored under `.gitignore` for security.
