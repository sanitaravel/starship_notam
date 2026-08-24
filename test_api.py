import requests
import json

URL = "https://notams.aim.faa.gov/notamSearch/search"

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "origin": "https://notams.aim.faa.gov",
    "referer": "https://notams.aim.faa.gov/notamSearch/nsapp.html",
}

def test_notam_search(keyword="SPACEX"):
    payload = {
        "searchType": 4,
        "freeFormText": keyword,
        "offset": 0,
        "radius": 10,
        "sortColumns": "5 false",
        "sortDirection": "true",
        "notamsOnly": "false",
        "recaptchaToken": "",  # important test: try empty first
    }

    response = requests.post(URL, headers=HEADERS, data=payload, timeout=30)

    print("Status:", response.status_code)
    print("Content-Type:", response.headers.get("content-type"))

    data = response.json()

    print("\nTotal NOTAMs:", data.get("totalNotamCount"))
    print("Returned:", len(data.get("notamList", [])))

    # print first NOTAM
    if data.get("notamList"):
        first = data["notamList"][0]
        print("\n--- SAMPLE NOTAM ---")
        print("Number:", first.get("notamNumber"))
        print("Facility:", first.get("facilityDesignator"))
        print("Start:", first.get("startDate"))
        print("End:", first.get("endDate"))
        print("Message:\n", first.get("icaoMessage"))

    return data


if __name__ == "__main__":
    test_notam_search("SPACEX")