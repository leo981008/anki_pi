import sqlite3
import sys

DB_NAME = "flashcards.db"

def migrate():
    print(f"🔧 Starting manual migration for {DB_NAME}...")
    
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    # We deliberately do NOT enable Foreign Keys yet to allow us to handle orphans manually
    cursor = conn.cursor()

    try:
        # 1. Check if we are in the old schema
        cursor.execute("PRAGMA table_info(cards)")
        columns = [row['name'] for row in cursor.fetchall()]
        
        if 'deck_id' not in columns:
            print("⚠️  'deck_id' column not found. The database might have already been migrated.")
            print("   Checking card_decks count...")
            cursor.execute("SELECT COUNT(*) FROM card_decks")
            print(f"   Links found: {cursor.fetchone()[0]}")
            return

        print("✅ Detected legacy schema (deck_id exists). Proceeding with migration...")

        # 2. Ensure destination table exists
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS card_decks (
                card_id INTEGER NOT NULL,
                deck_id INTEGER NOT NULL,
                PRIMARY KEY (card_id, deck_id)
            )
        ''')

        # 3. Migrate Links
        print("📊 Analyzing links...")
        cursor.execute("SELECT id, deck_id FROM cards WHERE deck_id IS NOT NULL")
        cards = cursor.fetchall()
        
        valid_links = []
        invalid_links = 0
        
        # Get valid deck IDs
        cursor.execute("SELECT id FROM decks")
        valid_deck_ids = set(row['id'] for row in cursor.fetchall())

        for card in cards:
            cid = card['id']
            did = card['deck_id']
            
            if did in valid_deck_ids:
                valid_links.append((cid, did))
            else:
                invalid_links += 1
                print(f"   ⚠️  Skipping orphaned card {cid} (linked to non-existent deck {did})")

        print(f"   Found {len(cards)} cards with links.")
        print(f"   Valid links to migrate: {len(valid_links)}")
        print(f"   Invalid/Orphaned links: {invalid_links}")

        if valid_links:
            cursor.executemany("INSERT OR IGNORE INTO card_decks (card_id, deck_id) VALUES (?, ?)", valid_links)
            print(f"✅ Successfully inserted {len(valid_links)} links into 'card_decks'.")
        
        # 4. Update Schema (Remove deck_id column)
        print("🔄 Updating 'cards' table schema...")
        
        # Create new table without deck_id
        cursor.execute('''
            CREATE TABLE cards_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                next_review DATE NOT NULL,
                interval INTEGER DEFAULT 0,
                repetition INTEGER DEFAULT 0,
                ef FLOAT DEFAULT 2.5,
                card_type TEXT NOT NULL DEFAULT 'recognize'
            )
        ''')

        # Copy data
        # Check which columns exist in source to be safe
        cols_to_copy = ['id', 'front', 'back', 'next_review', 'interval', 'repetition', 'ef']
        if 'card_type' in columns:
            cols_to_copy.append('card_type')
        
        cols_str = ", ".join(cols_to_copy)
        
        cursor.execute(f"""
            INSERT INTO cards_new ({cols_str})
            SELECT {cols_str} FROM cards
        """)
        
        # Swap tables
        cursor.execute("DROP TABLE cards")
        cursor.execute("ALTER TABLE cards_new RENAME TO cards")
        
        # Re-add Constraints to card_decks (Now pointing to new cards table)
        # We need to recreate card_decks to ensure FKs are bound to the new table if SQLite requires it,
        # but usually SQLite binds by name. However, to be 100% sure of the schema definition:
        
        # Rename temp
        cursor.execute("ALTER TABLE card_decks RENAME TO card_decks_old")
        
        cursor.execute('''
            CREATE TABLE card_decks (
                card_id INTEGER NOT NULL,
                deck_id INTEGER NOT NULL,
                PRIMARY KEY (card_id, deck_id),
                FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE,
                FOREIGN KEY(deck_id) REFERENCES decks(id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute("INSERT INTO card_decks SELECT * FROM card_decks_old")
        cursor.execute("DROP TABLE card_decks_old")

        conn.commit()
        print("✅ Migration completed successfully!")

    except Exception as e:
        conn.rollback()
        print(f"❌ Migration failed: {e}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
