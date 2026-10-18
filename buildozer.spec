[app]
title = AI Council
package.name = aicouncil
package.domain = org.aicouncil

source.dir = .
source.include_exts = py,json,png,jpg,kv,txt
version = 2.0.0

requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.2.1,requests,urllib3,certifi,idna,cython==0.29.36

orientation = portrait
fullscreen = 0

android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.archs = arm64-v8a
android.ndk = 25b
android.accept_sdk_license = True
p4a.branch = master
android.allow_backup = False

[buildozer]
log_level = 2
warn_on_root = 1
