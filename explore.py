import urllib.request
import re

req = urllib.request.Request(
    "https://whatmkreallysaid.com/seo/1.html",
    headers={"User-Agent": "Mozilla/5.0"}
)
html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")

# Find all href
links = re.findall(r'href=["\']([^"\']+)["\']', html)
print("=== LINKS ===")
for l in links:
    print(l)

# Find .md references
print("\n=== MD REFS ===")
md_refs = re.findall(r'[^"\'\s]+\.md[^"\'\s]*', html)
for m in md_refs:
    print(m)

# Find script src
print("\n=== SCRIPTS ===")
scripts = re.findall(r'src=["\']([^"\']+)["\']', html)
for s in scripts:
    print(s)
