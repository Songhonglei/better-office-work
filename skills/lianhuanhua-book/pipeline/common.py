"""Shared story schema, output settings, and atomic file helpers."""
import hashlib
import json
import os
import pathlib
import re
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
STORIES = ROOT / "stories"
IMAGES = ROOT / "assets" / "images"
STYLES = ROOT / "styles"
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
BASE_CHECKS = {
    "scene": "画面对应本页分镜和旁白，人物、动作、视线与物件能辨认。",
    "composition": "构图、画幅、空间关系和画风与本册一致，检查边缘及邻页衔接。",
}


def identifier(value, label="slug"):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_json(path, value):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    return sha(path.read_bytes())


def text_field(obj, key, allow_empty=False):
    if not isinstance(obj, dict):
        raise ValueError("Expected an object")
    value = obj.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"Missing or invalid field: {key}")
    return value


def output_settings(story):
    # Old white-line projects retain the old 80px interior crop.
    defaults = dict(width=1536, height=1024, crop_bottom=80 if "output" not in story and
                    story.get("style") == "lianhuanhua-baimiao" else 0,
                    cover_crop_bottom=0, quality=82, max_kb=450)
    settings = story.get("output", {})
    if not isinstance(settings, dict) or set(settings) - (set(defaults) | {"fit"}):
        raise ValueError("Invalid output settings")
    defaults.update({key: value for key, value in settings.items() if key != "fit"})
    for k, v in defaults.items():
        if type(v) is not int:
            raise ValueError(f"output.{k} must be an integer")
    if not (256 <= defaults["width"] <= 4096 and 256 <= defaults["height"] <= 4096):
        raise ValueError("Output dimensions must be 256–4096")
    if not 40 <= defaults["quality"] <= 100 or defaults["max_kb"] < 50:
        raise ValueError("Invalid quality or max_kb")
    for k in ("crop_bottom", "cover_crop_bottom"):
        if not 0 <= defaults[k] <= defaults["height"] - 200:
            raise ValueError(f"Invalid {k}")
    if "fit" in settings:
        if settings["fit"] not in ("pad", "strict"):
            raise ValueError("output.fit must be pad or strict")
        defaults["fit"] = settings["fit"]
    return defaults


def expected_size(story, page):
    s = output_settings(story)
    crop = s["cover_crop_bottom" if page["no"] == 0 else "crop_bottom"]
    return s["width"], s["height"] - crop


def generation_settings(story):
    output = output_settings(story)
    g = story.get("generation", {})
    if not isinstance(g, dict) or set(g) - {"width", "height"}:
        raise ValueError("Invalid generation settings")
    result = {k: g.get(k, output[k]) for k in ("width", "height")}
    for k, v in result.items():
        if type(v) is not int or not 256 <= v <= 4096 or v % 8:
            raise ValueError(f"generation.{k} must be divisible by 8 and between 256 and 4096")
    if output.get("fit") == "strict" and result["width"] * output["height"] != result["height"] * output["width"]:
        raise ValueError("With output.fit=strict, generation and output must have the same aspect ratio")
    return result


def check_map(data, name, *, allow_empty=False):
    if not isinstance(data, dict):
        raise ValueError(f"{name} must be an object keyed by detail ID")
    for key in data:
        identifier(key, name)
        if key in BASE_CHECKS:
            raise ValueError(f"{key} is reserved for the standard visual checks")
        text_field(data, key, allow_empty=allow_empty)
    return data


def detail_rules(story, page):
    """Resolve shared rules only where the page references them."""
    occurrences = page.get("track", {})
    result = {key: value["rule"] for key, value in story.get("continuity", {}).items()
              if isinstance(value, dict) and page["no"] in value["pages"]}
    for key, occurrence in occurrences.items():
        shared = story["continuity"][key]
        rule = shared["rule"] if isinstance(shared, dict) else shared
        result[key] = rule + (f" 本页要求：{occurrence}" if occurrence.strip() else "")
    return result | page.get("checks", {})


def visual_checks(story, page):
    return BASE_CHECKS | detail_rules(story, page) if "continuity" in story else {}


def page_numbers(values, count, name):
    if (not isinstance(values, list) or any(type(no) is not int or not 0 <= no < count for no in values)
            or len(values) != len(set(values))):
        raise ValueError(f"{name} must contain unique existing page numbers")


def shared_rules(values, count):
    if not isinstance(values, dict):
        raise ValueError("continuity must be an object keyed by detail ID")
    for key, value in values.items():
        if isinstance(value, dict):
            if not {"rule", "pages"} <= value.keys() <= {"rule", "pages", "label"} or not value["pages"]:
                raise ValueError(f"Continuity {key}: use a rule and its nonempty page list")
            if "label" in value:
                text_field(value, "label")
            page_numbers(value["pages"], count, f"Continuity {key}.pages")
            check_map({key: value["rule"]}, "continuity")
        else:
            check_map({key: value}, "continuity")
    return values


def validate_story(story, slug, complete=True):
    if not isinstance(story, dict):
        raise ValueError("Story must be an object")
    if identifier(story.get("slug")) != identifier(slug):
        raise ValueError("Story slug must match its filename")
    for k in ("title", "book", "style"):
        text_field(story, k)
    for k in ("author", "summary", "colophon", "era_anchor", "negative", "source", "era"):
        if k in story:
            text_field(story, k, allow_empty=True)
    identifier(story["style"], "style")
    if not (STYLES / (story["style"] + ".txt")).is_file():
        raise ValueError("Style file not found: " + story["style"])
    cast = story.get("cast")
    if not isinstance(cast, list):
        raise ValueError("cast must be an array")
    names = []
    for c in cast:
        names.append(text_field(c, "name"))
        text_field(c, "anchor")
        if "reference" in c:
            ref = pathlib.PurePath(text_field(c, "reference"))
            if ref.is_absolute() or ".." in ref.parts:
                raise ValueError("Reference must be relative to the story cast directory")
    if len(set(names)) != len(names):
        raise ValueError("Duplicate cast name")
    pages = story.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("pages must be a nonempty array")
    if complete and not 12 <= len(pages) <= 20:
        raise ValueError("A finished book must have 12–20 pages, including cover")
    continuity = shared_rules(story.get("continuity", {}), len(pages))
    page_numbers(story.get("samples", []), len(pages), "samples")
    for i, p in enumerate(pages):
        if not isinstance(p, dict):
            raise ValueError(f"Page {i} must be an object")
        if type(p.get("no")) is not int or p["no"] != i:
            raise ValueError(f"Pages must be unique, ordered and consecutive; expected {i}")
        if p.get("kind") != ("cover" if i == 0 else "page"):
            raise ValueError(f"Invalid kind on page {i}")
        for k in ("title", "scene", "caption"):
            text_field(p, k, allow_empty=(k == "caption" and i == 0))
        if "show_caption" in p and (i != 0 or type(p["show_caption"]) is not bool):
            raise ValueError("show_caption must be a boolean on the cover")
        if "caption_lines" in p:
            lines = p["caption_lines"]
            if (not isinstance(lines, list) or not lines
                    or any(not isinstance(line, str) or not line.strip() or line.splitlines() != [line] for line in lines)
                    or re.sub(r"\s+", "", "".join(lines)) != re.sub(r"\s+", "", p["caption"])):
                raise ValueError(f"Page {i}: caption_lines must use the same wording as caption, one nonempty line per item")
        if "era_anchor" in p:
            text_field(p, "era_anchor", allow_empty=True)
        if "track" in p or "checks" in p:
            if "continuity" not in story:
                raise ValueError("Declare continuity (an empty object is allowed) to track page details")
            tracked = check_map(p.get("track", {}), f"page {i} track", allow_empty=True)
            local = check_map(p.get("checks", {}), f"page {i} checks")
            if tracked.keys() - continuity.keys() or local.keys() & continuity.keys():
                raise ValueError(f"Page {i}: track must reference shared details; checks must use local IDs")
            if any(isinstance(continuity[key], dict) and i not in continuity[key]["pages"] for key in tracked):
                raise ValueError(f"Page {i}: add this occurrence to the shared detail's pages")
        focus = p.get("review_focus", {})
        if not isinstance(focus, dict) or focus.keys() - detail_rules(story, p).keys():
            raise ValueError(f"Page {i}: review_focus must reference a detail on the page")
        for box in focus.values():
            if (not isinstance(box, list) or len(box) != 4 or any(type(v) not in (int, float) for v in box)
                    or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)):
                raise ValueError(f"Page {i}: review_focus boxes use normalized left, top, right, bottom")
        if "who" in p:
            who = p["who"]
            if (not isinstance(who, list) or any(not isinstance(n, str) or n not in names for n in who)
                    or len(set(who)) != len(who)):
                raise ValueError(f"Invalid or duplicate cast in who on page {i}")
    output_settings(story)
    generation_settings(story)
    return story


def load_story(slug, complete=True):
    identifier(slug)
    return validate_story(read_json(STORIES / (slug + ".json")), slug, complete)


def get_page(story, no):
    if type(no) is not int or not 0 <= no < len(story["pages"]):
        raise ValueError(f"Page does not exist: {no}")
    return story["pages"][no]


def page_file(page):
    return f"{page['no']:03d}.jpg"
