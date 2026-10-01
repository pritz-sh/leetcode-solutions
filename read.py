import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "solved.json")
README_PATH = os.path.join(ROOT, "README.md")

DIFFICULTIES = ["Easy", "Medium", "Hard"]
LANGUAGES = {"cpp": "C++", "js": "JavaScript", "py": "Python", "rs": "Rust"}

GRAPHQL_URL = "https://leetcode.com/graphql"
QUERY = """
query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
  problemsetQuestionList: questionList(
    categorySlug: $categorySlug
    limit: $limit
    skip: $skip
    filters: $filters
  ) {
    total: totalNum
    questions: data {
      frontendQuestionId: questionFrontendId
      title
      titleSlug
      difficulty
    }
  }
}
"""

INCOMING_RE = re.compile(r"^(\d+)\.(" + "|".join(LANGUAGES) + r")$", re.IGNORECASE)


# --------------------------------------------------------------------------
# solved.json helpers
# --------------------------------------------------------------------------
def load_db():
    if os.path.exists(DB_PATH):
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    print("solved.json not found, scanning existing folders to build it...")
    return bootstrap_db()


def save_db(db):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, sort_keys=True)


def bootstrap_db():
    """Build the DB from an existing easy/medium/hard layout (one-time)."""
    db = {}
    for difficulty in DIFFICULTIES:
        diff_dir = os.path.join(ROOT, difficulty.lower())
        if not os.path.isdir(diff_dir):
            continue
        for folder in os.listdir(diff_dir):
            folder_path = os.path.join(diff_dir, folder)
            if not os.path.isdir(folder_path) or "-" not in folder:
                continue
            pid, name = folder.split("-", 1)
            if not pid.isdigit():
                continue
            stem = name.lower()
            slug = stem.replace("_", "-")
            langs = [
                ext for ext in LANGUAGES
                if os.path.exists(os.path.join(folder_path, f"{stem}.{ext}"))
            ]
            db[pid] = {
                "id": pid,
                "title": name.replace("_", " "),
                "slug": slug,
                "stem": stem,
                "difficulty": difficulty,
                "folder": folder,
                "languages": sorted(langs),
            }
    return db


# --------------------------------------------------------------------------
# LeetCode API
# --------------------------------------------------------------------------
def gql(variables):
    payload = json.dumps({"query": QUERY, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Referer": "https://leetcode.com/problemset/",
            "User-Agent": "Mozilla/5.0 (leetcode-readme-generator)",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def fetch_problem(number):
    """Find a problem by its frontend number. Returns a dict or None."""
    limit, skip = 100, 0
    while True:
        data = gql({
            "categorySlug": "",
            "skip": skip,
            "limit": limit,
            "filters": {"searchKeywords": str(number)},
        })
        result = data["data"]["problemsetQuestionList"]
        for q in result["questions"]:
            if q["frontendQuestionId"] == str(number):
                return q
        skip += limit
        if skip >= result["total"]:
            return None


def make_entry(q):
    slug = q["titleSlug"]
    stem = slug.replace("-", "_")
    pid = q["frontendQuestionId"]
    return {
        "id": pid,
        "title": q["title"],
        "slug": slug,
        "stem": stem,
        "difficulty": q["difficulty"],
        "folder": f"{pid}-{stem.title()}",
        "languages": [],
    }


# --------------------------------------------------------------------------
# Processing incoming files
# --------------------------------------------------------------------------
def find_incoming():
    files = []
    for name in os.listdir(ROOT):
        m = INCOMING_RE.match(name)
        if m and os.path.isfile(os.path.join(ROOT, name)):
            files.append((int(m.group(1)), m.group(2).lower(), name))
    return sorted(files)


def process(db):
    incoming = find_incoming()
    if not incoming:
        print("No files like 49.py / 1.cpp found next to read.py.")
        return False

    changed = False
    for number, ext, filename in incoming:
        pid = str(number)
        entry = db.get(pid)

        if entry is None:
            print(f"[{pid}] fetching from LeetCode...")
            try:
                q = fetch_problem(number)
            except (urllib.error.URLError, KeyError, TimeoutError, json.JSONDecodeError) as e:
                print(f"[{pid}] API error: {e}. Leaving {filename} untouched.")
                continue
            if q is None:
                print(f"[{pid}] problem not found. Leaving {filename} untouched.")
                continue
            entry = make_entry(q)
            db[pid] = entry
        else:
            print(f"[{pid}] already known ({entry['title']}), reusing its folder.")

        folder_path = os.path.join(ROOT, entry["difficulty"].lower(), entry["folder"])
        os.makedirs(folder_path, exist_ok=True)
        dest = os.path.join(folder_path, f"{entry['stem']}.{ext}")

        if os.path.exists(dest):
            print(f"[{pid}] {LANGUAGES[ext]} solution already exists at {dest}. "
                  f"Skipping (not overwriting). Delete {filename} or the old one manually.")
            continue

        shutil.move(os.path.join(ROOT, filename), dest)
        if ext not in entry["languages"]:
            entry["languages"].append(ext)
            entry["languages"].sort()
        print(f"[{pid}] {filename} -> {os.path.relpath(dest, ROOT)}")
        changed = True

    return changed


# --------------------------------------------------------------------------
# README
# --------------------------------------------------------------------------
def generate_table(db, difficulty):
    rows = [
        "| LeetCode ID | Problem | Solutions |",
        "| ----------- | ------- | --------- |",
    ]
    entries = [e for e in db.values() if e["difficulty"] == difficulty]
    for e in sorted(entries, key=lambda e: int(e["id"])):
        url = f"https://leetcode.com/problems/{e['slug']}"
        links = " &bull; ".join(
            f"[{lang}]({e['difficulty'].lower()}/{e['folder']}/{e['stem']}.{ext})"
            for ext, lang in LANGUAGES.items()  # all languages, whether or not they exist
        )
        rows.append(f"| {e['id']} | [{e['title']}]({url}) | {links} |")
    return "\n".join(rows)


def write_readme(db):
    sections = []
    for difficulty in DIFFICULTIES:
        sections.append(f"## {difficulty} Problems\n")
        sections.append(generate_table(db, difficulty))
        sections.append("")
    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(sections))


def main():
    db = load_db()
    process(db)
    save_db(db)
    write_readme(db)
    print("Done. solved.json and README.md updated.")


if __name__ == "__main__":
    sys.exit(main())
