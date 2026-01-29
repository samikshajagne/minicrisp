
import os

file_path = "d:/anticrisp/templates/map_dashboard.html"

try:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_content = content.replace('src="voice_search_logic.js"', 'src="/static/map_app/voice_search_logic.js"')
    new_content = new_content.replace('src="./voice_search_logic.js"', 'src="/static/map_app/voice_search_logic.js"')
    new_content = new_content.replace('src="image.png"', 'src="/static/map_app/image.png"')
    new_content = new_content.replace('src="./image.png"', 'src="/static/map_app/image.png"')

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    
    print("Migration successful")

except Exception as e:
    print(f"Error: {e}")
