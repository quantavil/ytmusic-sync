#!/usr/bin/env python3
import sys
from ytmusicapi import YTMusic

def main():
    print("====================================================")
    print("      YouTube Music Bot Authentication Setup        ")
    print("====================================================\n")
    print("This script will guide you through setting up Browser Cookie Headers")
    print("authentication for your YouTube Music bot.\n")
    
    print("To get your browser headers:")
    print("1. Open Chrome/Firefox/Safari and go to https://music.youtube.com")
    print("2. Ensure you are signed in.")
    print("3. Press F12 (or Cmd+Option+I on Mac) to open Developer Tools.")
    print("4. Go to the 'Network' tab.")
    print("5. Search or filter for '/browse' (or reload the page and look for a request named 'browse?...').")
    print("6. Right-click the 'browse' request, select 'Copy' -> 'Copy request headers' (or 'Copy as cURL').")
    print("7. Paste the copied string below when prompted.\n")
    
    input("Press [Enter] when you have copied the headers to your clipboard...")
    
    print("\nPaste your request headers below (press Ctrl+D or Ctrl+Z on Windows followed by Enter when done):\n")
    
    try:
        YTMusic.setup(filepath="browser.json")
        print("\n🎉 Success! Created 'browser.json' containing your browser authentication.")
        print("You can now run sync.py.")
    except Exception as e:
        print(f"\n❌ Error during setup: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
