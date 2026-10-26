import sys
import requests

URL = "https://playriftbound.com/en-us/news/announcements/product-drawing-faq/"

# Use a standard browser User-Agent to prevent basic blocks
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

def check_site():
    try:
        print(f"Visiting {URL}...")
        response = requests.get(URL, headers=HEADERS, timeout=15)
        
        print(f"HTTP Status Code: {response.status_code}")

        # Check for standard success
        if response.status_code == 200:
            page_text = response.text.lower()
            
            # Check for common blocking indicators (Cloudflare / WAF challenges)
            block_indicators = ["access denied", "cloudflare", "checking your browser", "attention required"]
            if any(indicator in page_text for indicator in block_indicators) and "product-drawing-faq" not in page_text:
                print("❌ Error: The site appears to be blocking requests or showing a challenge page.")
                sys.exit(1)
            else:
                print("Success: The site rendered correctly and returned 200.")
                sys.exit(0)
        else:
            print(f"Error: Received unexpected HTTP status code: {response.status_code}")
            sys.exit(1)

    except requests.exceptions.RequestException as e:
        print(f"Error: Failed to connect to the site. Exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    check_site()
