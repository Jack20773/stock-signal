import urllib.request

req = urllib.request.Request(
    "https://whatmkreallysaid.com/episode.html",
    headers={"User-Agent": "Mozilla/5.0"}
)
html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
print(html)
