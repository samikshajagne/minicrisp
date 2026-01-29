import csv

# Read and analyze the CSV file
with open('india1.csv', 'r', encoding='utf-8') as file:
    # Read first 5 rows to check structure
    reader = csv.reader(file)
    
    # Get headers
    headers = next(reader)
    print("CSV Headers:")
    print(headers)
    print(f"\nTotal columns: {len(headers)}")
    
    # Print first 3 data rows
    print("\nFirst 3 data rows:")
    for i, row in enumerate(reader):
        if i >= 3:
            break
        print(f"\nRow {i+1}:")
        for j, header in enumerate(headers):
            if j < len(row):
                print(f"  {header}: {row[j]}")
    
    # Reset to count total rows
    file.seek(0)
    total_rows = sum(1 for _ in file) - 1  # Subtract header
    print(f"\n\nTotal rows in CSV: {total_rows}")
