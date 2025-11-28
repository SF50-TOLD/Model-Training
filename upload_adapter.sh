#!/bin/bash
# Upload adapter to App Store Connect via Apple-Hosted Background Assets API
#
# Uploads versioned adapters (e.g., notam-adapter-26_0_0, notam-adapter-26_1_0)
# to support different Foundation Model toolkit versions.
#
# Usage:
#   ./upload_adapter.sh                      # Auto-detect version from toolkit
#   ./upload_adapter.sh --version 26_0_0     # Specify toolkit version explicitly
#   ./upload_adapter.sh --dry-run            # Validate without uploading

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".env" ]; then
    set -a && source .env && set +a
fi

# Configuration
ADAPTER_NAME="${ADAPTER_NAME:-NOTAMAdapter}"
OUTPUT_DIR="${OUTPUT_DIR:-exports}"
ADAPTER_PATH="$OUTPUT_DIR/$ADAPTER_NAME.fmadapter"
ASSET_PACK_BASE="${ASSET_PACK_BASE:-notam-adapter}"
ASC_API_BASE="https://api.appstoreconnect.apple.com/v1"

# Parse arguments
DRY_RUN=false
VERSION_OVERRIDE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN=true; shift ;;
        --version) VERSION_OVERRIDE="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --version VER   Specify toolkit version (e.g., 26_0_0, 26_1_0)"
            echo "  --dry-run       Validate without uploading"
            echo "  --help, -h      Show this help message"
            echo ""
            echo "Environment Variables (set in .env):"
            echo "  ASC_ISSUER_ID         App Store Connect API issuer ID"
            echo "  ASC_KEY_ID            App Store Connect API key ID"
            echo "  ASC_PRIVATE_KEY_PATH  Path to .p8 private key file"
            echo "  APP_APPLE_ID          Your app's Apple ID (numeric)"
            echo "  ASSET_PACK_BASE       Base asset pack ID (default: notam-adapter)"
            echo ""
            echo "The script creates versioned asset packs matching toolkit versions:"
            echo "  notam-adapter-26_0_0, notam-adapter-26_1_0, etc."
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "============================================================"
echo "Upload Adapter to App Store Connect"
echo "============================================================"
echo ""

# Validate prerequisites
for tool in jq python3 xcrun; do
    command -v "$tool" &>/dev/null || { echo "Error: $tool is required"; exit 1; }
done

xcrun ba-package --version &>/dev/null || { echo "Error: ba-package tool not found (requires Xcode)"; exit 1; }

[ -d "$ADAPTER_PATH" ] || { echo "Error: Adapter not found at $ADAPTER_PATH"; exit 1; }

for var in ASC_ISSUER_ID ASC_KEY_ID ASC_PRIVATE_KEY_PATH APP_APPLE_ID; do
    [ -n "${!var}" ] || { echo "Error: $var is not set"; exit 1; }
done

[ -f "$ASC_PRIVATE_KEY_PATH" ] || { echo "Error: Private key not found"; exit 1; }

# Detect toolkit version from directory name or use override
if [ -n "$VERSION_OVERRIDE" ]; then
    ADAPTER_VERSION="$VERSION_OVERRIDE"
else
    # Extract version from toolkit directory name (e.g., adapter_training_toolkit_v26_0_0)
    TOOLKIT_DIR=$(ls -d adapter_training_toolkit_v* 2>/dev/null | head -1)
    if [ -n "$TOOLKIT_DIR" ]; then
        # Extract version part after 'v' (e.g., 26_0_0 from adapter_training_toolkit_v26_0_0)
        ADAPTER_VERSION=$(echo "$TOOLKIT_DIR" | sed 's/.*_v//')
    else
        echo "Error: Could not find toolkit directory (adapter_training_toolkit_v*)"
        echo "Specify version manually with --version"
        exit 1
    fi
fi

ASSET_PACK_ID="${ASSET_PACK_BASE}-${ADAPTER_VERSION}"

echo "Adapter:     $ADAPTER_PATH"
echo "Version:     $ADAPTER_VERSION"
echo "Asset Pack:  $ASSET_PACK_ID"
echo ""

# Show adapter metadata
if [ -f "$ADAPTER_PATH/metadata.json" ]; then
    echo "Adapter Metadata:"
    jq -r '  "  Identifier: \(.adapterIdentifier)"
           , "  Toolkit:    \(.toolkitVersion // "unknown")"
           , "  Signature:  \(.baseModelSignature[:16])..."' "$ADAPTER_PATH/metadata.json" 2>/dev/null || true
    echo ""
fi

# Create asset pack archive using ba-package
echo "Creating asset pack archive..."
ARCHIVE_DIR=$(mktemp -d)
MANIFEST_FILE="$ARCHIVE_DIR/manifest.json"
ARCHIVE_FILE="$ARCHIVE_DIR/$ADAPTER_NAME.aar"

# Create manifest for ba-package
cat > "$MANIFEST_FILE" << EOF
{
    "assetPackID": "$ASSET_PACK_ID",
    "downloadPolicy": {
        "prefetch": {
            "installationEventTypes": [
                "firstInstallation",
                "subsequentUpdate"
            ]
        }
    },
    "fileSelectors": [
        {
            "directory": "$ADAPTER_NAME.fmadapter"
        }
    ],
    "platforms": [
        "iOS",
        "macOS",
        "visionOS"
    ]
}
EOF

# Package using ba-package from the exports directory
(cd "$OUTPUT_DIR" && xcrun ba-package package "$MANIFEST_FILE" --output-path "$ARCHIVE_FILE")

ARCHIVE_SIZE=$(stat -f%z "$ARCHIVE_FILE")
ARCHIVE_FILENAME=$(basename "$ARCHIVE_FILE")

echo "Archive: $(du -h "$ARCHIVE_FILE" | cut -f1)"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would upload to asset pack: $ASSET_PACK_ID"
    echo "Manifest:"
    cat "$MANIFEST_FILE"
    rm -rf "$ARCHIVE_DIR"
    exit 0
fi

# Generate JWT for App Store Connect API
generate_jwt() {
    python3 << PYTHON_EOF
import json, time, base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.backends import default_backend

def b64url(data):
    if isinstance(data, str): data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

with open("$ASC_PRIVATE_KEY_PATH", "rb") as f:
    key = serialization.load_pem_private_key(f.read(), None, default_backend())

now = int(time.time())
header = b64url(json.dumps({"alg":"ES256","kid":"$ASC_KEY_ID","typ":"JWT"}, separators=(',',':')))
payload = b64url(json.dumps({"iss":"$ASC_ISSUER_ID","iat":now,"exp":now+1200,"aud":"appstoreconnect-v1"}, separators=(',',':')))
msg = f"{header}.{payload}".encode()

sig = key.sign(msg, ec.ECDSA(hashes.SHA256()))
r, s = decode_dss_signature(sig)
print(f"{header}.{payload}.{b64url(r.to_bytes(32,'big')+s.to_bytes(32,'big'))}")
PYTHON_EOF
}

JWT_TOKEN=$(generate_jwt)
[ -n "$JWT_TOKEN" ] || { echo "Error: JWT generation failed"; rm -rf "$ARCHIVE_DIR"; exit 1; }

# API helper
api_call() {
    local method=$1 endpoint=$2 data=$3
    curl -s -w "\n%{http_code}" -X "$method" \
        -H "Authorization: Bearer $JWT_TOKEN" \
        -H "Content-Type: application/json" \
        ${data:+-d "$data"} "$ASC_API_BASE$endpoint"
}

check_response() {
    local response=$1 expected=$2 action=$3
    local code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')
    if [[ ! "$expected" =~ $code ]]; then
        echo "Error: $action (HTTP $code)"
        echo "$body" | jq -r '.errors[0].detail // .errors[0].title // "Unknown error"' 2>/dev/null || echo "$body"
        rm -rf "$ARCHIVE_DIR"
        exit 1
    fi
    echo "$body"
}

# Step 1: Find or create asset pack
echo "Finding/creating asset pack '$ASSET_PACK_ID'..."
EXISTING=$(curl -s -H "Authorization: Bearer $JWT_TOKEN" "$ASC_API_BASE/apps/$APP_APPLE_ID/backgroundAssets")
ASSET_PACK_UUID=$(echo "$EXISTING" | jq -r --arg id "$ASSET_PACK_ID" '.data[] | select(.attributes.assetPackIdentifier == $id) | .id' 2>/dev/null)

if [ -z "$ASSET_PACK_UUID" ] || [ "$ASSET_PACK_UUID" = "null" ]; then
    RESPONSE=$(api_call POST "/backgroundAssets" '{
        "data": {
            "type": "backgroundAssets",
            "attributes": {"assetPackIdentifier": "'"$ASSET_PACK_ID"'"},
            "relationships": {"app": {"data": {"type": "apps", "id": "'"$APP_APPLE_ID"'"}}}
        }
    }')
    BODY=$(check_response "$RESPONSE" "200|201" "Failed to create asset pack")
    ASSET_PACK_UUID=$(echo "$BODY" | jq -r '.data.id')
    echo "Created: $ASSET_PACK_UUID"
else
    echo "Found: $ASSET_PACK_UUID"
fi

# Step 2: Create version
echo "Creating version..."
RESPONSE=$(api_call POST "/backgroundAssetVersions" '{
    "data": {
        "type": "backgroundAssetVersions",
        "relationships": {"backgroundAsset": {"data": {"type": "backgroundAssets", "id": "'"$ASSET_PACK_UUID"'"}}}
    }
}')
BODY=$(check_response "$RESPONSE" "200|201" "Failed to create version")
VERSION_UUID=$(echo "$BODY" | jq -r '.data.id')
VERSION_NUMBER=$(echo "$BODY" | jq -r '.data.attributes.version // "1"')
echo "Version $VERSION_NUMBER: $VERSION_UUID"

# Step 3: Reserve upload
echo "Reserving upload..."
RESPONSE=$(api_call POST "/backgroundAssetUploadFiles" '{
    "data": {
        "type": "backgroundAssetUploadFiles",
        "attributes": {"assetType": "ASSET", "fileName": "'"$ARCHIVE_FILENAME"'", "fileSize": '"$ARCHIVE_SIZE"'},
        "relationships": {"backgroundAssetVersion": {"data": {"type": "backgroundAssetVersions", "id": "'"$VERSION_UUID"'"}}}
    }
}')
BODY=$(check_response "$RESPONSE" "200|201" "Failed to reserve upload")
UPLOAD_FILE_ID=$(echo "$BODY" | jq -r '.data.id')
UPLOAD_OPERATIONS=$(echo "$BODY" | jq -r '.data.attributes.uploadOperations')
NUM_OPERATIONS=$(echo "$UPLOAD_OPERATIONS" | jq 'length')
echo "Upload ID: $UPLOAD_FILE_ID ($NUM_OPERATIONS parts)"

# Step 4: Upload chunks
echo "Uploading..."
for i in $(seq 0 $((NUM_OPERATIONS - 1))); do
    URL=$(echo "$UPLOAD_OPERATIONS" | jq -r ".[$i].url")
    METHOD=$(echo "$UPLOAD_OPERATIONS" | jq -r ".[$i].method")
    OFFSET=$(echo "$UPLOAD_OPERATIONS" | jq -r ".[$i].offset")
    LENGTH=$(echo "$UPLOAD_OPERATIONS" | jq -r ".[$i].length")

    HEADERS=""
    for h in $(seq 0 $(($(echo "$UPLOAD_OPERATIONS" | jq -r ".[$i].requestHeaders | length") - 1))); do
        NAME=$(echo "$UPLOAD_OPERATIONS" | jq -r ".[$i].requestHeaders[$h].name")
        VALUE=$(echo "$UPLOAD_OPERATIONS" | jq -r ".[$i].requestHeaders[$h].value")
        HEADERS="$HEADERS -H \"$NAME: $VALUE\""
    done

    dd if="$ARCHIVE_FILE" bs=1 skip="$OFFSET" count="$LENGTH" 2>/dev/null | \
        eval curl -s -X "$METHOD" "$HEADERS" --data-binary @- "\"$URL\""
    echo "  Part $((i + 1))/$NUM_OPERATIONS"
done

# Step 5: Commit
echo "Committing..."
MD5=$(md5 -q "$ARCHIVE_FILE")
RESPONSE=$(api_call PATCH "/backgroundAssetUploadFiles/$UPLOAD_FILE_ID" '{
    "data": {
        "type": "backgroundAssetUploadFiles",
        "id": "'"$UPLOAD_FILE_ID"'",
        "attributes": {"sourceFileChecksum": "'"$MD5"'", "uploaded": true}
    }
}')
check_response "$RESPONSE" "200" "Failed to commit upload" >/dev/null

# Step 6: Check status
sleep 3
STATUS=$(curl -s -H "Authorization: Bearer $JWT_TOKEN" "$ASC_API_BASE/backgroundAssetVersions/$VERSION_UUID" | jq -r '.data.attributes.state // "PROCESSING"')

rm -rf "$ARCHIVE_DIR"

echo ""
echo "============================================================"
echo "Upload Complete!"
echo "============================================================"
echo ""
echo "Asset Pack:  $ASSET_PACK_ID"
echo "Version:     $VERSION_NUMBER"
echo "State:       $STATUS"
echo ""
echo "Monitor at: https://appstoreconnect.apple.com"
