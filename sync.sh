#!/bin/bash
# Enable absolute path tracking
cd "$(dirname "$0")" || exit 1
trap "echo -e '\nAborted by user.'; exit 130" INT

echo "===================================================="
echo "      YouTube Music Playlist Synchronization        "
echo "===================================================="
echo

echo "🚀 Running Sync for GLOBAL chart..."
uv run python3 sync.py --country global "$@"
GLOBAL_STATUS=$?

if [ $GLOBAL_STATUS -eq 130 ]; then
    echo "Aborted by user."
    exit 130
fi

echo
echo "----------------------------------------------------"
echo

echo "🚀 Running Sync for INDIA chart..."
uv run python3 sync.py --country in "$@"
INDIA_STATUS=$?

if [ $INDIA_STATUS -eq 130 ]; then
    echo "Aborted by user."
    exit 130
fi

echo
echo "===================================================="
if [ $GLOBAL_STATUS -eq 0 ] && [ $INDIA_STATUS -eq 0 ]; then
    echo "🎉 SUCCESS: Both charts synchronized successfully!"
    EXIT_CODE=0
else
    echo "❌ ERROR: One or more sync operations failed."
    EXIT_CODE=1
fi
echo "===================================================="
echo

if [ -t 0 ]; then
    read -p "Press [Enter] to close this window..."
fi

exit $EXIT_CODE
