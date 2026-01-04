import os
import shutil
import subprocess
import glob
from datetime import datetime

DB_NAME = "flashcards.db"
BACKUP_DIR = "backups"
MAX_BACKUPS = 5

def get_git_commit_hash():
    """Retrieves the short git commit hash."""
    try:
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], text=True).strip()
    except Exception:
        return "unknown"

def backup_database(reason="manual"):
    """
    Backs up the database file to the backup directory.
    Maintains only the latest MAX_BACKUPS files.
    """
    if not os.path.exists(DB_NAME):
        print(f"Warning: Database {DB_NAME} not found. Skipping backup.")
        return False

    os.makedirs(BACKUP_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    commit_hash = get_git_commit_hash()
    backup_filename = f"flashcards_{timestamp}_{commit_hash}_{reason}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)

    try:
        shutil.copy2(DB_NAME, backup_path)
        print(f"Database backed up to: {backup_path}")

        _rotate_backups()
        return True
    except Exception as e:
        print(f"Backup failed: {e}")
        return False

def _rotate_backups():
    """Keeps only the latest MAX_BACKUPS files in the backup directory."""
    try:
        # Pattern matches files starting with flashcards_ and ending in .db
        # We need to be careful to only select files created by this tool or similar naming
        files = glob.glob(os.path.join(BACKUP_DIR, "flashcards_*.db"))

        # Sort by modification time (newest last)
        files.sort(key=os.path.getmtime)

        if len(files) > MAX_BACKUPS:
            files_to_delete = files[:-MAX_BACKUPS]
            for f in files_to_delete:
                try:
                    os.remove(f)
                    print(f"Rotated old backup: {f}")
                except OSError as e:
                    print(f"Error deleting old backup {f}: {e}")

    except Exception as e:
        print(f"Error rotating backups: {e}")

if __name__ == "__main__":
    # Can be run manually
    backup_database()
