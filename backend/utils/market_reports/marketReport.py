
import asyncio
import pandas as pd
import logging
from pathlib import Path
import sys
import os

# Define base_dir as the directory containing this file
logger = logging.getLogger(__name__)

# Import statements that will be used when run as a script
if __name__ == "__main__":
    # Add parent directory to path to allow absolute imports
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(os.path.dirname(current_dir))
    sys.path.insert(0, parent_dir)
    
    # Use absolute imports when run as a script
    from parseWeb import setup_selenium_driver, get_yields_for_region
    from df2html import generate_market_report_html
    from html2pdf import save_report_as_pdf
    from processYields import process_yields_data, plot_combined_curves

else:
    from .parseWeb import setup_selenium_driver, get_yields_for_region
    from .df2html import generate_market_report_html
    from .html2pdf import save_report_as_pdf
    from .processYields import process_yields_data, plot_combined_curves

async def run_market_report(scrape_urls: dict, use_test_data: bool = False) -> tuple[str, dict]:
    """
    Generate the markets report with yield curves data,
    produce an HTML and PDF version, and return paths and collected data.
    If any data source fails, the report will be generated with the available data.
    
    Args:
        scrape_urls: Dictionary with URLs to scrape
        use_test_data: If True, load data from test files instead of fetching live data
        
    Returns:
        tuple: (pdf_path, collected_data_dict)
    """
    # 1. Create the directories
    reports_dir = Path('temp')
    (reports_dir / 'images').mkdir(exist_ok=True, parents=True)
    (reports_dir / 'yield_curves').mkdir(exist_ok=True, parents=True)
    logger.info(f"Verified directory structure in: {reports_dir}")

    # Initialize with empty values
    yields_df = None
    combined_df = None
    
    # 2. Process yield curves
    if use_test_data:
        try:
            # Load test yield curve data
            test_yields_path = reports_dir / 'bond_yields_all_regions.csv'
            test_summary_path = reports_dir / 'yield_curve_summary.csv'
            
            if test_yields_path.exists() and test_summary_path.exists():
                combined_df = pd.read_csv(test_yields_path)
                yields_df = pd.read_csv(test_summary_path)
                logger.info(f"Loaded test yield curves data from: {test_yields_path} and {test_summary_path}")
            else:
                logger.warning("Test yield curves data files not found")
        except Exception as e:
            logger.error(f"Failed to load test yield curves data: {str(e)}")
    else:
        # Original live yield curves code
        ft_url = scrape_urls.get('FT_URL')
        try:
            # ===================================================================
            # TEST ERROR CONDITION - REMOVE BEFORE DEPLOYMENT
            # Uncomment the line below to test error handling for yield curves
            # raise RuntimeError("TEST ERROR: Simulated yield curves failure")
            # ===================================================================
            
            driver = setup_selenium_driver()
            driver.get(ft_url)
            logger.info("Initialized Selenium driver and loaded FT bonds page")
            await asyncio.sleep(3)

            regions = [
                ('UK', 'United Kingdom'),
                ('US', 'United States'),
                ('JP', 'Japan'),
                ('EUR', 'Eurozone')
            ]

            all_data = []
            for region_code, region_name in regions:
                try:
                    df = get_yields_for_region(driver, region_code, region_name)
                    if df is not None:
                        all_data.append(df)
                        logger.info(f"Successfully collected data for {region_name}")
                    else:
                        logger.warning(f"Failed to collect data for {region_name}")
                except Exception as e:
                    logger.error(f"Error collecting data for {region_name}: {str(e)}")
                    # Continue with other regions

            if all_data:
                combined_df = pd.concat(all_data, ignore_index=True)
                output_file = reports_dir / "bond_yields_all_regions.csv"
                combined_df.to_csv(output_file, index=False)
                logger.info(f"Combined yields data saved to: {output_file}")
                
                try:
                    original_df, interpolated_df, yields_df = process_yields_data(combined_df)
                    yields_df.to_csv(reports_dir / 'yield_curve_summary.csv', index=False)
                    logger.info("Successfully processed yield curves data")
                    
                    # Generate yield curves plot
                    plot_combined_curves(original_df, interpolated_df, reports_dir)
                    logger.info("Successfully generated yield curves plot")
                except Exception as e:
                    logger.error(f"Failed to process yield data or generate plot: {str(e)}")
            else:
                logger.error("No yield data was collected")
        except Exception as e:
            logger.error(f"Failed to process yield curves: {str(e)}")
            # Continue without yield curves data



    # 3. Generate HTML report with available data
    try:
        market_report = reports_dir / 'market_report.html'
        market_data = {}
        
        # Only include data that was successfully retrieved
        if yields_df is not None:
            market_data['Regional Yields'] = yields_df
            
        if not market_data:
            raise RuntimeError("No market data available - all data sources failed")
            
        market_report_path, collected_data = generate_market_report_html(market_data, market_report)
        logger.info(f"Successfully generated market report with available data: {market_report_path}")
    except Exception as e:
        logger.error(f"Failed to generate market report: {str(e)}")
        raise RuntimeError(f"Failed to generate market report: {str(e)}")

    # 4. Convert HTML to PDF
    try:
        market_pdf = reports_dir / 'market_report.pdf'
        await save_report_as_pdf(str(market_report), str(market_pdf))
        logger.info(f"Successfully generated PDF report: {market_pdf}")
    except Exception as e:
        logger.error(f"Failed to generate PDF: {str(e)}")
        raise RuntimeError(f"Failed to generate PDF: {str(e)}")

    
    return market_pdf, collected_data


if __name__ == "__main__":
    # Set up logging when run as a script
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)
    
    use_test_data = False
    
    logger.info(f"Starting market report generation as standalone script (test mode: {use_test_data})")

    # Load scrape URLs config
    scrape_urls = {
        'FT_URL': 'https://markets.ft.com/data/bonds'
    }
    # Run the market report
    try:
        pdf_path, collected_data = asyncio.run(run_market_report(scrape_urls, use_test_data=use_test_data))
        logger.info(f"Market report generated successfully: {pdf_path}")
        
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error generating market report: {e}")
        sys.exit(1)

