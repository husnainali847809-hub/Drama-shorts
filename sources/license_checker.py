# Commercially reusable licenses only. CC BY permits commercial reuse with attribution.
# Exclude NC (non-commercial), ND (no-derivatives), and SA (share-alike) licenses.
ALLOWED_LICENSES = {
    "https://creativecommons.org/publicdomain/mark/1.0/",
    "http://creativecommons.org/publicdomain/mark/1.0/",
    "https://creativecommons.org/publicdomain/zero/1.0/",
    "http://creativecommons.org/publicdomain/zero/1.0/",
    "https://creativecommons.org/licenses/by/1.0/",
    "http://creativecommons.org/licenses/by/1.0/",
    "https://creativecommons.org/licenses/by/2.0/",
    "http://creativecommons.org/licenses/by/2.0/",
    "https://creativecommons.org/licenses/by/2.5/",
    "http://creativecommons.org/licenses/by/2.5/",
    "https://creativecommons.org/licenses/by/3.0/",
    "http://creativecommons.org/licenses/by/3.0/",
    "https://creativecommons.org/licenses/by/4.0/",
    "http://creativecommons.org/licenses/by/4.0/",
}

def normalize_license(value: str) -> str:
    return (value or "").strip().split("?")[0].rstrip("/") + "/" if value else ""

def license_is_allowed(value: str) -> bool:
    return normalize_license(value) in {normalize_license(x) for x in ALLOWED_LICENSES}

def attribution_required(value: str) -> bool:
    return "/licenses/by/" in normalize_license(value) or "/licenses/by-sa/" in normalize_license(value)

def license_label(value: str) -> str:
    normalized = normalize_license(value)
    if "publicdomain/mark" in normalized:
        return "Public Domain Mark 1.0"
    if "publicdomain/zero" in normalized:
        return "CC0 1.0"
    if "/licenses/by-sa/" in normalized:
        version = normalized.split("/licenses/by-sa/", 1)[1].strip("/")
        return f"CC BY-SA {version}"
    if "/licenses/by/" in normalized:
        version = normalized.split("/licenses/by/", 1)[1].strip("/")
        return f"CC BY {version}"
    return "Unverified"
