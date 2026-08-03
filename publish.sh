#!/usr/bin/env bash
#
# Publish alibabacloud-mcp-proxy to PyPI.
#
# Usage:
#   ./publish.sh              # publish to production PyPI
#   ./publish.sh --test       # publish to TestPyPI first
#   ./publish.sh --dry-run    # build only, do not upload
#   ./publish.sh --skip-git-tag  # publish without creating a Git release tag
#
# Prerequisites:
#   1. pip install build twine
#   2. Configure PyPI credentials via one of:
#      - ~/.pypirc
#      - TWINE_USERNAME / TWINE_PASSWORD env vars
#      - TWINE_USERNAME=__token__  TWINE_PASSWORD=pypi-xxxx  (API token)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
USE_TEST_PYPI=false
DRY_RUN=false
SKIP_GIT_TAG=false

for arg in "$@"; do
    case "$arg" in
        --test)     USE_TEST_PYPI=true ;;
        --dry-run)  DRY_RUN=true ;;
        --skip-git-tag) SKIP_GIT_TAG=true ;;
        -h|--help)
            echo "Usage: $0 [--test] [--dry-run] [--skip-git-tag]"
            echo "  --test          Upload to TestPyPI instead of production PyPI"
            echo "  --dry-run       Build only, do not upload or tag"
            echo "  --skip-git-tag  Publish without creating the v<version> Git tag"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg"
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Step 1: Check dependencies
# ---------------------------------------------------------------------------
echo "==> Checking build dependencies..."

for cmd in python3 pip; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: '$cmd' is not installed."
        exit 1
    fi
done

python3 -m pip install --quiet --upgrade build twine

# ---------------------------------------------------------------------------
# Step 1.5: Verify the local version has not already been published
# ---------------------------------------------------------------------------
echo "==> Verifying local version is newer than the published one..."

PACKAGE_NAME="$(python3 -c "
try:
    import tomllib
except ModuleNotFoundError:
    import pip._vendor.tomli as tomllib
print(tomllib.load(open('pyproject.toml','rb'))['project']['name'])
")"
LOCAL_VERSION="$(python3 -c "
try:
    import tomllib
except ModuleNotFoundError:
    import pip._vendor.tomli as tomllib
print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])
")"

if [ "$USE_TEST_PYPI" = true ]; then
    INDEX_URL="https://test.pypi.org/pypi/${PACKAGE_NAME}/json"
else
    INDEX_URL="https://pypi.org/pypi/${PACKAGE_NAME}/json"
fi

# curl uses the system CA bundle; --fail surfaces 4xx/5xx as a non-zero exit so
# we can distinguish "package not yet published" (404) from real network errors.
HTTP_CODE="$(curl -sS -o /tmp/.publish_index.json -w "%{http_code}" \
    --connect-timeout 5 --max-time 15 "${INDEX_URL}" || true)"

case "$HTTP_CODE" in
    200)
        PUBLISHED_VERSION="$(python3 -c "
import json, sys
from packaging.version import Version
data = json.load(open('/tmp/.publish_index.json'))
releases = list(data.get('releases', {}).keys())
print(sorted(releases, key=Version)[-1] if releases else '')
")"
        if [ -z "$PUBLISHED_VERSION" ]; then
            echo "    PyPI knows the package but lists no releases yet. Proceeding with ${LOCAL_VERSION}."
        elif python3 -c "
from packaging.version import Version
import sys
sys.exit(0 if Version('${LOCAL_VERSION}') > Version('${PUBLISHED_VERSION}') else 1)
" ; then
            echo "    Local ${LOCAL_VERSION} > published ${PUBLISHED_VERSION}. OK."
        else
            echo "Error: local version ${LOCAL_VERSION} is not newer than published ${PUBLISHED_VERSION}."
            echo "       Bump 'version' in pyproject.toml before publishing."
            exit 1
        fi
        ;;
    404)
        echo "    No prior release detected for ${PACKAGE_NAME} on this index. Proceeding with ${LOCAL_VERSION}."
        ;;
    *)
        echo "Error: failed to query ${INDEX_URL} (HTTP ${HTTP_CODE:-no-response})."
        echo "       Refusing to publish without confirming the latest published version."
        echo "       Re-run when the network is reachable, or skip with: VERSION_CHECK=skip ./publish.sh ..."
        if [ "${VERSION_CHECK:-}" = "skip" ]; then
            echo "    VERSION_CHECK=skip set; bypassing the safety check at your own risk."
        else
            exit 1
        fi
        ;;
esac
rm -f /tmp/.publish_index.json

# ---------------------------------------------------------------------------
# Step 2: Clean previous builds
# ---------------------------------------------------------------------------
echo "==> Cleaning previous builds..."
rm -rf dist/ build/
find src/ -name '*.egg-info' -type d -exec rm -rf {} + 2>/dev/null || true

# ---------------------------------------------------------------------------
# Step 2.5: Verify the Git release tag can be created after upload
# ---------------------------------------------------------------------------
TAG_NAME="v${LOCAL_VERSION}"
CREATE_GIT_TAG=false

if [ "$DRY_RUN" = false ] && [ "$USE_TEST_PYPI" = false ] && [ "$SKIP_GIT_TAG" = false ]; then
    CREATE_GIT_TAG=true
fi

if [ "$CREATE_GIT_TAG" = true ]; then
    echo "==> Verifying Git release tag ${TAG_NAME} can be created..."

    if ! command -v git >/dev/null 2>&1; then
        echo "Error: 'git' is not installed; cannot create release tag ${TAG_NAME}."
        exit 1
    fi
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo "Error: not inside a Git work tree; cannot create release tag ${TAG_NAME}."
        exit 1
    fi
    if [ -n "$(git status --porcelain)" ]; then
        echo "Error: working tree is not clean."
        echo "       Commit or discard local changes before publishing so ${TAG_NAME}"
        echo "       points to the exact source used for the PyPI artifact."
        exit 1
    fi
    if git rev-parse -q --verify "refs/tags/${TAG_NAME}" >/dev/null; then
        echo "Error: local Git tag ${TAG_NAME} already exists."
        exit 1
    fi

    GIT_HEAD_SHA="$(git rev-parse HEAD)"
    LS_REMOTE_STATUS=0
    git ls-remote --exit-code --tags origin "refs/tags/${TAG_NAME}" >/tmp/.publish_tag_check 2>/tmp/.publish_tag_check.err || LS_REMOTE_STATUS=$?
    if [ "$LS_REMOTE_STATUS" -eq 0 ]; then
        echo "Error: remote Git tag ${TAG_NAME} already exists on origin."
        rm -f /tmp/.publish_tag_check /tmp/.publish_tag_check.err
        exit 1
    elif [ "$LS_REMOTE_STATUS" -ne 2 ]; then
        echo "Error: failed to check whether remote Git tag ${TAG_NAME} exists."
        cat /tmp/.publish_tag_check.err
        rm -f /tmp/.publish_tag_check /tmp/.publish_tag_check.err
        exit 1
    fi
    rm -f /tmp/.publish_tag_check /tmp/.publish_tag_check.err

    echo "    ${TAG_NAME} will be created on commit ${GIT_HEAD_SHA} after PyPI upload succeeds."
elif [ "$DRY_RUN" = true ]; then
    echo "==> Dry run selected; skipping Git release tag creation."
elif [ "$USE_TEST_PYPI" = true ]; then
    echo "==> TestPyPI upload selected; skipping Git release tag creation."
elif [ "$SKIP_GIT_TAG" = true ]; then
    echo "==> --skip-git-tag selected; skipping Git release tag creation."
fi

# ---------------------------------------------------------------------------
# Step 3: Build
# ---------------------------------------------------------------------------
echo "==> Building package..."
python3 -m build

echo ""
echo "==> Built artifacts:"
ls -lh dist/

# ---------------------------------------------------------------------------
# Step 4: Verify
# ---------------------------------------------------------------------------
echo ""
echo "==> Verifying package with twine..."
python3 -m twine check dist/*

# ---------------------------------------------------------------------------
# Step 5: Upload
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "==> Dry run complete. Skipping upload."
    echo "    To upload manually:"
    echo "      python3 -m twine upload dist/*"
    exit 0
fi

echo ""
if [ "$USE_TEST_PYPI" = true ]; then
    echo "==> Uploading to TestPyPI..."
    python3 -m twine upload --repository testpypi dist/*
    echo ""
    echo "==> Done! Install from TestPyPI with:"
    echo "    pip install --index-url https://test.pypi.org/simple/ alibabacloud.mcp-proxy"
else
    echo "==> Uploading to PyPI..."
    python3 -m twine upload dist/*
    if [ "$CREATE_GIT_TAG" = true ]; then
        echo ""
        echo "==> Creating and pushing Git release tag ${TAG_NAME}..."
        git tag -a "${TAG_NAME}" -m "Release ${PACKAGE_NAME} ${LOCAL_VERSION}"
        git push origin "refs/tags/${TAG_NAME}"
    fi
    echo ""
    echo "==> Done! Install with:"
    echo "    pip install alibabacloud.mcp-proxy"
fi
