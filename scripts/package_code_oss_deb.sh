#!/usr/bin/env bash
# Package an assembled Code-OSS Linux x64 tree as an installable, unsigned .deb.
set -euo pipefail

archive=${1:?usage: package_code_oss_deb.sh <tar.gz> <output.deb> [version]}
output=${2:?usage: package_code_oss_deb.sh <tar.gz> <output.deb> [version]}
version=${3:-1.144.0}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

tar -xzf "$archive" -C "$work"
source_tree="$work/VSCode-linux-x64"
test -x "$source_tree/agentic-workbench"
test -f "$source_tree/resources/app/extensions/agentic-local/extension.js"

package="$work/package"
root="$package/opt/agentic-workbench"
mkdir -p "$root" "$package/DEBIAN" "$package/usr/bin" "$package/usr/share/applications"
cp -a "$source_tree/." "$root/"

cat > "$package/usr/bin/agentic-workbench" <<'EOF'
#!/bin/sh
exec /opt/agentic-workbench/agentic-workbench "$@"
EOF
chmod 0755 "$package/usr/bin/agentic-workbench"

cat > "$package/usr/share/applications/agentic-workbench.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Agentic Workbench
Comment=Local-first agentic code editor (experimental)
Exec=/usr/bin/agentic-workbench %F
Terminal=false
Categories=Development;IDE;
StartupWMClass=agentic-workbench
EOF

icon="$root/resources/app/resources/linux/code.png"
if [ -f "$icon" ]; then
  mkdir -p "$package/usr/share/pixmaps"
  cp "$icon" "$package/usr/share/pixmaps/agentic-workbench.png"
  echo "Icon=agentic-workbench" >> "$package/usr/share/applications/agentic-workbench.desktop"
fi

installed_kb=$(du -sk "$root" | cut -f1)
cat > "$package/DEBIAN/control" <<EOF
Package: agentic-workbench
Version: $version
Section: devel
Priority: optional
Architecture: amd64
Maintainer: Agentic Workbench <noreply@agentic-workbench.invalid>
Installed-Size: $installed_kb
Depends: libgtk-3-0 | libgtk-3-0t64, libnss3, libasound2 | libasound2t64, libgbm1, libx11-xcb1, libxss1, libxtst6, xdg-utils
Description: Local-first agentic code editor (experimental, unsigned)
 A Code-OSS based workbench with a first-party local AI extension.
 This package is an unsigned experimental build; it is not a production release.
EOF

mkdir -p "$(dirname "$output")"
dpkg-deb --build --root-owner-group "$package" "$output"
dpkg-deb --info "$output"
