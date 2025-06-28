import logging
from pathlib import Path
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration

logger = logging.getLogger(__name__)

async def save_report_as_pdf(html_path: str, output_pdf_path: str) -> None:
    """
    Convert an HTML file to PDF using WeasyPrint.
    
    Args:
        html_path: Path to the HTML file to convert
        output_pdf_path: Path where to save the PDF file
    """
    try:
        logger.info(f"Converting HTML to PDF: {html_path} -> {output_pdf_path}")
        
        # Create parent directories if needed
        output_path = Path(output_pdf_path)
        output_path.parent.mkdir(exist_ok=True, parents=True)
        
        # Configure fonts
        font_config = FontConfiguration()
        
        # Create CSS for margins and media type
        css = CSS(string='''
            @page {
                margin: 0.4in;
                size: A4;
            }
            body {
                margin: 0;
                padding: 0;
            }
        ''', font_config=font_config)
        
        # Convert HTML to PDF using WeasyPrint with custom settings
        HTML(filename=html_path).write_pdf(
            output_pdf_path,
            stylesheets=[css],
            font_config=font_config,
            presentational_hints=True  # Enable background colors and images
        )
        
        logger.info(f"Successfully saved PDF to: {output_pdf_path}")
    except Exception as e:
        logger.error(f"Error converting HTML to PDF: {str(e)}")
        raise 