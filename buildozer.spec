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
android.accept_sdk_license = True
android.allow_backup = False

[buildozer]
log_level = 2
warn_on_root = 1
