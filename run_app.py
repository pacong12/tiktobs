import os
import socket
import sys
import threading
import webbrowser
import uvicorn

# Add current directory to sys.path for PyInstaller resolution
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    os.chdir(sys._MEIPASS)

from app.main import app

# Host/port are configurable for deployment. .env is already loaded by the
# app.main import above, so these pick up TIKTOBS_HOST / TIKTOBS_PORT.
HOST = os.getenv("TIKTOBS_HOST", "127.0.0.1")
PORT = int(os.getenv("TIKTOBS_PORT", "8000"))

def port_in_use(host: str, port: int) -> bool:
    """Returns True if something is already bound to host:port.

    Uses SO_REUSEADDR so that leftover TIME_WAIT connections from a
    previous run do not cause a false 'port in use' error (uvicorn sets
    SO_REUSEADDR on its listener too, so this mirrors its bind behavior).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True

def open_browser():
    """Opens the dashboard in the default web browser after server start."""
    webbrowser.open(f"http://{HOST}:{PORT}")

import time

def startup_animation():
    print("\n" + "="*50)
    print("      TikTok OBS Live Integration Server          ")
    print("==================================================")
    
    tasks = [
        "Initializing core modules", 
        "Loading configuration", 
        "Mounting static assets", 
        "Preparing database connection", 
        "Starting local server"
    ]
    
    for task in tasks:
        spinner = ['|', '/', '-', '\\']
        for i in range(10):
            sys.stdout.write(f"\r[{spinner[i % 4]}] {task}...")
            sys.stdout.flush()
            time.sleep(0.05)
        sys.stdout.write(f"\r[*] {task}... Done!      \n")
        sys.stdout.flush()
        
    print("--------------------------------------------------")
    print(f"Server starting at http://{HOST}:{PORT} ...")
    print("Opening browser dashboard...")
    print("Press Ctrl+C to stop the server.")
    print("--------------------------------------------------\n")

if __name__ == "__main__":
    if port_in_use(HOST, PORT):
        print(f"\nError: port {PORT} is already in use.")
        print("Another instance of the server may already be running, or another")
        print("application is occupying the port. Close it and try again.")
        sys.exit(1)

    startup_animation()
    
    # Launch browser after 1.5s delay
    threading.Timer(1.5, open_browser).start()
    
    # Start uvicorn server programmatically
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
