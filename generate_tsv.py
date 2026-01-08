#!/usr/bin/env python3
"""
Generate a TSV file with rental statistics over time from apts-*.txt files.

Reads all apts-<timestamp>.txt files, extracts the date from the filename,
and calculates median, 25th percentile, and 75th percentile rent for each
apartment size (studio, 1br, 2br, 3br, 4br, 5br).

Output format matches "Boston Rents Over Time 2026 - Sheet2.tsv"
"""

import glob
import os
from datetime import datetime
import numpy as np

def parse_apts_file(filename):
    """Parse an apts file and return dict of bedroom_count -> list of prices"""
    prices_by_bedroom = {}

    with open(filename) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 3:
                continue

            # Skip entries with None price
            if parts[0] == 'None':
                continue

            price = int(parts[0])
            bedroom_count = int(parts[1])

            if bedroom_count not in prices_by_bedroom:
                prices_by_bedroom[bedroom_count] = []
            prices_by_bedroom[bedroom_count].append(price)

    return prices_by_bedroom

def calculate_stats(prices):
    """Calculate median, 25th, and 75th percentile"""
    if not prices:
        return None, None, None

    prices_array = np.array(prices)
    median = int(np.percentile(prices_array, 50))
    p25 = int(np.percentile(prices_array, 25))
    p75 = int(np.percentile(prices_array, 75))

    return median, p25, p75

def main():
    # Find all apts files
    apts_files = sorted(glob.glob('apts-*.txt'))

    # Process each file
    data = []  # List of (date, bedroom_stats) tuples

    for filename in apts_files:
        # Extract timestamp from filename
        basename = os.path.basename(filename)
        timestamp_str = basename.replace('apts-', '').replace('.txt', '')

        # Skip files that don't have a pure numeric timestamp
        if not timestamp_str.isdigit():
            continue

        timestamp = int(timestamp_str)

        # Convert to date
        date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')

        if date in [
                "2013-11-18",
                "2013-11-21",
                "2013-12-18",
                "2014-01-18",
                "2015-07-17",
        ]:
            continue # bad data
        
        # Parse the file
        prices_by_bedroom = parse_apts_file(filename)

        # Calculate stats for each bedroom count (0-5)
        bedroom_stats = {}
        for bedroom_count in range(6):  # 0=studio through 5=5br
            if bedroom_count in prices_by_bedroom:
                median, p25, p75 = calculate_stats(prices_by_bedroom[bedroom_count])
                bedroom_stats[bedroom_count] = (median, p25, p75)
            else:
                bedroom_stats[bedroom_count] = (None, None, None)

        data.append((date, bedroom_stats))

    # Sort by date
    data.sort(key=lambda x: x[0])

    # Map bedroom count to label
    bedroom_labels = {
        0: 'studio',
        1: '1br',
        2: '2br',
        3: '3br',
        4: '4br',
        5: '5br'
    }

    # Order of bedroom types in output (matching the example)
    bedroom_order = [2, 0, 1, 3, 4, 5]  # 2br, studio, 1br, 3br, 4br, 5br

    # Write TSV output
    with open('rents_over_time.tsv', 'w') as f:
        # Header row 1 - bedroom types
        header1_parts = []
        for br in bedroom_order:
            header1_parts.extend([bedroom_labels[br], '', ''])
        f.write('\t'.join(['month'] + header1_parts) + '\n')

        # Header row 2 - median/25th/75th
        header2_parts = []
        for _ in bedroom_order:
            header2_parts.extend(['median', '25th', '75th'])
        f.write('\t'.join(['month'] + header2_parts) + '\n')

        # Data rows
        for date, bedroom_stats in data:
            row_parts = [date]

            for br in bedroom_order:
                median, p25, p75 = bedroom_stats[br]
                if median is not None:
                    row_parts.extend([f'${median:,}', f'${p25:,}', f'${p75:,}'])
                else:
                    row_parts.extend(['', '', ''])

            f.write('\t'.join(row_parts) + '\n')

    print(f"Processed {len(data)} files")
    print(f"Output written to rents_over_time.tsv")

if __name__ == '__main__':
    main()
