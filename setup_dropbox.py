import os
import requests
from dotenv import load_dotenv, set_key

def main():
    print("=== Dropbox Local OAuth Setup ===")
    
    # Load existing .env if any
    env_path = ".env"
    load_dotenv(env_path)
    
    app_key = os.getenv("DROPBOX_APP_KEY", "")
    if not app_key or app_key == "your_dropbox_app_key":
        app_key = input("Enter your Dropbox App Key: ").strip()
        if app_key:
            set_key(env_path, "DROPBOX_APP_KEY", app_key)
        
    app_secret = os.getenv("DROPBOX_APP_SECRET", "")
    if not app_secret or app_secret == "your_dropbox_app_secret":
        app_secret = input("Enter your Dropbox App Secret: ").strip()
        if app_secret:
            set_key(env_path, "DROPBOX_APP_SECRET", app_secret)
        
    if not app_key or not app_secret:
        print("Error: App Key and App Secret are required.")
        return

    # 1. Provide the Auth URL
    auth_url = f"https://www.dropbox.com/oauth2/authorize?client_id={app_key}&response_type=code&token_access_type=offline"
    print("\n" + "="*70)
    print("1. Go to this URL in your web browser:")
    print(auth_url)
    print("\n2. Click 'Allow' (you might need to log in first).")
    print("3. Copy the short Access Code it gives you.")
    print("="*70 + "\n")
    
    # 2. Get the Access Code from user
    access_code = input("Paste the Access Code here: ").strip()
    
    if not access_code:
        print("Error: Access Code is required.")
        return
        
    # 3. Exchange code for tokens
    print("\nExchanging code for Refresh Token...")
    token_url = "https://api.dropboxapi.com/oauth2/token"
    
    data = {
        "code": access_code,
        "grant_type": "authorization_code",
    }
    
    auth = (app_key, app_secret)
    
    try:
        response = requests.post(token_url, data=data, auth=auth)
        response.raise_for_status()
        
        token_data = response.json()
        refresh_token = token_data.get("refresh_token")
        
        if refresh_token:
            print("\nSUCCESS! Here is your Refresh Token:")
            print("-" * 50)
            print(refresh_token)
            print("-" * 50)
            
            # Save it
            set_key(env_path, "DROPBOX_REFRESH_TOKEN", refresh_token)
            print("\n✅ Saved DROPBOX_REFRESH_TOKEN to .env!")
            print("You can now run 'python main.py'!")
        else:
            print("\nError: The response did not contain a refresh token.")
            print("Response:", token_data)
            print("This usually happens if you used an access code twice. Try generating a new URL.")
            
    except requests.exceptions.HTTPError as e:
        print("\nFailed to get token!")
        print("Status Code:", e.response.status_code)
        print("Error Definition:", e.response.text)
    except Exception as e:
        print(f"\nAn error occurred: {e}")

if __name__ == "__main__":
    main()
