import folium
import pandas as pd
import json
import os
import re

# Major cities from around the world
CITIES = [
    "Mumbai", "Delhi", "New Delhi", "Bangalore", "Bengaluru", "Hyderabad", "Chennai", "Kolkata",
    "Pune", "Ahmedabad", "Surat", "Jaipur", "Lucknow", "Kanpur", "Nagpur", "Indore", "Thane",
    "Bhopal", "Visakhapatnam", "Patna", "Vadodara", "Ghaziabad", "Ludhiana", "Agra", "Nashik",
    "Faridabad", "Meerut", "Rajkot", "Varanasi", "Srinagar", "Aurangabad", "Dhanbad", "Amritsar",
    "Allahabad", "Ranchi", "Coimbatore", "Jabalpur", "Gwalior", "Vijayawada", "Jodhpur", "Madurai",
    "Raipur", "Kochi", "Chandigarh", "Gurgaon", "Noida", "Vapi", "Ankleshwar", "Bharuch",
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia", "San Antonio",
    "San Diego", "Dallas", "San Jose", "Austin", "Jacksonville", "San Francisco", "Seattle",
    "Denver", "Boston", "Atlanta", "Miami", "Washington DC", "Las Vegas",
    "London", "Birmingham", "Manchester", "Leeds", "Glasgow", "Liverpool", "Bristol", "Edinburgh",
    "Berlin", "Hamburg", "Munich", "Cologne", "Frankfurt", "Stuttgart", "Dusseldorf", "Dortmund",
    "Paris", "Marseille", "Lyon", "Toulouse", "Nice", "Nantes", "Strasbourg", "Bordeaux",
    "Beijing", "Shanghai", "Shenzhen", "Guangzhou", "Chengdu", "Hangzhou", "Wuhan", "Xian",
    "Tokyo", "Osaka", "Yokohama", "Nagoya", "Sapporo", "Kobe", "Kyoto", "Fukuoka",
    "Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide", "Gold Coast", "Canberra",
    "Toronto", "Montreal", "Vancouver", "Calgary", "Edmonton", "Ottawa", "Winnipeg",
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
    "Central African Republic", "Chad", "Chile", "China", "Colombia", "Comoros", "Congo", "Costa Rica", 
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

def get_sidebar_html(
    city_options,
    state_options,
    country_options,
    product_category_options,
    product_name_options,
    type_checkboxes,
    industry_radios,
    total_rows
):
    return f"""
<div id="sidebar">
  <div id="sidebar-content">

    <!-- Upload Section -->
    <div class="upload-section">
      <span class="upload-label">📤 Upload & Map CSV Data</span>
      <input type="file" id="csv-file-input" accept=".csv" />
      <small id="upload-status">Select a CSV file</small>
    </div>

    <!-- Industry Filter -->
    <div id="industry-header" onclick="toggleIndustry()">
      <h3>🏭 Industry <span id="industry-toggle">▲</span></h3>
    </div>
    <div id="industry-container">
      {industry_radios}
    </div>

    <!-- Filters -->
    <div id="filter-header" onclick="toggleFilters()">
      <h3>🔍 Filters <span id="filter-toggle">▼</span></h3>
    </div>

    <div id="filter-container">
      <select id="filter-city">{city_options}</select>
      <select id="filter-state">{state_options}</select>
      <select id="filter-country">{country_options}</select>
      <select id="filter-product-category">{product_category_options}</select>
      <select id="filter-product-name">{product_name_options}</select>

      <div id="type-checkboxes">
        {type_checkboxes}
      </div>

      <button onclick="resetFilters()">Reset Filters</button>
    </div>

    <!-- Company Details -->
    <div class="company-details">
      <h4>📋 Company Details</h4>
      <div><b>Name:</b> <span id="company-name"></span></div>
      <div><b>Website:</b> <span id="company-website"></span></div>
      <div><b>Phone:</b> <span id="company-phone"></span></div>
      <div><b>Email:</b> <span id="company-email"></span></div>
      <div><b>Address:</b> <span id="company-address"></span></div>
      <div><b>Type:</b> <span id="company-type"></span></div>
      <div><b>Category:</b> <span id="product-category"></span></div>
      <div><b>Product:</b> <span id="product-name"></span></div>
      <div><b>Revenue:</b> <span id="company-revenue"></span></div>
    </div>

    <div class="filter-count">
      Total Companies: <b>{total_rows}</b>
    </div>

  </div>
</div>
"""

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
    
    # Create address column if not exists
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
             
        mask = df["lat"].isna() | df["lon"].isna()
        new_lats = df.loc[mask, "address"].apply(lambda addr: geocode_cache.get(addr, {}).get("lat"))
        new_lons = df.loc[mask, "address"].apply(lambda addr: geocode_cache.get(addr, {}).get("lon"))
        df.loc[mask, "lat"] = pd.to_numeric(new_lats, errors='coerce')
        df.loc[mask, "lon"] = pd.to_numeric(new_lons, errors='coerce')
    else:
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
    
    # Prepare filter options
    def get_unique_items(df, column_name, exclude_geo=False, states_list=None):
        items = set()
        if column_name in df.columns:
             for val in df[column_name].dropna().astype(str):
                for item in val.split(','):
                    cleaned = item.strip().strip("'").strip('"').strip()
                    if not cleaned or cleaned.lower() in ['not available', 'nan', 'none']: continue
                    if '@' in cleaned: continue
                    digits_only = re.sub(r'[\s\-\+\(\)\.]', '', cleaned)
                    if len(digits_only) > 6 and digits_only.isdigit(): continue
                    if re.match(r'^[\d,\.]+$', cleaned): continue
                    if exclude_geo:
                        cleaned_lower = cleaned.lower()
                        if cleaned_lower in [c.lower() for c in COUNTRIES]: continue
                        if cleaned_lower in [c.lower() for c in CITIES]: continue
                        if states_list and cleaned_lower in [s.lower() for s in states_list]: continue
                    items.add(cleaned)
        return sorted(list(items))
    
    cities = CITIES
    countries = COUNTRIES
    states = get_unique_items(df_with_coords, "State")
    
    company_types = sorted(list({
        "Manufacturer", "Distributor", "Supplier", "Trader", "Exporter", 
        "Importer", "Wholesaler", "Retailer", "Producer", "Processor",
        "Refiner", "Contractor", "Consultant", "Research & Development",
        "Service Provider", "Agent", "Dealer", "Stockist", "Fabricator",
        "Engineering Company", "Pharmaceutical Company"
    }))

    product_categories = get_unique_items(df_with_coords, "Product Category", exclude_geo=True, states_list=states)
    product_names = get_unique_items(df_with_coords, "Product Name", exclude_geo=True, states_list=states)
    industries = get_unique_items(df_with_coords, "Industry")
    if not industries: industries = ["Chemicals", "Textile", "Paper"]

    # Generate Options HTML
    city_options = '<option value="">All Cities</option>\n' + '\n'.join(f'<option value="{c}">{c}</option>' for c in cities)
    country_options = '<option value="">All Countries</option>\n' + '\n'.join(f'<option value="{c}">{c}</option>' for c in countries)
    state_options = '<option value="">All States</option>\n' + '\n'.join(f'<option value="{s}">{s}</option>' for s in states)
    product_category_options = '<option value="">All Product Categories</option>\n' + '\n'.join(f'<option value="{c}">{c}</option>' for c in product_categories)
    product_name_options = '<option value="">All Products</option>\n' + '\n'.join(f'<option value="{p}">{p}</option>' for p in product_names)
    
    type_checkboxes = '\n'.join(f'<label><input type="checkbox" class="type-checkbox" value="{c}" onchange="applyFilters()"> {c}</label>' for c in company_types)
    
    industry_radios = '<label><input type="radio" name="industry" value="" checked onchange="applyFilters()"> All Industries</label>\n'
    for ind in industries:
        industry_radios += f'<label><input type="radio" name="industry" value="{ind.lower()}" onchange="applyFilters()"> {ind}</label>\n'

    # Get Sidebar HTML
    sidebar_html = get_sidebar_html(
        city_options, state_options, country_options,
        product_category_options, product_name_options,
        type_checkboxes, industry_radios, total_rows
    )

    # Clean function
    def clean(val):
        return str(val) if pd.notna(val) and str(val).strip() != "" else "Not available"

    # Prepare marker data
    marker_data_full = []
    for idx, row in df_with_coords.iterrows():
        marker_data_full.append({
            "name": clean(row.get("Company Name", "Chemical Company")),
            "website": clean(row.get("Website URL", "")),
            "phone": clean(row.get("Phone Number", "")),
            "email": clean(row.get("Email ID", "")),
            "address": clean(row.get("Address", "")),
            "city": clean(row.get("City", "")),
            "state": clean(row.get("State", "")),
            "country": clean(row.get("Country", "")),
            "type": clean(row.get("Company Type", "")),
            "category": clean(row.get("Product Category", "")),
            "product": clean(row.get("Product Name", "")),
            "industry": clean(row.get("Industry", "")),
            "revenue": clean(row.get("Annual Revenue", "")),
            "lat": float(row["lat"]),
            "lon": float(row["lon"])
        })
    marker_data_json = json.dumps(marker_data_full)
    
    # State-Country Map
    state_to_country = {}
    if "State" in df_with_coords.columns and "Country" in df_with_coords.columns:
        temp_df = df_with_coords[["State", "Country"]].dropna().drop_duplicates()
        for _, row in temp_df.iterrows():
            s_val = str(row["State"]).strip()
            c_val = str(row["Country"]).strip()
            if s_val and c_val:
                for s_part in s_val.split(','):
                    s_clean = s_part.strip()
                    if s_clean and s_clean.lower() != 'not available':
                        state_to_country[s_clean] = c_val
    state_country_map_json = json.dumps(state_to_country)

    # Keywords for search
    type_keywords_json = json.dumps({t.lower(): t for t in company_types})
    state_keywords_json = json.dumps({s.lower(): s for s in states})
    city_keywords_json = json.dumps({c.lower(): c for c in cities})
    country_keywords_json = json.dumps({c.lower(): c for c in countries})
    product_category_keywords_json = json.dumps({c.lower(): c for c in product_categories})
    product_name_keywords_json = json.dumps({p.lower(): p for p in product_names})

    # --- HTML with DECK.GL ---
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
        /* Sidebar Styles */
        #sidebar {{
            position: fixed; top: 0; left: 0; width: 350px; height: 100vh;
            background: white; border-right: 1px solid #ccc; z-index: 9998; overflow-y: auto;
        }}
        #sidebar-content {{ padding: 20px; }}
        .upload-section {{ background: #fff8e1; padding: 10px; margin-bottom: 10px; border: 1px solid #ffecb3; }}
        .filter-section {{ margin-bottom: 10px; }}
        select {{ width: 100%; padding: 5px; margin-bottom: 5px; }}
        .company-details div {{ margin-bottom: 5px; font-size: 13px; }}
    </style>
</head>
<body>
    {sidebar_html}
    <div id="map-container"></div>
    
    <script>
        var totalMarkers = {total_rows};
        var markerDataFull = {marker_data_json};
        var BATCH_SIZE = 5000;
        var currentFilteredData = [];
        
        var stateCountryMap = {state_country_map_json};
        var allTypeKeywords = {type_keywords_json};
        var allStateKeywords = {state_keywords_json};
        var allCityKeywords = {city_keywords_json};
        var allCountryKeywords = {country_keywords_json};
        var allProductCategoryKeywords = {product_category_keywords_json};
        var allProductNameKeywords = {product_name_keywords_json};
        
        // Define missing coordinate objects to prevent crash
        var cityCoords = {{
            "Mumbai": {{lat: 19.07, lon: 72.87, zoom: 11}},
            "Delhi": {{lat: 28.61, lon: 77.20, zoom: 11}},
            "New Delhi": {{lat: 28.61, lon: 77.20, zoom: 11}},
            "Geneva": {{lat: 46.20, lon: 6.14, zoom: 12}},
            "Stockholm": {{lat: 59.32, lon: 18.06, zoom: 12}}
        }};
        var stateCoords = {{}};
        var countryCoords = {{}};

        var deckgl = new deck.DeckGL({{
            container: 'map-container',
            mapStyle: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
            initialViewState: {{ longitude: 0, latitude: 20, zoom: 2 }},
            controller: true,
            layers: []
        }});
        
        function createMarkerLayer(data) {{
            return new deck.ScatterplotLayer({{
                id: 'companies',
                data: data,
                getPosition: d => [d.lon, d.lat],
                getRadius: 5000,
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
            document.getElementById('company-website').innerHTML = company.website ? `<a href="${{company.website}}" target="_blank">${{company.website}}</a>` : 'Not available';
            document.getElementById('company-phone').innerHTML = company.phone ? `<a href="tel:${{company.phone}}">${{company.phone}}</a>` : 'Not available';
            document.getElementById('company-email').innerHTML = company.email ? `<a href="mailto:${{company.email}}">${{company.email}}</a>` : 'Not available';
            document.getElementById('company-address').textContent = company.address || 'Not available';
            document.getElementById('company-type').textContent = company.type || 'Not available';
            document.getElementById('product-category').textContent = company.category || 'Not available';
            document.getElementById('product-name').textContent = company.product || 'Not available';
            document.getElementById('company-revenue').textContent = company.revenue || 'Not available';
        }}
        
        function toggleIndustry() {{
            var container = document.getElementById('industry-container');
            container.style.display = container.style.display === 'none' ? 'block' : 'none';
        }}
        function toggleFilters() {{
            var container = document.getElementById('filter-container');
            container.style.display = container.style.display === 'none' ? 'block' : 'none';
        }}
        function resetFilters() {{
            document.getElementById('filter-city').value = '';
            document.getElementById('filter-state').value = '';
            document.getElementById('filter-country').value = '';
            document.getElementById('filter-product-category').value = '';
            document.getElementById('filter-product-name').value = '';
            applyFilters();
        }}
        
        function applyFilters() {{
            // Minimal filter logic for demonstration
            var city = document.getElementById('filter-city').value;
            var state = document.getElementById('filter-state').value;
            var country = document.getElementById('filter-country').value;
            
            currentFilteredData = markerDataFull.filter(d => {{
                if (city && d.city !== city) return false;
                if (state && d.state !== state) return false;
                if (country && d.country !== country) return false;
                return true;
            }});
            
            renderMarkers(currentFilteredData);
        }}
        
        // Initialize
        document.addEventListener('DOMContentLoaded', function() {{
            currentFilteredData = markerDataFull;
            renderMarkers(currentFilteredData);
        }});
    </script>
</body>
</html>
"""
    
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(full_html)
    
    print(f"    [OK] Deck.gl map generated with {total_rows} markers")

if __name__ == "__main__":
    with open("debug_log.txt", "w") as log:
        log.write("Starting script...\n")
        try:
            if not os.path.exists("india1.csv"):
                log.write("Error: india1.csv not found\n")
            else:
                log.write("Found india1.csv. Reading...\n")
                df = pd.read_csv("india1.csv")
                log.write(f"Columns: {list(df.columns)}\n")
                generate_map_incremental(df, {}, "index.html")
                log.write("Finished generation.\n")
        except Exception as e:
            log.write(f"Exception: {e}\n")
