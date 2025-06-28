import asyncio
from typing import Dict, Any
from utils.logger import logger
import os
from pathlib import Path
from datetime import datetime, timezone

import aiofiles
from services.supabase_client import get_supabase_client
from utils.market_reports.marketReport import run_market_report


async def generate_market_report(chat_id: str, message_id: int = None, temp_msg_id: str = None) -> Dict[str, Any]:
    """
    Generate a market report for a specific chat and send it to the user.
    
    Args:
        chat_id: The chat ID to generate the report for
        message_id: Optional message ID to update
        temp_msg_id: Optional temporary message ID for status updates
        
    Returns:
        Dict containing the report data, file URL, and message to send to user
    """
    logger.info(f"Generating market report for chat_id: {chat_id}")
    
    # Initialize variables that might need cleanup
    market_pdf = None
    market_report = None
    
    try:
        # Get Supabase client
        supabase = get_supabase_client()
        
        # Get market report configuration from the reports table
        report_config = await supabase.get_market_report_config()
        if not report_config:
            error_msg = f"No market report configuration found"
            logger.error(error_msg)
            raise ValueError(error_msg)
            
        # Extract URLs from the config
        scrape_urls = {k: v for k, v in report_config.items() if isinstance(v, str)}
        
        if not scrape_urls:
            error_msg = "No scrape URLs found in report configuration"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info(f"Using market report configuration for chat_id {chat_id} with {len(scrape_urls)} scrape URLs")

        # Run report generation (now only with yield curves)
        market_pdf_path, collected_data = await run_market_report(scrape_urls, use_test_data=False) # TODO: Remove use_test_data before deployment
        
        # Read the PDF file before any cleanup
        async with aiofiles.open(market_pdf_path, 'rb') as f:
            pdf_data = await f.read()
        
        # Upload the PDF to Supabase storage
        storage_path = await supabase.upload_pdf_to_storage(
            chat_id=chat_id,
            report_type="market_report",
            pdf_data=pdf_data
        )
        
        # Generate public URL for the file and create formatted file name
        # Always use today's date and time in UTC for both filename and message timestamp
        current_datetime = datetime.now(timezone.utc)
        formatted_date = current_datetime.strftime('%a %d-%m-%Y %H:%M:%S')
        current_date = current_datetime.strftime('%d%m%Y')
        file_name = f"market_report_{current_date}.pdf"
        file_url = f"{os.getenv('SUPABASE_URL', '')}/storage/v1/object/public/{storage_path}"
        
        # Create a summary message with key information
        message = "<b>Market Report Summary</b>\n"
        message += f"{formatted_date} UTC\n\n"
        
        # Add yield curve data
        if 'Regional Yields' in collected_data:
            yields_data = collected_data['Regional Yields']['data']
            # Check for UK yields (1M and 30Y)
            if 'United Kingdom' in yields_data.index:
                uk_data = yields_data.loc['United Kingdom']
                if '1M' in uk_data and '30Y' in uk_data:
                    message += f"<b>UK Yields:</b> 1M {uk_data['1M']:.2f}%, 30Y {uk_data['30Y']:.2f}%\n"
        

        
        # Return the result
        return {
            "status": "completed",
            "chat_id": chat_id,
            "message_id": message_id,
            "temp_msg_id": temp_msg_id,
            "report_type": "market_report",
            "message": message,
            "file_url": file_url,
            "file_name": file_name,
            "file_type": "document",
            "generated_at": formatted_date
        }
        
    except Exception as e:
        logger.error(f"Market report generation failed: {str(e)}", exc_info=True)
        raise
    finally:
        # Clean up temporary files
        try:
            if market_pdf and Path(market_pdf).exists():
                Path(market_pdf).unlink()
                logger.info(f"Cleaned up temporary PDF file: {market_pdf}")
            if market_report and Path(market_report).exists():
                Path(market_report).unlink()
                logger.info(f"Cleaned up temporary HTML file: {market_report}")
        except Exception as e:
            logger.error(f"Error cleaning up temporary files: {str(e)}") 