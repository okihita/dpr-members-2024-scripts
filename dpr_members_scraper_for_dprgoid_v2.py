import json
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# --- Add Selenium Imports ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager # Optional: Helps manage driver install
from selenium.common.exceptions import WebDriverException
# Choose options based on browser (example using Chrome)
from selenium.webdriver.chrome.options import Options


BASE_URL = 'https://en.dpr.go.id/anggota/'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'DNT': '1',
}

REQUEST_DELAY_SECONDS = 2
OUTPUT_FILENAME = 'dpr_members_v2.json'  # <--- Define output file name

FACTION_NAMES_ID = {
    'Great Indonesia Movement Party Faction': 'Gerindra',
    'Democrat Party Faction': 'Demokrat',
    'Indonesian Democratic Party of Struggle Faction': 'PDIP',
    'Golkar Party Faction': 'Golkar',
    'Prosperous Justice Party Faction': 'PKS',
    'National Mandate Party Faction': 'PAN',
    'National Democrat Party Faction': 'NasDem',
    'National Awakening Party Faction': 'PKB'
}
REQUEST_TIMEOUT_SECONDS = 15 # Keep increased timeout


def setup_driver():
    """Sets up the Selenium WebDriver."""
    options = Options()
    # --- Common options to make Selenium look less like automation ---
    options.add_argument('--headless') # Run headless (no GUI window) - WAFs sometimes detect headless, remove if causing issues
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument("--disable-blink-features=AutomationControlled") # Try to hide automation flags
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    # Set a realistic User-Agent (Selenium often uses its own, but setting it can help)
    options.add_argument(f'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36') # Example UA

    print("Initializing WebDriver...")
    try:
        # Option 1: Use webdriver-manager (install with pip install webdriver-manager)
        # Automatically downloads and manages the driver
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        # Option 2: Specify path to downloaded driver explicitly
        # driver_path = '/path/to/your/chromedriver' #<-- Replace with actual path if not using webdriver-manager
        # service = ChromeService(executable_path=driver_path)
        # driver = webdriver.Chrome(service=service, options=options)

        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})") # More anti-detection
        print("WebDriver initialized.")
        return driver
    except WebDriverException as e:
        print(f"Error initializing WebDriver: {e}")
        print("Ensure WebDriver is installed and accessible (check path or use webdriver-manager).")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during WebDriver setup: {e}")
        return None


def fetch_html_with_selenium(driver, url, wait_time=10):
    """Fetches HTML using Selenium, waiting for page load."""
    if not driver:
        return None
    print(f"Attempting to fetch {url} using Selenium...")
    try:
        driver.get(url)
        # Wait a bit for potential JS rendering or redirects
        time.sleep(wait_time) # Adjust wait time as needed
        html_content = driver.page_source
        print(f"Successfully fetched content from {url}")
        return html_content
    except WebDriverException as e:
        print(f"Selenium error fetching {url}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during Selenium fetch: {e}")
        return None


def parse_members(individual_row_html_content):
    if not individual_row_html_content:
        return []

    soup = BeautifulSoup(individual_row_html_content, 'html.parser')
    dpr_members_data = []
    member_rows = soup.select('tbody tr')  # Structure as per 06 Apr 2025
    unique_factions = set()

    if not member_rows:
        print('No members found. Wrong HTML selector?')

    for row in member_rows:
        cells = row.find_all('td')

        # Basic check: Ensure we have enough cells to avoid IndexError
        if len(cells) < 4:
            # print(f"Skipping row, expected at least 4 cells, found {len(cells)}")
            continue  # Skip malformed rows

        try:
            # --- Extract data based on the provided HTML structure ---
            member_id = cells[0].text.strip()

            # Cell 1: Image and Profile Link (td class="hidden-xs")
            profile_link_tag = cells[1].find('a')
            relative_profile_url = profile_link_tag['href'] if profile_link_tag else None
            profile_url = urljoin(BASE_URL, relative_profile_url) if relative_profile_url else 'N/A'

            image_tag = cells[1].find('img')
            image_url = image_tag['src'] if image_tag else 'N/A'

            # Cell 2: Name, Faction, District, Email
            name_link_tag = cells[2].find('a')
            name = name_link_tag.text.strip() if name_link_tag else 'N/A'

            # Get all contents of the cell, filter out the link, handle <br>
            cell_contents = cells[2].contents
            other_info = []
            for content in cell_contents:
                if isinstance(content, str):  # Handle text nodes directly
                    text = content.strip()
                    if text:
                        other_info.append(text)
                elif content.name == 'br':  # Handle <br> tags as separators conceptually
                    continue  # Usually implies a new line / piece of info follows
                # Add checks for other tags if necessary

            # Assign based on expected order after the name link + <br> tags
            faction_name_english = other_info[0] if len(other_info) > 0 else 'N/A'
            faction_name_id = FACTION_NAMES_ID.get(faction_name_english)

            district = other_info[1] if len(other_info) > 1 else 'N/A'
            email_raw = other_info[2] if len(other_info) > 2 else 'N/A'
            email = email_raw.replace('[at]', '@')  # Clean email

            # Cell 3: Commission
            roles = list(cells[3].stripped_strings)

            # --- Structure the Data ---
            dpr_members_data.append({
                'id': member_id,
                'name': name,
                'faction': faction_name_id,
                'district': district,
                'email': email,
                'roles': roles,
                'profile_url': profile_url,
                'image_url': image_url
            })

        except (AttributeError, IndexError, TypeError) as e:
            print(f"Error parsing a row: {e} - skipping row. HTML content might vary.")

    return dpr_members_data


if __name__ == '__main__':

    driver = setup_driver()
    if not driver:
        print("Exiting due to WebDriver setup failure.")
        exit()


    members_html = fetch_html_with_selenium(driver, BASE_URL, wait_time=5) # Shorter wait for list?


    if members_html:
        dpr_members = parse_members(members_html)

        # --- Add JSON Saving Logic Here ---
        if dpr_members:  # Only save if members were found
            print(f"\nSaving {len(dpr_members)} members to {OUTPUT_FILENAME}...")
            try:
                # Use 'with' to ensure the file is closed properly
                # Use encoding='utf-8' to handle various characters
                # Use ensure_ascii=False for non-English characters if needed
                # Use indent=4 for pretty-printing the JSON
                with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
                    json.dump(dpr_members, f, ensure_ascii=False, indent=4)
                print(f"Successfully saved data to {OUTPUT_FILENAME}")
            except IOError as e:
                print(f"Error saving data to {OUTPUT_FILENAME}: {e}")
            except Exception as e:
                print(f"An unexpected error occurred during saving: {e}")
        else:
            print("\nNo member data found or extracted, skipping save.")
        # --- End JSON Saving Logic ---

    else:
        print("\nFailed to fetch HTML, cannot parse members.")

    # --- Clean up WebDriver ---
    if driver:
        print("Closing WebDriver...")
        driver.quit()

    print("\nFINISH")
