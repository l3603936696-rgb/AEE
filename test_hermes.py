import urllib.request
import json

for port in [18789, 18791, 35387]:
    try:
        r = urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models', timeout=5)
        data = r.read().decode()
        print(f"Port {port}: {data[:300]}")
    except Exception as e:
        print(f"Port {port}: {e}")
