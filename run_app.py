import os
import sys
import threading
import webbrowser
import uvicorn

# Add current directory to sys.path for PyInstaller resolution
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    os.chdir(sys._MEIPASS)

from app.main import app

def open_browser():
    """Opens the dashboard in the default web browser after server start."""
    webbrowser.open("http://127.0.0.1:8000")

if __name__ == "__main__":
    print("==================================================")
    print("      TikTok OBS Live Integration Server          ")
    print("==================================================")
    print("Server starting at http://127.0.0.1:8000 ...")
    print("Opening browser dashboard...")
    print("Press Ctrl+C to stop the server.")
    print("--------------------------------------------------")
    
    # Launch browser after 1.5s delay
    threading.Timer(1.5, open_browser).start()
    
    # Start uvicorn server programmatically
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
