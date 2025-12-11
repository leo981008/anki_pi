from playwright.sync_api import sync_playwright, expect
import time
import re

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    # 1. Go to Swipe Mode directly
    print("Navigating to Swipe Mode...")
    page.goto("http://localhost:10000/swipe_mode/1")

    # 2. Check if card is already visible (auto-start) or need to click download
    print("Checking for flashcard...")
    try:
        page.locator(".flashcard").wait_for(state="visible", timeout=10000)
        print("Card is visible.")
    except:
        print("Card not visible, looking for download button...")
        try:
            download_btn = page.locator("button.main-action-btn", has_text=re.compile(r"下載今日課程|繼續學習"))
            download_btn.click()
            print("Clicked download button.")

            # Wait for download overlay to disappear
            page.wait_for_selector("#download-overlay", state="hidden", timeout=10000)

            # Now card should be visible
            expect(page.locator(".flashcard")).to_be_visible(timeout=10000)
        except Exception as e:
            print(f"Failed to start session: {e}")
            page.screenshot(path="/home/jules/verification/error_start_2.png")
            return

    # Verify button labels have shortcuts
    print("Verifying button labels...")
    expect(page.locator(".btn-no")).to_contain_text("(←)")
    expect(page.locator(".btn-yes")).to_contain_text("(→)")
    print("Button labels verified.")

    # 3. Test Keyboard Shortcuts
    print("Testing Space key (Flip)...")

    # Check initial state (not flipped)
    expect(page.locator(".flashcard")).not_to_have_class(re.compile(r"flipped"))

    # Press Space to flip
    page.keyboard.press("Space")

    # Verify flipped class
    try:
        expect(page.locator(".flashcard")).to_have_class(re.compile(r"flipped"), timeout=2000)
        print("Card flipped successfully.")
    except AssertionError:
         print("Card did not flip!")

    # Take screenshot of flipped card
    page.screenshot(path="/home/jules/verification/flipped_card.png")

    # Press ArrowRight to Remember
    print("Testing ArrowRight key (Remember)...")
    page.keyboard.press("ArrowRight")

    # Should move to finish screen since we have 1 card
    print("Waiting for finish screen...")
    try:
        # Look for "恭喜完成" or "Sync" button which appears at end
        expect(page.locator("text=恭喜完成")).to_be_visible(timeout=5000)
        print("Finish screen visible.")
    except:
        print("Finish screen not found.")

    page.screenshot(path="/home/jules/verification/finish_screen.png")

    browser.close()

if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
