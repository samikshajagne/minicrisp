# Mini Crisp

## Prerequisites
- Python 3.10+
- Windows (Powershell)

## Setup
1. Create a virtual environment:
   ```powershell
   python -m venv .venv
   ```

2. Activate the virtual environment:
   ```powershell
   .\.venv\Scripts\activate
   ```

3. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

## Running the Application
To start the server:
```powershell
.\.venv\Scripts\activate
python main.py
```
The application will be available at [http://localhost:8000](http://localhost:8000).

## Development Mode (Auto-reload)
If you want the server to restart automatically when you change code:
```powershell
.\.venv\Scripts\activate
uvicorn main:app --reload
```
