import pandas as pd
import shutil
import os

MASTER_FILE = 'master.csv'
import datetime

MASTER_FILE = 'master.csv'
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP_FILE = f'master_backup_{timestamp}.csv'

def remove_duplicates():
    if not os.path.exists(MASTER_FILE):
        print(f"Error: {MASTER_FILE} not found.")
        return

    # Create backup
    try:
        shutil.copy2(MASTER_FILE, BACKUP_FILE)
        print(f"Backup created at {BACKUP_FILE}")
    except Exception as e:
        print(f"Error creating backup: {e}")
        return

    try:
        df = pd.read_csv(MASTER_FILE)
        initial_count = len(df)
        print(f"Initial record count: {initial_count}")

        # Normalize for comparison (temporarily)
        # We need to handle potential mixed types or NaNs in 'Company Name' and 'Website'
        
        # Create a mask for duplicates
        # We want to identify duplicates based on Company Name OR Website.
        # However, simply dropping duplicates on specific subset columns keeps the *first* occurrence by default,
        # but standard drop_duplicates considers row a duplicate if ALL specified subset columns match.
        # That's NOT what we described. We said if Company Name matches OR Website matches.
        # One way is to identify duplicates for each criterion separately and then combine indices to drop.

        # 1. Duplicates by Company Name
        # clean names for better matching (strip, lower)
        # Note: We won't modify the original data for matching, just use a temp series
        names = df['Company Name'].astype(str).str.strip().str.lower()
        # Mark all duplicates as True (keep='first' marks 2nd+ as True)
        dup_names = names.duplicated(keep='first')
        
        # 2. Duplicates by Website
        # Ignore empty websites
        websites = df['Website'].astype(str).str.strip().str.lower()
        # Treat 'nan' or empty strings as non-duplicates for the purpose of matching (e.g. two rows with empty website are not duplicates of each other just because of that)
        # So replace 'nan', 'none', '' with unique values or just mask them out.
        # A safer way: Only check duplication where website is valid.
        
        # Filter out invalid websites for duplication check
        # common invalid entries seen in preview: "nan", empty
        valid_web_mask = ~websites.isin(['nan', 'none', '', 'not available'])
        
        # We only care about duplicates WHERE the website is valid
        # So we can calculate duplicates on the whole series, but only consider them if the website was valid.
        dup_websites_raw = websites.duplicated(keep='first')
        dup_websites = dup_websites_raw & valid_web_mask

        # Combine duplicate masks
        total_dups_mask = dup_names | dup_websites
        
        # Filter dataframe
        df_cleaned = df[~total_dups_mask]
        
        final_count = len(df_cleaned)
        removed_count = initial_count - final_count
        
        print(f"Final record count: {final_count}")
        print(f"Duplicates removed: {removed_count}")

            
        # Write back to CSV
        df_cleaned.to_csv(MASTER_FILE, index=False)
        print(f"Successfully cleaned duplicates and saved to {MASTER_FILE}")

    except Exception as e:
        print(f"An error occurred during processing: {e}")

if __name__ == "__main__":
    remove_duplicates()
