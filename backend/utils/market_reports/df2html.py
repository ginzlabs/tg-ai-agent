import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from jinja2 import Template
import os
from PIL import Image

def optimize_image(image_path, quality=10):
    """
    Optimize image by reducing its quality and size.
    
    Parameters:
        image_path (str): Path to the original image
        quality (int): Quality of the output image (1-100)
    
    Returns:
        str: Path to the optimized image
    """
    # Generate optimized image path
    base, ext = os.path.splitext(image_path)
    opt_path = f"{base}_opt.jpg"
    
    # Open image
    with Image.open(image_path) as img:
        # Convert to RGB if needed
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        # Reduce size by 30%
        new_size = tuple(int(dim * 0.7) for dim in img.size)
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Save with high compression
        img.save(opt_path, 'JPEG', 
                quality=quality, 
                optimize=True,
                progressive=True,
                subsampling='4:2:0')
    
    return opt_path

def generate_insights_report(df, value_column, name_column, output_file="report.html"):
    """Generates a report with statistical insights and visualizations."""

    if value_column not in df.columns or name_column not in df.columns:
        raise ValueError("Specified columns are not in the dataframe.")

    try:
        df[value_column] = pd.to_numeric(df[value_column], errors="coerce")
    except Exception as e:
        raise ValueError(f"Error converting {value_column} to numeric: {e}")

    df = df.dropna(subset=[value_column])

    extra_stats = {
        "Smallest Value": df[value_column].min(),
        "Largest Value": df[value_column].max(),
        "Mean": df[value_column].mean(),
        "Median": df[value_column].median(),
        "Mode": df[value_column].mode().iloc[0] if not df[value_column].mode().empty else "N/A",
        "Standard Deviation": df[value_column].std(),
        "5th Percentile": df[value_column].quantile(0.05),
        "10th Percentile": df[value_column].quantile(0.10),
        "15th Percentile": df[value_column].quantile(0.15),
        "25th Percentile": df[value_column].quantile(0.25),
        "50th Percentile (Median)": df[value_column].quantile(0.5),
        "75th Percentile": df[value_column].quantile(0.75)
    }

    extra_stats_df = pd.DataFrame(list(extra_stats.items()), columns=["Statistic", "Value"])
    extra_stats_df['Value'] = extra_stats_df['Value'].apply(lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else x)

    # Create images directory inside the reports directory
    output_dir = os.path.dirname(output_file)
    image_dir = os.path.join(output_dir, "images")
    os.makedirs(image_dir, exist_ok=True)

    hist_path = os.path.join(image_dir, "histogram.png")
    box_path = os.path.join(image_dir, "boxplot.png")
    bar_path = os.path.join(image_dir, "barplot.png")

    # Turn off interactive mode for saving figures
    plt.ioff()

    # Histogram
    fig_width_inches = 8
    fig_height_inches = fig_width_inches * (5/8)
    fig, axes = plt.subplots(1, 1, figsize=(fig_width_inches, fig_height_inches))
    sns.histplot(df[value_column], kde=True, bins=20, color="blue", ax=axes)
    axes.set_title("Distribution of Values")
    axes.set_xlabel(value_column)
    axes.set_ylabel("Frequency")
    fig.savefig(hist_path)
    plt.close(fig)

    # Boxplot
    fig, axes = plt.subplots(1, 1, figsize=(fig_width_inches, fig_height_inches))
    sns.boxplot(x=df[value_column], color="orange", ax=axes)
    axes.set_title("Box Plot of Values")
    axes.set_xlabel(value_column)
    fig.savefig(box_path)
    plt.close(fig)

    # Bar plot
    fig, axes = plt.subplots(1, 1, figsize=(fig_width_inches, fig_height_inches))
    sns.barplot(x=name_column, y=value_column, data=df, palette="viridis", ax=axes)
    axes.set_xticklabels(axes.get_xticklabels(), rotation=45, ha="right")
    plt.tight_layout()
    axes.set_title("Values by Name")
    fig.savefig(bar_path)
    plt.close(fig)

    # Use relative paths for images in HTML
    rel_hist_path = os.path.relpath(hist_path, os.path.dirname(output_file))
    rel_box_path = os.path.relpath(box_path, os.path.dirname(output_file))
    rel_bar_path = os.path.relpath(bar_path, os.path.dirname(output_file))

    # HTML template with updated styling
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Data Insights Report</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                margin: 10px; 
                padding: 10px; 
                font-size: 0.8em;
            }
            h1 {
                font-size: 1.5em;
            }
            h2 {
                font-size: 1.2em;
            }
            table {
                border-collapse: collapse;
                width: 40%;               /* Make table narrower */
                margin: 0 0 10px 0;       /* Align table to the left */
                font-size: 1em;
                table-layout: fixed;      /* Crucial for fixed widths */
                min-width: 400px;         /* Prevent table from getting too small */
            }
            th, td {
                border: 1px solid #ddd;
                padding: 5px;
                text-align: left;
                width: 50%;               /* Each column 50% of the table */
                overflow-wrap: break-word; /* For modern browsers */
                word-wrap: break-word;     /* For older browsers */
                vertical-align: top;
            }
            th { 
                background-color: #f4f4f4; 
            }

            /* Container for images */
            .flex-container {
                display: flex;
                flex-wrap: wrap;
                justify-content: flex-start; /* Align images to the left */
                max-width: 900px;
                margin: 10px 0 0 0;         /* Align container to the left */
            }
            /* Fixed image width so that 2 fit in a row on larger screens */
            .flex-container img {
                width: 350px; 
                height: auto;
                margin: 10px;
                box-sizing: border-box;
            }

            /* For screens below 768px, stack images vertically and center them */
            @media (max-width: 768px) {
                .flex-container {
                    flex-direction: column;
                    align-items: center; /* Center images on mobile */
                }
                .flex-container img {
                    width: 90%;         /* Images take up 90% of screen width */
                    margin: 10px auto; /* Center images with small margins */
                }
            }

            @media print {
                body {
                    font-size: 10pt;
                }
                .flex-container {
                    display: flex;
                    flex-direction: row;
                }
                .flex-container img {
                    width: 30%;
                }
                table {
                    font-size: 10pt;
                }
            }

            /* Add these styles to the existing CSS */
            .yield-curve-image {
                flex: 1;
                min-width: 400px;
                display: flex;
                align-items: flex-start;
                justify-content: center;
            }
            .yield-curve-image img {
                max-width: 100%;
                height: auto;
                border-radius: 4px;
            }
            .yields-table {
                flex: 0 1 auto;
                min-width: 300px;
            }
            @media (max-width: 768px) {
                .yield-curve-image {
                    min-width: 100%;
                    margin-top: 20px;
                }
            }
        </style>
    </head>
    <body>
        <h1>Data Insights Report</h1>

        <h2>Statistics</h2>
        <table>
            <thead>
                <tr>
                    <th>Statistic</th>
                    <th>Value</th>
                </tr>
            </thead>
            <tbody>
                {% for row in extra_stats %}
                <tr>
                    <td>{{ row["Statistic"] }}</td>
                    <td>{{ row["Value"] }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        <h2>Visualizations</h2>
        <div class="flex-container">
            <img src="{{ hist_path }}" alt="Histogram">
            <img src="{{ box_path }}" alt="Box Plot">
            <img src="{{ bar_path }}" alt="Bar Plot">
        </div>
    </body>
    </html>
    """

    # Render HTML
    template = Template(html_template)
    rendered_html = template.render(
        extra_stats=extra_stats_df.to_dict(orient="records"),
        hist_path=rel_hist_path,
        box_path=rel_box_path,
        bar_path=rel_bar_path
    )

    # Write HTML file
    with open(output_file, "w", encoding="utf-8") as file:
        file.write(rendered_html)

    print(f"Report generated and saved to {output_file}")


def generate_market_report_html(market_data: dict, output_file="market_report.html"):
    """
    Generates a market report with statistics and best rates tables for different currency pairs,
    and includes regional yields data.
    
    Parameters:
        market_data (dict): Dictionary with keys for currency pairs and yields data
        output_file (str): Path to save the HTML report
    """
    
    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(output_file)
    os.makedirs(output_dir, exist_ok=True)
    
    # Use the yield curves image directly
    yield_curves_path = os.path.join(output_dir, 'yield_curves', 'combined_yield_curves.svg')
    relative_image_path = os.path.relpath(yield_curves_path, output_dir)

    # Process each dataset
    processed_data = {}
    for key, df in market_data.items():
        if key == 'Regional Yields':
            # Process yields data - sort in specific order and pass through
            region_order = ['United Kingdom', 'United States', 'Eurozone', 'Japan']
            df = df.reindex(region_order)
            processed_data[key] = {
                'type': 'yields',
                'data': df
            }


    # HTML template
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Market Report</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 10px;
                padding: 0;
                background-color: #f5f5f5;
                font-size: 11px;
            }
            .market-section {
                background-color: white;
                border-radius: 4px;
                padding: 10px;
                padding-bottom: 5px; /* Reduced from 25px to 15px */
                margin-bottom: 5px;
            }
            .header-container {
                display: flex;
                justify-content: space-between;
                align-items: baseline;
                margin: 5px 0 10px 0;
            }
            h1 {
                color: #333;
                margin: 0;
                font-size: 16px;
                flex: 1;
            }
            .timestamp {
                color: #666;
                font-size: 12px;
                text-align: right;
                margin-left: 20px;
            }
            h2 {
                color: #444;
                margin: 5px 0 10px 0;
                font-size: 14px;
            }
            h3 {
                font-size: 12px;
                margin: 5px 0;
                color: #555;
            }

            table {
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 10px;
                background-color: white;
                font-size: 11px;
            }
            th, td {
                padding: 4px 6px;
                border-bottom: 1px solid #eee;
                text-align: left;
            }
            td.number, th.number {
                text-align: right;
            }
            th {
                background-color: #e6f3ff;
                color: #333;
                font-weight: bold;
                font-size: 11px;
            }
            tr:hover {
                background-color: #f8f9fa;
            }

            .yields-table {
                margin-top: 20px;
            }
            .yields-table td, .yields-table th {
                text-align: right;
            }
            .yields-table td:first-child, .yields-table th:first-child {
                text-align: left;
            }
            @media print {
                body { font-size: 9pt; }
                h1 { font-size: 14pt; }
                h2 { font-size: 12pt; }
                h3 { font-size: 10pt; }
                table { font-size: 8pt; }
                .timestamp { font-size: 10pt; }
                th {
                    background-color: #f0f7ff !important;
                    -webkit-print-color-adjust: exact;
                    print-color-adjust: exact;
                }
            }
            /* Update these styles in the existing CSS */
            .yield-curve-image {
                flex: 1;
                max-width: 45%;
                display: flex;
                align-items: flex-start;
                justify-content: center;
            }
            .yield-curve-image img {
                width: 100%;
                height: auto;
                max-width: 350px;
                border-radius: 4px;
            }
            .yields-table {
                flex: 1;
                max-width: 55%;
                min-width: 300px;
            }
            @media (max-width: 768px) {
                .yield-curve-image, .yields-table {
                    max-width: 100%;
                }
                .yield-curve-image {
                    margin-top: 20px;
                }
            }
            .yields-content {
                display: grid;
                grid-template-columns: 60% 40%;
                grid-gap: 20px;
                padding: 0;
                margin: 5px 0 0px 0;  /* Reduced from 20px to 10px */
                padding-bottom: 5px;  /* Reduced from 30px to 15px */
            }

        </style>
    </head>
    <body>
        <div class="header-container">
            <h1>Market Report</h1>
            <div class="timestamp">Generated on: {{ timestamp }} UTC</div>
        </div>
        
        {% for key, data in market_data.items() %}
        <div class="market-section">
            {% if data.type == 'yields' %}
            <h2>{{ key }}</h2>
            <div class="yields-content">
                <div>
                    <table>
                        <thead>
                            <tr>
                                <th>Region</th>
                                {% for col in data.data.columns %}
                                <th class="number">{{ col }}</th>
                                {% endfor %}
                            </tr>
                        </thead>
                        <tbody>
                            {% for _, row in data.data.iterrows() %}
                            <tr>
                                <td>{{ row.name }}</td>
                                {% for col in data.data.columns %}
                                <td class="number">{{ "%.2f%%"|format(row[col]) }}</td>
                                {% endfor %}
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                <div style="margin-top: -25px; text-align: right;">
                    <img src="{{ relative_image_path }}" alt="Combined Yield Curves" style="width: 240px; margin-right: 25px; height: auto;">
                </div>
            </div>
            {% endif %}
        </div>
        {% endfor %}
    </body>
    </html>
    """
    
    # Render HTML with UTC timestamp
    now = pd.Timestamp.now()
    template = Template(html_template)
    rendered_html = template.render(
        market_data=processed_data,
        timestamp=now.strftime("%d-%m-%Y %H:%M:%S"),
        now_date=now.strftime("%d-%m-%Y"),
        relative_image_path=relative_image_path
    )
    
    # Write HTML file
    with open(output_file, "w", encoding="utf-8") as file:
        file.write(rendered_html)
    
    print(f"Market report generated and saved to {output_file}")

    return output_file, processed_data
