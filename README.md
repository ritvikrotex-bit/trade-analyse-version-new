# 📊 Trade Analyzer & 🌐 IP Lookup Tool

A Streamlit web app built by Rotex to analyze trader activity — detecting scalping, burst, and reversal trades, plus IP insights.

## Features

- **Trade Analysis**: Upload Excel trade reports and analyze trading patterns
  - Scalping detection (configurable threshold: 60/120/180 seconds)
  - Reversal trade identification (opposite trades within 20 seconds)
  - Burst trade detection (multiple trades within 2 seconds)
  - Toxic trading percentage calculation
  - Download filtered trade data (CSV/Excel)

- **IP Lookup**: Quick IP address geolocation and ISP information
  - Multiple IP lookups at once
  - Location, ISP, timezone details
  - Interactive maps
  - Export results to CSV

## Run Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run app.py
```

The app will open at `http://localhost:8501`

## Deployment

This app is ready for deployment on [Streamlit Cloud](https://share.streamlit.io):

1. Push this repository to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub account
4. Select this repository
5. Set main file path to `app.py`
6. Click Deploy

## Project Structure

```
.
├── app.py              # Main Streamlit application
├── requirements.txt    # Python dependencies
├── Rotex.png          # Header logo
├── Eagleeye.png       # Footer logo
├── .streamlit/
│   └── config.toml    # Streamlit theme configuration
└── README.md          # This file
```

## Requirements

- Python 3.8+
- See `requirements.txt` for all dependencies

## License

Built with ❤ using Streamlit • For efficient trade analysis and quick IP insights

