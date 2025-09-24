#!/bin/bash

# Test script for delete account endpoint using curl
# Usage: ./test_delete_curl.sh [JWT_TOKEN]

echo "🧪 Testing Delete Account Endpoint with curl"
echo "=============================================="

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

echo "Testing DELETE $BASE_URL/users/delete-account"
echo "JWT Token: ${JWT_TOKEN:0:20}..."
echo ""

# Test the delete account endpoint
echo "Sending DELETE request..."
response=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
    -X DELETE \
    -H "Authorization: Bearer $JWT_TOKEN" \
    -H "Content-Type: application/json" \
    "$BASE_URL/users/delete-account")

# Parse response and status code
http_body=$(echo "$response" | sed '$d')
http_code=$(echo "$response" | tail -n1 | sed 's/.*HTTP_STATUS://')

echo "Response Code: $http_code"
echo "Response Body:"
echo "$http_body" | python -m json.tool 2>/dev/null || echo "$http_body"

if [ "$http_code" = "200" ]; then
    echo ""
    echo "✅ Account deletion successful!"
    echo "The user and all associated data have been removed."
elif [ "$http_code" = "401" ]; then
    echo ""
    echo "❌ Authentication failed"
    echo "Please check your JWT token."
elif [ "$http_code" = "500" ]; then
    echo ""
    echo "❌ Server error during deletion"
    echo "Check the server logs for details."
else
    echo ""
    echo "❌ Unexpected response code: $http_code"
fi

echo ""
echo "📋 Endpoint Information:"
echo "URL: DELETE /users/delete-account"
echo "Headers: Authorization: Bearer <JWT_TOKEN>"
echo "Authentication: Required (JWT)"
echo "Action: Permanently deletes user and all data"
echo ""
echo "Deletion Order (to handle foreign key constraints):"
echo "1. Flash cards → 2. Quiz questions → 3. Learning resources"
echo "4. Set user.root_folder_id = NULL → 5. Folders → 6. User"