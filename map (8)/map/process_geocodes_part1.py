import folium
import pandas as pd
import json
import os
import re

# Major cities from around the world (curated list, no phone numbers)
CITIES = [
    # India
    "Mumbai", "Delhi", "New Delhi", "Bangalore", "Bengaluru", "Hyderabad", "Chennai", "Kolkata",
    "Pune", "Ahmedabad", "Surat", "Jaipur", "Lucknow", "Kanpur", "Nagpur", "Indore", "Thane",
    "Bhopal", "Visakhapatnam", "Patna", "Vadodara", "Ghaziabad", "Ludhiana", "Agra", "Nashik",
    "Faridabad", "Meerut", "Rajkot", "Varanasi", "Srinagar", "Aurangabad", "Dhanbad", "Amritsar",
    "Allahabad", "Ranchi", "Coimbatore", "Jabalpur", "Gwalior", "Vijayawada", "Jodhpur", "Madurai",
    "Raipur", "Kochi", "Chandigarh", "Gurgaon", "Noida", "Vapi", "Ankleshwar", "Bharuch",
    # USA
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia", "San Antonio",
    "San Diego", "Dallas", "San Jose", "Austin", "Jacksonville", "San Francisco", "Seattle",
    "Denver", "Boston", "Atlanta", "Miami", "Washington DC", "Las Vegas",
    # UK
    "London", "Birmingham", "Manchester", "Leeds", "Glasgow", "Liverpool", "Bristol", "Edinburgh",
    # Germany
    "Berlin", "Hamburg", "Munich", "Cologne", "Frankfurt", "Stuttgart", "Dusseldorf", "Dortmund",
    # France
    "Paris", "Marseille", "Lyon", "Toulouse", "Nice", "Nantes", "Strasbourg", "Bordeaux",
    # China
    "Beijing", "Shanghai", "Shenzhen", "Guangzhou", "Chengdu", "Hangzhou", "Wuhan", "Xian",
    # Japan
    "Tokyo", "Osaka", "Yokohama", "Nagoya", "Sapporo", "Kobe", "Kyoto", "Fukuoka",
    # Australia
    "Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide", "Gold Coast", "Canberra",
    # Canada
    "Toronto", "Montreal", "Vancouver", "Calgary", "Edmonton", "Ottawa", "Winnipeg",
    # Other major cities
    "Dubai", "Singapore", "Hong Kong", "Bangkok", "Seoul", "Jakarta", "Manila", "Kuala Lumpur",
    "Moscow", "Istanbul", "Cairo", "Johannesburg", "Cape Town", "Lagos", "Nairobi",
    "Sao Paulo", "Rio de Janeiro", "Buenos Aires", "Mexico City", "Lima", "Bogota",
    "Amsterdam", "Brussels", "Vienna", "Zurich", "Geneva", "Stockholm", "Copenhagen", "Oslo",
    "Madrid", "Barcelona", "Rome", "Milan", "Athens", "Warsaw", "Prague", "Budapest"
]
CITIES = sorted(list(set(CITIES)))

# All countries in the world
COUNTRIES = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Argentina", "Armenia", "Australia", 
    "Austria", "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus", "Belgium", 
    "Belize", "Benin", "Bhutan", "Bolivia", "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", 
    "Bulgaria", "Burkina Faso", "Burundi", "Cambodia", "Cameroon", "Canada", "Cape Verde", 
    "Central African Republic", "Central African Republic", "Chad", "Chile", "China", "Colombia", "Comoros", "Congo", "Costa Rica", 
    "Croatia", "Cuba", "Cyprus", "Czech Republic", "Denmark", "Djibouti", "Dominica", "Dominican Republic", 
    "East Timor", "Ecuador", "Egypt", "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia", "Ethiopia", 
    "Fiji", "Finland", "France", "Gabon", "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Grenada", 
    "Guatemala", "Guinea", "Guinea-Bissau", "Guyana", "Haiti", "Honduras", "Hungary", "Iceland", "India", 
    "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy", "Ivory Coast", "Jamaica", "Japan", "Jordan", 
    "Kazakhstan", "Kenya", "Kiribati", "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon", "Lesotho", 
    "Liberia", "Libya", "Liechtenstein", "Lithuania", "Luxembourg", "Macedonia", "Madagascar", "Malawi", 
    "Malaysia", "Maldives", "Mali", "Malta", "Marshall Islands", "Mauritania", "Mauritius", "Mexico", 
    "Micronesia", "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco", "Mozambique", "Myanmar", 
    "Namibia", "Nauru", "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea", 
    "Norway", "Oman", "Pakistan", "Palau", "Panama", "Papua New Guinea", "Paraguay", "Peru", "Philippines", 
    "Poland", "Portugal", "Qatar", "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis", "Saint Lucia", 
    "Saint Vincent", "Samoa", "San Marino", "Sao Tome and Principe", "Saudi Arabia", "Senegal", "Serbia", 
    "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia", "Solomon Islands", "Somalia", 
    "South Africa", "South Korea", "South Sudan", "Spain", "Sri Lanka", "Sudan", "Suriname", "Swaziland", 
    "Sweden", "Switzerland", "Syria", "Taiwan", "Tajikistan", "Tanzania", "Thailand", "Togo", "Tonga", 
    "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan", "Tuvalu", "Uganda", "Ukraine", 
    "United Arab Emirates", "United Kingdom", "United States", "Uruguay", "Uzbekistan", "Vanuatu", 
    "Vatican City", "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe"
]

def load_geocode_cache():
    """Load geocoded data from JSON file."""
    json_file = "data/geocoded_cache1.json"
    if os.path.exists(json_file):
        with open(json_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def extract_pd_from_html(html_file):
    """
    Extract company data from existing HTML map file.
    Parses the openSidebar() calls to recover data.
    """
    data = []
    if not os.path.exists(html_file):
        return pd.DataFrame()
        
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        matches = re.findall(r'onclick="openSidebar\((.*?)\)\s*"', content, re.DOTALL)
        
        geocode_cache = load_geocode_cache()
        
        for args_str in matches:
            arg_matches = re.findall(r"'([^']*(?:\\.[^']*)*)'", args_str)
            
            if len(arg_matches) >= 8:
                # Unescape JS escaping
                def unescape_js(s):
                    return s.replace("\\'", "'").replace('\\"', '"')
                    
                company_name = unescape_js(arg_matches[0])
                website = unescape_js(arg_matches[1])
                phone = unescape_js(arg_matches[2])
                email = unescape_js(arg_matches[3])
                address = unescape_js(arg_matches[4])
                company_type = unescape_js(arg_matches[5])
                prod_cat = unescape_js(arg_matches[6])
                prod_name = unescape_js(arg_matches[7])
                
                # Recover lat/lon from cache since we don't store it in openSidebar
                # But address is unique key usually
                lat = None
                lon = None
                
                # Try to find coord in cache
                addr_lower = address.lower().strip()
                if addr_lower in geocode_cache:
                    lat = geocode_cache[addr_lower].get('lat')
                    lon = geocode_cache[addr_lower].get('lon')
                
                data.append({
                    "Company Name": company_name,
                    "Website URL": website,
                    "Phone Number": phone,
                    "Email ID": email,
                    "Address": address,
                    "Company Type": company_type,
                    "Product Category": prod_cat,
                    "Product Name": prod_name,
                    "City": extract_city(address), 
                    "State": extract_state(address), 
                    "Country": extract_country(address), 
                    "lat": lat,
                    "lon": lon
                })

    except Exception as e:
        print(f"[WARN] Error extracting data from HTML: {e}")
        return pd.DataFrame()
        
    return pd.DataFrame(data)

def extract_city(addr):
    parts = addr.split(',')
    if len(parts) >= 2: return parts[-2].strip()
    return ""

def extract_state(addr):
    return ""

def extract_country(addr):
    parts = addr.split(',')
    if len(parts) >= 1: return parts[-1].strip()
    return ""

def generate_map_incremental(input_data, geocode_cache, output_html, override_total=None):
    """
    Generate map incrementally using input CSV/DataFrame and current geocode cache.
    Includes filter functionality for city, country, and company type.
    """
    # Load input data
    if isinstance(input_data, str):
        if os.path.exists(input_data):
            df = pd.read_csv(input_data)
        else:
            print(f"[ERR] Input file not found: {input_data}")
            return
    elif isinstance(input_data, pd.DataFrame):
        df = input_data
    else:
        print("[ERR] Invalid input data type")
        return
    
    # Create address column if not exists (logic for CSV input)
    if "address" not in df.columns:
        address_parts = []
        for col in ['Address', 'City', 'Country']:
            if col in df.columns:
                address_parts.append(df[col].fillna('').astype(str).str.strip())
            else:
                address_parts.append(pd.Series([''] * len(df)))
        
        df["address"] = address_parts[0]
        for part in address_parts[1:]:
            df["address"] = df["address"] + part.apply(lambda x: f", {x}" if x else "")
        df["address"] = df["address"].str.strip().str.lower()
    
    # Check for latitude/longitude columns in CSV (case-insensitive)
    lat_col = None
    lon_col = None
    for col in df.columns:
        col_lower = col.lower().strip()
        if col_lower in ['latitude', 'lat']:
            lat_col = col
        elif col_lower in ['longitude', 'lon', 'long']:
            lon_col = col
    
    # Use coordinates from CSV if available, otherwise use geocode cache
    if lat_col and lon_col:
        print(f"    [INFO] Using coordinates from columns: {lat_col}, {lon_col}")
        if "lat" not in df.columns or df["lat"].isna().all():
             df["lat"] = pd.to_numeric(df[lat_col], errors='coerce')
        if "lon" not in df.columns or df["lon"].isna().all():
             df["lon"] = pd.to_numeric(df[lon_col], errors='coerce')
             
        # For rows without valid coordinates, fall back to geocode cache
        mask = df["lat"].isna() | df["lon"].isna()
        # Explicitly cast to numeric to avoid FutureWarning
        new_lats = df.loc[mask, "address"].apply(lambda addr: geocode_cache.get(addr, {}).get("lat"))
        new_lons = df.loc[mask, "address"].apply(lambda addr: geocode_cache.get(addr, {}).get("lon"))
        df.loc[mask, "lat"] = pd.to_numeric(new_lats, errors='coerce')
        df.loc[mask, "lon"] = pd.to_numeric(new_lons, errors='coerce')
    else:
        # No lat/lon columns in CSV, use geocode cache
        if "lat" not in df.columns:
            df["lat"] = None
        if "lon" not in df.columns:
            df["lon"] = None
            
        mask = df["lat"].isna() | df["lon"].isna()
        new_lats = df.loc[mask, "address"].apply(lambda addr: geocode_cache.get(addr, {}).get("lat"))
        new_lons = df.loc[mask, "address"].apply(lambda addr: geocode_cache.get(addr, {}).get("lon"))
        df.loc[mask, "lat"] = pd.to_numeric(new_lats, errors='coerce')
        df.loc[mask, "lon"] = pd.to_numeric(new_lons, errors='coerce')
    
    # Remove rows without coordinates
    df_with_coords = df.dropna(subset=["lat", "lon"])
    
    # Use override_total if provided (to show full master count while mapping only delta)
    total_rows = override_total if override_total is not None else len(df_with_coords)
    
    if total_rows == 0:
        print("    [WARN] No coordinates found yet, skipping map generation")
        return
    
    # Clean function
    def clean(val):
        return str(val) if pd.notna(val) and str(val).strip() != "" else "Not available"
    
    # Collect unique values for filters (properly handle DataFrame columns)
    def get_unique_values(df, column_name):
        if column_name in df.columns:
            values = df[column_name].dropna().astype(str).str.strip()
            unique_vals = sorted(set(v for v in values if v and v.lower() != 'not available'))
            return unique_vals
        return []

    # Collect unique items from comma-separated strings
    def get_unique_items(df, column_name, exclude_geo=False, states_list=None):
        items = set()
        if column_name in df.columns:
             for val in df[column_name].dropna().astype(str):
                for item in val.split(','):
                    cleaned = item.strip().strip("'").strip('"').strip()
                    
                    if not cleaned or cleaned.lower() in ['not available', 'nan', 'none']:
                        continue
                    if '@' in cleaned:
                        continue
                    digits_only = re.sub(r'[\s\-\+\(\)\.]', '', cleaned)
                    if len(digits_only) > 6 and digits_only.isdigit():
                        continue
                    if re.match(r'^[\d,\.]+$', cleaned):
                        continue
                        
                    if exclude_geo:
                        cleaned_lower = cleaned.lower()
                        if cleaned_lower in [c.lower() for c in COUNTRIES]:
                            continue
                        if cleaned_lower in [c.lower() for c in CITIES]:
                            continue
                        if states_list and cleaned_lower in [s.lower() for s in states_list]:
                            continue
                        
                    items.add(cleaned)
        return sorted(list(items))
    
    cities = CITIES
    countries = COUNTRIES
    
    states = get_unique_items(df_with_coords, "State")
    
    company_types = [
        "Manufacturer", "Distributor", "Supplier", "Trader", "Exporter", 
        "Importer", "Wholesaler", "Retailer", "Producer", "Processor",
        "Refiner", "Contractor", "Consultant", "Research & Development",
        "Service Provider", "Agent", "Dealer", "Stockist", "Fabricator",
        "Engineering Company", "Pharmaceutical Company"
    ]
    company_types = sorted(set(company_types)) 

    product_categories = get_unique_items(df_with_coords, "Product Category", exclude_geo=True, states_list=states)
    product_names = get_unique_items(df_with_coords, "Product Name", exclude_geo=True, states_list=states)
    
    industries = get_unique_items(df_with_coords, "Industry")
    if not industries:
        industries = ["Chemicals", "Textile", "Paper"] 
    
    # --- DECK.GL IMPLEMENTATION (Replaces Folium) ---
    full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chemical Companies Global Map</title>
    <script src="https://unpkg.com/deck.gl@latest/dist.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Arial, sans-serif; overflow: hidden; }}
        #map-container {{ width: 100vw; height: 100vh; position: relative; }}
{sidebar_html}
    </style>
</head>
<body>
    <div id="sidebar">
        <div id="sidebar-content">
            {generate_sidebar_content(
                city_options, state_options, country_options,
                product_category_options, product_name_options,
                type_checkboxes, industry_radios,
                total_rows
            )}
        </div>
    </div>
    <div id="map-container"></div>
    <div style="position: fixed; top: 10px; left: 50%; transform: translateX(-50%); background-color: rgba(255, 255, 255, 0.95); border: 2px solid #4a9d5f; border-radius: 8px; z-index: 9999; padding: 10px 20px; box-shadow: 0 4px 8px rgba(0,0,0,0.2);">
        <h3 style="margin: 0; color: #2d5f3f;">🧪 Chemical Companies Global Map</h3>
        <p style="margin: 4px 0 0; font-size: 12px; color: #4a9d5f;">Use filters on left | Click marker for details | Total: {total_rows} companies</p>
    </div>
    <script>
        var totalMarkers = {total_rows};
        var markerDataFull = {marker_data_json};
        var BATCH_SIZE = 5000;
        var currentFilteredData = [];
        var selectedFile = null;
        var uploadedColumns = [];
        var standardColumns = ['Company Name', 'Industry', 'Website URL', 'Company Linkedin Url', 'Company Type', 'Product Category', 'City', 'State', 'Country', 'Address', 'Latitude', 'Longitude', 'Phone Number', 'Annual Revenue'];
        var allTypeKeywords = {type_keywords_json};
        var allStateKeywords = {state_keywords_json};
        var allCityKeywords = {city_keywords_json};
        var allCountryKeywords = {country_keywords_json};
        var allProductCategoryKeywords = {product_category_keywords_json};
        var allProductNameKeywords = {product_name_keywords_json};
        var stateCountryMap = {state_country_map_json};
        
        var deckgl = new deck.DeckGL({{
            container: 'map-container',
            mapStyle: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
            initialViewState: {{ longitude: 78, latitude: 20, zoom: 3, pitch: 0, bearing: 0 }},
            controller: true,
            layers: []
        }});
        
        function createMarkerLayer(data) {{
            return new deck.ScatterplotLayer({{
                id: 'companies',
                data: data,
                getPosition: d => [d.lon, d.lat],
                getRadius: 50000,
                getFillColor: [68, 157, 95],
                getLineColor: [45, 95, 63],
                lineWidthMinPixels: 1,
                pickable: true,
                onClick: (info) => {{ if (info.object) updateSidebarDetails(info.object); }}
            }});
        }}
        
        function renderMarkers(data) {{
            const layer = createMarkerLayer(data);
            deckgl.setProps({{ layers: [layer] }});
        }}
        
        function updateSidebarDetails(company) {{
            document.getElementById('company-name').textContent = company.name || 'Not available';
            const website = company.website || 'Not available';
            if (website !== 'Not available' && website) {{ document.getElementById('company-website').innerHTML = '<a href="' + website + '" target="_blank">' + website + '</a>'; }} else {{ document.getElementById('company-website').textContent = 'Not available'; }}
            const phone = company.phone || 'Not available';
            if (phone !== 'Not available' && phone) {{ document.getElementById('company-phone').innerHTML = '<a href="tel:' + phone + '">' + phone + '</a>'; }} else {{ document.getElementById('company-phone').textContent = 'Not available'; }}
            const email = company.email || 'Not available';
            if (email !== 'Not available' && email) {{ document.getElementById('company-email').innerHTML = '<a href="mailto:' + email + '">' + email + '</a>'; }} else {{ document.getElementById('company-email').textContent = 'Not available'; }}
            document.getElementById('company-address').textContent = company.address || 'Not available';
            document.getElementById('company-type').textContent = company.type || 'Not available';
            document.getElementById('product-category').textContent = company.category || 'Not available';
            document.getElementById('product-name').textContent = company.product || 'Not available';
            document.getElementById('company-revenue').textContent = company.revenue || 'Not available';
        }}
        
        document.addEventListener('DOMContentLoaded', function() {{
            currentFilteredData = markerDataFull;
            applyFilters();
        }});
        // ... (rest of JS functions for filters, upload, voice search)
        // City coordinates for zoom
        var cityCoords = {{
            "Mumbai": {{lat: 19.07, lon: 72.87, zoom: 11}},
            "Delhi": {{lat: 28.61, lon: 77.20, zoom: 11}},
            "New Delhi": {{lat: 28.61, lon: 77.20, zoom: 11}},
            "Bangalore": {{lat: 12.97, lon: 77.59, zoom: 11}},
            "Bengaluru": {{lat: 12.97, lon: 77.59, zoom: 11}},
            "Hyderabad": {{lat: 17.38, lon: 78.48, zoom: 11}},
            "Chennai": {{lat: 13.08, lon: 80.27, zoom: 11}},
            "Kolkata": {{lat: 22.57, lon: 88.36, zoom: 11}},
            "Pune": {{lat: 18.52, lon: 73.85, zoom: 11}},
            "Ahmedabad": {{lat: 23.02, lon: 72.57, zoom: 11}},
            "Vadodara": {{lat: 22.30, lon: 73.19, zoom: 11}},
            "Surat": {{lat: 21.17, lon: 72.83, zoom: 11}},
            "Jaipur": {{lat: 26.91, lon: 75.78, zoom: 11}},
            "Lucknow": {{lat: 26.84, lon: 80.94, zoom: 11}},
            "Nagpur": {{lat: 21.14, lon: 79.08, zoom: 11}},
            "Indore": {{lat: 22.71, lon: 75.85, zoom: 11}},
            "Bhopal": {{lat: 23.25, lon: 77.41, zoom: 11}},
            "Coimbatore": {{lat: 11.01, lon: 76.95, zoom: 11}},
            "Kochi": {{lat: 9.93, lon: 76.26, zoom: 11}},
            "Chandigarh": {{lat: 30.73, lon: 76.77, zoom: 11}},
            "Gurgaon": {{lat: 28.45, lon: 77.02, zoom: 11}},
            "Noida": {{lat: 28.53, lon: 77.39, zoom: 11}},
            "Thane": {{lat: 19.21, lon: 72.97, zoom: 11}},
            "Ankleshwar": {{lat: 21.62, lon: 73.00, zoom: 12}},
            "Vapi": {{lat: 20.37, lon: 72.90, zoom: 12}},
            "Bharuch": {{lat: 21.70, lon: 72.98, zoom: 12}},
            "Rajkot": {{lat: 22.30, lon: 70.80, zoom: 11}},
            "Nashik": {{lat: 19.99, lon: 73.78, zoom: 11}},
            "Aurangabad": {{lat: 19.87, lon: 75.34, zoom: 11}},
            "Faridabad": {{lat: 28.40, lon: 77.31, zoom: 11}},
            "Ghaziabad": {{lat: 28.66, lon: 77.43, zoom: 11}},
            "Kanpur": {{lat: 26.45, lon: 80.35, zoom: 11}},
            "Agra": {{lat: 27.17, lon: 78.01, zoom: 11}},
            "Varanasi": {{lat: 25.31, lon: 82.98, zoom: 11}},
            "Allahabad": {{lat: 25.43, lon: 81.84, zoom: 11}},
            "Meerut": {{lat: 28.98, lon: 77.71, zoom: 11}},
            "Jodhpur": {{lat: 26.28, lon: 73.02, zoom: 11}},
            "Madurai": {{lat: 9.92, lon: 78.11, zoom: 11}},
            "Jabalpur": {{lat: 23.18, lon: 79.93, zoom: 11}},
            "Gwalior": {{lat: 26.22, lon: 78.17, zoom: 11}},
            "Ludhiana": {{lat: 30.90, lon: 75.85, zoom: 11}},
            "Amritsar": {{lat: 31.63, lon: 74.87, zoom: 11}},
            "Patna": {{lat: 25.59, lon: 85.13, zoom: 11}},
            "Ranchi": {{lat: 23.35, lon: 85.33, zoom: 11}},
            "Dhanbad": {{lat: 23.79, lon: 86.43, zoom: 11}},
            "Raipur": {{lat: 21.25, lon: 81.63, zoom: 11}},
            "Visakhapatnam": {{lat: 17.68, lon: 83.21, zoom: 11}},
            "Vijayawada": {{lat: 16.50, lon: 80.65, zoom: 11}},
            "Srinagar": {{lat: 34.08, lon: 74.79, zoom: 11}},
            "New York": {{lat: 40.71, lon: -74.00, zoom: 11}},
            "Los Angeles": {{lat: 34.05, lon: -118.24, zoom: 10}},
            "Chicago": {{lat: 41.87, lon: -87.62, zoom: 11}},
            "Houston": {{lat: 29.76, lon: -95.36, zoom: 10}},
            "Phoenix": {{lat: 33.44, lon: -112.07, zoom: 10}},
            "Philadelphia": {{lat: 39.95, lon: -75.16, zoom: 11}},
            "San Antonio": {{lat: 29.42, lon: -98.49, zoom: 10}},
            "San Diego": {{lat: 32.71, lon: -117.16, zoom: 11}},
            "Dallas": {{lat: 32.77, lon: -96.79, zoom: 10}},
            "San Jose": {{lat: 37.33, lon: -121.88, zoom: 11}},
            "Austin": {{lat: 30.26, lon: -97.74, zoom: 11}},
            "Jacksonville": {{lat: 30.33, lon: -81.65, zoom: 10}},
            "San Francisco": {{lat: 37.77, lon: -122.41, zoom: 12}},
            "Seattle": {{lat: 47.60, lon: -122.33, zoom: 11}},
            "Denver": {{lat: 39.73, lon: -104.99, zoom: 11}},
            "Boston": {{lat: 42.36, lon: -71.05, zoom: 12}},
            "Atlanta": {{lat: 33.74, lon: -84.38, zoom: 11}},
            "Miami": {{lat: 25.76, lon: -80.19, zoom: 11}},
            "Washington DC": {{lat: 38.90, lon: -77.03, zoom: 12}},
            "Las Vegas": {{lat: 36.16, lon: -115.13, zoom: 11}},
            "London": {{lat: 51.50, lon: -0.12, zoom: 11}},
            "Birmingham": {{lat: 52.48, lon: -1.90, zoom: 11}},
            "Manchester": {{lat: 53.48, lon: -2.24, zoom: 11}},
            "Leeds": {{lat: 53.80, lon: -1.54, zoom: 11}},
            "Glasgow": {{lat: 55.86, lon: -4.25, zoom: 11}},
            "Liverpool": {{lat: 53.40, lon: -2.98, zoom: 11}},
            "Bristol": {{lat: 51.45, lon: -2.58, zoom: 11}},
            "Edinburgh": {{lat: 55.95, lon: -3.18, zoom: 11}},
            "Berlin": {{lat: 52.52, lon: 13.40, zoom: 11}},
            "Hamburg": {{lat: 53.55, lon: 9.99, zoom: 11}},
            "Munich": {{lat: 48.13, lon: 11.57, zoom: 11}},
            "Cologne": {{lat: 50.93, lon: 6.95, zoom: 11}},
            "Frankfurt": {{lat: 50.11, lon: 8.68, zoom: 11}},
            "Stuttgart": {{lat: 48.77, lon: 9.17, zoom: 11}},
            "Dusseldorf": {{lat: 51.22, lon: 6.77, zoom: 11}},
            "Dortmund": {{lat: 51.51, lon: 7.46, zoom: 11}},
            "Paris": {{lat: 48.85, lon: 2.35, zoom: 12}},
            "Marseille": {{lat: 43.29, lon: 5.36, zoom: 11}},
            "Lyon": {{lat: 45.76, lon: 4.83, zoom: 11}},
            "Toulouse": {{lat: 43.60, lon: 1.44, zoom: 11}},
            "Nice": {{lat: 43.71, lon: 7.26, zoom: 12}},
            "Nantes": {{lat: 47.21, lon: -1.55, zoom: 11}},
            "Strasbourg": {{lat: 48.57, lon: 7.75, zoom: 11}},
            "Bordeaux": {{lat: 44.83, lon: -0.57, zoom: 11}},
            "Beijing": {{lat: 39.90, lon: 116.40, zoom: 10}},
            "Shanghai": {{lat: 31.23, lon: 121.47, zoom: 10}},
            "Shenzhen": {{lat: 22.54, lon: 114.05, zoom: 11}},
            "Guangzhou": {{lat: 23.12, lon: 113.25, zoom: 10}},
            "Chengdu": {{lat: 30.57, lon: 104.06, zoom: 10}},
            "Hangzhou": {{lat: 30.29, lon: 120.16, zoom: 10}},
            "Wuhan": {{lat: 30.59, lon: 114.29, zoom: 10}},
            "Xian": {{lat: 34.26, lon: 108.94, zoom: 10}},
            "Tokyo": {{lat: 35.68, lon: 139.69, zoom: 11}},
            "Osaka": {{lat: 34.69, lon: 135.50, zoom: 11}},
            "Yokohama": {{lat: 35.44, lon: 139.63, zoom: 11}},
            "Nagoya": {{lat: 35.18, lon: 136.90, zoom: 11}},
            "Sapporo": {{lat: 43.06, lon: 141.35, zoom: 11}},
            "Kobe": {{lat: 34.69, lon: 135.19, zoom: 11}},
            "Kyoto": {{lat: 35.01, lon: 135.76, zoom: 11}},
            "Fukuoka": {{lat: 33.59, lon: 130.40, zoom: 11}},
            "Sydney": {{lat: -33.86, lon: 151.20, zoom: 11}},
            "Melbourne": {{lat: -37.81, lon: 144.96, zoom: 11}},
            "Brisbane": {{lat: -27.46, lon: 153.02, zoom: 11}},
            "Perth": {{lat: -31.95, lon: 115.86, zoom: 10}},
            "Adelaide": {{lat: -34.92, lon: 138.60, zoom: 11}},
            "Gold Coast": {{lat: -28.01, lon: 153.42, zoom: 11}},
            "Canberra": {{lat: -35.28, lon: 149.12, zoom: 11}},
            "Toronto": {{lat: 43.65, lon: -79.38, zoom: 11}},
            "Montreal": {{lat: 45.50, lon: -73.56, zoom: 11}},
            "Vancouver": {{lat: 49.28, lon: -123.12, zoom: 11}},
            "Calgary": {{lat: 51.04, lon: -114.07, zoom: 10}},
            "Edmonton": {{lat: 53.54, lon: -113.49, zoom: 10}},
            "Ottawa": {{lat: 45.42, lon: -75.69, zoom: 11}},
            "Winnipeg": {{lat: 49.89, lon: -97.13, zoom: 11}},
            "Dubai": {{lat: 25.20, lon: 55.27, zoom: 11}},
            "Singapore": {{lat: 1.35, lon: 103.82, zoom: 12}},
            "Hong Kong": {{lat: 22.39, lon: 114.10, zoom: 11}},
            "Bangkok": {{lat: 13.75, lon: 100.50, zoom: 11}},
            "Seoul": {{lat: 37.56, lon: 126.97, zoom: 11}},
            "Jakarta": {{lat: -6.20, lon: 106.84, zoom: 10}},
            "Manila": {{lat: 14.59, lon: 120.98, zoom: 11}},
            "Kuala Lumpur": {{lat: 3.13, lon: 101.68, zoom: 11}},
            "Moscow": {{lat: 55.75, lon: 37.61, zoom: 10}},
            "Istanbul": {{lat: 41.00, lon: 28.97, zoom: 10}},
            "Cairo": {{lat: 30.04, lon: 31.23, zoom: 10}},
            "Johannesburg": {{lat: -26.20, lon: 28.04, zoom: 10}},
            "Cape Town": {{lat: -33.92, lon: 18.42, zoom: 11}},
            "Lagos": {{lat: 6.52, lon: 3.37, zoom: 10}},
            "Nairobi": {{lat: -1.28, lon: 36.82, zoom: 11}},
            "Sao Paulo": {{lat: -23.55, lon: -46.63, zoom: 10}},
            "Rio de Janeiro": {{lat: -22.90, lon: -43.17, zoom: 11}},
            "Buenos Aires": {{lat: -34.60, lon: -58.38, zoom: 11}},
            "Mexico City": {{lat: 19.43, lon: -99.13, zoom: 10}},
            "Lima": {{lat: -12.04, lon: -77.02, zoom: 11}},
            "Bogota": {{lat: 4.71, lon: -74.07, zoom: 11}},
            "Amsterdam": {{lat: 52.36, lon: 4.89, zoom: 12}},
            "Brussels": {{lat: 50.85, lon: 4.35, zoom: 12}},
            "Vienna": {{lat: 48.20, lon: 16.36, zoom: 11}},
            "Zurich": {{lat: 47.37, lon: 8.54, zoom: 12}},
            "Geneva": {{lat: 46.20, lon: 6.14, zoom: 12}},
            "Stockholm": {{lat: 59.32, lon: 18.06, zoom: 11}},
            "Copenhagen": {{lat: 55.67, lon: 12.56, zoom: 11}},
            "Oslo": {{lat: 59.91, lon: 10.75, zoom: 11}},
            "Madrid": {{lat: 40.41, lon: -3.70, zoom: 11}},
            "Barcelona": {{lat: 41.38, lon: 2.17, zoom: 11}},
            "Rome": {{lat: 41.90, lon: 12.49, zoom: 11}},
            "Milan": {{lat: 45.46, lon: 9.18, zoom: 11}},
            "Athens": {{lat: 37.98, lon: 23.72, zoom: 11}},
            "Warsaw": {{lat: 52.22, lon: 21.01, zoom: 11}},
            "Prague": {{lat: 50.07, lon: 14.43, zoom: 11}},
            "Budapest": {{lat: 47.49, lon: 19.04, zoom: 11}}
        }};
        
        // State coordinates for zoom (with actual boundaries)
        var stateCoords = {{
            "Andhra Pradesh": {{bounds: [[12.62, 76.76], [19.92, 84.79]]}},
            "Arunachal Pradesh": {{bounds: [[26.65, 91.55], [29.47, 97.42]]}},
            "Assam": {{bounds: [[24.15, 89.69], [27.97, 96.02]]}},
            "Bihar": {{bounds: [[24.28, 83.32], [27.52, 88.30]]}},
            "Chhattisgarh": {{bounds: [[17.78, 80.24], [24.11, 84.40]]}},
            "Goa": {{bounds: [[14.90, 73.68], [15.80, 74.34]]}},
            "Gujarat": {{bounds: [[20.12, 68.16], [24.71, 74.48]]}},
            "Haryana": {{bounds: [[27.66, 74.46], [30.93, 77.60]]}},
            "Himachal Pradesh": {{bounds: [[30.38, 75.58], [33.26, 79.00]]}},
            "Jharkhand": {{bounds: [[21.97, 83.33], [25.35, 87.97]]}},
            "Karnataka": {{bounds: [[11.60, 74.06], [18.45, 78.59]]}},
            "Kerala": {{bounds: [[8.28, 74.86], [12.79, 77.42]]}},
            "Madhya Pradesh": {{bounds: [[21.07, 74.03], [26.87, 82.82]]}},
            "Maharashtra": {{bounds: [[15.60, 72.60], [22.03, 80.90]]}},
            "Manipur": {{bounds: [[23.83, 93.00], [25.69, 94.78]]}},
            "Meghalaya": {{bounds: [[25.03, 89.81], [26.12, 92.80]]}},
            "Mizoram": {{bounds: [[21.94, 92.26], [24.52, 93.44]]}},
            "Nagaland": {{bounds: [[25.20, 93.34], [27.04, 95.24]]}},
            "Odisha": {{bounds: [[17.78, 81.34], [22.57, 87.49]]}},
            "Punjab": {{bounds: [[29.53, 73.87], [32.51, 76.95]]}},
            "Rajasthan": {{bounds: [[23.06, 69.48], [30.19, 78.27]]}},
            "Sikkim": {{bounds: [[27.08, 88.00], [28.13, 88.95]]}},
            "Tamil Nadu": {{bounds: [[8.08, 76.23], [13.57, 80.35]]}},
            "Telangana": {{bounds: [[15.83, 77.27], [19.92, 81.33]]}},
            "Tripura": {{bounds: [[22.94, 91.09], [24.53, 92.34]]}},
            "Uttar Pradesh": {{bounds: [[23.87, 77.09], [30.41, 84.64]]}},
            "Uttarakhand": {{bounds: [[28.72, 77.58], [31.46, 81.03]]}},
            "West Bengal": {{bounds: [[21.53, 85.82], [27.22, 89.88]]}},
            "Delhi": {{bounds: [[28.40, 76.84], [28.88, 77.35]]}},
            "Chandigarh": {{bounds: [[30.67, 76.69], [30.79, 76.85]]}},
            "Puducherry": {{bounds: [[10.79, 79.61], [12.03, 79.86]]}}
        }};
        
        // Country coordinates for zoom (with actual boundaries)
        var countryCoords = {{
            "Afghanistan": {{bounds: [[29.37, 60.52], [38.49, 74.88]]}},
            "Albania": {{bounds: [[39.64, 19.26], [42.66, 21.05]]}},
            "Algeria": {{bounds: [[18.97, -8.67], [37.09, 11.98]]}},
            "Argentina": {{bounds: [[-55.06, -73.56], [-21.78, -53.59]]}},
            "Australia": {{bounds: [[-43.64, 113.16], [-10.69, 153.64]]}},
            "Austria": {{bounds: [[46.38, 9.53], [49.02, 17.16]]}},
            "Bangladesh": {{bounds: [[20.74, 88.01], [26.63, 92.67]]}},
            "Belgium": {{bounds: [[49.50, 2.55], [51.50, 6.40]]}},
            "Brazil": {{bounds: [[-33.75, -73.98], [5.27, -34.79]]}},
            "Canada": {{bounds: [[41.68, -141.00], [83.11, -52.62]]}},
            "Chile": {{bounds: [[-55.98, -75.64], [-17.51, -66.42]]}},
            "China": {{bounds: [[18.16, 73.50], [53.56, 134.77]]}},
            "Colombia": {{bounds: [[-4.22, -79.00], [13.39, -66.87]]}},
            "Czech Republic": {{bounds: [[48.55, 12.09], [51.06, 18.86]]}},
            "Denmark": {{bounds: [[54.56, 8.07], [57.75, 15.19]]}},
            "Egypt": {{bounds: [[22.00, 24.70], [31.67, 36.90]]}},
            "Finland": {{bounds: [[59.81, 20.55], [70.09, 31.59]]}},
            "France": {{bounds: [[41.33, -5.14], [51.09, 9.56]]}},
            "Germany": {{bounds: [[47.27, 5.87], [55.06, 15.04]]}},
            "Greece": {{bounds: [[34.80, 19.37], [41.75, 29.65]]}},
            "Hungary": {{bounds: [[45.74, 16.11], [48.58, 22.90]]}},
            "India": {{bounds: [[6.75, 68.16], [35.50, 97.40]]}},
            "Indonesia": {{bounds: [[-10.94, 95.01], [5.91, 141.02]]}},
            "Iran": {{bounds: [[25.06, 44.04], [39.78, 63.32]]}},
            "Iraq": {{bounds: [[29.06, 38.79], [37.38, 48.56]]}},
            "Ireland": {{bounds: [[51.42, -10.48], [55.38, -6.00]]}},
            "Israel": {{bounds: [[29.50, 34.27], [33.29, 35.89]]}},
            "Italy": {{bounds: [[36.65, 6.63], [47.09, 18.52]]}},
            "Japan": {{bounds: [[24.25, 122.94], [45.52, 153.99]]}},
            "Kenya": {{bounds: [[-4.68, 33.91], [5.03, 41.90]]}},
            "Kuwait": {{bounds: [[28.53, 46.55], [30.10, 48.43]]}},
            "Malaysia": {{bounds: [[0.86, 99.64], [7.36, 119.27]]}},
            "Mexico": {{bounds: [[14.53, -118.36], [32.72, -86.71]]}},
            "Morocco": {{bounds: [[27.67, -13.17], [35.93, -1.03]]}},
            "Nepal": {{bounds: [[26.35, 80.06], [30.45, 88.20]]}},
            "Netherlands": {{bounds: [[50.75, 3.36], [53.47, 7.21]]}},
            "New Zealand": {{bounds: [[-47.29, 166.43], [-34.39, 178.52]]}},
            "Nigeria": {{bounds: [[4.27, 2.69], [13.89, 14.68]]}},
            "Norway": {{bounds: [[57.98, 4.65], [71.19, 31.08]]}},
            "Pakistan": {{bounds: [[23.69, 60.87], [37.10, 77.84]]}},
            "Peru": {{bounds: [[-18.35, -81.33], [-0.04, -68.65]]}},
            "Philippines": {{bounds: [[4.59, 116.93], [21.12, 126.60]]}},
            "Poland": {{bounds: [[49.00, 14.12], [54.84, 24.15]]}},
            "Portugal": {{bounds: [[36.96, -9.50], [42.15, -6.19]]}},
            "Qatar": {{bounds: [[24.47, 50.75], [26.15, 51.64]]}},
            "Romania": {{bounds: [[43.62, 20.26], [48.27, 29.69]]}},
            "Russia": {{bounds: [[41.19, 19.64], [81.86, 180.00]]}},
            "Saudi Arabia": {{bounds: [[16.38, 34.57], [32.16, 55.67]]}},
            "Singapore": {{bounds: [[1.26, 103.60], [1.47, 104.09]]}},
            "South Africa": {{bounds: [[-34.84, 16.46], [-22.13, 32.89]]}},
            "South Korea": {{bounds: [[33.19, 125.89], [38.61, 129.58]]}},
            "Spain": {{bounds: [[35.95, -9.30], [43.75, 4.33]]}},
            "Sri Lanka": {{bounds: [[5.92, 79.65], [9.84, 81.88]]}},
            "Sweden": {{bounds: [[55.34, 11.11], [69.06, 24.16]]}},
            "Switzerland": {{bounds: [[45.82, 5.96], [47.81, 10.49]]}},
            "Taiwan": {{bounds: [[21.90, 120.00], [25.30, 122.00]]}},
            "Thailand": {{bounds: [[5.61, 97.35], [20.46, 105.64]]}},
            "Turkey": {{bounds: [[35.82, 25.66], [42.11, 44.79]]}},
            "Ukraine": {{bounds: [[44.39, 22.14], [52.38, 40.23]]}},
            "United Arab Emirates": {{bounds: [[22.63, 51.58], [26.08, 56.38]]}},
            "United Kingdom": {{bounds: [[49.87, -8.18], [60.86, 1.77]]}},
            "United States": {{bounds: [[24.52, -124.73], [49.38, -66.95]]}},
            "Vietnam": {{bounds: [[8.56, 102.14], [23.39, 109.47]]}},
            "Maharashtra": {{bounds: [[15.60, 72.60], [22.03, 80.90]]}}
        }};
        
        // Get map reference
        var map = null;
        document.addEventListener('DOMContentLoaded', function() {{
            setTimeout(function() {{
                var mapContainer = document.querySelector('.folium-map');
                if (mapContainer && mapContainer._leaflet_map) {{
                    map = mapContainer._leaflet_map;
                }} else {{
                    // Try alternative method
                    for (var key in window) {{
                        if (window[key] instanceof L.Map) {{
                            map = window[key];
                            break;
                        }}
                    }}
                }}
                // Initialize counter with actual marker count
                document.getElementById('visible-count').textContent = markerDataFull.length;
            }}, 1000);
        }});
    </script>
    """
    m.get_root().html.add_child(folium.Element(sidebar_html))

    m.save(output_html)
    print(f"    [OK] Map generated with {total_rows} markers and filters for {len(cities)} cities, {len(countries)} countries, {len(company_types)} company types")

def generate_map_from_json(csv_file, output_html):
    """
    Generate map using data from CSV and geocode cache from JSON.
    """
    cache = load_geocode_cache()
    generate_map_incremental(csv_file, cache, output_html)

# Keep old function name for compatibility
def generate_map(csv_file, output_html):
    """Legacy function - calls the new JSON-based version."""
    generate_map_from_json(csv_file, output_html)

