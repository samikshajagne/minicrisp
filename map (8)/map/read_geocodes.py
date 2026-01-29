import pandas as pd
import json

# Read the CSV file
df = pd.read_csv('india1.csv')

# Display first few rows and column names
print("Column names:")
print(df.columns.tolist())
print("\nFirst 5 rows:")
print(df.head())
print(f"\nTotal rows: {len(df)}")

# Check for latitude/longitude columns (common names)
lat_cols = [col for col in df.columns if any(x in col.lower() for x in ['lat', 'latitude'])]
lon_cols = [col for col in df.columns if any(x in col.lower() for x in ['lon', 'long', 'longitude'])]

print(f"\nPossible latitude columns: {lat_cols}")
print(f"Possible longitude columns: {lon_cols}")

# If we find lat/lon columns, create a sample JSON for the map
if lat_cols and lon_cols:
    lat_col = lat_cols[0]
    lon_col = lon_cols[0]
    
    # Filter rows with valid coordinates
    valid_data = df.dropna(subset=[lat_col, lon_col])
    
    # Create GeoJSON structure
    features = []
    for idx, row in valid_data.head(100).iterrows():  # Sample first 100
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(row[lon_col]), float(row[lat_col])]
            },
            "properties": row.to_dict()
        }
        features.append(feature)
    
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    # Save to file
    with open('geocodes.json', 'w', encoding='utf-8') as f:
        json.dump(geojson, f, indent=2, ensure_ascii=False)
    
    print(f"\nCreated geocodes.json with {len(features)} locations")
else:
    print("\nCould not automatically detect lat/lon columns")
