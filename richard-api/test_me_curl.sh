#!/bin/bash

# Test script for /users/me endpoint using curl
# Usage: ./test_me_curl.sh [JWT_TOKEN]

echo "🧪 Testing /users/me Endpoint with curl"
echo "======================================="

JWT_TOKEN=${1:-"your-jwt-token-here"}
BASE_URL="http://localhost:8000"

if [ "$JWT_TOKEN" = "your-jwt-token-here" ]; then
    echo "❌ Please provide a valid JWT token as the first argument"
    echo "Usage: $0 <JWT_TOKEN>"
    echo ""
    echo "To get a JWT token:"
    echo "1. Sign in through the app or API"
    echo "2. Use the returned jwt_token from the auth response"
    echo ""
    echo "Example:"
    echo "$0 eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
    exit 1
fi

echo "Testing GET $BASE_URL/users/me"
echo "JWT Token: ${JWT_TOKEN:0:20}..."
echo ""

# Test the /users/me endpoint
echo "Sending GET request..."
response=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
    -X GET \
    -H "Authorization: Bearer $JWT_TOKEN" \
    -H "Content-Type: application/json" \
    "$BASE_URL/users/me")

# Parse response and status code
http_body=$(echo "$response" | sed '$d')
http_code=$(echo "$response" | tail -n1 | sed 's/.*HTTP_STATUS://')

echo "Response Code: $http_code"
echo "Response Body:"
echo "$http_body" | python -m json.tool 2>/dev/null || echo "$http_body"

if [ "$http_code" = "200" ]; then
    echo ""
    echo "✅ User information retrieved successfully!"
    echo "The endpoint is working correctly."
elif [ "$http_code" = "401" ]; then
    echo ""
    echo "❌ Authentication failed"
    echo "Please check your JWT token."
elif [ "$http_code" = "422" ]; then
    echo ""
    echo "❌ Validation error"
    echo "Check the request format."
else
    echo ""
    echo "❌ Unexpected response code: $http_code"
fi

echo ""
echo "📋 Endpoint Information:"
echo "URL: GET /users/me"
echo "Headers: Authorization: Bearer <JWT_TOKEN>"
echo "Authentication: Required (JWT)"
echo "Purpose: Get current authenticated user's profile information"