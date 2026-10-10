#!/bin/bash
# Enable absolute path tracking
cd "$(dirname "$0")" || exit 1
trap "echo -e '\nAborted by user.'; exit 130" INT

echo "===================================================="
echo "      YouTube Music Playlist Synchronization        "
echo "===================================================="
echo

CHARTS=("global" "in" "us" "radio" "apple_songs")

# If first arg matches one of our charts, run only that chart
TARGET_CHART=""
PASSED_ARGS=()

for arg in "$@"; do
    if [[ " ${CHARTS[*]} " =~ " ${arg} " ]] && [ -z "$TARGET_CHART" ]; then
        TARGET_CHART="$arg"
    else
        PASSED_ARGS+=("$arg")
    fi
done

if [ -n "$TARGET_CHART" ]; then
    RUN_CHARTS=("$TARGET_CHART")
else
    RUN_CHARTS=("${CHARTS[@]}")
fi

FAILED_CHARTS=()

for chart in "${RUN_CHARTS[@]}"; do
    echo "🚀 Running Sync for ${chart^^} chart..."
    uv run python3 sync.py --country "$chart" "${PASSED_ARGS[@]}"
    STATUS=$?
    if [ $STATUS -eq 130 ]; then
        echo "Aborted by user."
        exit 130
    elif [ $STATUS -ne 0 ]; then
        FAILED_CHARTS+=("$chart")
    fi
    echo
    echo "----------------------------------------------------"
    echo
done

echo "===================================================="
if [ ${#FAILED_CHARTS[@]} -eq 0 ]; then
    echo "🎉 SUCCESS: All requested charts synchronized successfully!"
    EXIT_CODE=0
else
    echo "❌ ERROR: Failed to synchronize charts: ${FAILED_CHARTS[*]}"
    EXIT_CODE=1
fi
echo "===================================================="
echo

if [ -t 0 ]; then
    read -p "Press [Enter] to close this window..."
fi

exit $EXIT_CODE
