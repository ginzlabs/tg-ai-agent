import pandas as pd
import re
from bs4 import BeautifulSoup
import sys
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os
from datetime import datetime
import requests
import logging

# Get logger but don't configure it - let parent application handle configuration
logger = logging.getLogger(__name__)

class WebPageParser:
    """
    A simplified class to process webpages and extract exchange rates using direct parsing.
    """

    def __init__(self, html_content):
        self.html_content = html_content

    def process_bestchange(self):
        """
        Processes a webpage if it contains 'bestchange' in the URL and extracts exchange rates.

        Returns:
            pd.DataFrame: A dataframe with columns 'Name' and 'Exchange Rate'.
        """
        exchange_data = []

        # Directly search for fields in the HTML content
        rate_matches = re.findall(r'<div class="fs">([0-9.]+)', self.html_content)
        name_matches = re.findall(r'<div class="ca".*?>(.*?)</div>', self.html_content)

        if len(rate_matches) != len(name_matches):
            logger.warning("Mismatch between rates and names. Some data may be missing.")

        for name, rate in zip(name_matches, rate_matches):
            exchange_data.append({
                'Name': name.strip(),
                'Exchange Rate': rate.strip()
            })

        # Check if any data was extracted
        if not exchange_data:
            raise ValueError("No exchange rate data found in the page.")

        # Convert to DataFrame
        return pd.DataFrame(exchange_data)

    def process_ftyields(self, region=''):
        """
        Processes Financial Times bond yields webpage and extracts yield data.

        Parameters:
            region (str): The region for which the yields are being processed

        Returns:
            pd.DataFrame: A dataframe with columns for Maturity, Yield, Today's Change, 
                         1 Week Ago, and 1 Month Ago.
        """
        try:
            # Parse HTML content using BeautifulSoup
            soup = BeautifulSoup(self.html_content, 'html.parser')
            
            # Find the yields table
            table = soup.find("table", class_="mod-ui-table mod-yields-app__panel-content mod-ui-table--freeze-pane")
            
            if not table:
                raise ValueError("Yields table not found in the page content")

            # Initialize lists to store data
            data = []
            
            # Extract rows
            rows = table.find_all("tr")[1:]  # Skip header row
            for row in rows:
                cols = row.find_all("td")
                if cols:
                    row_data = {
                        'Region': region,
                        'Maturity': cols[0].text.strip(),
                        'Yield': self._clean_percentage(cols[1].text.strip()),
                        'Today\'s Change': cols[2].text.strip(),
                        '1 Week Ago': self._clean_percentage(cols[3].text.strip()),
                        '1 Month Ago': self._clean_percentage(cols[4].text.strip())
                    }
                    data.append(row_data)

            # Convert to DataFrame
            df = pd.DataFrame(data)
            
            # Verify the data
            logger.info(f"Verification for {region}:")
            logger.info(f"Rows extracted: {len(df)}")
            if not df.empty:
                logger.info(f"First row: {df.iloc[0].to_dict()}")
            
            return df

        except Exception as e:
            logger.error(f"Error processing FT yields page: {str(e)}")
            raise

    def _clean_percentage(self, value):
        """Helper method to clean percentage values"""
        if not value:
            return None
        return value.replace('%', '').strip()

    def parse(self, url, region=''):
        """
        Determines the type of webpage and processes it accordingly.

        Parameters:
            url (str): The URL of the webpage.
            region (str): The region for yield data (for FT bonds page)

        Returns:
            pd.DataFrame: Processed data as a dataframe.
        """
        if "bestchange" in url.lower():
            logger.info("Processing a 'bestchange' page...")
            return self.process_bestchange()
        elif "markets.ft.com" in url.lower() and "bonds" in url.lower():
            logger.info(f"Processing Financial Times bonds page for region: {region}...")
            return self.process_ftyields(region)
        else:
            raise NotImplementedError("This parser currently only supports 'bestchange' and FT bonds pages.")

def setup_selenium_driver():
    """Set up and return a configured Chrome WebDriver instance."""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
    
    selenium_url = os.getenv("SELENIUM_REMOTE_URL")

    if selenium_url:
        # ✅ Running in Docker with selenium container
        print(f"[INFO] Using remote Selenium driver at {selenium_url}")
        return webdriver.Remote(
            command_executor=selenium_url,
            options=chrome_options
        )
    else:
        # ✅ Running locally with native ChromeDriver
        print("[INFO] Using local ChromeDriver")
        return webdriver.Chrome(options=chrome_options)

def get_yields_for_region(driver, region_code, region_name):
    """
    Get yields data for a specific region using the FT API.
    
    Parameters:
        driver: Selenium WebDriver instance
        region_code (str): The region code (UK, US, JP, EUR)
        region_name (str): The full name of the region
    
    Returns:
        pd.DataFrame: DataFrame containing the yields data for the region
    """
    try:
        # print(f"Attempting to get data for {region_name} ({region_code})...")
        
        # Get cookies from current session
        cookies = {cookie['name']: cookie['value'] for cookie in driver.get_cookies()}
        # print(f"Cookies obtained: {len(cookies)} cookies")
        
        # Set up API request
        api_url = f"https://markets.ft.com/data/bonds/ajax/getyieldstable?regionCode={region_code}"
        headers = {
            'User-Agent': driver.execute_script("return navigator.userAgent;"),
            'Accept': 'application/json',
            'Referer': 'https://markets.ft.com/data/bonds'
        }
        
        # Create a session and update it with selenium cookies
        session = requests.Session()
        session.cookies.update(cookies)
        session.headers.update(headers)
        
        # Make API request
        # print(f"Making API request to: {api_url}")
        response = session.get(api_url)
        response.raise_for_status()
        
        # Parse JSON response
        json_data = response.json()
        
        if not json_data or 'html' not in json_data:
            raise ValueError(f"Invalid response format for region {region_code}")
        
        # Parse the HTML content from the response
        html_content = json_data['html']
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract data from the table rows
        rows = []
        for tr in soup.find_all('tr'):
            cols = tr.find_all('td')
            if len(cols) >= 5:  # Ensure we have all required columns
                # Extract maturity (handle both full and abbreviated versions)
                maturity_cell = cols[0]
                maturity = maturity_cell.find('span', class_='mod-ui-hide-xsmall')
                if not maturity:
                    maturity = maturity_cell.find('span', class_='mod-ui-hide-small-above')
                maturity = maturity.text if maturity else cols[0].text.strip()
                
                row = {
                    'Region': region_name,
                    'Maturity': maturity,
                    'Yield': cols[1].text.strip(),
                    'Today\'s Change': cols[2].text.strip(),
                    '1 Week Ago': cols[3].text.strip(),
                    '1 Month Ago': cols[4].text.strip()
                }
                rows.append(row)
        
        if not rows:
            raise ValueError(f"No data rows found in response for {region_code}")
        
        df = pd.DataFrame(rows)
        # print(f"Successfully retrieved data via API for {region_name}")
        
        # Verify the data
        # print(f"Verification for {region_name}:")
        # print(f"Rows extracted: {len(df)}")
        # if not df.empty:
            # print("First row:", df.iloc[0].to_dict())
        
        return df
        
    except Exception as e:
        print(f"Error getting data for {region_name}: {str(e)}", file=sys.stderr)
        return None

if __name__ == "__main__":
    # Only configure logging if running as main script
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    driver = None
    try:
        # Create mkt_reports directory if it doesn't exist
        script_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        reports_dir = os.path.join(script_dir, 'mkt_reports')
        os.makedirs(reports_dir, exist_ok=True)
        
        # FT Bonds URL
        url = "https://markets.ft.com/data/bonds"
        
        logger.info("Initializing Selenium WebDriver...")
        driver = setup_selenium_driver()
        
        logger.info(f"Fetching data from {url}...")
        driver.get(url)
        
        # Wait for initial page load
        time.sleep(5)
        
        # Define regions to fetch
        regions = [
            ('UK', 'United Kingdom'),
            ('US', 'United States'),
            ('JP', 'Japan'),
            ('EUR', 'Eurozone')
        ]
        
        # Collect data for all regions
        all_data = []
        for region_code, region_name in regions:
            logger.info(f"\nFetching data for {region_name}...")
            df = get_yields_for_region(driver, region_code, region_name)
            if df is not None:
                # Verify the data is unique for this region
                logger.info(f"Verification for {region_name}:")
                logger.info(df[['Region', 'Yield']].head())
                all_data.append(df)
                logger.info(f"Added data for {region_name}")
            else:
                logger.warning(f"Failed to get data for {region_name}")
        
        # Combine all data
        if all_data:
            combined_df = pd.concat(all_data, ignore_index=True)
            
            # Verify the combined data
            logger.info("\nVerification of combined data:")
            for region in combined_df['Region'].unique():
                region_data = combined_df[combined_df['Region'] == region]
                logger.info(f"\n{region} - {len(region_data)} rows")
                logger.info("Sample yields:", region_data['Yield'].head().tolist())
            
            # Display the results
            logger.info("\nBond Yields Data for All Regions:")
            logger.info("=" * 100)
            logger.info(combined_df.to_string(index=False))
            logger.info("=" * 100)
            
            # Save to CSV with fixed filename
            output_file = os.path.join(reports_dir, "bond_yields_all_regions.csv")
            combined_df.to_csv(output_file, index=False)
            logger.info(f"\nData has been saved to {output_file}")
        else:
            logger.info("No data was collected for any region.")
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        if driver:
            logger.error(f"Page source at error: {driver.page_source[:500]}...")
        sys.exit(1)
    finally:
        if driver:
            logger.info("Closing WebDriver...")
            driver.quit()

