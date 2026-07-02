#!/bin/bash
# Enable absolute path tracking
cd "$(dirname "$0")"

echo "===================================================="
echo "      YouTube Music Playlist Synchronization        "
echo "===================================================="
echo

echo "🚀 Running Sync for GLOBAL chart..."
uv run python3 sync.py --country global
GLOBAL_STATUS=$?

echo
echo "----------------------------------------------------"
echo

echo "🚀 Running Sync for INDIA chart..."
uv run python3 sync.py --country in
INDIA_STATUS=$?

echo
echo "===================================================="
if [ $GLOBAL_STATUS -eq 0 ] && [ $INDIA_STATUS -eq 0 ]; then
    echo "🎉 SUCCESS: Both charts synchronized successfully!"
else
    echo "❌ ERROR: One or more sync operations failed."
fi
echo "===================================================="
echo

read -p "Press [Enter] to close this window..."
