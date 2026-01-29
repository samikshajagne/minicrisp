#!/usr/bin/env python3
"""
Main script to launch the MapLibre + Deck.gl map with markers from CSV
This script starts a local HTTP server and opens the map in your default browser
"""

import http.server
import socketserver
import webbrowser
import os
import sys
from pathlib import Path

# Configuration
PORT = 8000
MAP_FILE = "index.html"

def main():
    # Get the directory where this script is located
    script_dir = Path(__file__).parent.absolute()
    
    # Change to the script directory
    os.chdir(script_dir)
    
    # Check if required files exist
    if not os.path.exists(MAP_FILE):
        print(f"❌ Error: {MAP_FILE} not found in {script_dir}")
        sys.exit(1)
    
    if not os.path.exists("india1.csv"):
        print(f"⚠️  Warning: india1.csv not found. Map will load without markers.")
    
    # Create HTTP server
    Handler = http.server.SimpleHTTPRequestHandler
    
    try:
        with socketserver.TCPServer(("", PORT), Handler) as httpd:
            print("=" * 60)
            print("🌍 MapLibre + Deck.gl Map Server")
            print("=" * 60)
            print(f"✓ Server started at http://localhost:{PORT}/")
            print(f"✓ Map file: {MAP_FILE}")
            print(f"✓ Data file: india1.csv")
            print()
            print("📍 Opening map in your default browser...")
            print()
            print("Press Ctrl+C to stop the server")
            print("=" * 60)
            
            # Open browser after a short delay
            map_url = f"http://localhost:{PORT}/{MAP_FILE}"
            webbrowser.open(map_url)
            
            # Start serving
            httpd.serve_forever()
            
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped. Goodbye!")
        sys.exit(0)
    except OSError as e:
        if e.errno == 10048 or e.errno == 48:  # Port already in use (Windows/Unix)
            print(f"❌ Error: Port {PORT} is already in use.")
            print(f"💡 Try closing other applications or change PORT in main.py")
        else:
            print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
