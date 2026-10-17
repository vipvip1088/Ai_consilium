[app]
title = AI Council
package.name = aicouncil
package.domain = org.aicouncil
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 0.1
requirements = python3,kivy==2.2.1,requests,urllib3,certifi,idna,cython==0.29.36
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True
p4a.branch = develop

[buildozer]
log_level = 2
warn_on_root = 0
