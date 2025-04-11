import json
import urllib

import requests
import os
from urllib.parse import urlparse, urlunparse
import time
from dotenv import load_dotenv
import webbrowser

# --- Configuration ---
load_dotenv()
API_KEY = os.environ.get("GOOGLE_API_KEY")  # Get this from your Cloud console
CX_ID = os.environ.get("GOOGLE_CX_ID")  # Enable Custom JSON Search, then get the CX code

if not API_KEY or not CX_ID:
    print("ERROR: Google API Key or CX ID not set.")
    print("Please set GOOGLE_API_KEY and GOOGLE_CX_ID environment variables or edit the script (insecure).")
    exit()

SOURCE_FILENAME = 'dpr_members_socials.json'  # Save to a new file initially

PLATFORMS = {
    "instagram": "instagram.com",
    "twitter": "twitter.com",  # Consider adding x.com as well or handling redirects
    "tiktok": "tiktok.com",
    "facebook": "facebook.com",
    "youtube": "youtube.com",
}

MANUAL_GOOGLE_SEARCH_API_URL = "https://www.google.com/search?q="
MANUAL_TWITTER_SEARCH_API_URL = "https://x.com/search?q="
MANUAL_TIKTOK_SEARCH_API_URL = "https://www.tiktok.com/search?q="
MANUAL_FACEBOOK_SEARCH_API_URL = "https://www.facebook.com/search/top/?q="
MANUAL_YOUTUBE_SEARCH_API_URL = "https://www.youtube.com/results?search_query="


SEARCH_API_URL = "https://www.googleapis.com/customsearch/v1"
REQUEST_DELAY_SECONDS = 1.1  # Add delay between API calls to avoid rate limits


# --- Helper Functions ---

def load_json_file(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Input file not found: {filename}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {filename}: {e}")
        return None


def save_update_json_file(filename, data):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"Data successfully saved to {filename}") # Optional: confirmation per save
        return True
    except IOError as e:
        print(f"Error saving data to {filename}: {e}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred saving data: {e}")
        return False


def call_google_search_api(query, api_key, cx_id, num_results=10):
    params = {
        'key': api_key,
        'cx': cx_id,
        'q': query,
        'num': num_results
    }
    try:
        response = requests.get(SEARCH_API_URL, params=params, timeout=15)
        response.raise_for_status()  # Raise HTTPError for bad responses (4XX or 5XX)
        return response.json()
    except requests.exceptions.Timeout:
        print("Error: Google Search API request timed out.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error during Google Search API request: {e}")
        # Check for specific status codes if needed (e.g., 429 Too Many Requests)
        if e.response is not None:
            print(f"API Response Status: {e.response.status_code}")
            print(f"API Response Body: {e.response.text[:500]}...")  # Print snippet of error
        return None


def filter_potential_profile_link(link, platform_domain):
    """
    Filters a URL to check if it looks like a main profile/page/channel link
    and not a link to a specific post/video/story.
    Returns the cleaned URL if valid, otherwise None.
    *** This logic needs refinement and is platform-specific. May change with time. ***
    """
    try:
        parsed = urlparse(link)
        # Basic check: Ensure scheme and correct domain
        if not parsed.scheme or parsed.netloc.lower().replace('www.', '') != platform_domain:
            return None

        # Normalize path, remove trailing slash
        path = parsed.path.rstrip('/')
        # Remove query params and fragments for most checks initially
        cleaned_url = urlunparse((parsed.scheme, parsed.netloc, path, '', '', ''))

        # --- Platform-Specific Rules (EXAMPLES - NEEDS THOROUGH TESTING/REFINEMENT) ---
        if platform_domain == "instagram.com":
            # Allow root, /username/. Deny /p/, /reel/, /stories/
            path_parts = path.strip('/').split('/')
            if len(path_parts) > 0:  # Basic username check, at least one path
                if path_parts[0] not in ['p', 'reels', 'stories', 'explore']:  # Deny specific post types etc.
                    return f"{parsed.scheme}://{platform_domain}/{path_parts[0]}" # Custom final combination


        elif platform_domain == "twitter.com" or platform_domain == "x.com":  # Handle both
            # Allow /username. Deny /status/, /i/, /explore/
            path_parts = path.strip('/').split('/')
            if len(path_parts) > 0 and path_parts[0] != '':
                if path_parts[0] not in ['i', 'status', 'explore', 'home', 'notifications', 'messages']:
                    return f"{parsed.scheme}://{platform_domain}/{path_parts[0]}"  # Custom final combination

        elif platform_domain == "tiktok.com":
            # Allow /@username. Deny /video/, /music/
            path_parts = path.strip('/').split('/')
            if len(path_parts) > 0:
                if path_parts[0].startswith('@'):
                    return f"{parsed.scheme}://{platform_domain}/{path_parts[0]}"  # Custom final combination
                # Sometimes links omit the '@', check for username-like structure
                elif path_parts[0] != '' and path_parts[0] not in ['video', 'music', 'explore', 'discover', 'tag']:  # Ensure it's not known content path
                    # Assume it might be a profile, needs user check
                    return f"{parsed.scheme}://{platform_domain}/{path_parts[0]}"  # Custom final combination

        elif platform_domain == "facebook.com":
            # Allow /username, /pages/name/id, /groups/id. Deny /posts/, /videos/, /photos/, /story.php, watch/
            # This is complex due to many FB URL formats. Be less strict maybe.
            path_parts = path.strip('/').split('/')
            if not any(part in path for part in
                       ['/posts', '/videos', '/photos', '/story.php', '/watch', '/events', '/notes', '/sharer']):
                # Basic check: allow if it doesn't contain obvious content paths
                # More robust checks needed for username vs page vs group structure if required
                if len(path_parts) > 0 and path_parts[0] not in ['login.php', 'signup.php', 'help', 'settings', 'ajax',
                                                                 'dialog', 'photo.php']:  # Avoid non-profile paths
                    # Accept links with query parameters if they look like profiles (e.g., profile.php?id=...)
                    if 'profile.php' in path and 'id=' in parsed.query:
                        return link  # Keep query params for profile.php?id=
                    elif not parsed.query or 'sk=' not in parsed.query:  # Avoid view-specific query params
                        return cleaned_url
                elif len(path_parts) == 0 or path_parts[0] == '':  # Allow root domain
                    return cleaned_url

        elif platform_domain == "youtube.com":
            # Allow /channel/ID, /c/Name, /@Handle. Deny /watch, /shorts/, /feed/, /results/
            path_parts = path.strip('/').split('/')
            if len(path_parts) >= 1:
                first_part = path_parts[0]
                if first_part == 'channel': # YouTube channel
                    return cleaned_url
                elif first_part == 'c': # YT community
                    return cleaned_url
                elif first_part.startswith('@'): # YT username
                    return cleaned_url
                # Sometimes user profiles appear like youtube.com/user/username
                elif first_part == 'user' and len(path_parts) >= 2:
                    return cleaned_url
            elif not path or path == '/':  # Allow root channel link if it ever appears
                return cleaned_url

        # Default: If no specific rule matched or denied, return None
        return None

    except Exception as e:
        print(f"Warning: Error parsing or filtering URL '{link}': {e}")
        return None


# --- Main Workflow ---
if __name__ == "__main__":
    print("Starting Social Media Link Finder...")
    member_data = load_json_file(SOURCE_FILENAME)

    if member_data is None:
        exit()

    total_members = len(member_data)
    print(f"Loaded {total_members} members. Will save progress to {SOURCE_FILENAME}")

    for index, member in enumerate(member_data):
        member_name = member.get('name', 'Nama Tidak Terbaca')
        member_faction = member.get('faction', '')  # Get faction, default to empty string
        print(f"\n--- Processing Member {index + 1}/{total_members}: {member_name} ---")

        # Ensure 'socials' dictionary exists
        member.setdefault('socials', {})
        if member.get('socials'):
            print(f"  - This person already has saved socials object from the input JSON file.")
            continue

        webbrowser.open(f"{MANUAL_GOOGLE_SEARCH_API_URL}{member.get('name', 'Frieren')}", new=2, autoraise=False)
        for platform, domain in PLATFORMS.items():
            # Skip if platform link already exists for this member
            if platform in member['socials'] and member['socials'][platform]:
                print(f"  - Skipping {platform.title()} (already present: {member['socials'][platform]})")
                continue

            print(f"  - Searching for {platform.title()}...")

            # Construct search query
            query_parts = [f"site:{domain}", "dpr ri", member_name] # Customize this
            if platform == "tiktok":
                query_parts.append("-inurl:discover") # For TikTod, avoid "discover"/search links
            query = " ".join(filter(None, query_parts))  # Join non-empty parts
            print(f"  - Searching for {query}...")

            # Add delay before API call
            time.sleep(REQUEST_DELAY_SECONDS)

            search_results = call_google_search_api(query, API_KEY, CX_ID)

            potential_links = []
            unique_links = set()  # Avoid showing duplicate filtered links

            if search_results and 'items' in search_results:
                print(f"    > Found {len(search_results['items'])} raw results.")
                for item in search_results['items']:
                    link = item.get('link')[:100]
                    print(link)
                    if link:
                        filtered_link = filter_potential_profile_link(link, domain)
                        if filtered_link and filtered_link not in unique_links:
                            potential_links.append(filtered_link)
                            unique_links.add(filtered_link)
            elif search_results is None:
                print(f"    > API call failed for {platform.title()}. Skipping.")
                continue  # Skip to next platform if API failed
            else:
                print("    > No results found.")

            # User Selection
            selected_url = None
            print(f"    ? Potential {platform.title()} links found:")

            if len(potential_links) == 0:
                print(f"    > No potential profile links found after filtering for {platform.title()}.")
                print(f"    > Search manually: {MANUAL_GOOGLE_SEARCH_API_URL}{urllib.parse.quote_plus(query)}")
                webbrowser.open(f"{MANUAL_GOOGLE_SEARCH_API_URL}{urllib.parse.quote_plus(query)}", new=2, autoraise=False)

            else:
                for i, url in enumerate(potential_links):
                    print(f"      [{i + 1}] {url}")
                print(f"      > Verify manually: {MANUAL_GOOGLE_SEARCH_API_URL}{urllib.parse.quote_plus(query)}")
                webbrowser.open(f"{MANUAL_GOOGLE_SEARCH_API_URL}{urllib.parse.quote_plus(query)}", new=2, autoraise=False)

            while True:  # Loop for valid input
                user_choice = input(
                    f"      Enter the number of the correct link, (S)kip, (M)anual Entry, or Enter to skip: ").strip().lower()

                if user_choice == 's': # If user chooses to skip
                    print(f"    > Skipped {platform.title()}.")
                    break  # Exit input loop, go to next platform

                if user_choice == 'm':
                    selected_url = input(f"    > Input manually the url: ").strip().lower()
                    break

                try:
                    choice_index = int(user_choice) - 1
                    if 0 <= choice_index < len(potential_links):
                        selected_url = potential_links[choice_index]
                        print(f"    > Selected: {selected_url}")
                        break  # Exit input loop
                    else:
                        print("      Invalid number. Please try again.")

                except ValueError:
                    print("      Invalid input. Please enter a number, or 's' to skip, or 'm' to add manually.")

            # Store selected URL (even if None, store explicitly maybe? Or just skip?)
            if selected_url:
                member['socials'][platform] = selected_url
            # If you want to explicitly mark skipped platforms:
            elif not user_choice or user_choice == 's':
                member['socials'][platform] = None # Or leave the key absent

        # --- Save progress after each member ---
        if not save_update_json_file(SOURCE_FILENAME, member_data):
            print(f"CRITICAL: Failed to save progress after processing {member_name}. Exiting.")
            exit()  # Stop if saving fails

    print("\n--- Finished processing all members ---")
    print(f"Final data saved to {SOURCE_FILENAME}")
