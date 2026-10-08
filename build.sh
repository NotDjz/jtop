#!/bin/sh
# Build the .deb and refresh the signed APT repo in docs/ (served by GitHub Pages).
# Release a new version: bump VERSION, run ./build.sh, commit, push.
set -e
VERSION=1.0
KEY=notdjz@users.noreply.github.com
cd "$(dirname "$0")"

pkg=$(mktemp -d)
install -Dm755 jtop.py "$pkg/usr/bin/jtop"
mkdir "$pkg/DEBIAN"
cat > "$pkg/DEBIAN/control" <<EOF
Package: jtop
Version: $VERSION
Architecture: all
Maintainer: notdjz <$KEY>
Depends: python3
Section: utils
Priority: optional
Homepage: https://github.com/notdjz/jtop
Description: hardware components and live usage, htop style
 Two tabs: a list of the machine's components, and live CPU, memory,
 disk, network and temperature usage.
EOF
mkdir -p docs
dpkg-deb --root-owner-group --build "$pkg" "docs/jtop_${VERSION}_all.deb"
rm -r "$pkg"

cd docs
apt-ftparchive packages . > Packages
gzip -kf Packages
apt-ftparchive -o APT::FTPArchive::Release::Origin=jtop -o APT::FTPArchive::Release::Label=jtop \
  release . > ../Release.tmp
mv ../Release.tmp Release
gpg --batch --yes -u "$KEY" --clearsign -o InRelease Release
gpg --export "$KEY" > jtop.gpg
touch .nojekyll  # serve files as-is, no Jekyll processing
