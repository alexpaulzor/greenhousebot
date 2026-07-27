"""
WiFi credentials — COPY this to secrets.py and fill in. secrets.py is gitignored.

    cp firmware/secrets_example.py firmware/secrets.py
    # then edit firmware/secrets.py

main.py imports secrets; if it's missing, the controller still runs fully offline
(buttons + LCD work), just without the web page.
"""

WIFI_SSID = "your-network"
WIFI_PASSWORD = "your-password"
