#!/usr/bin/env python3
"""
Test script for the /users/me endpoint.
This script demonstrates how to get the current user's information.
"""

import requests
import json

# Configuration
BASE_URL = "http://localhost:8000"

def test_me_endpoint(jwt_token):
    """
    Test the /users/me endpoint to get current user information.

    Args:
        jwt_token (str): Valid JWT authentication token
    """
    print("🧪 Testing /users/me Endpoint")
    print("=" * 40)

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(f"{BASE_URL}/users/me", headers=headers)

        print(f"Response Status: {response.status_code}")
        print("Response Headers:", dict(response.headers))
        print()

        if response.status_code == 200:
            user_data = response.json()
            print("✅ User information retrieved successfully!")
            print("User Data:")
            print(json.dumps(user_data, indent=2))

            # Validate expected fields
            expected_fields = ['id', 'email', 'first_name', 'last_name', 'profile_picture_url', 'created_at', 'updated_at']
            print(f"\n📋 Field Validation:")
            for field in expected_fields:
                if field in user_data:
                    value = user_data[field]
                    if value:
                        print(f"✅ {field}: {value}")
                    else:
                        print(f"⚪ {field}: null/empty")
                else:
                    print(f"❌ {field}: missing")

        elif response.status_code == 401:
            print("❌ Authentication failed")
            print("Response:", response.text)
            print("Please check your JWT token.")

        elif response.status_code == 422:
            print("❌ Validation error")
            print("Response:", response.json())

        else:
            print(f"❌ Unexpected response code: {response.status_code}")
            print("Response:", response.text)

    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to the API server.")
        print("Make sure the FastAPI server is running on localhost:8000")
        print("Run: python -m uvicorn app.main:app --reload")

    except Exception as e:
        print(f"❌ Test failed with error: {e}")


def show_endpoint_info():
    """Display information about the /users/me endpoint."""
    print("🔍 /users/me Endpoint Information")
    print("=" * 40)
    print("URL: GET /users/me")
    print("Authentication: JWT Bearer Token required")
    print("Parameters: None (uses current authenticated user)")
    print()
    print("Response format:")
    print(json.dumps({
        "id": 123,
        "email": "user@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "profile_picture_url": "https://example.com/avatar.jpg",
        "created_at": "2024-01-15T10:30:00",
        "updated_at": "2024-01-15T10:30:00"
    }, indent=2))
    print()
    print("Usage with curl:")
    print("curl -X GET \\")
    print("  http://localhost:8000/users/me \\")
    print("  -H 'Authorization: Bearer YOUR_JWT_TOKEN' \\")
    print("  -H 'Content-Type: application/json'")


def main():
    show_endpoint_info()
    print("\n" + "=" * 50)

    # Get JWT token from user
    jwt_token = input("Enter your JWT token (or press Enter to skip test): ").strip()

    if jwt_token:
        print()
        test_me_endpoint(jwt_token)
    else:
        print("Skipping live test. Use this script with a valid JWT token to test the endpoint.")


if __name__ == "__main__":
    main()