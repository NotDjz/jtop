#!/bin/sh
# Build the .deb and refresh the signed APT repo in docs/ (served by GitHub Pages).
# Release a new version: bump VERSION, run ./build.sh, commit, push.
set -e
VERSION=1.2
KEY=notdjz@users.noreply.github.com
cd "$(dirname "$0")"

pkg=$(mktemp -d)
install -Dm755 jtop.py "$pkg/usr/lib/jtop/jtop.py"
install -Dm644 jtop_fun.py "$pkg/usr/lib/jtop/jtop_fun.py"
[ -f loading.txt ] && install -Dm644 loading.txt "$pkg/usr/lib/jtop/loading.txt"
mkdir -p "$pkg/usr/bin"
ln -s ../lib/jtop/jtop.py "$pkg/usr/bin/jtop"
chmod -R u=rwX,go=rX "$pkg"  # mktemp makes the root 0700; dirs must be 0755 like the real filesystem
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
 Three tabs: the machine's components, live CPU, memory, disk, network,
 temperature and battery usage, and a process list.
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
