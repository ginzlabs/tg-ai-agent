import pandas as pd
import os
import re
import numpy as np
from scipy.interpolate import CubicSpline
import matplotlib.pyplot as plt
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def convert_period_to_months(period):
    """
    Convert period string (e.g., '1 Month', '2 Year') to number of months.
    
    Args:
        period (str): Period string like '1 Month', '3 Month', '6 Month', '1 Year', etc.
    
    Returns:
        int: Number of months
    """
    # Clean and standardize the input
    period = period.lower().strip()
    
    # Extract number and unit
    match = re.match(r'(\d+)\s*(month|year|m|y)', period)
    if not match:
        raise ValueError(f"Invalid period format: {period}")
    
    number = int(match.group(1))
    unit = match.group(2)
    
    # Convert to months
    if unit.startswith('y'):
        return number * 12
    else:
        return number

def clean_percentage(value):
    """
    Clean percentage values and convert to float.
    
    Args:
        value (str): Percentage value like '4.78%', '>-0.01', etc.
        
    Returns:
        float: Cleaned numeric value
    """
    if pd.isna(value) or value == '':
        return None
        
    # Remove % symbol and whitespace
    value = value.replace('%', '').strip()
    
    # Handle special characters
    value = value.replace('>', '').replace('<', '')
    
    try:
        return float(value)
    except ValueError:
        return None

def process_yields_data(input_data):
    """
    Process yields data from either a DataFrame or a CSV file.
    
    Args:
        input_data: Either a pandas DataFrame or a string path to a CSV file
    """
    try:
        # Check if input is DataFrame or path
        if isinstance(input_data, pd.DataFrame):
            df = input_data.copy()
            logger.info("Processing yields from provided DataFrame")
        else:
            logger.info(f"Loading yields data from file: {input_data}")
            df = pd.read_csv(input_data)
        
        # Clean numeric columns
        df['Yield'] = df['Yield'].apply(clean_percentage)
        df['Today\'s Change'] = df['Today\'s Change'].apply(clean_percentage)
        df['1 Week Ago'] = df['1 Week Ago'].apply(clean_percentage)
        df['1 Month Ago'] = df['1 Month Ago'].apply(clean_percentage)
        
        # Add standardized period names and months
        df['Period_Std'] = df['Maturity'].apply(standardize_period_name)
        df['Months'] = df['Maturity'].apply(convert_period_to_months)
        
        # Sort by Region and Months
        df = df.sort_values(['Region', 'Months'])
        
        # Verify data after cleaning
        #print("\nData sample after cleaning:")
        #print(df.head())
        #print("\nData summary:")
        #print(df.describe())
        
        #print("\nProcessing original data complete. Starting interpolation...")
        
        # Interpolate yield curves
        interpolated_df = interpolate_yield_curve(df)
        
        if interpolated_df.empty:
            raise ValueError("No data was generated during interpolation")
            
        #print(f"\nInterpolation complete. Generated {len(interpolated_df)} points across {len(interpolated_df['Region'].unique())} regions")
        
        # Create summary DataFrame
        summary_df = create_summary_df(interpolated_df)
        
        #print("\nSummary of yields at key tenors:")
        #print(summary_df.round(2))
        
        return df, interpolated_df, summary_df
        
    except Exception as e:
        #print(f"\nError details:")
        #print(f"Type: {type(e)}")
        #print(f"Message: {str(e)}")
        raise

def standardize_period_name(period):
    """
    Convert period string to standardized format (e.g., '1 Month' to '1M', '2 Year' to '2Y').
    
    Args:
        period (str): Period string like '1 Month', '3 Month', '6 Month', '1 Year', etc.
    
    Returns:
        str: Standardized period name
    """
    # Clean and standardize the input
    period = period.lower().strip()
    
    # Extract number and unit
    match = re.match(r'(\d+)\s*(month|year|m|y)', period)
    if not match:
        raise ValueError(f"Invalid period format: {period}")
    
    number = match.group(1)
    unit = match.group(2)
    
    # Convert to standard format
    if unit.startswith('y'):
        return f"{number}Y"
    else:
        return f"{number}M"

def interpolate_yield_curve(df):
    """
    Interpolate yield curves for each region using cubic spline interpolation.
    
    Args:
        df (pd.DataFrame): DataFrame with columns [Region, Period, Yield, Months]
        
    Returns:
        pd.DataFrame: DataFrame with interpolated yields at monthly intervals
    """
    # Create target months (1 month to 30 years in monthly steps)
    target_months = np.arange(1, 361)  # 30 years * 12 months + 1
    
    interpolated_data = []
    
    for region in df['Region'].unique():
        try:
            # Get data for this region
            region_data = df[df['Region'] == region].sort_values('Months')
            
            #print(f"\nDebug - {region} data:")
            #print(f"Number of points: {len(region_data)}")
            #print("Original points (Months, Yield):")
            #for _, row in region_data.iterrows():
            #    print(f"{row['Months']}: {row['Yield']:.4f}")
            
            if len(region_data) < 2:
                #print(f"Warning: Not enough data points for {region}")
                continue
            
            # Create cubic spline interpolator
            cs = CubicSpline(region_data['Months'].values, 
                           region_data['Yield'].values, 
                           bc_type='natural')
            
            # Interpolate for all target months
            interpolated_yields = cs(target_months)
            
            # Verify interpolation results
            #print(f"Interpolation range: {min(interpolated_yields):.4f} to {max(interpolated_yields):.4f}")
            
            # Add to results
            for months, yield_value in zip(target_months, interpolated_yields):
                interpolated_data.append({
                    'Region': region,
                    'Months': int(months),
                    'Period': f"{months}M" if months < 12 else f"{months//12}Y",
                    'Yield': round(float(yield_value), 4)
                })
                
            #print(f"Successfully interpolated yield curve for {region}")
            
        except Exception as e:
            #print(f"Warning: Could not interpolate yield curve for {region}: {str(e)}")
            continue
    
    interpolated_df = pd.DataFrame(interpolated_data)
    
    # Verify final interpolated data
    #print("\nDebug - Final interpolated data summary:")
    #for region in interpolated_df['Region'].unique():
    #    region_data = interpolated_df[interpolated_df['Region'] == region]
    #    print(f"\n{region}:")
    #    print(f"Points: {len(region_data)}")
    #    print(f"Yield range: {region_data['Yield'].min():.4f} to {region_data['Yield'].max():.4f}")
    
    return interpolated_df

def plot_yield_curves(original_df, interpolated_df, output_dir):
    """
    Plot yield curves for each region, comparing actual vs interpolated values.
    
    Args:
        original_df (pd.DataFrame): Original yield curve data
        interpolated_df (pd.DataFrame): Interpolated yield curve data
        output_dir (str): Directory to save the plots
    """
    # Create plots directory if it doesn't exist
    plots_dir = os.path.join(output_dir, 'yield_curves')
    os.makedirs(plots_dir, exist_ok=True)
    
    # Set up the plotting style
    plt.style.use('classic')  # Using classic style instead of seaborn-darkgrid
    
    # Get current date
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    # Create plots for each region
    for region in original_df['Region'].unique():
        # Create a new figure for each region with white background
        plt.figure(figsize=(15, 10), facecolor='white')
        ax = plt.gca()
        ax.set_facecolor('white')
        
        # Get data for this region
        original_data = original_df[original_df['Region'] == region].sort_values('Months')
        interpolated_data = interpolated_df[interpolated_df['Region'] == region].sort_values('Months')
        
        # Plot actual points with error bars
        plt.errorbar(original_data['Months'], original_data['Yield'],
                    yerr=abs(original_data['Today\'s Change']),
                    fmt='ro', label='Actual', markersize=8, capsize=5,
                    ecolor='gray', alpha=0.5)
        
        # Plot interpolated curve
        plt.plot(interpolated_data['Months'], interpolated_data['Yield'],
                'b-', label='Interpolated', linewidth=2, alpha=0.7)
        
        # Add historical values as dashed lines
        if '1 Week Ago' in original_data.columns:
            plt.plot(original_data['Months'], original_data['1 Week Ago'],
                    'g--', label='1 Week Ago', alpha=0.5)
        if '1 Month Ago' in original_data.columns:
            plt.plot(original_data['Months'], original_data['1 Month Ago'],
                    'r--', label='1 Month Ago', alpha=0.5)
        
        # Customize the plot
        plt.title(f'Yield Curve - {region} ({current_date})', fontsize=16, pad=20)
        plt.xlabel('Months', fontsize=14)
        plt.ylabel('Yield (%)', fontsize=14)
        plt.grid(True, linestyle='--', alpha=0.3)
        plt.legend(fontsize=12, loc='best', framealpha=1)
        
        # Add text annotations for actual points
        for _, row in original_data.iterrows():
            plt.annotate(f"{row['Period_Std']}\n{row['Yield']:.2f}%",
                        (row['Months'], row['Yield']),
                        xytext=(5, 5), textcoords='offset points',
                        fontsize=8, bbox=dict(facecolor='white', 
                                            edgecolor='gray',
                                            alpha=0.7))
        
        # Set axis limits with some padding
        plt.xlim(0, max(original_data['Months']) * 1.1)
        ymin = min(original_data['Yield'].min(), interpolated_data['Yield'].min()) * 0.9
        ymax = max(original_data['Yield'].max(), interpolated_data['Yield'].max()) * 1.1
        plt.ylim(ymin, ymax)
        
        # Add grid and adjust layout
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.tight_layout()
        
        # Save the plot
        #plt.savefig(os.path.join(plots_dir, f'yield_curve_{region.replace(" ", "_")}.png'),
        #            dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()

def plot_combined_curves(original_df, interpolated_df, output_dir):
    """
    Create a single plot combining yield curves from all regions with logarithmic x-axis.
    Output will be saved as a vector SVG file for optimal quality at any size.
    
    Args:
        original_df (pd.DataFrame): Original yield curve data
        interpolated_df (pd.DataFrame): Interpolated yield curve data
        output_dir (str): Directory to save the plots
    """
    # Create plots directory if it doesn't exist
    plots_dir = os.path.join(output_dir, 'yield_curves')
    os.makedirs(plots_dir, exist_ok=True)
    
    # Set up colors for each region and axes
    colors = {
        'United Kingdom': '#0057B7',  # Royal Blue
        'United States': '#BF0A30',   # Red
        'Japan': '#FF1493',          # Deep Pink
        'Eurozone': '#404040'        # Dark Gray
    }
    grey_color = '#666666'  # Define grey color for axes and text

    # Create a new figure with white background
    plt.figure(figsize=(12, 7), facecolor='white')
    ax = plt.gca()
    ax.set_facecolor('white')
    
    # Set grey color for spines (box)
    for spine in ax.spines.values():
        spine.set_color(grey_color)
    
    # Set grey color for tick labels and axes labels
    ax.tick_params(colors=grey_color)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color(grey_color)
    
    # Set grey color for ylabel
    plt.ylabel('Yield (%)', fontsize=24, labelpad=15, color=grey_color)
    
    # Increase font sizes globally
    plt.rcParams.update({
        'font.size': 14,
        'axes.labelsize': 20,
        'axes.titlesize': 22,
        'xtick.labelsize': 16,
        'ytick.labelsize': 16,
        'legend.fontsize': 18
    })
    
    # Get current date
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    # Set x-axis to logarithmic scale
    plt.xscale('log')
    
    # Plot each region
    for region in sorted(original_df['Region'].unique()):
        color = colors.get(region, '#000000')  # default to black if region not in colors dict
        
        # Get data for this region
        original_data = original_df[original_df['Region'] == region].sort_values('Months')
        interpolated_data = interpolated_df[interpolated_df['Region'] == region].sort_values('Months')
        
        # Plot actual points with larger markers
        plt.scatter(original_data['Months'], original_data['Yield'],
                   color=color, s=80, zorder=5, alpha=0.8)
        
        # Plot interpolated curve with thicker lines
        plt.plot(interpolated_data['Months'], interpolated_data['Yield'],
                color=color, label=region, linewidth=2.5, alpha=0.8)
        
        # Add historical values as thinner dashed lines
        if '1 Week Ago' in original_data.columns:
            plt.plot(original_data['Months'], original_data['1 Week Ago'],
                    color=color, linestyle='--', linewidth=1.5, alpha=0.4)
        if '1 Month Ago' in original_data.columns:
            plt.plot(original_data['Months'], original_data['1 Month Ago'],
                    color=color, linestyle=':', linewidth=1.5, alpha=0.4)
    
    # Customize the plot with larger fonts
    plt.xlabel('')  # Remove x-axis label
    plt.legend(fontsize=18, loc='lower right', framealpha=1)
    
    # Set axis limits with some padding
    plt.xlim(0.8, max(original_df['Months']) * 1.1)
    
    # Calculate y-axis limits with special handling for low values
    min_yield = min(original_df['Yield'].min(), interpolated_df['Yield'].min())
    max_yield = max(original_df['Yield'].max(), interpolated_df['Yield'].max())
    
    # If any value is less than 0.2%, set lower limit to -1% or actual minimum
    if min_yield < 0.2:
        ymin = min(-1, min_yield * 1.1)
    else:
        ymin = min_yield * 0.9
    
    ymax = max_yield * 1.1
    plt.ylim(ymin, ymax)
    
    # Set x-axis ticks to show standard periods, including 0
    major_ticks = [1, 3, 6, 12, 24, 60, 120, 360]
    plt.xticks([0.8] + major_ticks, 
               ['0'] + [f"{x}M" if x < 12 else f"{x//12}Y" for x in major_ticks], 
               fontsize=16, 
               color=grey_color)  # Set tick labels to grey
    plt.yticks(fontsize=16)
    
    # Add grid lines
    plt.grid(True, which='major', linestyle='-', alpha=0.2)
    plt.grid(True, which='minor', linestyle=':', alpha=0.1)
    
    # Adjust layout with more padding for larger fonts
    plt.tight_layout(pad=1.2)
    
    # Save the plot as SVG vector format
    plt.savefig(os.path.join(plots_dir, 'combined_yield_curves.svg'),
                format='svg', bbox_inches='tight', facecolor='white')
    plt.close()

def create_summary_df(interpolated_df):
    """
    Create a summary DataFrame with specific tenors for each region.
    
    Args:
        interpolated_df (pd.DataFrame): DataFrame with interpolated yield curves
        
    Returns:
        pd.DataFrame: Summary DataFrame with yields at specific tenors
    """
    # Define target months for summary
    target_months = [1, 6, 12, 36, 60, 120, 360]  # 1M, 6M, 1Y, 3Y, 5Y, 10Y, 30Y
    
    summary_data = []
    for region in sorted(interpolated_df['Region'].unique()):
        region_data = interpolated_df[interpolated_df['Region'] == region]
        row_data = {'Region': region}
        
        # Get yields for each target month
        for months in target_months:
            tenor_data = region_data[region_data['Months'] == months]
            if not tenor_data.empty:
                column_name = f"{months}M" if months < 12 else f"{months//12}Y"
                row_data[column_name] = tenor_data['Yield'].iloc[0]
        
        summary_data.append(row_data)
    
    # Create DataFrame and set index to Region
    summary_df = pd.DataFrame(summary_data)
    summary_df.set_index('Region', inplace=True)
    
    # Rename columns to standard format
    column_names = ['1M', '6M', '1Y', '3Y', '5Y', '10Y', '30Y']
    summary_df.columns = column_names
    
    return summary_df

if __name__ == "__main__":
    try:
        # Try to find the CSV file in the mkt_reports directory
        script_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        default_csv_path = os.path.join(script_dir, 'mkt_reports', 'bond_yields_all_regions.csv')
        
        if not os.path.exists(default_csv_path):
            raise FileNotFoundError(f"Could not find yields data file at {default_csv_path}")
        
        # Process the data and generate plots
        original_df, interpolated_df, summary_df = process_yields_data(default_csv_path)
        
        # Generate plots
        output_dir = os.path.dirname(default_csv_path)
        plot_combined_curves(original_df, interpolated_df, output_dir)
        
        # Save processed data
        original_df.to_csv(os.path.join(output_dir, 'processed_yields.csv'), index=False)
        interpolated_df.to_csv(os.path.join(output_dir, 'interpolated_yields.csv'), index=False)
        summary_df.to_csv(os.path.join(output_dir, 'yield_curve_summary.csv'))
        
    except Exception as e:
        exit(1)
