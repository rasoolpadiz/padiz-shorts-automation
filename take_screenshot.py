import pyautogui
import pygetwindow as gw

# Find Chrome window and bring to front
chrome_windows = [w for w in gw.getWindowsWithTitle('Google Cloud') if w.visible]
if not chrome_windows:
    chrome_windows = [w for w in gw.getWindowsWithTitle('Chrome') if w.visible]

print("Found windows:", [w.title for w in chrome_windows])
if chrome_windows:
    w = chrome_windows[0]
    w.activate()
    pyautogui.screenshot(r"C:\youtube_pipeline\screen.png")
    print("Screenshot taken!")
