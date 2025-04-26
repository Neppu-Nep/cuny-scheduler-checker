import json
import logging
import math
import os
import time

import backoff
import bs4
import requests
import urllib3
from dotenv import load_dotenv

urllib3.disable_warnings()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class CUNY:
    """Handles the multi-step login process for CUNYfirst and fetches class data.

    Manages cookies manually throughout the login redirect chain.
    Includes retry logic for fetching class data in case of session expiry.
    """

    main_url = "https://cssa.cunyfirst.cuny.edu/psc/cnycsprd/EMPLOYEE/SA/s/WEBLIB_VSB.TRANSFER_FUNCS.FieldFormula.IScript_RedirectVSBuilder?INSTITUTION=LAG01"
    class_data_url = "https://sb.cunyfirst.cuny.edu/api/class-data"

    def __init__(self, username, password):
        """Initializes the CUNY client with credentials."""
        logging.debug("Initializing CUNY client...")
        self.next_url = self.main_url

        self.username = username
        self.password = password
        self.cookies = {}
        self.headers = {"User-Agent": "CUNY/1.0"}
        self.class_data_cookies = None
        self.terms = None

        self._setup()
        logging.debug("CUNY client initialized.")

    def _setup(self):
        self.login()
        self.terms = self._get_term()

    def _nWindow(self):
        """Generates time-based parameters required for the class data API request.

        The exact purpose of 't' and 'e' is unclear but seems necessary for the API.
        Based on observed network requests.
        """
        t = math.floor(time.time() / 60) % 1000
        e = t % 3 + t % 39 + t % 42
        logging.debug(f"_nWindow generated: t={t}, e={e}")
        return {"t": t, "e": e}

    def _step_one(self):
        """Initiates the login process by hitting the main VSB redirect URL."""
        logging.debug("Executing Step 1: Initial VSB redirect...")
        response = requests.get(self.next_url, verify=False, allow_redirects=False, headers=self.headers)
        response.raise_for_status()
        self.cookies.update(response.cookies.get_dict())
        self.next_url = response.headers['Location']

    def _step_two(self):
        """Follows the first redirect, likely to the SSO login page."""
        logging.debug("Executing Step 2: Follow first redirect...")
        response = requests.get(self.next_url, allow_redirects=False, cookies=self.cookies, headers=self.headers)
        response.raise_for_status()
        self.cookies.update(response.cookies.get_dict())
        self.next_url = "https://ssologin.cuny.edu/oam/server/auth_cred_submit"

    def _step_three(self):
        """Submits the username and password to the SSO login form."""
        logging.debug("Executing Step 3: Submitting credentials...")
        form_data = {
            "username": self.username,
            "password": self.password,
        }
        response = requests.post(self.next_url, data=form_data, allow_redirects=False, cookies=self.cookies, headers=self.headers)
        response.raise_for_status()
        self.cookies.update(response.cookies.get_dict())
        self.next_url = response.headers['Location']

    def _step_four(self):
        """Follows the redirect after successful authentication."""
        logging.debug("Executing Step 4: Following post-authentication redirect...")
        response = requests.get(self.next_url, verify=False, allow_redirects=False, cookies=self.cookies, headers=self.headers)
        response.raise_for_status()
        self.cookies = response.cookies.get_dict()

    def _step_five(self):
        """Re-accesses the original VSB URL with the authenticated cookies."""
        logging.debug("Executing Step 5: Re-accessing main VSB URL...")
        response = requests.get(self.main_url, verify=False, allow_redirects=False, cookies=self.cookies, headers=self.headers)
        response.raise_for_status()
        self.cookies.update(response.cookies.get_dict())

    def _step_six(self):
        """Accesses a variation of the VSB URL to obtain cookies for the class data API."""
        logging.debug("Executing Step 6: Accessing VSB URL variation for API cookies...")
        api_cookie_url = self.main_url + "&"
        response = requests.get(api_cookie_url, verify=False, allow_redirects=False, cookies=self.cookies, headers=self.headers)
        response.raise_for_status()
        self.class_data_cookies = response.cookies.get_dict()

    def _get_day(self, day: str) -> str:
        """Converts numeric day representation (from HTML) to abbreviated day name."""
        match day:
            case "1": return "Mon"
            case "2": return "Tue"
            case "3": return "Wed"
            case "4": return "Thu"
            case "5": return "Fri"
            case "6": return "Sat"
            case "7": return "Sun"
            case _: return "Unk"

    def _build_time(self, timeblock_ids: list[str], timeblocks: dict[str, bs4.element.Tag], hour_12: bool = True) -> str:
        """Constructs a human-readable time string from timeblock data.

        Args:
            timeblock_ids: List of timeblock IDs associated with a class section.
            timeblocks: A dictionary mapping timeblock IDs to their corresponding BeautifulSoup Tag objects.
            hour_12: Whether to format time in 12-hour (AM/PM) format.

        Returns:
            A formatted string like "Mon, Wed: 09:00 AM to 10:15 AM, Fri: 11:00 AM to 12:00 PM".
            Handles multiple distinct time slots for a single class section.
        """
        days_by_time = {}

        for timeblock_id in timeblock_ids:
            if timeblock_id not in timeblocks:
                logging.warning(f"Timeblock ID {timeblock_id} not found in timeblocks map.")
                continue
            timeblock = timeblocks[timeblock_id]
            day_abbr = self._get_day(timeblock.attrs.get('day', ''))

            t1 = int(timeblock.attrs.get('t1', 0))
            h1 = t1 // 60
            m1 = t1 % 60

            t2 = int(timeblock.attrs.get('t2', 0))
            h2 = t2 // 60
            m2 = t2 % 60

            if hour_12:
                a1 = "AM" if h1 < 12 else "PM"
                h1 = h1 % 12
                if h1 == 0:
                    h1 = 12

                a2 = "AM" if h2 < 12 else "PM"
                h2 = h2 % 12
                if h2 == 0:
                    h2 = 12

                time_str = f"{h1:02d}:{m1:02d} {a1} to {h2:02d}:{m2:02d} {a2}"
            else:
                time_str = f"{h1:02d}:{m1:02d} to {h2:02d}:{m2:02d}"

            if time_str not in days_by_time:
                days_by_time[time_str] = []
            days_by_time[time_str].append(day_abbr)

        day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Unk"]
        time_parts = []
        for time_str, days in days_by_time.items():
            sorted_days = sorted(list(set(days)), key=lambda day: day_order.index(day) if day in day_order else len(day_order))
            time_parts.append(f"{', '.join(sorted_days)}: {time_str}")

        return "\n".join(time_parts) if time_parts else "TBA"

    def _get_colleges(self, term: str, course_names: list[str]) -> dict[str, str]:
        """Fetches college names for specified courses.

        Args:
            course_names: List of course subjects/catalog numbers (e.g., ["CSCI-381"]).
            term: The term ID (e.g., '3202530' for Fall 2024).

        Returns:
            A dictionary mapping course codes to their corresponding college names.
        """
        logging.debug(f"Fetching colleges for courses: {course_names}")
        url = "https://sb.cunyfirst.cuny.edu/api/string-to-filter"
        data = {"term": term, "itemnames": ",".join(course_names)}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        headers.update(self.headers)
        response = requests.post(url, cookies=self.class_data_cookies, headers=headers, data=data)
        response.raise_for_status()
        course_college_map = {course['cnKey']: course['va'] for course in response.json() if 'cnKey' in course}
        return course_college_map

    def _get_term(self) -> dict:
        """Fetches available terms from the criteria page.

        Parses JavaScript data embedded in the page to get term IDs and names.

        Returns:
            A dictionary mapping term IDs (str) to term details (dict with 'name' and 'enrollable').
        """
        logging.debug("Fetching available terms...")

        if self.terms:
            return self.terms

        url = "https://sb.cunyfirst.cuny.edu/criteria.jsp"
        try:
            response = requests.get(url, cookies=self.class_data_cookies, headers=self.headers)
            response.raise_for_status()

            js_data_str = response.text.split("return EE.initEntrance(")[1].split(");")[0]
            term_json = json.loads(js_data_str)

            term_map = {}
            for term_id, term_data in term_json.items():
                term_map[term_id] = {
                    "name": term_data.get('name', 'Unknown Term'),
                    "enrollable": term_data.get('enrollable', False)
                }
            logging.debug(f"Found terms: {term_map}")
            return term_map
        except (requests.exceptions.RequestException, IndexError, json.JSONDecodeError, KeyError) as e:
            logging.error(f"Failed to get or parse terms: {e}")
            return {}

    @backoff.on_exception(
        backoff.expo,
        Exception,
        max_tries=2,
        on_backoff=lambda details: CUNY.login(details['args'][0], force_refresh=True)
    )
    def get_class_data(self, term: str, course_names: list[str], course_codes: list[str]) -> list[dict]:
        """Fetches class section data for specified courses in a given term.

        Uses the cookies obtained during login. Retries with re-login if an exception occurs
        (likely due to expired session/cookies).

        Args:
            term: The term ID (e.g., '3202530' for Fall 2024).
            course_names: List of course subjects/catalog numbers (e.g., ["CSCI-381"]).
                         The API seems to use this format for lookup.
            course_codes: List of specific class section codes (e.g., ["49509"]).
                         Used to filter the results to only these sections.

        Returns:
            A list of dictionaries, each representing a class section with details like
            instructor, time, seats, etc. Returns an empty list if no matching sections
            are found or an error occurs after retries.
        """
        logging.debug(f"Getting class data for courses {course_names} (sections {course_codes}) in term {term}...")

        if not self.class_data_cookies:
            logging.error("Cannot get class data: Login required (no API cookies).")
            self.login()
            if not self.class_data_cookies:
                logging.error("Login attempt failed, cannot proceed to get class data.")
                return []

        parameters = {
            "term": term
        }
        parameters.update(self._nWindow())
        course_college_map = self._get_colleges(term, course_names)

        for index, course in enumerate(course_names):
            if course not in course_college_map:
                continue

            parameters[f"course_{index}_0"] = course
            parameters[f"va_{index}_0"] = course_college_map[course]

        logging.debug(f"Requesting class data with parameters: {parameters}")
        try:
            response = requests.get(
                self.class_data_url,
                verify=False,
                params=parameters,
                cookies=self.class_data_cookies,
                headers=self.headers
            )
            response.raise_for_status()
            logging.debug(f"Class data request status code: {response.status_code}")

            if "Oops, you must log into this application before loading that link." in response.text:
                logging.warning("Session likely expired based on response text.")
                raise Exception("Cookies likely expired.")

            class_data = []
            soup = bs4.BeautifulSoup(response.text, "html.parser")

            all_timeblocks = soup.find_all("timeblock")
            timeblocks_map = {tb.attrs.get('id'): tb for tb in all_timeblocks if tb.attrs.get('id')}

            for course_section in soup.find_all("block"):
                section_code = course_section.attrs.get('key')
                if section_code in course_codes:
                    parent_course = course_section.find_parent("course")
                    college = parent_course.parent.find("campus").attrs.get('v', 'N/A')
                    course_number = parent_course.attrs.get('key', 'N/A') if parent_course else 'N/A'

                    timeblock_ids = course_section.attrs.get('timeblockids', '').split(",")
                    valid_timeblock_ids = [tid for tid in timeblock_ids if tid]

                    try:
                        waitlist_cap = int(course_section.attrs.get('wc', 0))
                        waitlist_students = int(course_section.attrs.get('ws', 0))
                        max_enrollment = int(course_section.attrs.get('me', 0))
                        open_seats_val = int(course_section.attrs.get('os', 0))

                        waitlist_available = waitlist_cap - waitlist_students
                        seats_available = open_seats_val
                        is_open = waitlist_students > 0 or seats_available > 0
                    except ValueError:
                        logging.warning(f"Could not parse seat/waitlist numbers for section {section_code}")
                        waitlist_str = "Err/Err"
                        seats_str = "Err/Err"
                        available_str = "❓UNKNOWN"
                    else:
                        waitlist_str = f"{waitlist_available}/{waitlist_cap}"
                        seats_str = f"{max_enrollment - seats_available}/{max_enrollment}"
                        available_str = "🟩 POTENTIALLY OPEN" if is_open else "🟥 CLOSED"

                    class_data.append({
                        "Course Number": course_number,
                        "Course Code": section_code,
                        "Term": self.terms[term]["name"],
                        "College": college,
                        "Instructor": course_section.attrs.get('teacher', 'N/A'),
                        "Time": self._build_time(valid_timeblock_ids, timeblocks_map),
                        "Waitlist": waitlist_str,
                        "Seats": seats_str,
                        "Available": available_str
                    })
            logging.debug(f"Retrieved class data: {class_data}")
            return class_data

        except requests.exceptions.RequestException as e:
            logging.error(f"HTTP error during class data fetch: {e}")
            raise Exception(f"Request failed: {e}") from e
        except (AttributeError, KeyError, bs4.FeatureNotFound, ValueError) as e:
            logging.error(f"Error parsing class data response: {e}")
            return []
        except Exception as e:
            logging.error(f"An unexpected error occurred in get_class_data: {e}")
            raise e

    def login(self, force_refresh: bool = False):
        """Executes the complete CUNYfirst login sequence.

        Args:
            force_refresh: If True, forces the login process even if cookies seem to exist.
                           Used by the backoff mechanism on retries.
        """
        if not force_refresh and self.class_data_cookies:
            logging.debug("Valid API cookies exist. Skipping login.")
            return

        try:
            logging.info("Starting CUNY Login Process...")
            self._step_one()
            self._step_two()
            self._step_three()
            self._step_four()
            self._step_five()
            self._step_six()
            if self.class_data_cookies:
                logging.info("Login successful, API cookies obtained.")
            else:
                logging.error("Login process completed, but API cookies were not set.")
        except requests.exceptions.RequestException as e:
            logging.error(f"An HTTP error occurred during the login process: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logging.error(f"Response Status: {e.response.status_code}")
        except Exception as e:
            logging.error(f"An unexpected error occurred during login: {e}")


if __name__ == "__main__":
    CONFIG_FILE = "config.yaml"
    username = None
    password = None
    discord_webhook_url = None

    load_dotenv()

    username = os.getenv('CUNY_USERNAME')
    password = os.getenv('CUNY_PASSWORD')
    discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    logging.info("Loaded credentials using python-dotenv")

    if not username or not password or not discord_webhook_url:
        logging.error("Error: 'USERNAME' or 'PASSWORD' or 'DISCORD_WEBHOOK_URL' not found in the .env file or environment variables.")
        exit(1)

    cuny_client = CUNY(username.lower(), password)
    cuny_client.login()

    if not cuny_client.class_data_cookies:
        logging.error("Login failed. Cannot retrieve class data.")
        exit(1)

    logging.info("Fetching available terms...")
    terms = cuny_client._get_term()

    class_data = []
    course_names = os.getenv('COURSE_NAMES').split(',')
    course_codes = os.getenv('COURSE_CODES').split(',')

    if not course_names or not course_codes:
        logging.error("Error: 'COURSE_NAMES' or 'COURSE_CODES' not found in the .env file or environment variables.")
        exit(1)

    for term_id, term_data in terms.items():
        if term_data["enrollable"]:
            logging.info(f"Fetching class data for term {term_data['name']}...")
            class_data.extend(cuny_client.get_class_data(
                term=term_id,
                course_names=course_names,
                course_codes=course_codes
            ))

    course_map = {course_data["Course Code"]: course_data for course_data in class_data}
    for course_code in course_codes:
        if course_code not in course_map:
            embed = {
                "title": f"❌ Class Not Found: {course_code}",
                "description": "The specified course code could not be found in the fetched data for any enrollable term. Please double-check the code.",
                "color": 0xFF0000
            }
            payload = {
                "embeds": [embed]
            }
            requests.post(discord_webhook_url, json=payload)
            time.sleep(1)
            continue

        course_info = course_map[str(course_code)]
        if course_info["Available"] == "🟩 POTENTIALLY OPEN":
            embed = {
                "title": f"✅ Class Potentially Open: {course_info['Course Number']} ({course_code}) {course_info['College']}",
                "description": f"Term: {course_info['Term']}",
                "color": 0x00FF00,
                "fields": [
                    {"name": "Instructor", "value": course_info['Instructor'], "inline": True},
                    {"name": "Seats", "value": course_info['Seats'], "inline": True},
                    {"name": "Waitlist", "value": course_info['Waitlist'], "inline": True},
                    {"name": "Time", "value": course_info['Time'], "inline": True},
                ]
            }
            payload = {
                "content": f"<@{os.getenv('DISCORD_USER_ID', '')}> Class **{course_info['Course Number']} ({course_code})** might be open!",
                "embeds": [embed]
            }
            requests.post(discord_webhook_url, json=payload)
