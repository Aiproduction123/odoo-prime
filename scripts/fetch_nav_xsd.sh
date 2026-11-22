#!/usr/bin/env bash
# Downloads the official NAV Online Invoice 3.0 schemas into data/nav_xsd/
# so scripts/check_nav_demo.py can validate generated invoice XML offline.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/nav_xsd
osa=https://raw.githubusercontent.com/nav-gov-hu/Online-Invoice/master/src/schemas/nav/gov/hu/OSA
common=https://raw.githubusercontent.com/nav-gov-hu/Common/common-1.0.0/schemas/src/main/resources/xsd/hu/gov/nav/schemas/NTCA/1.0/common/common.xsd
curl -fsSL "$osa/invoiceData.xsd" -o data/nav_xsd/invoiceData.xsd
curl -fsSL "$osa/invoiceBase.xsd" -o data/nav_xsd/invoiceBase.xsd
curl -fsSL "$common" -o data/nav_xsd/common.xsd
echo "NAV schemas saved in data/nav_xsd/"
