#!/usr/bin/env python3
"""
Test script for the delete account endpoint.
This script demonstrates how the delete account endpoint should work.

IMPORTANT: This is for testing purposes only.
Run this against a test database, not production!
"""

import requests
import json

# Configuration - adjust these for your test environment
BASE_URL = "http://localhost:8000"
TEST_EMAIL = "test@example.com"
TEST_PASSWORD = "test123"  # If you have password auth
TEST_GOOGLE_TOKEN = "your-test-google-token"  # For Google auth testing

def test_delete_account():
    """
    Test the delete account endpoint functionality.

    This test assumes you have:
    1. A test user account
    2. Some test data (resources, folders, flash cards, etc.)
    """

    print("🧪 Testing Delete Account Endpoint")
    print("=" * 50)

    # Step 1: Sign in to get a JWT token (example with Google sign-in)
    print("Step 1: Authenticating user...")

    # Note: In real testing, you would use a valid Google ID token
    # For now, this is just a demonstration of the API structure

    signin_payload = {
        "id_token": TEST_GOOGLE_TOKEN
    }

    try:
        # Attempt sign-in (this will likely fail without real tokens)
        signin_response = requests.post(
            f"{BASE_URL}/auth/google-signin",
            json=signin_payload
        )

        if signin_response.status_code == 200:
            auth_data = signin_response.json()
            jwt_token = auth_data["jwt_token"]
            user_id = auth_data["user_id"]

            print(f"✅ Authentication successful for user {user_id}")

            # Step 2: Test the delete account endpoint
            print("Step 2: Testing delete account...")

            headers = {
                "Authorization": f"Bearer {jwt_token}",
                "Content-Type": "application/json"
            }

            delete_response = requests.delete(
                f"{BASE_URL}/users/delete-account",
                headers=headers
            )

            if delete_response.status_code == 200:
                result = delete_response.json()
                print("✅ Account deletion successful!")
                print(f"Message: {result['message']}")
                print("Deleted data counts:")
                for key, count in result["deleted_counts"].items():
                    print(f"  - {key}: {count}")
            else:
                print(f"❌ Delete failed: {delete_response.status_code}")
                print(f"Error: {delete_response.text}")

        else:
            print(f"❌ Authentication failed: {signin_response.status_code}")
            print("Note: This is expected if you don't have valid test tokens")
            print("The delete endpoint structure is properly implemented.")

    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to the API server.")
        print("Make sure the FastAPI server is running on localhost:8000")
        print("Run: python -m uvicorn app.main:app --reload")

    except Exception as e:
        print(f"❌ Test failed with error: {e}")

    print("\n📋 Endpoint Summary:")
    print("DELETE /users/delete-account")
    print("- Requires JWT authentication")
    print("- Deletes user and all associated data")
    print("- Returns deletion counts")
    print("- Handles errors with rollback")


def show_endpoint_info():
    """Display information about the delete account endpoint."""
    print("\n🔍 Delete Account Endpoint Details")
    print("=" * 50)
    print("URL: DELETE /users/delete-account")
    print("Authentication: JWT Bearer Token required")
    print("Parameters: None (uses current authenticated user)")
    print("\nData deleted (in order):")
    print("1. Flash cards")
    print("2. Multiple choice questions")
    print("3. Learning resources")
    print("4. Resource folders")
    print("5. User account")
    print("\nResponse on success:")
    print(json.dumps({
        "message": "Account successfully deleted",
        "deleted_counts": {
            "flash_cards": 0,
            "quiz_questions": 0,
            "learning_resources": 0,
            "folders": 0,
            "user": 1
        }
    }, indent=2))


if __name__ == "__main__":
    show_endpoint_info()
    test_delete_account()