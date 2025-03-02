import os
import sys
import subprocess

# Define the target folder for local installations
LIBS_DIR = os.path.join(os.getcwd(), "libs")
if not os.path.exists(LIBS_DIR):
    os.makedirs(LIBS_DIR)

# List of required packages (all third-party modules used in your code)
required_packages = [
    "spotipy",
    "yt-dlp",
    "requests",
    "flask",
    "jinja2"
]

def install_packages(packages):
    for pkg in packages:
        try:
            # Replace hyphens with underscores for module names (e.g., yt-dlp -> yt_dlp)
            __import__(pkg.replace('-', '_'))
            print(f"{pkg} is already installed.")
        except ImportError:
            print(f"Installing {pkg} into {LIBS_DIR} ...")
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "--target=" + LIBS_DIR, pkg
            ])

install_packages(required_packages)
print("All dependencies installed/updated in the 'libs' folder.")
print("Launching main application...")
subprocess.check_call([sys.executable, "main.py"])
