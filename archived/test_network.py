#!/usr/bin/env python3
import urllib.request
try:
    resp = urllib.request.urlopen('https://api.telegram.org', timeout=10)
    print('Network OK:', resp.status)
except Exception as e:
    print('Network error:', e)
