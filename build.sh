#!/bin/bash
# Build blockhost-common .deb package

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION=$(grep -oP 'Version: \K.*' "$SCRIPT_DIR/DEBIAN/control")
PACKAGE_NAME="blockhost-common_${VERSION}_all"

echo "Building ${PACKAGE_NAME}.deb..."

# Create build directory
BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

# Copy package contents
cp -r "$SCRIPT_DIR/DEBIAN" "$BUILD_DIR/"
cp -r "$SCRIPT_DIR/etc" "$BUILD_DIR/"
cp -r "$SCRIPT_DIR/usr" "$BUILD_DIR/"
mkdir -p "$BUILD_DIR/var/lib/blockhost"

# Set permissions
chmod 755 "$BUILD_DIR/DEBIAN/postinst"
chmod 755 "$BUILD_DIR/DEBIAN/prerm"
chmod 755 "$BUILD_DIR/DEBIAN/postrm"

# Build package
dpkg-deb --build "$BUILD_DIR" "${SCRIPT_DIR}/../${PACKAGE_NAME}.deb"

echo "Built: ${SCRIPT_DIR}/../${PACKAGE_NAME}.deb"
echo ""
echo "Install with:"
echo "  sudo dpkg -i ${PACKAGE_NAME}.deb"
