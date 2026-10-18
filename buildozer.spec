[app]
title = AI Council
package.name = aicouncil
package.domain = org.example

source.dir = .
source.include_exts = py,json,png,jpg,kv,txt
version = 2.0.0

requirements = python3,kivy,requests,certifi

orientation = portrait
fullscreen = 0

android.permissions = INTERNET
android.api = 36
android.minapi = 24
android.archs = arm64-v8a
android.ndk = 29
android.accept_sdk_license = True
android.allow_backup = False

# Fix for the logged failure:
# python-for-android's default master branch currently resolves a CPython 3.14
# charset-normalizer wheel with an Android platform tag, then pip --target
# rejects that wheel as unsupported. The develop branch supports Python 3.14.
# See: https://github.com/kivy/buildozer/issues/2051
p4a.branch = develop

[buildozer]
log_level = 2
warn_on_root = 1
