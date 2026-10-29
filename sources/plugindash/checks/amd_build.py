"""Does every AMD module in amd/src have its built file in amd/build? (Moodle only serves amd/build.)"""

from __future__ import annotations

from ..model import AMBER, OK, Finding

ID = "amd_build"
TITLE = "AMD builds"
DESCRIPTION = "Amber if a module in amd/src has no amd/build/<name>.min.js or .min.js.map; rebuild with grunt."
ORDER = 53

# What to do about each kind of problem: the first key found in the finding's message wins; "" is the default.
FIX = {
    "": ("Rebuild with grunt in a checkout of the lowest supported Moodle branch (npx grunt amd --root=<plugin "
         "dir>) and commit amd/src and amd/build together."),
}


def run(repo, plugin, ctx):
    sources = repo.list_dir("amd/src")
    if sources is None:
        return []  # No JavaScript modules.
    modules = sorted(name[:-3] for name in sources if name.endswith(".js"))
    if not modules:
        return []
    built = set(repo.list_dir("amd/build") or [])
    missing = [f"{m}.min.js" for m in modules if f"{m}.min.js" not in built]
    missing += [f"{m}.min.js.map" for m in modules if f"{m}.min.js.map" not in built]
    if missing:
        shown = ", ".join(missing[:4]) + (f" and {len(missing) - 4} more" if len(missing) > 4 else "")
        return [Finding(ID, AMBER, f"amd/build is missing {shown}; rebuild with grunt and commit", repo.html_url)]
    return [Finding(ID, OK, f"{len(modules)} AMD module{'s' if len(modules) != 1 else ''} built")]
