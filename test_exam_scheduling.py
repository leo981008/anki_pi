import math
from datetime import datetime, timezone, timedelta
import database as db


def test_exam_scheduling():
    print("=== Starting Exam Scheduling Integration Test ===")

    # 1. Setup Test Deck and Cards
    conn = db.get_db_connection()
    cur = conn.cursor()

    # Create test deck
    cur.execute("INSERT INTO decks (name) VALUES (?)", ("Test Exam Deck",))
    deck_id = cur.lastrowid
    print(f"Created Test Deck: ID={deck_id}")

    # Add 5 dummy cards
    card_ids = []
    now = datetime.now(timezone.utc)
    now_str = db.format_datetime_for_db(now)
    for i in range(5):
        cur.execute(
            """
            INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                f"test_word_{i}",
                f"測試單字_{i}",
                now_str,
                0,
                0,
                None,
                None,
                None,
                0,
                0,
                "recognize",
            ),
        )
        card_id = cur.lastrowid
        card_ids.append(card_id)
        cur.execute(
            "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
            (card_id, deck_id),
        )

    conn.commit()
    conn.close()
    print(f"Added 5 dummy cards: {card_ids}")

    try:
        # 2. Create first exam (in 5 days)
        local_now = now.astimezone()
        exam_1_date_local = (local_now + timedelta(days=5)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        exam_1_date = exam_1_date_local.astimezone(timezone.utc)
        exam_1_date_str = exam_1_date.isoformat()
        print(f"Creating Exam 1 scheduled for: {exam_1_date_str}")

        exam_1_id = db.create_exam(
            "Test Exam 1 (5 days)", exam_1_date_str, deck_ids=[deck_id]
        )
        print(f"Created Exam 1: ID={exam_1_id}")

        # Verify cards are distributed (next_review should be updated and spread between today and Day 4)
        conn = db.get_db_connection()
        updated_cards = conn.execute(
            "SELECT id, next_review FROM cards WHERE id IN (SELECT card_id FROM card_decks WHERE deck_id = ?)",
            (deck_id,),
        ).fetchall()

        print("Distributed review times for Exam 1:")
        dates = []
        for c in updated_cards:
            dt = db.parse_db_datetime(c["next_review"])
            dates.append(dt)
            print(f"  Card ID {c['id']}: next_review = {c['next_review']}")

        # Verify that all next_reviews are before the exam date
        for dt in dates:
            assert (
                dt < exam_1_date
            ), f"Review date {dt} is not before exam date {exam_1_date}!"
        print("[PASS] Verification successful: All cards scheduled before Exam 1.")

        # 3. Test submit_card_review cap
        # Standard FSRS review should set a due date, but since Exam 1 is in 5 days,
        # next_review should be capped to 4 days from now (exam_date - 1 day).
        card_to_review = card_ids[0]
        print(f"Reviewing Card ID {card_to_review}...")

        # Call review API
        next_review_str = db.submit_card_review(card_to_review, 3)  # Good rating
        next_review_dt = db.parse_db_datetime(next_review_str)
        print(f"New scheduled next_review: {next_review_str}")

        # Cap date is exam_1_date - 1 day
        expected_cap = exam_1_date - timedelta(days=1)
        assert next_review_dt <= expected_cap + timedelta(
            seconds=5
        ), f"Review date {next_review_dt} is not capped correctly to {expected_cap}!"
        print(
            "[PASS] Verification successful: submit_card_review next_review is capped correctly."
        )

        # 4. Create second exam (in 10 days)
        exam_2_date_local = (local_now + timedelta(days=10)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        exam_2_date = exam_2_date_local.astimezone(timezone.utc)
        exam_2_date_str = exam_2_date.isoformat()
        print(f"Creating Exam 2 scheduled for: {exam_2_date_str}")

        exam_2_id = db.create_exam(
            "Test Exam 2 (10 days)", exam_2_date_str, deck_ids=[deck_id]
        )
        print(f"Created Exam 2: ID={exam_2_id}")

        # 5. Simulate Exam 1 passing / expiring
        print("Simulating Exam 1 passing (updating its date to yesterday)...")
        conn = db.get_db_connection()
        yesterday_str = db.format_datetime_for_db(now - timedelta(days=1))
        conn.execute(
            "UPDATE exams SET date = ? WHERE id = ?", (yesterday_str, exam_1_id)
        )
        conn.commit()
        conn.close()

        # Process expired exams
        print("Running process_expired_exams()...")
        db.process_expired_exams()

        # Check that Exam 1 is marked as processed
        conn = db.get_db_connection()
        exam_1 = conn.execute(
            "SELECT processed FROM exams WHERE id = ?", (exam_1_id,)
        ).fetchone()
        assert exam_1["processed"] == 1, "Exam 1 was not marked as processed!"
        print("[PASS] Verification successful: Exam 1 marked as processed.")

        # Check that cards are now distributed/capped based on Exam 2 (in 10 days)
        updated_cards = conn.execute(
            "SELECT id, next_review FROM cards WHERE id IN (SELECT card_id FROM card_decks WHERE deck_id = ?)",
            (deck_id,),
        ).fetchall()
        print("Distributed review times after Exam 1 expired (now targeting Exam 2):")
        dates_2 = []
        for c in updated_cards:
            dt = db.parse_db_datetime(c["next_review"])
            dates_2.append(dt)
            print(f"  Card ID {c['id']}: next_review = {c['next_review']}")

        for dt in dates_2:
            assert (
                dt < exam_2_date
            ), f"Review date {dt} is not before Exam 2 date {exam_2_date}!"
        print(
            "[PASS] Verification successful: All cards redistributed/scheduled before Exam 2."
        )

        # Review card again, should be capped to Exam 2's day before (9 days from now)
        print("Reviewing card again targeting Exam 2...")
        next_review_str_2 = db.submit_card_review(card_to_review, 3)
        next_review_dt_2 = db.parse_db_datetime(next_review_str_2)
        expected_cap_2 = exam_2_date - timedelta(days=1)
        assert (
            next_review_dt_2 <= expected_cap_2 + timedelta(seconds=5)
        ), f"Review date {next_review_dt_2} is not capped correctly to {expected_cap_2}!"
        print("[PASS] Verification successful: Card review capped targeting Exam 2.")

    finally:
        # 6. Cleanup
        print("Cleaning up test data...")
        conn = db.get_db_connection()
        cur = conn.cursor()

        # Delete test exams
        cur.execute("DELETE FROM exams WHERE name LIKE 'Test Exam%'")
        # Delete test cards
        for cid in card_ids:
            cur.execute("DELETE FROM cards WHERE id = ?", (cid,))
            cur.execute("DELETE FROM card_decks WHERE card_id = ?", (cid,))
        # Delete test deck
        cur.execute("DELETE FROM decks WHERE id = ?", (deck_id,))

        conn.commit()
        conn.close()
        print("Test data cleaned up successfully.")


def test_exam_scheduling_new_cards_cutoff():
    print("=== Starting Exam Scheduling New Cards Cutoff Test ===")
    conn = db.get_db_connection()
    cur = conn.cursor()

    # Create test deck
    cur.execute("INSERT INTO decks (name) VALUES (?)", ("Cutoff Test Deck",))
    deck_id = cur.lastrowid
    print(f"Created Cutoff Test Deck: ID={deck_id}")

    # Add 10 new cards (reps = 0)
    new_card_ids = []
    now = datetime.now(timezone.utc)
    now_str = db.format_datetime_for_db(now)
    for i in range(10):
        cur.execute(
            """
            INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                f"cutoff_new_{i}",
                f"測試新卡_{i}",
                now_str,
                0,
                0,
                None,
                None,
                None,
                0,
                0,
                "recognize",
            ),
        )
        card_id = cur.lastrowid
        new_card_ids.append(card_id)
        cur.execute(
            "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
            (card_id, deck_id),
        )

    # Add 2 late review cards (reps = 1, next_review = now + 15 days)
    late_card_ids = []
    late_review = now + timedelta(days=15)
    late_review_str = db.format_datetime_for_db(late_review)
    for i in range(2):
        cur.execute(
            """
            INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                f"cutoff_late_{i}",
                f"測試遲到_{i}",
                late_review_str,
                2,
                1,
                2.0,
                3.0,
                now_str,
                1,
                0,
                "recognize",
            ),
        )
        card_id = cur.lastrowid
        late_card_ids.append(card_id)
        cur.execute(
            "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
            (card_id, deck_id),
        )

    conn.commit()
    conn.close()
    print("Added 10 new cards and 2 late cards.")

    try:
        # Test Case 1: Exam in 10 days (> 7 days)
        exam_date_1 = now + timedelta(days=10)
        exam_date_1_str = db.format_datetime_for_db(exam_date_1)
        print(f"Creating Exam 1 scheduled for: {exam_date_1_str} (in 10 days)")
        exam_id_1 = db.create_exam(
            "Test Cutoff Exam 10d", exam_date_1_str, deck_ids=[deck_id]
        )

        # Retrieve the actual stored date from the DB (it gets normalized to local midnight)
        conn = db.get_db_connection()
        exam_row_1 = conn.execute(
            "SELECT date FROM exams WHERE id = ?", (exam_id_1,)
        ).fetchone()
        conn.close()
        db_exam_date_1 = db.parse_db_datetime(exam_row_1["date"])

        # Mimic database.py dynamic distribution logic
        total_days_1 = (db_exam_date_1.date() - now.date()).days
        cutoff_date_1 = db_exam_date_1 - timedelta(days=7)
        days_to_cutoff_1 = (cutoff_date_1.date() - now.date()).days

        if days_to_cutoff_1 > 0:
            days_for_new_1 = days_to_cutoff_1
        else:
            days_for_new_1 = max(1, total_days_1)

        expected_count_1 = math.ceil(10 / days_for_new_1)

        # Verify dynamic count in get_study_cards
        new_study, due_study = db.get_study_cards(deck_id=deck_id)
        print(
            f"get_study_cards returned {len(new_study)} new cards for today (Expected: {expected_count_1})."
        )
        assert (
            len(new_study) == expected_count_1
        ), f"Expected {expected_count_1} new cards today, got {len(new_study)}"

        # Verify distribute_exam_cards schedule
        conn = db.get_db_connection()
        scheduled_new = conn.execute(
            "SELECT id, next_review FROM cards WHERE id IN ({})".format(
                ",".join(map(str, new_card_ids))
            )
        ).fetchall()
        scheduled_late = conn.execute(
            "SELECT id, next_review FROM cards WHERE id IN ({})".format(
                ",".join(map(str, late_card_ids))
            )
        ).fetchall()
        conn.close()

        print("Checking new cards schedule dates (should be before cutoff date):")
        for row in scheduled_new:
            dt = db.parse_db_datetime(row["next_review"])
            print(f"  New card {row['id']}: next_review = {row['next_review']}")
            if days_to_cutoff_1 > 0:
                assert (
                    dt < cutoff_date_1
                ), f"New card {row['id']} scheduled at {dt} is not before cutoff {cutoff_date_1}"
            else:
                assert (
                    dt < db_exam_date_1
                ), f"New card {row['id']} scheduled at {dt} is not before exam {db_exam_date_1}"

        print("Checking late cards schedule dates (should be before exam date):")
        for row in scheduled_late:
            dt = db.parse_db_datetime(row["next_review"])
            print(f"  Late card {row['id']}: next_review = {row['next_review']}")
            assert (
                dt < db_exam_date_1
            ), f"Late card {row['id']} scheduled at {dt} is not before exam {db_exam_date_1}"

        # Delete Exam 1 to test Case 2
        print("Removing Exam 1 to test Case 2...")
        conn = db.get_db_connection()
        conn.execute("DELETE FROM exams WHERE id = ?", (exam_id_1,))
        conn.execute("DELETE FROM exam_decks WHERE exam_id = ?", (exam_id_1,))
        # Reset card next_reviews for a clean slate
        conn.execute(
            "UPDATE cards SET next_review = ? WHERE id IN ({})".format(
                ",".join(map(str, new_card_ids))
            ),
            (now_str,),
        )
        conn.execute(
            "UPDATE cards SET next_review = ? WHERE id IN ({})".format(
                ",".join(map(str, late_card_ids))
            ),
            (late_review_str,),
        )
        conn.commit()
        conn.close()

        # Test Case 2: Exam in 5 days (<= 7 days)
        exam_date_2 = now + timedelta(days=5)
        exam_date_2_str = db.format_datetime_for_db(exam_date_2)
        print(f"Creating Exam 2 scheduled for: {exam_date_2_str} (in 5 days)")
        exam_id_2 = db.create_exam(
            "Test Cutoff Exam 5d", exam_date_2_str, deck_ids=[deck_id]
        )

        # Retrieve actual stored date
        conn = db.get_db_connection()
        exam_row_2 = conn.execute(
            "SELECT date FROM exams WHERE id = ?", (exam_id_2,)
        ).fetchone()
        conn.close()
        db_exam_date_2 = db.parse_db_datetime(exam_row_2["date"])

        # Mimic database.py dynamic distribution logic
        total_days_2 = (db_exam_date_2.date() - now.date()).days
        cutoff_date_2 = db_exam_date_2 - timedelta(days=7)
        days_to_cutoff_2 = (cutoff_date_2.date() - now.date()).days

        if days_to_cutoff_2 > 0:
            days_for_new_2 = days_to_cutoff_2
        else:
            days_for_new_2 = max(1, total_days_2)

        expected_count_2 = math.ceil(10 / days_for_new_2)

        # Verify dynamic count in get_study_cards
        new_study_2, due_study_2 = db.get_study_cards(deck_id=deck_id)
        print(
            f"get_study_cards returned {len(new_study_2)} new cards for today (Expected: {expected_count_2})."
        )
        assert (
            len(new_study_2) == expected_count_2
        ), f"Expected {expected_count_2} new cards today, got {len(new_study_2)}"

        # Verify distribute_exam_cards schedule
        conn = db.get_db_connection()
        scheduled_new_2 = conn.execute(
            "SELECT id, next_review FROM cards WHERE id IN ({})".format(
                ",".join(map(str, new_card_ids))
            )
        ).fetchall()
        conn.close()

        print(
            "Checking new cards schedule dates for Exam 2 (should be before exam date):"
        )
        for row in scheduled_new_2:
            dt = db.parse_db_datetime(row["next_review"])
            print(f"  New card {row['id']}: next_review = {row['next_review']}")
            assert (
                dt < db_exam_date_2
            ), f"New card {row['id']} scheduled at {dt} is not before exam {db_exam_date_2}"

        print("[PASS] Cutoff logic integration tests passed successfully.")

    finally:
        # Cleanup
        print("Cleaning up cutoff test data...")
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM exams WHERE name LIKE 'Test Cutoff%'")
        for cid in new_card_ids + late_card_ids:
            cur.execute("DELETE FROM cards WHERE id = ?", (cid,))
            cur.execute("DELETE FROM card_decks WHERE card_id = ?", (cid,))
        cur.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
        conn.commit()
        conn.close()
        print("Cutoff Test clean up done.")


def test_study_cards_by_exam_id():
    print("=== Starting Study Cards by Exam ID Test ===")
    conn = db.get_db_connection()
    cur = conn.cursor()

    # Create test deck
    cur.execute("INSERT INTO decks (name) VALUES (?)", ("Exam ID Test Deck",))
    deck_id = cur.lastrowid

    # Add 3 dummy cards
    card_ids = []
    now = datetime.now(timezone.utc)
    now_str = db.format_datetime_for_db(now)
    for i in range(3):
        cur.execute(
            """
            INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                f"exam_id_word_{i}",
                f"測試單字_{i}",
                now_str,
                0,
                0,
                None,
                None,
                None,
                0,
                0,
                "recognize",
            ),
        )
        card_id = cur.lastrowid
        card_ids.append(card_id)
        cur.execute(
            "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
            (card_id, deck_id),
        )

    conn.commit()
    conn.close()

    try:
        # Create exam (in 5 days)
        exam_date = now + timedelta(days=5)
        exam_date_str = db.format_datetime_for_db(exam_date)
        exam_id = db.create_exam(
            "Test Exam ID Study", exam_date_str, deck_ids=[deck_id]
        )

        # Get cards by exam_id
        new_study, due_study = db.get_study_cards(exam_id=exam_id)

        # Verify that all 3 cards are returned since reps=0 and they are in the scope of the exam
        assert len(new_study) > 0, "No new study cards returned for exam_id!"
        for card in new_study:
            assert card["front"].startswith("exam_id_word_")

        print("[PASS] Study cards by exam_id successfully verified.")

    finally:
        # Cleanup
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM exams WHERE name = 'Test Exam ID Study'")
        for cid in card_ids:
            cur.execute("DELETE FROM cards WHERE id = ?", (cid,))
            cur.execute("DELETE FROM card_decks WHERE card_id = ?", (cid,))
        cur.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
        conn.commit()
        conn.close()
        print("Exam ID Study test clean up done.")


def test_today_counters():
    print("=== Starting Today Counters Test ===")
    conn = db.get_db_connection()
    cur = conn.cursor()

    # 1. Create two test decks
    cur.execute("INSERT INTO decks (name) VALUES (?)", ("Exam Target Deck",))
    deck_exam_id = cur.lastrowid

    cur.execute("INSERT INTO decks (name) VALUES (?)", ("General Target Deck",))
    deck_general_id = cur.lastrowid

    # 2. Add cards to both
    now = datetime.now(timezone.utc)
    now_str = db.format_datetime_for_db(now)

    # Card in exam deck
    cur.execute(
        """
        INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "today_exam_w1",
            "測試考試單字1",
            now_str,
            0,
            0,
            None,
            None,
            None,
            0,
            0,
            "recognize",
        ),
    )
    c_exam_id = cur.lastrowid
    cur.execute(
        "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
        (c_exam_id, deck_exam_id),
    )

    # Card in general deck
    cur.execute(
        """
        INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "today_general_w1",
            "測試一般單字1",
            now_str,
            0,
            0,
            None,
            None,
            None,
            0,
            0,
            "recognize",
        ),
    )
    c_general_id = cur.lastrowid
    cur.execute(
        "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
        (c_general_id, deck_general_id),
    )

    conn.commit()
    conn.close()

    try:
        # 3. Create an upcoming exam for the first deck
        exam_date = now + timedelta(days=10)
        exam_date_str = db.format_datetime_for_db(exam_date)
        _ = db.create_exam(
            "Test Today Counters Exam", exam_date_str, deck_ids=[deck_exam_id]
        )

        # 4. Get summary stats
        stats = db.get_today_summary_stats()
        print(f"Stats returned: {stats}")

        # Check that we have at least 1 in exams and 1 in general
        assert (
            stats["exam_total"] >= 1
        ), "Exam deck cards should be counted in exam_total!"
        assert (
            stats["general_total"] >= 1
        ), "General deck cards should be counted in general_total!"
        assert (
            stats["today_total"] == stats["exam_total"] + stats["general_total"]
        ), "today_total should sum exam_total and general_total!"

        # 5. Get cards list
        exam_new_cards, exam_due_cards = db.get_today_cards(only_exams=True)
        general_new_cards, general_due_cards = db.get_today_cards(only_exams=False)

        # Verify specific front words are in the lists
        exam_fronts = [c["front"] for c in exam_new_cards + exam_due_cards]
        general_fronts = [c["front"] for c in general_new_cards + general_due_cards]

        print(f"Exam fronts: {exam_fronts}")
        print(f"General fronts: {general_fronts}")

        assert "today_exam_w1" in exam_fronts, "today_exam_w1 must be in exam cards!"
        assert (
            "today_general_w1" in general_fronts
        ), "today_general_w1 must be in general cards!"
        assert (
            "today_exam_w1" not in general_fronts
        ), "today_exam_w1 must NOT be in general cards!"
        assert (
            "today_general_w1" not in exam_fronts
        ), "today_general_w1 must NOT be in exam cards!"

        print("[PASS] Today counters test successfully verified.")

    finally:
        # Cleanup
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM exams WHERE name = 'Test Today Counters Exam'")
        cur.execute(
            "DELETE FROM cards WHERE front IN ('today_exam_w1', 'today_general_w1')"
        )
        cur.execute(
            "DELETE FROM card_decks WHERE deck_id IN (?, ?)",
            (deck_exam_id, deck_general_id),
        )
        cur.execute(
            "DELETE FROM decks WHERE id IN (?, ?)", (deck_exam_id, deck_general_id)
        )
        conn.commit()
        conn.close()
        print("Today counters test cleanup done.")


def test_card_type_merging():
    print("=== Starting Card Type Merging Integration Test ===")
    conn = db.get_db_connection()
    cur = conn.cursor()

    # Create test deck
    cur.execute("INSERT INTO decks (name) VALUES (?)", ("Merge Test Deck",))
    deck_id = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        # Test Case 1: add_card recognize + recognize -> recognize
        cid1, merged = db.add_card("merge_word_1", "測試1", "recognize", [deck_id])
        assert not merged
        c1 = db.get_card_by_id(cid1)
        assert c1["card_type"] == "recognize"

        # Add second recognize card to merge
        cid1_new, merged = db.add_card(
            "merge_word_1", "測試1_加強", "recognize", [deck_id]
        )
        assert merged
        assert cid1 == cid1_new
        c1_merged = db.get_card_by_id(cid1)
        assert c1_merged["card_type"] == "recognize"
        assert c1_merged["back"] == "測試1\n\n測試1_加強"

        # Test Case 2: add_card recognize + spell -> spell
        cid2, merged = db.add_card("merge_word_2", "測試2", "recognize", [deck_id])
        assert not merged

        cid2_new, merged = db.add_card("merge_word_2", "測試2_拼寫", "spell", [deck_id])
        assert merged
        c2_merged = db.get_card_by_id(cid2)
        assert c2_merged["card_type"] == "spell"

        # Test Case 3: add_card spell + recognize -> spell
        cid3, merged = db.add_card("merge_word_3", "測試3", "spell", [deck_id])
        assert not merged

        cid3_new, merged = db.add_card(
            "merge_word_3", "測試3_認讀", "recognize", [deck_id]
        )
        assert merged
        c3_merged = db.get_card_by_id(cid3)
        assert c3_merged["card_type"] == "spell"

        # Test Case 4: import_csv_data recognize + spell -> spell
        # Create initial recognize card
        cid4, merged = db.add_card(
            "merge_csv_word", "舊CSV解釋", "recognize", [deck_id]
        )
        assert not merged

        # Import CSV with spell type
        csv_text = "merge_csv_word,新CSV解釋\n"
        imported, merged_count = db.import_csv_data(
            csv_text, [deck_id], card_type="spell"
        )
        assert imported == 0
        assert merged_count == 1

        c4_merged = db.get_card_by_id(cid4)
        assert c4_merged["card_type"] == "spell"
        assert c4_merged["back"] == "舊CSV解釋\n\n新CSV解釋"

        # Test Case 5: import_csv_data spell + recognize -> spell
        # Create initial spell card
        cid5, merged = db.add_card("merge_csv_word_2", "舊CSV解釋2", "spell", [deck_id])
        assert not merged

        # Import CSV with recognize type
        csv_text_2 = "merge_csv_word_2,新CSV解釋2\n"
        imported_2, merged_count_2 = db.import_csv_data(
            csv_text_2, [deck_id], card_type="recognize"
        )
        assert imported_2 == 0
        assert merged_count_2 == 1

        c5_merged = db.get_card_by_id(cid5)
        assert c5_merged["card_type"] == "spell"

        print("[PASS] Card type merging integration tests passed successfully.")

    finally:
        # Cleanup
        print("Cleaning up merge test data...")
        conn = db.get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM cards WHERE front LIKE 'merge_%'")
        cur.execute("DELETE FROM card_decks WHERE deck_id = ?", (deck_id,))
        cur.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
        conn.commit()
        conn.close()
        print("Merge Test clean up done.")


def test_desired_retention_scheduling():
    print("=== Starting Desired Retention Scheduling Test ===")

    # Setup test deck
    conn = db.get_db_connection()
    try:
        with conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO decks (name) VALUES (?)", ("Test Retention Deck",))
            deck_id = cur.lastrowid
    finally:
        conn.close()

    # Save original retention to restore later
    original_retention = db.get_setting("desired_retention")

    try:
        # Create card 1 (retention 0.70)
        db.set_setting("desired_retention", "0.70")

        conn = db.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                now_str = db.format_datetime_for_db(datetime.now(timezone.utc))
                yesterday_str = db.format_datetime_for_db(
                    datetime.now(timezone.utc) - timedelta(days=1)
                )
                cur.execute(
                    """
                    INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        "retention_word_1",
                        "保留率測試_1",
                        now_str,
                        2,
                        0,
                        10.0,
                        5.0,
                        yesterday_str,
                        1,
                        0,
                        "recognize",
                    ),
                )
                c1_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
                    (c1_id, deck_id),
                )
        finally:
            conn.close()

        # Review card 1
        db.submit_card_review(c1_id, 3)  # Rating: Good

        c1_updated = db.get_card_by_id(c1_id)
        c1_due = db.parse_db_datetime(c1_updated["next_review"])

        # Create card 2 (retention 0.99)
        db.set_setting("desired_retention", "0.99")

        conn = db.get_db_connection()
        try:
            with conn:
                cur = conn.cursor()
                now_str = db.format_datetime_for_db(datetime.now(timezone.utc))
                yesterday_str = db.format_datetime_for_db(
                    datetime.now(timezone.utc) - timedelta(days=1)
                )
                cur.execute(
                    """
                    INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        "retention_word_2",
                        "保留率測試_2",
                        now_str,
                        2,
                        0,
                        10.0,
                        5.0,
                        yesterday_str,
                        1,
                        0,
                        "recognize",
                    ),
                )
                c2_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
                    (c2_id, deck_id),
                )
        finally:
            conn.close()

        # Review card 2
        db.submit_card_review(c2_id, 3)  # Rating: Good

        c2_updated = db.get_card_by_id(c2_id)
        c2_due = db.parse_db_datetime(c2_updated["next_review"])

        print(f"Desired Retention 0.70 -> Next Review: {c1_due}")
        print(f"Desired Retention 0.99 -> Next Review: {c2_due}")

        # Retention 0.99 will have a much shorter interval than 0.70
        assert (
            c2_due < c1_due
        ), f"Retention 0.99 due ({c2_due}) should be earlier than 0.70 due ({c1_due})"
        print(
            "[PASS] Verification successful: Higher retention results in shorter review intervals."
        )

    finally:
        # Restore setting
        if original_retention is not None:
            db.set_setting("desired_retention", original_retention)
        else:
            conn = db.get_db_connection()
            try:
                with conn:
                    conn.execute("DELETE FROM settings WHERE key = 'desired_retention'")
            finally:
                conn.close()

        # Clean up
        conn = db.get_db_connection()
        try:
            with conn:
                conn.execute("DELETE FROM cards WHERE front LIKE 'retention_word_%'")
                conn.execute("DELETE FROM card_decks WHERE deck_id = ?", (deck_id,))
                conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
        finally:
            conn.close()
        print("Retention Test clean up done.")


def test_fsrs_scheduling_fixes():
    print("=== Starting FSRS Scheduling Fixes Test ===")

    # 1. Setup Test Deck and Cards
    conn = db.get_db_connection()
    cur = conn.cursor()

    # Create test deck
    cur.execute("INSERT INTO decks (name) VALUES (?)", ("Test Rollover Deck",))
    deck_id = cur.lastrowid

    # Add a dummy card for Exam Capping
    cur.execute(
        """
        INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            "capping_word",
            "測試單字_capping",
            db.format_datetime_for_db(datetime.now(timezone.utc)),
            2,
            0,
            2.0,
            5.0,
            None,
            1,
            0,
            "recognize",
        ),
    )
    cap_card_id = cur.lastrowid
    cur.execute(
        "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
        (cap_card_id, deck_id),
    )

    conn.commit()
    conn.close()

    try:
        # Create an exam scheduled for tomorrow morning (12 hours from now)
        now = datetime.now(timezone.utc)
        exam_date = now + timedelta(hours=12)
        exam_id = db.create_exam(
            "Tomorrow Exam", exam_date.isoformat(), deck_ids=[deck_id]
        )

        # Now review the card.
        next_review_str = db.submit_card_review(cap_card_id, 3)  # Good
        next_review_dt = db.parse_db_datetime(next_review_str)

        # Verify it is not capped to now
        time_diff = abs((next_review_dt - now).total_seconds())
        assert time_diff > 10, f"Card was capped to now (diff: {time_diff}s)!"
        print("[PASS] Verification successful: Exam capping bug is fixed.")

        # Clean up the exam
        conn = db.get_db_connection()
        conn.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
        conn.execute("DELETE FROM exam_decks WHERE exam_id = ?", (exam_id,))
        conn.commit()
        conn.close()

        # 2. Test Rollover Cutoff for Review cards
        conn = db.get_db_connection()
        cur = conn.cursor()

        # Card A (Review, due in 2 hours)
        future_today = now + timedelta(hours=2)
        cur.execute(
            """
            INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "review_future_today",
                "測試_A",
                db.format_datetime_for_db(future_today),
                2,
                0,
                2.0,
                5.0,
                db.format_datetime_for_db(now),
                1,
                0,
                "recognize",
            ),
        )
        card_a_id = cur.lastrowid
        cur.execute(
            "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
            (card_a_id, deck_id),
        )

        # Card B (Learning, due in 10 minutes)
        learning_future = now + timedelta(minutes=10)
        cur.execute(
            """
            INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "learning_future",
                "測試_B",
                db.format_datetime_for_db(learning_future),
                1,
                0,
                2.0,
                5.0,
                db.format_datetime_for_db(now),
                1,
                0,
                "recognize",
            ),
        )
        card_b_id = cur.lastrowid
        cur.execute(
            "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
            (card_b_id, deck_id),
        )

        conn.commit()
        conn.close()

        # Get study cards
        new_cards, due_cards = db.get_study_cards(deck_id=deck_id)
        due_ids = [c["id"] for c in due_cards]

        # Card A (Review) should be due because it's due within today's rollover limit
        # Card B (Learning) should NOT be due because it requires waiting 10 minutes
        assert card_a_id in due_ids, "Review card scheduled for later today is not due!"
        assert (
            card_b_id not in due_ids
        ), "Learning card scheduled for 10 minutes from now is due prematurely!"
        print("[PASS] Verification successful: Rollover due logic behaves correctly.")

    finally:
        # Clean up
        conn = db.get_db_connection()
        conn.execute(
            "DELETE FROM cards WHERE id IN (SELECT card_id FROM card_decks WHERE deck_id = ?)",
            (deck_id,),
        )
        conn.execute("DELETE FROM card_decks WHERE deck_id = ?", (deck_id,))
        conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
        conn.commit()
        conn.close()
        print("FSRS Scheduling Fixes Test clean up done.")


def test_daily_new_limit_behavior():
    print("=== Starting Daily New Limit Behavior Test ===")
    conn = db.get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO decks (name) VALUES (?)", ("Daily Limit Test Deck",))
    deck_id = cur.lastrowid

    now = datetime.now(timezone.utc)
    now_str = db.format_datetime_for_db(now)
    card_ids = []
    for i in range(25):
        cur.execute(
            """
            INSERT INTO cards (front, back, next_review, state, step, reps, card_type)
            VALUES (?, ?, ?, 0, 0, 0, 'recognize')
        """,
            (f"limit_word_{i}", f"解釋_{i}", now_str),
        )
        cid = cur.lastrowid
        card_ids.append(cid)
        cur.execute(
            "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
            (cid, deck_id),
        )
    conn.commit()
    conn.close()

    try:
        # 1. When daily_new_limit is 0 (unlimited), all 25 cards should be returned
        db.set_setting("daily_new_limit", "0")
        new_cards, _ = db.get_study_cards(deck_id=deck_id)
        assert (
            len(new_cards) == 25
        ), f"Expected 25 cards for limit=0, got {len(new_cards)}"
        print("[PASS] Limit=0 correctly returns all 25 new cards.")

        # 2. When daily_new_limit is 10, exactly 10 cards should be returned
        db.set_setting("daily_new_limit", "10")
        new_cards, _ = db.get_study_cards(deck_id=deck_id)
        assert (
            len(new_cards) == 10
        ), f"Expected 10 cards for limit=10, got {len(new_cards)}"
        print("[PASS] Limit=10 correctly caps new cards to 10.")

        # 3. Setting back to 0 should restore unlimited
        db.set_setting("daily_new_limit", "0")
        new_cards, _ = db.get_study_cards(deck_id=deck_id)
        assert (
            len(new_cards) == 25
        ), f"Expected 25 cards for limit=0, got {len(new_cards)}"
        print("[PASS] Resetting limit=0 correctly restores unlimited.")

    finally:
        conn = db.get_db_connection()
        conn.execute(
            "DELETE FROM cards WHERE id IN (SELECT card_id FROM card_decks WHERE deck_id = ?)",
            (deck_id,),
        )
        conn.execute("DELETE FROM card_decks WHERE deck_id = ?", (deck_id,))
        conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
        conn.commit()
        conn.close()
        print("Daily Limit Test clean up done.")


if __name__ == "__main__":
    test_exam_scheduling()
    test_exam_scheduling_new_cards_cutoff()
    test_study_cards_by_exam_id()
    test_today_counters()
    test_card_type_merging()
    test_desired_retention_scheduling()
    test_fsrs_scheduling_fixes()
    test_daily_new_limit_behavior()
