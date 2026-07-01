#!/usr/bin/env python3
import sys
import subprocess
import json
from pathlib import Path
from ytmusicapi import YTMusic

def main():
    print("====================================================")
    # Highlight title
    print("      YouTube Music Bot Authentication Setup        ")
    print("====================================================\n")
    print("Please choose your authentication method:")
    print("1) Browser Cookie Headers (Recommended for quick, easy setup)")
    print("2) OAuth 2.0 (Recommended for long-term production cron jobs)")
    print("\n----------------------------------------------------")
    
    choice = input("Enter choice (1 or 2): ").strip()
    
    if choice == "1":
        print("\n--- Browser Cookie Setup Selected ---")
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
            # YTMusic.setup handles reading multiline input from stdin and generating the JSON file.
            YTMusic.setup(filepath="browser.json")
            print("\n🎉 Success! Created 'browser.json' containing your browser authentication.")
            print("You can now run sync.py.")
        except Exception as e:
            print(f"\n❌ Error during setup: {e}")
            sys.exit(1)
            
    elif choice == "2":
        print("\n⚠️ WARNING: YouTube's OAuth 2.0 implementation is currently experiencing a backend bug (Issue #813).")
        print("  Using OAuth will likely cause playlist mutations to fail with '400 Bad Request'.")
        print("  It is highly recommended to use option 1 (Browser Cookie Headers) instead.\n")
        print("--- OAuth 2.0 Setup Selected ---")
        print("To complete this flow, you need a Google Cloud Project with the YouTube Data API v3 enabled.")
        print("If you haven't set this up yet, go to: https://console.cloud.google.com")
        print("1. Create a Project.")
        print("2. Enable YouTube Data API v3.")
        print("3. Configure OAuth consent screen as External (Publish to Production for non-expiring tokens).")
        print("4. Go to Credentials -> Create Credentials -> OAuth client ID.")
        print("5. Select application type 'TV and Limited Input devices'.")
        print("6. Keep the Client ID and Client Secret ready.\n")
        
        confirm = input("Do you have your Client ID and Client Secret ready? (y/n): ").strip().lower()
        if confirm != 'y':
            print("Aborting. Please get your credentials first.")
            sys.exit(1)
            
        client_id = input("Enter your Google Youtube Data API client ID: ").strip()
        client_secret = input("Enter your Google Youtube Data API client secret: ").strip()
        
        if not client_id or not client_secret:
            print("Error: Client ID and Secret are required.")
            sys.exit(1)
            
        print("\nLaunching the ytmusicapi OAuth interactive flow...")
        print("It will prompt for Client ID/Secret, display a link (https://google.com/device), and a code.")
        print("Authorize it in your browser using your bot/personal account.\n")
        
        try:
            ytmusicapi_bin = Path(sys.executable).parent / "ytmusicapi"
            # ytmusicapi oauth sometimes returns exit code 1 upon successful completion.
            # We run it and check if oauth.json exists afterwards.
            subprocess.run([str(ytmusicapi_bin), "oauth"])
            
            oauth_file = Path("oauth.json")
            if not oauth_file.exists():
                print("\n❌ Error: oauth.json was not created. Setup failed.")
                sys.exit(1)
                
            # Load, inject client credentials, and save back
            with open(oauth_file, "r") as f:
                data = json.load(f)
                
            data["client_id"] = client_id
            data["client_secret"] = client_secret
            
            with open(oauth_file, "w") as f:
                json.dump(data, f, indent=2)
                
            print("\n🎉 Success! Created 'oauth.json' containing your OAuth 2.0 credentials.")
            print("You can now run sync.py.")
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
            sys.exit(1)
    else:
        print("Invalid choice. Please run the script again and select 1 or 2.")
        sys.exit(1)

if __name__ == "__main__":
    main()
