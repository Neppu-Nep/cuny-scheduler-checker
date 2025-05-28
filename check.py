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

# Change logging.INFO to logging.DEBUG for more detailed output
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class CUNYException(Exception):
    pass


class CUNY:

    main_url = "https://cssa.cunyfirst.cuny.edu/psc/cnycsprd/EMPLOYEE/SA/s/WEBLIB_VSB.TRANSFER_FUNCS.FieldFormula.IScript_RedirectVSBuilder?INSTITUTION=LAG01"
    auth_url = "https://ssologin.cuny.edu/oam/server/auth_cred_submit"

    page_url = "https://sb.cunyfirst.cuny.edu/criteria.jsp"
    class_data_url = "https://sb.cunyfirst.cuny.edu/api/class-data"
    search_url = "https://sb.cunyfirst.cuny.edu/api/string-to-filter"
    enrollment_state_url = "https://sb.cunyfirst.cuny.edu/api/getEnrollmentState"
    enroll_options_url = "https://sb.cunyfirst.cuny.edu/api/enroll-options"
    perform_action_url = "https://sb.cunyfirst.cuny.edu/api/perform-action"

    def __init__(self, username, password):
        """Initializes the CUNY client with credentials."""
        logging.debug("Initializing CUNY client...")
        self.username = username
        self.password = password
        self.headers = {"User-Agent": "CUNY/1.0"}

        self.cookies = {}
        self.terms = None

        self._setup()
        logging.debug("CUNY client initialized.")

    def _setup(self):
        self._login()
        self.terms = self._get_term()

    @backoff.on_exception(
        backoff.expo,
        requests.exceptions.RequestException,
        max_tries=3
    )
    def _get(self, url: str, params: dict = None, headers: dict = None, **kwargs) -> requests.Response:
        """Performs a GET request with the specified URL and parameters."""
        logging.debug(f"GET request to {url} with params {params}")
        headers = headers or {}
        headers.update(self.headers)
        response = requests.get(url, params=params, cookies=self.cookies, headers=headers, allow_redirects=False, **kwargs)
        response.raise_for_status()
        return response
    
    @backoff.on_exception(
        backoff.expo,
        requests.exceptions.RequestException,
        max_tries=3
    )
    def _post(self, url: str, data: dict = None, headers: dict = None, **kwargs) -> requests.Response:
        """Performs a POST request with the specified URL and data."""
        logging.debug(f"POST request to {url} with data {data}")
        headers = headers or {}
        headers.update(self.headers)
        response = requests.post(url, data=data, cookies=self.cookies, headers=headers, allow_redirects=False, **kwargs)
        response.raise_for_status()
        return response
    
    def _check_session_text(self, text: str) -> None:
        if "Oops, you must log into this application before loading that link." in text:
            # raise CUNYException("Session expired. Please log in again.")
            logging.error("Session expired. Please log in again.")
            exit(0)

    def _nWindow(self):
        """Generates time-based parameters required for the class data API request."""
        t = math.floor(time.time() / 60) % 1000
        e = t % 3 + t % 39 + t % 42
        logging.debug(f"_nWindow generated: t={t}, e={e}")
        return {"t": t, "e": e}
    
    def _get_session_id(self):
        """Initializes the session ID for the CUNYfirst login for enrollment later on."""
        logging.debug("Getting session ID...")
        response = self._get(self.main_url, verify=False)
        return response.cookies.get_dict()
    
    def _login(self):
        """Login to CUNYfirst using the provided username and password."""
        session_cookies = self._get_session_id()

        logging.debug("Executing Step 1: Initial VSB redirect...")
        s1_response = self._get(self.main_url, verify=False)
        self.cookies.update(s1_response.cookies.get_dict())

        if s1_response.headers.get('Location') == "http://portaldown.cuny.edu/cunyfirst":
            logging.error("CUNY is down right now. Skipping login.")
            return
        
        logging.debug("Executing Step 2: Redirect to SSO login...")
        s2_response = self._get(s1_response.headers['Location'])
        self.cookies.update(s2_response.cookies.get_dict())

        logging.debug("Executing Step 3: Submitting credentials...")
        s3_response = self._post(self.auth_url, data={"username": self.username, "password": self.password})
        self.cookies.update(s3_response.cookies.get_dict())

        logging.debug("Executing Step 4: Following post-authentication redirect...")
        s4_response = self._get(s3_response.headers['Location'], verify=False)
        self.cookies = s4_response.cookies.get_dict()

        logging.debug("Executing Step 5: Re-accessing main VSB URL...")
        s5_response = self._get(self.main_url, verify=False)
        self.cookies.update(s5_response.cookies.get_dict())
        
        logging.debug("Executing Step 6: Accessing VSB URL variation for API cookies...")
        s6_response = self._get(self.main_url + "&", verify=False)
        self.cookies.update(s6_response.cookies.get_dict())

        logging.debug("Executing Step 7: Refreshing WEB Session Cookie...")
        s7_response = self._get(self.page_url, verify=False)

        self.cookies = s6_response.cookies.get_dict()
        self.cookies.update(session_cookies)
        self.cookies.update(s7_response.cookies.get_dict())

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
        """Constructs a human-readable time string from timeblock data."""
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

    @backoff.on_exception(
        backoff.expo,
        CUNYException,
        max_tries=2,
        on_backoff=_login
    )
    def _get_colleges(self, term: str, course_names: list[str]) -> dict[str, str]:
        """Fetches college data for specified courses."""
        logging.debug(f"Fetching colleges for courses: {course_names}")
        data = {"term": term, "itemnames": ",".join(course_names)}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = self._post(self.search_url, data=data, headers=headers)
        self._check_session_text(response.text)
        course_college_map = {course['cnKey']: course['va'] for course in response.json() if 'cnKey' in course}
        logging.debug(f"Course to college mapping: {json.dumps(course_college_map, indent=2)}")

        return course_college_map

    @backoff.on_exception(
        backoff.expo,
        CUNYException,
        max_tries=2,
        on_backoff=_login
    )
    def _get_term(self) -> dict:
        """Fetches available terms from the criteria page."""
        logging.debug("Fetching available terms...")

        if self.terms:
            return self.terms

        response = self._get(self.page_url)
        self._check_session_text(response.text)
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

    @backoff.on_exception(
        backoff.expo,
        CUNYException,
        max_tries=2,
        on_backoff=_login
    )
    def get_enrollment_status(self, term: str, course_name: str) -> bool:
        """Fetches the enrollment status for a given term."""
        logging.debug(f"Fetching enrollment status for term {term}...")
        response = self._get(self.enrollment_state_url, params={"term": term})
        self._check_session_text(response.text)
        enrollment_data = response.json()
        enrolled_courses = [course["cnKey"] for course in enrollment_data["cnfs"]]
        logging.debug(f"Enrolled courses: {enrolled_courses}")
        return course_name in enrolled_courses

    def try_enroll(self, term: str, selection_key: str, selection_va: str) -> bool:
        """Attempts to enroll in a class section using the provided selection key and VA."""
        logging.debug(f"Attempting to enroll in class with selection key {selection_key} and VA {selection_va}...")

        # T = Term (Not in shopping cart)
        # C = Shopping Cart
        # E = Enroll

        # Required to be able to perform the action later on
        self._get(self.enroll_options_url, params={"statea": "T", "keya": selection_key, "stateb": "E", "keyb": selection_key})

        # statea0/keya0/vaa0 -> Initial enrollment state (T) and key/VA for the class
        # stateb0/keyb0/vab0 -> Desired enrollment state (E) and key/VA for the class
        # Multiple classes would be statea1/keya1/vaa1, stateb1/keyb1/vab1, etc.
        params = {
            "statea0": "T",
            "keya0": selection_key,
            "vaa0": selection_va,
            "stateb0": "E",
            "keyb0": selection_key,
            "vab0": selection_va,
            "schoolTermId": term
        }
        response = self._get(self.perform_action_url, params=params)
        logging.debug(f"Enrollment attempt response: {response.text}")
        return True if response.status_code == 200 and "Failed" not in response.text else False

    @backoff.on_exception(
        backoff.expo,
        CUNYException,
        max_tries=2,
        on_backoff=_login
    )
    def get_class_data(self, term: str, course_names: list[str], course_codes: list[str]) -> list[dict]:
        """Fetches class section data for specified courses in a given term."""
        logging.debug(f"Getting class data for courses {course_names} (sections {course_codes}) in term {term}...")

        parameters = {
            "term": term
        }
        parameters.update(self._nWindow())
        course_college_map = self._get_colleges(term, course_names)
        
        if not course_college_map:
            logging.warning("No valid courses found for the specified term.")
            return []

        for index, course in enumerate(course_names):
            if course not in course_college_map:
                continue

            parameters[f"course_{index}_0"] = course
            parameters[f"va_{index}_0"] = course_college_map[course]

        response = self._get(self.class_data_url, params=parameters, verify=False)
        self._check_session_text(response.text)

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
                    available = -1
                else:
                    waitlist_str = f"{waitlist_available}/{waitlist_cap}"
                    seats_str = f"{max_enrollment - seats_available}/{max_enrollment}"
                    available = 1 if is_open else 0
                
                enrolled = False
                if available == 1:
                    logging.debug(f"Class {course_number} ({section_code}) is potentially open. Attempting to enroll...")
                    selection_block = course_section.find_parent("selection")
                    selection_key = selection_block.attrs.get('key', 'N/A')
                    selection_va = selection_block.attrs.get('va', 'N/A')

                    if self.get_enrollment_status(term, course_number):
                        logging.debug(f"Already enrolled in {course_number} ({section_code})")
                        continue

                    if self.try_enroll(term, selection_key, selection_va):
                        logging.debug(f"Successfully enrolled in {course_number} ({section_code})")
                        enrolled = True
                    else:
                        logging.debug(f"Failed to enroll in {course_number} ({section_code})")

                class_data.append({
                    "Course Number": course_number,
                    "Course Code": section_code,
                    "Term": self.terms[term]["name"],
                    "College": college,
                    "Instructor": course_section.attrs.get('teacher', 'N/A'),
                    "Time": self._build_time(valid_timeblock_ids, timeblocks_map),
                    "Waitlist": waitlist_str,
                    "Seats": seats_str,
                    "Available": available,
                    "enrolled": enrolled
                })
        logging.debug(f"Retrieved class data: {class_data}")
        return class_data


if __name__ == "__main__":
    CONFIG_FILE = "config.yaml"
    username = None
    password = None
    discord_webhook_url = None

    load_dotenv()

    username = os.getenv('CUNY_USERNAME')
    password = os.getenv('CUNY_PASSWORD')
    discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    discord_user_id = os.getenv('DISCORD_USER_ID', '')
    logging.info("Loaded credentials using python-dotenv")

    if not username or not password or not discord_webhook_url:
        logging.error("Error: 'USERNAME' or 'PASSWORD' or 'DISCORD_WEBHOOK_URL' not found in the .env file or environment variables.")
        exit(1)

    cuny_client = CUNY(username.lower(), password)

    if not cuny_client.cookies:
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
        if course_info["Available"] == 1 and not course_info["enrolled"]:
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
                "content": f"<@{discord_user_id}> Class **{course_info['Course Number']} ({course_code})** might be open!",
                "embeds": [embed]
            }
            requests.post(discord_webhook_url, json=payload)
            logging.debug(f"Sent Discord notification for course {course_code}.")
        elif course_info["enrolled"]:
            embed = {
                "title": f"✅ Successfully Enrolled: {course_info['Course Number']} ({course_code})",
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
                "content": f"<@{discord_user_id}> Successfully enrolled in **{course_info['Course Number']} ({course_code})**!",
                "embeds": [embed]
            }
            requests.post(discord_webhook_url, json=payload)
            logging.debug(f"Sent Discord notification for course {course_code}.")
