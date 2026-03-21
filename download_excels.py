"""
Script to automate downloading Excel files from nine websites.
Requires Selenium WebDriver and appropriate browser driver.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    TimeoutException,
)
import time
import os
from pathlib import Path
from typing import Dict, Optional, Any
from dotenv import load_dotenv


def download_excel_from_website(
    url: str,
    login_credentials: Dict[str, Any],
    download_path: str = "./downloads",
    button_text: str = "Descargar Excel",
    wait_timeout: int = 30,
    target_filename: Optional[str] = None,
    allow_insecure_download: bool = False,
) -> bool:
    """
    Navigates to a website, logs in, finds and clicks the download Excel button,
    and downloads the file locally.
    
    Args:
        url: The website URL to visit
        login_credentials: Dictionary with 'username' and 'password' keys
        download_path: Local directory path to save the downloaded file
        button_text: Text of the button to click (default: "Descargar excel")
        wait_timeout: Maximum time to wait for elements (in seconds)
        target_filename: Desired filename to rename the downloaded Excel file to
        allow_insecure_download: If True, disables Chrome's blocking of flagged downloads
    
    Returns:
        bool: True if download was successful, False otherwise
    """
    # Create download directory if it doesn't exist
    os.makedirs(download_path, exist_ok=True)
    
    # Configure Chrome options for downloads
    chrome_options = Options()
    # Normalize the path for ChromeDriver compatibility
    abs_download_path = os.path.abspath(download_path)
    # Ensure forward slashes for ChromeDriver on all platforms
    normalized_path = abs_download_path.replace('\\', '/')
    
    prefs = {
        "download.default_directory": normalized_path,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        # Let insecure downloads proceed when explicitly requested
        "safebrowsing.disable_download_protection": allow_insecure_download,
        "profile.default_content_setting_values.automatic_downloads": 1,
    }
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    if allow_insecure_download:
        chrome_options.add_argument("--safebrowsing-disable-download-protection")
        chrome_options.add_argument("--allow-running-insecure-content")
    
    driver = None
    try:
        # Initialize the WebDriver (Chrome)
        # webdriver-manager automatically handles ChromeDriver installation
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.maximize_window()

        try:
            driver.execute_cdp_cmd(
                "Page.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": abs_download_path},
            )
        except Exception as e:
            print(f"Warning: could not set download behavior via CDP: {e}")
        
        print(f"Navigating to {url}...")
        driver.get(url)
        
        # Wait for page to load
        time.sleep(2)
        
        # Find and fill login form
        print("Attempting to log in...")
        wait = WebDriverWait(driver, wait_timeout)

        # Prefer an explicit locator if provided in config
        username_field = None
        explicit_locator = login_credentials.get("username_locator")
        if explicit_locator:
            try:
                username_field = wait.until(EC.element_to_be_clickable(explicit_locator))
            except TimeoutException:
                print("Warning: explicit username locator did not resolve, falling back to guesses")

        # Try to find username/email field (common selectors)
        username_selectors = [
            "input[name='username']",
            "input[name='email']",
            "input[type='email']",
            "input[id*='user']",
            "input[id*='email']",
            "input[type='text']",
            # ASP.NET specific patterns
            "input[name*='txtEmail']",
            "input[id*='txtEmail']",
            "input[name*='MainContent']",
            "input[id*='MainContent']"
        ]
        
        for selector in username_selectors:
            try:
                username_field = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                if username_field.is_displayed():
                    break
            except:
                continue
        
        if not username_field:
            # Try by XPath with common patterns
            try:
                username_field = wait.until(
                    EC.presence_of_element_located((By.XPATH, "//input[contains(@placeholder, 'user') or contains(@placeholder, 'email') or contains(@placeholder, 'Email') or contains(@name, 'txtEmail') or contains(@id, 'txtEmail')]"))
                )
            except:
                print("Warning: Could not find username field automatically. You may need to customize the selector.")
                return False
        
        username_field.clear()
        username_field.send_keys(login_credentials['username'])
        
        # Find and fill password field (use explicit locator first if provided)
        password_field = None
        explicit_password = login_credentials.get("password_locator")
        if explicit_password:
            try:
                password_field = wait.until(EC.element_to_be_clickable(explicit_password))
            except TimeoutException:
                print("Warning: explicit password locator did not resolve, falling back to default selector")

        if not password_field:
            password_field = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        password_field.clear()
        password_field.send_keys(login_credentials['password'])

        # Find and click login button
        login_button = None
        explicit_login_btn = login_credentials.get("login_button_locator")
        if explicit_login_btn:
            try:
                login_button = wait.until(EC.element_to_be_clickable(explicit_login_btn))
            except TimeoutException:
                print("Warning: explicit login button locator did not resolve, falling back to guesses")

        login_button_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:contains('Login')",
            "button:contains('Iniciar')",
            "button:contains('Entrar')"
        ]

        for selector in login_button_selectors:
            try:
                login_button = driver.find_element(By.CSS_SELECTOR, selector)
                if login_button.is_displayed():
                    break
            except:
                continue
        
        if not login_button:
            # Try by text content
            try:
                login_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Login') or contains(text(), 'Iniciar') or contains(text(), 'Entrar')]")
            except:
                print("Warning: Could not find login button automatically. You may need to customize the selector.")
                return False
        
        login_button.click()
        
        # Wait for login to complete
        print("Waiting for login to complete...")
        time.sleep(5)  # Increased wait time to allow page to fully load
        
        # Scroll to top to ensure the page is in a consistent state
        # This helps make buttons visible that might be hidden due to scroll position
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)  # Wait for scroll to complete
        
        # Navigate to or find the download button
        print(f"Looking for button/link with text: '{button_text}'...")
        
        # Try multiple ways to find the button or link
        download_button = None
        
        # Method 1: <input type="submit"> with value attribute (most common for submit buttons)
        try:
            download_button = wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, f"//input[@type='submit' and @value='{button_text}']")
                )
            )
        except TimeoutException:
            pass
        except Exception:
            pass
        
        # Method 2: <input type="submit"> with value containing the text (case-insensitive)
        if not download_button:
            try:
                inputs = driver.find_elements(By.XPATH, "//input[@type='submit']")
                for inp in inputs:
                    if inp.get_attribute('value') and button_text.lower() in inp.get_attribute('value').lower():
                        download_button = inp
                        break
            except Exception:
                pass
        
        # Method 3: <button> containing the text
        if not download_button:
            try:
                download_button = wait.until(
                    EC.presence_of_element_located(
                        (By.XPATH, f"//button[contains(normalize-space(text()), '{button_text}')]")
                    )
                )
            except TimeoutException:
                pass
            except Exception:
                pass
        
        # Method 4: <a> link containing the text
        if not download_button:
            try:
                download_button = wait.until(
                    EC.presence_of_element_located(
                        (By.XPATH, f"//a[contains(normalize-space(text()), '{button_text}')]")
                    )
                )
            except TimeoutException:
                pass
            except Exception:
                pass
        
        # Method 5: link by (partial) link text
        if not download_button:
            try:
                download_button = wait.until(
                    EC.presence_of_element_located((By.LINK_TEXT, button_text))
                )
            except TimeoutException:
                pass
            except Exception:
                pass
        
        if not download_button:
            try:
                download_button = wait.until(
                    EC.presence_of_element_located((By.PARTIAL_LINK_TEXT, button_text))
                )
            except TimeoutException:
                pass
            except Exception:
                pass
        
        # Method 6: any clickable button with case-insensitive text match
        if not download_button:
            try:
                buttons = driver.find_elements(By.TAG_NAME, "button")
                for btn in buttons:
                    if button_text.lower() in btn.text.lower():
                        download_button = btn
                        break
            except Exception:
                pass
        
        # Method 7: Try finding by ID containing "DownloadExcel" or "cmdDownloadExcel" (backup for specific sites)
        if not download_button:
            try:
                download_button = wait.until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//input[@type='submit' and (contains(@id, 'DownloadExcel') or contains(@id, 'cmdDownloadExcel'))]")
                    )
                )
            except TimeoutException:
                pass
            except Exception:
                pass
        
        if not download_button:
            print(f"Error: Could not find button or link with text '{button_text}'")
            return False
        
        # Robust click: scroll into view and use JavaScript click to avoid overlay issues
        print("Clicking download button...")
        
        # Scroll the button into view (scroll up a bit to avoid totals section overlay)
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'start', inline: 'center', behavior: 'smooth'});",
            download_button,
        )
        time.sleep(1)  # Wait for scroll to complete
        
        # Scroll up a bit more to ensure the button is clear of any overlays below it
        driver.execute_script("window.scrollBy(0, -50);")
        time.sleep(0.5)
        
        # Ensure element is still in the DOM and visible
        try:
            # Verify element is still attached to DOM
            _ = download_button.is_displayed()
        except Exception:
            print("Warning: Button may not be visible, proceeding anyway...")
        
        # Use JavaScript click which bypasses overlay/interception issues
        try:
            driver.execute_script("arguments[0].click();", download_button)
            print("Successfully clicked using JavaScript")
        except Exception as js_e:
            # Fallback: try regular click if JS click fails
            print(f"JavaScript click failed, trying regular click: {js_e}")
            try:
                download_button.click()
            except (ElementClickInterceptedException, ElementNotInteractableException) as e:
                print(f"Regular click also failed: {e}")
                return False
        
        # Wait for download to complete by watching .crdownload temp files
        print("Waiting for download to complete...")
        start_time = time.time()
        initial_files = set(os.listdir(download_path))
        download_detected = False
        while time.time() - start_time < wait_timeout:
            current_files = os.listdir(download_path)
            cr_in_progress = [f for f in current_files if f.endswith('.crdownload')]
            if not cr_in_progress:
                new_files = set(current_files) - initial_files
                if new_files:
                    download_detected = True
                    break
                time.sleep(1)
                continue
            time.sleep(1)
        else:
            print("Warning: download may not have finished before timeout")

        if not download_detected:
            print("Warning: No new file detected in the download folder.")
            return False

        if target_filename:
            renamed = rename_latest_download(download_path, target_filename)
            if not renamed:
                print("Warning: Download completed, but could not rename the file.")
        
        print(f"Download completed! Files should be in: {os.path.abspath(download_path)}")
        return True
        
    except Exception as e:
        print(f"Error occurred: {str(e)}")
        return False
        
    finally:
        if driver:
            driver.quit()


def rename_latest_download(download_path: str, target_filename: str) -> bool:
    download_dir = os.path.abspath(download_path)
    try:
        entries = [
            os.path.join(download_dir, name)
            for name in os.listdir(download_dir)
            if not name.endswith(".crdownload")
            and name.lower().endswith((".xlsx", ".xls", ".xlsm"))
        ]
    except FileNotFoundError:
        return False

    files = [p for p in entries if os.path.isfile(p)]
    if not files:
        return False

    latest_path = max(files, key=os.path.getmtime)
    target_path = os.path.join(download_dir, target_filename)
    os.replace(latest_path, target_path)
    return True


def main():
    """
    Main function that calls the download function for nine websites.
    Configure your URLs and credentials here.
    """
    env_path = Path(__file__).with_name(".env")
    load_dotenv(dotenv_path=env_path)

    # Configuration for Website 1
    website1_config = {
        "url": "https://yauras-mayorista.cl/wholesale/",
        "credentials": {
            "username": "chiragmahtani9@gmail.com",
            "password": "CHIRAG01",
            "username_locator": (By.ID, "MainContent_txtEmail"),  # e.g. (By.ID, "MainContent_txtEmail")
            "password_locator": (By.ID, "MainContent_txtPassword"),
            "login_button_locator": (By.ID, "MainContent_cmdLogin")
        },
        "button_text": "Descargar Excel",  # You can customize this
        "target_filename": "Yauras.xlsx"
    }

    # Configuration for Website 2
    website2_config = {
        "url": "https://cosmetic-distribucion.cl/WholeSale/Login",  
        "credentials": {
            "username": "chiragmahtani9@gmail.com", 
            "password": "chirag024",
            "username_locator": (By.ID, "MainContent_txtEmail"),
            "password_locator": (By.ID, "MainContent_txtPassword"),
            "login_button_locator": (By.ID, "MainContent_cmdLogin")
        },
        "button_text": "Descargar Excel",  # You can customize this
        "target_filename": "Cosmetic Mayorista.xlsx"
    }

    # Configuration for Website 3
    website3_config = {
        "url": "https://pdlbodega.cl/wholesale/Login", 
        "credentials": {
            "username": "chiragmahtani9@gmail.com",
            "password": "Chirag1111",
            "username_locator": (By.ID, "MainContent_txtEmail"),
            "password_locator": (By.ID, "MainContent_txtPassword"),
            "login_button_locator": (By.ID, "MainContent_cmdLogin")
        },
        "button_text": "Descargar Excel",  # You can customize this
        "target_filename": "Productos de Lujo VIP.xlsx"
    }

    # Configuration for Website 4
    website4_config = {
        "url": "https://eliteperfumes-mayorista.cl/WholeSale/Login",  
        "credentials": {
            "username": "chiragmahtani9@gmail.com", 
            "password": "Chirag2021",
            "username_locator": (By.ID, "MainContent_txtEmail"),
            "password_locator": (By.ID, "MainContent_txtPassword"),
            "login_button_locator": (By.ID, "MainContent_cmdLogin")
        },
        "button_text": "Descargar Excel",  # You can customize this
        "target_filename": "ElitePerfumes Mayorista.xlsx"
    }

    # Configuration for Website 5
    website5_config = {
        "url": "https://www.iconic-distribucion.cl/wholesale/Login",  
        "credentials": {
            "username": "chiragmahtani9@gmail.com", 
            "password": "Mundoaroma556",
            "username_locator": (By.ID, "MainContent_txtEmail"),
            "password_locator": (By.ID, "MainContent_txtPassword"),
            "login_button_locator": (By.ID, "MainContent_cmdLogin")
        },
        "button_text": "Descargar Excel",  # You can customize this
        "target_filename": "Iconic Distribucion.xlsx"
    }

    # Configuration for Website 6
    website6_config = {
        "url": "https://elitebrands-mayorista.cl/wholesale/",  
        "credentials": {
            "username": "chiragmahtani9@gmail.com",  
            "password": "76208829-0",
            "username_locator": (By.ID, "MainContent_txtEmail"),
            "password_locator": (By.ID, "MainContent_txtPassword"),
            "login_button_locator": (By.ID, "MainContent_cmdLogin")
        },
        "button_text": "Descargar Excel",  # You can customize this
        "target_filename": "Elite Brands.xlsx"
    }

    # Configuration for Website 7
    website7_config = {
        "url": "https://www.silk-distribucion.cl/wholesale/Login",  
        "credentials": {
            "username": "chiragmahtani9@gmail.com",  
            "password": "chirag789",
            "username_locator": (By.ID, "MainContent_txtEmail"),
            "password_locator": (By.ID, "MainContent_txtPassword"),
            "login_button_locator": (By.ID, "MainContent_cmdLogin")
        },
        "button_text": "Descargar Excel",  # You can customize this
        "target_filename": "Silk Mayorista.xlsx"
    }


    # Download path for Excel files
    chile_download_path = os.path.abspath("./downloads")
    
    print("=" * 50)
    print("Starting Excel download automation...")
    print("=" * 50)

    # Download from Website 1
    print("\n[1/7] Processing Website 1...")
    success1 = download_excel_from_website(
        url=website1_config["url"],
        login_credentials=website1_config["credentials"],
        download_path=chile_download_path,
        button_text=website1_config["button_text"],
        target_filename=website1_config["target_filename"]
    )

    if success1:
        print("[OK] Website 1: Download successful")
    else:
        print("[FAIL] Website 1: Download failed")

    # Download from Website 2
    print("\n[2/7] Processing Website 2...")
    success2 = download_excel_from_website(
        url=website2_config["url"],
        login_credentials=website2_config["credentials"],
        download_path=chile_download_path,
        button_text=website2_config["button_text"],
        target_filename=website2_config["target_filename"]
    )

    if success2:
        print("[OK] Website 2: Download successful")
    else:
        print("[FAIL] Website 2: Download failed")

    # Download from Website 3
    print("\n[3/7] Processing Website 3...")
    success3 = download_excel_from_website(
        url=website3_config["url"],
        login_credentials=website3_config["credentials"],
        download_path=chile_download_path,
        button_text=website3_config["button_text"],
        target_filename=website3_config["target_filename"]
    )

    if success3:
        print("[OK] Website 3: Download successful")
    else:
        print("[FAIL] Website 3: Download failed")

    # Download from Website 4
    print("\n[4/7] Processing Website 4...")
    success4 = download_excel_from_website(
        url=website4_config["url"],
        login_credentials=website4_config["credentials"],
        download_path=chile_download_path,
        button_text=website4_config["button_text"],
        target_filename=website4_config["target_filename"]
    )

    if success4:
        print("[OK] Website 4: Download successful")
    else:
        print("[FAIL] Website 4: Download failed")

    # Download from Website 5
    print("\n[5/7] Processing Website 5...")
    success5 = download_excel_from_website(
        url=website5_config["url"],
        login_credentials=website5_config["credentials"],
        download_path=chile_download_path,
        button_text=website5_config["button_text"],
        target_filename=website5_config["target_filename"]
    )

    if success5:
        print("[OK] Website 5: Download successful")
    else:
        print("[FAIL] Website 5: Download failed")

    # Download from Website 6
    print("\n[6/7] Processing Website 6...")
    success6 = download_excel_from_website(
        url=website6_config["url"],
        login_credentials=website6_config["credentials"],
        download_path=chile_download_path,
        button_text=website6_config["button_text"],
        target_filename=website6_config["target_filename"]
    )

    if success6:
        print("[OK] Website 6: Download successful")
    else:
        print("[FAIL] Website 6: Download failed")

    # Download from Website 7
    print("\n[7/7] Processing Website 7...")
    success7 = download_excel_from_website(
        url=website7_config["url"],
        login_credentials=website7_config["credentials"],
        download_path=chile_download_path,
        button_text=website7_config["button_text"],
        target_filename=website7_config["target_filename"]
    )

    if success7:
        print("[OK] Website 7: Download successful")
    else:
        print("[FAIL] Website 7: Download failed")

    print("\n" + "=" * 50)
    print("Automation completed!")
    print("=" * 50)


if __name__ == "__main__":
    main()
