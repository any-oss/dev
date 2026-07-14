#!/bin/bash

# Set up backup folder
BACKUP_DIR="_backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "📦 Backing up files to $BACKUP_DIR"

# List of files/folders to remove (relative to repo root)
FILES_TO_REMOVE=(
    ".github/ISSUE_TEMPLATE"
    ".github/SECURITY.md"
    ".github/pull_request_template.md"
    ".github/workflows/blank.yml"
    ".github/workflows/ci.yml"
    "CODE_OF_CONDUCT.md"
    "CONTRIBUTING.md"
    # Add any other files you want to remove, e.g.:
    # "OLD_README.md"
)

# Move each file/folder to backup
for item in "${FILES_TO_REMOVE[@]}"; do
    if [ -e "$item" ]; then
        echo "🗑️  Moving $item to $BACKUP_DIR"
        mkdir -p "$BACKUP_DIR/$(dirname "$item")"
        mv "$item" "$BACKUP_DIR/$item"
    else
        echo "⏭️  Skipping $item (not found)"
    fi
done

echo "✅ Cleanup complete. Backups saved in $BACKUP_DIR"
echo "📌 To restore: mv $BACKUP_DIR/* ."
echo ""
echo "Remaining files:"
ls -la