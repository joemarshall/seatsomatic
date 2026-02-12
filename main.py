# main.py
# Kivy app to display iCal events, launch web view at event time, and automate form filling

import webview
import requests
from icalendar import Calendar
from datetime import datetime
import pytz
import re
from datetime import timedelta

import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="Show iCal events and auto-launch lecture webview.")
    parser.add_argument("ical_url", help="URL to the iCal feed")
    parser.add_argument("--testmode","-t", action="store_true", help="Open the first upcoming event immediately for testing")
    parser.add_argument("--jsconsole","-j", action="store_true", help="Open the webview JS console")
    return parser.parse_args()

LECTURE_URL = "https://uon.seats.cloud/angular/#/lectures"

class Event:
    def __init__(self, summary, start, end, description, location):
        self.summary = summary
        self.start = start
        self.end = end
        self.description = description
        self.location = location
        self.module_code = self.extract_module_code(description)

    def extract_module_code(self, description):
        match = re.search(r"Module:?\s*([A-Z0-9]+)", description or "")
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
                start = component.get('dtstart').dt
                end = component.get('dtend').dt
                if isinstance(start, datetime) and start > now:
                    summary = str(component.get('summary'))
                    description = str(component.get('description', ''))
                    location = str(component.get('location', ''))
                    event = Event(summary, start, end, description, location)
                    print(f"Fetched event: {event}")
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

def open_lecture_webview(event, module_override=None, location_override=None, time_override=None):
    # This function is called on the main thread
    def on_loaded():
        try:
            url = lecture_window.get_current_url()
            print(f"Webview loaded URL: {url}")
            if url and url.startswith(LECTURE_URL):
                module_id = module_override or event.module_code
                location_value = location_override or event.location
                start_time_value = time_override or event.start.strftime('%H:%M')
                js = f'''
                    (async function() {{
                        if (window.pywebview && window.pywebview.api && window.pywebview.api.log_js) {{
                            const originalLog = console.log;
                            console.log = function(...args) {{
                                try {{
                                    window.pywebview.api.log_js(args.join(' '));
                                }} catch (e) {{}}
                                originalLog.apply(console, args);
                            }};
                        }}
                        function clickDivWithText(text) {{
                            var divs = Array.from(document.querySelectorAll('div'));
                            for (var div of divs) {{
                                if (div.textContent && div.textContent.trim().toLowerCase()===text.toLowerCase()) {{
                                    console.log('Found div for text:', text, '=>', div.textContent.trim());
                                    console.log('Clicking date div for:', text);
                                    div.click();
                                    return true;
                                }}
                            }}
                            console.log('Div not found for text:', text);
                            return false;
                        }}
                        function clickButtonWithText(text) {{
                            var btns = Array.from(document.querySelectorAll('button'));
                            for (var btn of btns) {{
                                if (btn.textContent && btn.textContent.trim().toLowerCase() === text.toLowerCase()) {{
                                    console.log('Clicking button:', text);
                                    btn.click();
                                    return true;
                                }}
                            }}
                            return false;
                        }}
                        function waitForButton(text, timeout=5000) {{
                            return new Promise((resolve, reject) => {{
                                let elapsed = 0;
                                function check() {{
                                    if (clickButtonWithText(text)) {{
                                        resolve();
                                    }} else if (elapsed > timeout) {{
                                        reject('Button not found: ' + text);
                                    }} else {{
                                        console.log('Waiting for button:', text);
                                        elapsed += 200;
                                        setTimeout(check, 200);
                                    }}
                                }}
                                check();
                            }});
                        }}
                        async function tryStartDate() {{
                            var found = clickDivWithText('Start Date');
                            if (!found) {{
                                if (window.pywebview && window.pywebview.api && window.pywebview.api.log_div_not_found) {{
                                    window.pywebview.api.log_div_not_found('Start Date');
                                }}
                                setTimeout(tryStartDate, 1000);
                                return;
                            }}
                            await waitForButton('today');
                            await waitForButton('select range');

                            // Click search container div (if any) and enter module ID into its input
                            var searchContainer = document.querySelector('input[type="search"], input[placeholder*="Search" i], input[name*="search" i]');
                            var searchInput = null;
                            if (searchContainer) {{
                                console.log('Found search container div:'+searchContainer.outerHTML);
                                console.log('Clicking search container div');
                                searchContainer.click();
                                searchInput = searchContainer.querySelector('input');
                            }} else {{
                                console.log('Search container div not found');
                            }}
                            if (!searchInput) {{
                                searchInput = document.querySelector('input[type="search"], input[placeholder*="Search" i], input[name*="search" i]');
                            }}
                            if (searchInput) {{
                                console.log('Sending module ID to search input:', '{module_id}');
                                searchInput.focus();
                                searchInput.value = '{module_id}';
                                searchInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                searchInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            }} else {{
                                console.log('Search input not found');
                            }}

                            // Fill module code and location fields if present
                            var moduleInput = document.querySelector('input[name*="module" i], input[placeholder*="Module" i]');
                            if (moduleInput) moduleInput.value = '{module_id}';
                            var locationInput = document.querySelector('input[name*="location" i], input[placeholder*="Location" i]');
                            if (locationInput) locationInput.value = '{location_value}';

                            var searchBtn = document.querySelector('button[type="submit"], button[aria-label*="Search" i]');
                            if (searchBtn) searchBtn.click();

                            // Wait for results and click QR code cell
                            function waitForQrCell(timeout=10000) {{
                                return new Promise((resolve, reject) => {{
                                    let elapsed = 0;
                                    function check() {{
                                        var rows = Array.from(document.querySelectorAll('tr'));
                                        var targetRow = null;
                                        for (var row of rows) {{
                                            var text = row.textContent || '';
                                            if (text.includes('{start_time_value}') && text.includes('{location_value}')) {{
                                                targetRow = row;
                                                break;
                                            }}
                                        }}
                                        if (targetRow) {{
                                            var qrCell = targetRow.querySelector('i[aria-label="QR code"]');
                                            if (qrCell) {{
                                                console.log('Found matching row, clicking QR code cell...');
                                                qrCell.click();
                                                resolve();
                                                return;
                                            }}
                                        }}
                                        if (elapsed > timeout) {{
                                            reject('QR code cell not found for matching row');
                                        }} else {{
                                            elapsed += 200;
                                            setTimeout(check, 200);
                                        }}
                                    }}
                                    check();
                                }});
                            }}

                            waitForQrCell().catch(function(err) {{
                                console.log(err);
                            }});
                        }}
                        tryStartDate();
                    }})();
                '''
                print("Injecting JS to set form fields and select date range...")
                lecture_window.evaluate_js(js)
            elif url and url.startswith("https://uon.seats.cloud/angular/"):
                print("Redirecting to lectures page...")
                lecture_window.load_url(LECTURE_URL)
            else:
                print("Not on lectures or angular page yet; checking sign-in options...")
                js = r'''
                    (function() {
                        if (window.pywebview && window.pywebview.api && window.pywebview.api.log_js) {
                            const originalLog = console.log;
                            console.log = function(...args) {
                                try {
                                    window.pywebview.api.log_js(args.join(' '));
                                } catch (e) {}
                                originalLog.apply(console, args);
                            };
                        }
                        function clickDivWithText(text) {
                            var divs = Array.from(document.querySelectorAll('div'));
                            for (var div of divs) {
                                //console.log('Checking div:', div.textContent,div.outerHTML);
                                if (div.textContent && div.textContent.trim().toLowerCase() === text.toLowerCase()) {
                                    console.log('Found div for text:', text, '=>', div.textContent.trim());
                                    div.click();
                                    return true;
                                }
                            }
                            return false;
                        }
                        function tryClickSignIn()
                        {
                            var signInDiv = document.querySelector('[data-test-id="signinOptions"]');
                            var clickedSignIn = false;
                            if (signInDiv) {
                                console.log('Clicking signInOptions div (data-test-id)');
                                signInDiv.click();
                                clickedSignIn = true;
                            } else {
                                console.log('signInOptions div not found (data-test-id)');
                            }
                            var continueBtn = document.getElementById('idSIButton9');
                            var clickedContinue = false;
                            if (continueBtn) {
                                console.log('Clicking idSIButton9 input');
                                continueBtn.click();
                                clickedContinue = true;
                            } else {
                                console.log('idSIButton9 input not found');
                            }
                            var clickedPasskey = clickDivWithText('Face, fingerprint, PIN or security key');
                            return { clickedSignIn, clickedPasskey, clickedContinue };
                        }
                        
                        function waitUntilSignedIn(timeout=500) 
                        {						
                            var result = tryClickSignIn();
                            if (!result.clickedSignIn && !result.clickedPasskey && !result.clickedContinue) {
                                setTimeout(waitUntilSignedIn, timeout);
                            }
                        }
                        setTimeout(waitUntilSignedIn, 500);

                        
                    })();
                '''
                lecture_window.evaluate_js(js)
        except Exception as e:
            print(f"Error in on_loaded: {e}")

    lecture_window = webview.create_window(
        f"Lecture: {event.summary}",
        LECTURE_URL,
        width=1200,
        height=800
    )
    lecture_window.expose(log_js)
    lecture_window.events.loaded += on_loaded

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
                open_lecture_webview(
                    events[0],
                    module_override="COMP/3007/01/SPR",
                    location_override="JC-EXCHANGE-C33",
                    time_override="14:00"
                )
            else:
                while events and events[0].start <= now + timedelta(minutes=15) and events[0].end >= now:
                    event = events.pop(0)
                    print(f"Opening lecture window for event: {event}")
                    open_lecture_webview(event)
        except Exception as e:
            print(f"Error checking events: {e}")
        # Schedule next check on the main thread via JS
        indow.evaluate_js("setTimeout(() => window.pywebview.api.check_events(), 1000);")

    def log_div_not_found(label):
        print(f"Could not find '{label}' div. Retrying...")

    def open_event(index):
        try:
            idx = int(index)
            if 0 <= idx < len(events):
                event = events[idx]
                print(f"Opening lecture window for clicked event: {event}")
                open_lecture_webview(event)
            else:
                print(f"Invalid event index: {index}")
        except Exception as e:
            print(f"Error opening event: {e}")

    window = webview.create_window("Event List", html=html, width=600, height=800)
    window.expose(check_events)
    window.expose(log_div_not_found)
    window.expose(log_js)
    window.expose(open_event)
    webview.start(func=check_events, debug=jsconsole)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt received. Exiting.")
        import os
        os._exit(0)
