# main.py
# Kivy app to display iCal events, launch web view at event time, and automate form filling

from unittest import case
import webview
import requests
from icalendar import Calendar
from datetime import datetime
import pytz
import re
from datetime import timedelta
from enum import Enum
import argparse
from pathlib import Path
from jsactions import *
from webview.menu import Menu, MenuAction, MenuSeparator


def parse_args():
    parser = argparse.ArgumentParser(
        description="Show iCal events and auto-launch lecture webview."
    )
    parser.add_argument("ical_url", help="URL to the iCal feed")
    parser.add_argument(
        "--testmode",
        "-t",
        action="store_true",
        help="Open the first upcoming event immediately for testing",
    )
    parser.add_argument(
        "--jsconsole", "-j", action="store_true", help="Open the webview JS console"
    )
    return parser.parse_args()


LECTURE_URL = "https://uon.seats.cloud/angular/#/lectures"
BASE_URL = "https://uon.seats.cloud/angular/#/"

OPEN_WINDOWS = {}


class EventActions(Enum):
    INIT_ACTIONS = "INIT_ACTIONS"
    LOGIN_TO_SYSTEM = "LOGIN_TO_SYSTEM"
    NAVIGATE_TO_PAGE = "NAVIGATE_TO_PAGE"
    SELECT_DATE = "SELECT_DATE"
    DO_SEARCH = "DO_SEARCH"
    OPEN_QRCODE = "OPEN_QRCODE"
    STOPPED = "STOPPED"


class Event:
    def __init__(self, summary, start, end, description, location):
        self.summary = summary
        self.start = start
        self.end = end
        self.description = description
        self.location = location
        self.module_code = self.extract_module_code(description)

    def extract_module_code(self, description):
        match = re.search(r"Module code:?\s*([A-Z0-9/]+)", description or "")
        if not match:
            match = re.search(r"([A-Z]{4}/\d{4}/\d{2}/[A-Z]+)", description or "")
        return match.group(1) if match else ""

    def __str__(self):
        return f"{self.summary} | {self.start} - {self.end} | {self.location} | {self.module_code}"


def log_js(message):
    print(f"[JS] {message}")


def fetch_events(ical_url):
    try:
        print(f"Fetching iCal from: {ical_url}")
        r = requests.get(ical_url)
        cal = Calendar.from_ical(r.text)
        events = []
        now = datetime.now(pytz.utc)
        for component in cal.walk():
            if component.name == "VEVENT":
                start = component.get("dtstart").dt
                end = component.get("dtend").dt
                if isinstance(start, datetime) and end > now:
                    summary = str(component.get("summary"))
                    description = str(component.get("description", ""))
                    location = str(component.get("location", ""))
                    event = Event(summary, start, end, description, location)
                    events.append(event)
        events.sort(key=lambda e: e.start)
        print(f"Total upcoming events: {len(events)}")
        return events
    except Exception as e:
        print(f"Error loading events: {e}")
        return []


def build_event_list_html(events):
    html = """
    <html><head><meta charset='utf-8'><title>Upcoming Events</title></head><body>
    <h2>Upcoming Events</h2>
    <ul>
    """
    if not events:
        html += "<li><b>No upcoming events found.</b></li>"
    for idx, event in enumerate(events):
        html += (
            "<li>"
            f"<div class='event' data-index='{idx}' onclick='openEvent({idx})'"
            " style='cursor:pointer; padding:8px; border:1px solid #ddd; border-radius:6px; margin-bottom:8px;'>"
            f"<b>{event.summary}</b><br>Start: {event.start}<br>End: {event.end}<br>Location: {event.location}<br>Module: {event.module_code}"
            "</div></li>"
        )
    html += """
    </ul>
    <p>This window will automatically open the lecture page at the event time.</p>
    <script>
        function openEvent(index) {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.open_event) {
                window.pywebview.api.open_event(index);
            } else {
                console.log('pywebview api not ready');
            }
        }
    </script>
    </body></html>
    """
    return html


def get_actions_for_state(state, event):
    start_formatted = event.start.strftime("%d %B %Y")
    end_formatted = event.end.strftime("%d %B %Y")
    ACTIONS_FOR_STATE = {
        EventActions.LOGIN_TO_SYSTEM: [
            JSFailIfLoggedIn(BASE_URL, LECTURE_URL),
            JSClickBySelector('[data-test-id="signinOptions"]', timeout=10000),
            JSClickByText(
                "Face, fingerprint, PIN or security key",
                element_type="div",
                timeout=5000,
            ),
            JSClickByText("Yes", element_type="input", timeout=2000),
            JSWait(timeout=500),
        ],
        EventActions.NAVIGATE_TO_PAGE: [JSNavigateToMainPage(BASE_URL, LECTURE_URL)],
        EventActions.SELECT_DATE: [
            JSWait(timeout=100),
            JSClickByText("Start Date", element_type="label", timeout=5000),
            JSWait(timeout=500),
            JSClickBySelector(f'#calendarStart button[aria-label="{start_formatted}"]'),
            JSClickBySelector(f'#calendarEnd button[aria-label="{end_formatted}"]'),
            JSClickByText("Select Range", element_type="button"),
        ],
        EventActions.DO_SEARCH: [
            JSWait(timeout=100),
            JSClickBySelector(
                'input[type="search"], input[placeholder*="Search" i], input[name*="search" i]'
            ),
            JSWait(timeout=100),
            JSInputBySelector(
                'input[type="search"], input[placeholder*="Search" i], input[name*="search" i]',
                value=event.module_code,
            ),
        ],
        EventActions.OPEN_QRCODE: [
            JSClickByMultiText(
                [event.module_code, event.location, event.start.strftime("%H:%M")],
                click_selector='i[aria-label="QR code"]',
                element_type="tr",
                timeout=5000,
            ),
            JSWait(timeout=1000),
            JSActionBringToFront(),
            JSWait(timeout=1000),
            JSHoldWhileVisibleXPath('//H2[contains(.,"Check In")]'),
            JSWait(timeout=1000),
        ],
    }
    return ACTIONS_FOR_STATE.get(state, [])


def open_lecture_webview(
    event, module_override=None, location_override=None, time_override=None
):
    # This function is called on the main thread
    cur_state = EventActions.INIT_ACTIONS
    current_actions = []
    this_action = None

    def state_error(error):
        nonlocal cur_state
        print("Error, state:", cur_state, error)
        import sys

        sys.exit(0)

    def handle_state(reloaded=False):
        nonlocal this_action
        if this_action is None:
            action_done()
        else:
            if reloaded:
                # page reloaded
                print("Page reloaded, reapplying current action:", this_action)
                this_action.apply(lecture_window, action_done, state_error)
            else:
                print("Still waiting for action finish, current action:", this_action)

    def action_error(*argv, **args):
        print("Error in action:", argv, args)
        import sys

        sys.exit(-1)

    def action_done(*argv, **args):
        nonlocal current_actions, cur_state, this_action
        if this_action is not None:
            print("DONE ACTION:", this_action)
        this_action = None

        if len(current_actions) == 0:
            if cur_state == EventActions.INIT_ACTIONS:
                print("Initializing actions, starting with navigate to page")
                cur_state = EventActions.NAVIGATE_TO_PAGE
            elif cur_state == EventActions.LOGIN_TO_SYSTEM:
                print("Finished login, moving to navigate to page")
                cur_state = EventActions.NAVIGATE_TO_PAGE
            elif cur_state == EventActions.OPEN_QRCODE:
                print("Reloading QR code as it has closed")
            elif cur_state == EventActions.DO_SEARCH:
                print("Finished search, moving to open QR code")
                cur_state = EventActions.OPEN_QRCODE
            elif cur_state == EventActions.SELECT_DATE:
                print("Finished selecting date, moving to search")
                cur_state = EventActions.DO_SEARCH
            elif cur_state == EventActions.NAVIGATE_TO_PAGE:
                print("Finished navigating to page, moving to select date")
                cur_state = EventActions.SELECT_DATE
            elif cur_state == EventActions.STOPPED:
                print("Auto check-in stopped, no further actions will be taken.")
                return
            current_actions = get_actions_for_state(cur_state, event)
        print("Handling state:", cur_state)
        this_action = current_actions.pop(0)
        print(f"applying action: {this_action}")
        this_action.apply(lecture_window, action_done, action_error)

    def on_loaded():
        print("On loaded")
        print("W:", lecture_window.evaluate_js("window.toString()"))
        print("PW:", lecture_window.evaluate_js("window.pywebview.toString()"))
        print("RL:", lecture_window.evaluate_js("window.pywebview.api.real_loaded"))
        print("RL:", lecture_window.evaluate_js("window.pywebview.api"))
        lecture_window.evaluate_js("""
                                   (function() {
                                   if(window.called_real_loaded){
                                   return;
                                   }
                                   console.log("In ON LOADED HANDLER");
                                   async function tryCallRealLoaded(){
                                        if(window.called_real_loaded){
                                            return;
                                        }
                                        if (window.pywebview && window.pywebview.api && window.pywebview.api.real_loaded) 
                                        {
                                              window.called_real_loaded=true;
                                              console.log("Calling real_loaded from JS");
                                              console.log("REAL LOADED FUNCTION:",window.pywebview.api.real_loaded);
                                              window.pywebview.api.real_loaded();
                                        }
                                        else{
                                            console.log("pywebview api not ready for real_loaded, retrying...");
                                            window.setTimeout(tryCallRealLoaded, 200);
                                        }
                                   }
                                   
                                   tryCallRealLoaded();
                                   })();""")

    def real_loaded(*args):
        print("Loaded new page")
        handle_state(reloaded=True)
        return True
    
    def disable_auto_checkin():
        nonlocal cur_state,current_actions,this_action
        if cur_state == EventActions.OPEN_QRCODE:
            cur_state = EventActions.STOPPED
            this_action=None
            current_actions=[]
            print("Auto check-in disabled by user.")


    window_menu = [Menu("Settings", [MenuAction("Disable auto-open of checkin",function=disable_auto_checkin)])]

    lecture_window = webview.create_window(
        f"Lecture: {event.summary}", BASE_URL, width=1200, height=800, menu=window_menu
    )
    OPEN_WINDOWS[event] = lecture_window

    def action_success(result):
        nonlocal cur_state
        print("Action success with result:", result)
        if result == True:
            action_done(result)
        else:
            if cur_state == EventActions.NAVIGATE_TO_PAGE and result == False:
                cur_state = EventActions.LOGIN_TO_SYSTEM
                action_done(True)
                return
            print(f"Action {this_action} did not return True,Failed:", result)
            import sys

            sys.exit(-1)

    def action_fail(error):
        print(f"Action {this_action} failed with error:", error)
        import sys

        sys.exit(-1)

    def close_window():
        OPEN_WINDOWS[event] = None

    lecture_window.expose(action_success)
    lecture_window.expose(action_fail)
    lecture_window.expose(real_loaded)
    lecture_window.events.loaded += on_loaded
    lecture_window.events.closed += close_window


def main():
    args = parse_args()
    ical_url = args.ical_url
    testmode = args.testmode
    jsconsole = args.jsconsole
    events = fetch_events(ical_url)
    html = build_event_list_html(events)
    testmode_used = False

    def check_events():
        nonlocal testmode_used
        try:
            now = datetime.now(pytz.utc)
            if testmode and events and not testmode_used:
                print("Test mode: opening specific event immediately.")
                testmode_used = True
                open_lecture_webview(events[0])
            else:
                for event in events:
                    if event.start <= now + timedelta(minutes=15) and event.end >= now:
                        if event not in OPEN_WINDOWS:
                            print(f"Opening lecture window for event: {event}")
                            open_lecture_webview(event)
        except Exception as e:
            print(f"Error checking events: {e}")
        # Schedule next check on the main thread via JS
        window.evaluate_js(
            "setTimeout(() => window.pywebview.api.check_events(), 1000);"
        )

    def log_div_not_found(label):
        print(f"Could not find '{label}' div. Retrying...")

    def open_event(index):
        try:
            idx = int(index)
            if 0 <= idx < len(events):
                event = events[idx]
                print(f"Opening lecture window for clicked event: {event}")
                if event in OPEN_WINDOWS and OPEN_WINDOWS[event] is not None:
                    print("Window already open for this event.")
                    OPEN_WINDOWS[event].bring_to_front()
                else:
                    open_lecture_webview(event)
            else:
                print(f"Invalid event index: {index}")
        except Exception as e:
            print(f"Error opening event: {e}")

    window = webview.create_window(
        "Upcoming Teaching Sessions", html=html, width=600, height=800
    )
    window.expose(check_events)
    window.expose(log_div_not_found)
    window.expose(log_js)
    window.expose(open_event)
    webview.start(func=check_events, debug=jsconsole, private_mode=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt received. Exiting.")
        import os

        os._exit(0)
