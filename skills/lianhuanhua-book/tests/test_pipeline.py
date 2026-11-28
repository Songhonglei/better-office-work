import copy
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import comfyui
import comfyui_edit
import common
import progress
import make_prompts
import review_workbench
import rework

def png(color="white", size=(320, 256)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()

class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="book-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name) / "book"
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns("__pycache__", "tests", "assets", "site"))
        self.slug = "test-book"
        self.story = dict(slug=self.slug, title="Test", book="Original", author="Author", style="lianhuanhua-baimiao",
                          cast=[{"name":"Alice","anchor":"black coat and square face"}],
                          output={"width":320,"height":256,"crop_bottom":0,"max_kb":450},
                          pages=[dict(no=i, kind="cover" if i==0 else "page", title=f"page-{i}",
                                      caption=f"Caption {i}", scene=f"Scene {i}", who=[]) for i in range(12)])
        self.story["pages"][1]["who"] = ["Alice"]
        self.story["pages"][1]["scene"] = "Alice walks in the park"
        self.path = self.root / "stories" / (self.slug+".json")
        self.save_story()
        self.images = self.root / "assets" / "images" / self.slug
        self.raw = self.images / "_raw"
        self.raw.mkdir(parents=True)
        self.patchers = [
            patch.object(common, "STORIES", self.root/"stories"),
            patch.object(common, "STYLES", self.root/"styles"),
            patch.object(progress, "IMAGES", self.root/"assets"/"images"),
            patch.object(make_prompts, "STYLES", self.root/"styles"),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def save_story(self):
        self.path.write_text(json.dumps(self.story))
    def cli(self, name, *args, success=True):
        p = subprocess.run([sys.executable, str(self.root/"pipeline"/(name+".py")), *args],
                           cwd=self.root, text=True, capture_output=True)
        self.assertEqual(p.returncode == 0, success, p.stdout+"\n"+p.stderr)
        return p

    def fill_raw(self):
        for i in range(12):
            (self.raw/f"{i:02d}-page.png").write_bytes(png())
    def fill_processed(self):
        self.fill_raw()
        self.cli("post_process","--slug",self.slug)
    def approve_all(self):
        for i in range(12):
            progress.review(self.story,i,"approved","synthetic test; not an actual visual judgment")

    def test_happy_path_and_publish_gate(self):
        self.fill_processed()
        self.cli("verify","--slug",self.slug)
        self.cli("verify","--slug",self.slug,"--require-approved",success=False)
        self.approve_all()
        self.cli("verify","--slug",self.slug,"--require-approved")
        self.cli("build_site","--require-approved")
        read = self.root/"site/read"/self.slug/"index.html"
        self.assertIn('id="p11"', read.read_text())
        self.assertTrue((self.root/"site/assets"/self.slug/"011.jpg").exists())
        self.assertFalse((self.root/"site/assets"/self.slug/"progress.json").exists())

    def test_caption_layout_preserves_visual_approvals(self):
        self.story["pages"][0]["caption"] = "Cover caption by request only"
        self.story["pages"][1]["caption"] = "雨停了。灯还亮着。她推开门。"
        self.save_story()
        self.fill_processed()
        self.approve_all()
        self.story.pop("author")
        self.story["pages"][1]["caption_lines"] = ["雨停了。", "灯还亮着。", "她推开门。"]
        self.save_story()
        self.cli("build_site", "--require-approved")
        read = self.root / "site/read" / self.slug / "index.html"
        doc = read.read_text()
        self.assertNotIn("Cover caption by request only", doc)
        self.assertNotIn('class="sub"', doc)
        self.assertNotIn('class="card-book">Original ·', (self.root / "site/index.html").read_text())
        self.assertIn('<p class="caption-body caption-lines">雨停了。\n灯还亮着。\n她推开门。</p>', doc)
        self.story["pages"][0]["show_caption"] = True
        self.save_story()
        self.cli("build_site", "--require-approved")
        self.assertIn("Cover caption by request only", read.read_text())
        self.story["pages"][1]["caption_lines"][2] = "他关上门。"
        self.save_story()
        self.cli("build_site", "--require-approved", success=False)

    def test_workbench_keeps_review_choices_and_notes_separate_from_reader(self):
        self.story["continuity"] = {"umbrella": {"label": "Oil-paper umbrella", "rule": "Curved handle", "pages": [0, 2]}}
        self.story["pages"][2]["review_focus"] = {"umbrella": [0.25, 0.2, 0.75, 0.8]}
        self.save_story()
        common.load_story(self.slug)
        old = progress.ingest(self.story, 2, png("oldlace"))
        published = progress.ingest(self.story, 2, png("white"))
        baseline = (self.images / "progress.json").read_bytes()
        public_image = (self.images / "002.jpg").read_bytes()
        select = {"action": "select", "page": 2, "version": old["id"]}
        review_workbench.change_review(self.story, select)
        annotation = dict(select, action="annotate", message="Watch the handle angle", detail="umbrella", pin=[0.5, 0.6])
        review_workbench.change_review(self.story, annotation)
        view = review_workbench.book_view(self.story)
        self.assertEqual(view["pages"][2]["selected"], old["id"])
        self.assertEqual(view["pages"][2]["baseline"], published["id"])
        note = view["pages"][2]["notes"][0]
        self.assertEqual((note["version"], note["pin"]), (old["id"], [0.5, 0.6]))
        self.assertEqual([p["no"] for p in view["details"][0]["pages"]], [0, 2])
        page, version = review_workbench.archive_lookup(self.story, 2, old["id"])
        with Image.open(io.BytesIO(review_workbench.image_bytes(self.story, page, version, "umbrella"))) as image:
            self.assertEqual(image.width, 160)
        review_workbench.change_review(self.story, dict(select, action="resolve", note=note["id"], resolved=True))
        self.assertTrue(review_workbench.review_state(self.story)["notes"]["2"][0]["resolved"])
        self.assertEqual((self.images / "progress.json").read_bytes(), baseline)
        self.assertEqual((self.images / "002.jpg").read_bytes(), public_image)

    def test_rework_priority_resume_and_archive_stay_on_requested_page(self):
        server = "http://127.0.0.1:8188"
        tasks = []
        before = {}
        for number in (8, 9):
            version = progress.ingest(self.story, number, png())
            before[number] = version["id"]
            review_workbench.change_review(self.story, {"action": "annotate", "page": number, "version": version["id"], "message": "Review this page"})
            note = review_workbench.review_state(self.story)["notes"][str(number)][0]
            task = rework.enqueue(self.story, number, version["id"], note["id"])
            self.assertEqual(rework.enqueue(self.story, number, version["id"], note["id"])["id"], task["id"])
            tasks.append(task)
        rework.change_task(self.story, tasks[1]["id"], rank=5)
        claimed, resume = rework.claim(self.story, server)
        self.assertFalse(resume)
        self.assertEqual((claimed["id"], claimed["page"]), (tasks[1]["id"], 9))
        data = progress.manifest(self.story)
        data["pages"]["9"]["job"] = {"prompt_id": "same-model-job", "task_id": claimed["id"], "server": server}
        progress.save(self.story, data)
        rework.settle(self.story, claimed, SimpleNamespace(stdout="queued", stderr="job still pending"))
        paused = rework.queue_view(self.story)["tasks"][0]
        self.assertEqual((paused["status"], paused["prompt_id"]), ("paused", "same-model-job"))
        renewed, resume = rework.claim(self.story, server)
        self.assertTrue(resume)
        self.assertEqual((renewed["prompt_id"], renewed["runs"]), ("same-model-job", 2))
        result = progress.ingest(self.story, 9, png(), "comfyui", {"task_id": claimed["id"], "prompt_id": "same-model-job"}, select_version=False)
        self.assertNotEqual(result["id"], before[9])
        rework.settle(self.story, renewed, SimpleNamespace(stdout="saved", stderr=""))
        final = rework.queue_view(self.story)["tasks"]
        self.assertEqual(next(t for t in final if t["page"] == 9)["candidate"], result["id"])
        self.assertEqual(next(t for t in final if t["page"] == 8)["runs"], 0)
        self.assertEqual({int(i): row["selected"] for i, row in progress.manifest(self.story)["pages"].items()}, before)

    def test_rework_dry_run_adds_the_annotation_to_one_candidate(self):
        result = self.cli("comfyui", "--slug", self.slug, "--page", "9", "--preset", "qwen-q4", "--candidate",
                          "--task-id", "test-task", "--revision-note", "Keep the drop small", "--dry-run")
        graph = json.loads(result.stdout)
        self.assertIn("Keep the drop small", graph["4"]["inputs"]["prompt"])
        self.assertTrue(graph["8"]["inputs"]["filename_prefix"].endswith("/009"))

    def test_local_rework_persists_a_bounded_source_mask_and_comparison_scope(self):
        source = progress.ingest(self.story, 9, png("white"))
        review_workbench.change_review(self.story, {"action": "annotate", "page": 9, "version": source["id"], "message": "Small drop"})
        note = review_workbench.review_state(self.story)["notes"]["9"][0]
        full = rework.enqueue(self.story, 9, source["id"], note["id"])
        box = [0.25, 0.25, 0.5, 0.5]
        local = rework.enqueue(self.story, 9, source["id"], note["id"], preset="qwen-q6", scope="local", box=box)
        self.assertNotEqual(local["id"], full["id"])
        self.assertEqual(rework.enqueue(self.story, 9, source["id"], note["id"], preset="qwen-q6", scope="local", box=box)["id"], local["id"])
        mask = self.images / local["mask"]
        self.assertEqual(common.file_sha(mask), local["mask_sha256"])
        with Image.open(mask) as image:
            self.assertEqual(image.size, (320, 256))
            x1, y1, x2, y2 = image.getbbox()
            self.assertTrue(80 <= x1 < x2 <= 160 and 64 <= y1 < y2 <= 128)
            self.assertEqual(image.getpixel((114, 92)), 255)
        self.assertLess(review_workbench.comparison_focus(self.story, 9, source["id"], local["id"])[0], box[0])
        with self.assertRaises(ValueError):
            review_workbench.comparison_focus(self.story, 8, source["id"], local["id"])

    def test_schema_rejects_short_and_duplicate(self):
        self.story['pages'] = self.story['pages'][:2]
        self.save_story()
        self.cli('verify','--slug',self.slug,success=False)
        self.cli('make_prompts','--slug',self.slug)
        self.story['pages'][1]['no']=0
        self.save_story()
        self.cli('make_prompts','--slug',self.slug,success=False)

    def test_wrong_size_corrupt_extra(self):
        self.fill_processed()
        f=self.images/"001.jpg"
        Image.new("RGB",(300,200),"white").save(f)
        self.cli("verify","--slug",self.slug,success=False)
        f.write_bytes(b"corrupt")
        self.cli("verify","--slug",self.slug,success=False)
        f.write_bytes((self.images/"000.jpg").read_bytes())
        (self.images/"099.jpg").write_bytes(f.read_bytes())
        self.cli("verify","--slug",self.slug,success=False)

    def test_raw_duplicates_stop_before_writes(self):
        self.fill_raw()
        (self.raw/"01-duplicate.png").write_bytes(png("black"))
        self.cli("post_process","--slug",self.slug,success=False)
        self.assertFalse((self.images/"000.jpg").exists())

    def test_build_preserves_previous_on_failure_and_cleans_on_success(self):
        self.fill_processed()
        self.cli("build_site")
        site = self.root/"site"
        old = (site/"index.html").read_bytes()
        extra = site/"stale.txt"
        extra.write_text("old")
        f=self.images/"001.jpg"
        data=f.read_bytes()
        f.unlink()
        self.cli("build_site",success=False)
        self.assertEqual((site/"index.html").read_bytes(),old)
        self.assertTrue(extra.exists())
        f.write_bytes(data)
        self.cli("build_site")
        self.assertFalse(extra.exists())

    def test_prompt_landscape_and_black_coat(self):
        self.cli("make_prompts","--slug",self.slug)
        p=(self.images/"prompts/00.txt").read_text()
        self.assertNotIn("Alice",p)
        self.assertNotIn("人物以干净有力的墨线勾勒", p)
        self.assertNotIn("人物服饰", p)
        self.assertIn("建筑、山石、树木", p)
        p=(self.images/"prompts/01.txt").read_text()
        self.assertIn("Alice",p)
        self.assertIn("black coat",p)
        self.assertIn("人物以干净有力的墨线勾勒", p)
        self.assertIn("衣饰按人物设定保留深浅", p)
        self.assertNotIn("[[cast]]", p)

    def test_idempotent_versions_rollback_and_stale(self):
        a=progress.ingest(self.story,1,png(),"imagegen")
        self.assertEqual(a["id"],progress.ingest(self.story,1,png(),"imagegen")["id"])
        progress.review(self.story,1,"approved","checked")
        b=progress.ingest(self.story,1,png("black"),"imagegen")
        self.assertNotEqual(a["id"],b["id"])
        self.assertEqual(progress.state(self.story,self.story["pages"][1])[0],"pending")
        data=progress.manifest(self.story)
        progress.select(self.story,data,1,a)
        self.assertEqual(progress.state(self.story,self.story["pages"][1])[0],"approved")
        self.story["pages"][1]["scene"]="A changed scene"
        self.save_story()
        self.assertEqual(progress.state(self.story,self.story["pages"][1])[0],"stale")
        self.assertEqual(len(progress.manifest(self.story)["pages"]["1"]["versions"]),2)

    def test_reference_snapshot_change(self):
        self.story["cast"][0]["reference"]="alice.png"
        f=self.images/"cast/alice.png"
        f.parent.mkdir()
        f.write_bytes(png())
        self.save_story()
        v=progress.ingest(self.story,1,png(),"imagegen")
        snap=progress.version_dir(self.story,1,v)/"references/01.png"
        self.assertEqual(snap.read_bytes(),f.read_bytes())
        f.write_bytes(png("black"))
        self.assertEqual(progress.state(self.story,self.story["pages"][1])[0],"stale")

    def test_shared_detail_changes_only_its_pages(self):
        self.story["continuity"] = {"umbrella": {"rule": "One bamboo cane hook", "pages": [0, 2]}}
        self.story["pages"][2]["track"] = {"umbrella": "Hook touches doorjamb"}
        original = [progress.context(self.story, p)[1] for p in self.story["pages"]]
        p0, p1, p2 = self.story["pages"][:3]
        self.assertIn("One bamboo cane hook", make_prompts.render_page(self.story, p0))
        self.assertNotIn("umbrella", common.visual_checks(self.story, p1))
        self.assertIn("Hook touches doorjamb", common.visual_checks(self.story, p2)["umbrella"])
        self.story["continuity"]["umbrella"]["rule"] = "One straight bamboo handle"
        current = [progress.context(self.story, p)[1] for p in self.story["pages"]]
        self.assertEqual([n for n, hashes in enumerate(zip(original, current)) if hashes[0] != hashes[1]], [0, 2])
        self.story["pages"][1]["track"] = {"umbrella": "In the doorway"}
        with self.assertRaisesRegex(ValueError, "add this occurrence"):
            common.validate_story(self.story, self.slug)

    def test_detail_gate_and_candidate_selection(self):
        self.story["continuity"] = {}
        page = self.story["pages"][0]
        page["checks"] = {"support": "Umbrella tip touches the pavement"}
        self.save_story()
        original = progress.ingest(self.story, 0, png())
        candidate = progress.ingest(self.story, 0, png("black"), select_version=False)
        result = progress.checklist(self.story, [page])[0]
        self.assertEqual(result["selected"], original["id"])
        self.assertEqual(result["candidates"], [candidate["id"]])
        self.assertEqual(result["results"]["support"]["status"], "unverified")
        with self.assertRaisesRegex(ValueError, "approval requires all pass"):
            progress.review(self.story, 0, "approved", "No details", version_id=candidate["id"], promote=True)
        bad = {"support": {"status": "fail", "note": "There is a visible gap beneath the tip"}}
        progress.review(self.story, 0, "rejected", "Gap visible", bad, candidate["id"])
        self.assertEqual(progress.state(self.story, page)[1]["id"], original["id"])
        self.assertEqual(progress.checklist(self.story, [page], candidate["id"])[0]["results"], result["results"] | bad)
        good = {key: {"status": "pass", "note": "Synthetic check result"} for key in result["rules"]}
        fixed = progress.ingest(self.story, 0, png("blue"), select_version=False)
        progress.review(self.story, 0, "approved", "Checked", good, fixed["id"], True)
        status, selected = progress.state(self.story, page)
        self.assertEqual((status, selected["id"]), ("approved", fixed["id"]))
        self.assertEqual(selected["review_checks"], good)

    def test_sample_preflight_only_targets_declared_pages(self):
        self.story["samples"] = [3, 0]
        self.save_story()
        result = self.cli("comfyui", "--slug", self.slug, "--preset", "qwen-q4", "--samples", "--dry-run")
        self.assertLess(result.stdout.index(f"{self.slug}/003"), result.stdout.index(f"{self.slug}/000"))
        self.assertNotIn(f"{self.slug}/001", result.stdout)
        self.assertFalse((self.images / "progress.json").exists())

    def test_local_edit_composes_only_within_mask(self):
        base = Image.new("RGB", (320, 256), "white")
        mask = Image.new("L", base.size)
        ImageDraw.Draw(mask).rectangle((45, 50, 66, 72), fill=255)
        with self.assertRaisesRegex(ValueError, "contain the entire"):
            comfyui_edit.edit_area(base, mask, 64, 256, (50, 0, 200, 200))
        box, size = comfyui_edit.edit_area(base, mask, 64, 256)
        result = comfyui_edit.compose(base, mask, box, Image.new("RGB", size, "black"), size)
        self.assertEqual(result.getpixel((50, 60)), (0, 0, 0))
        self.assertEqual(result.getpixel((67, 73)), (255, 255, 255))

    def test_legacy_rerun_preserves_new_selection(self):
        a=progress.ingest(self.story,1,png(),"legacy-import")
        b=progress.ingest(self.story,1,png("black"),"imagegen")
        again=progress.ingest(self.story,1,png(),"legacy-import")
        self.assertEqual(again["id"],a["id"])
        self.assertEqual(progress.state(self.story,self.story["pages"][1])[1]["id"],b["id"])
        self.story["pages"][1]["caption"]="Changed caption"
        self.assertEqual(progress.state(self.story,self.story["pages"][1])[0],"stale")
        with self.assertRaises(ValueError):
            progress.ingest(self.story,1,png(),"legacy-import")

    def test_css_content_hash_changes_same_length(self):
        self.fill_processed()
        self.cli("build_site")
        before=(self.root/"site/index.html").read_text()
        css=self.root/"templates/style.css"
        b=css.read_bytes()
        css.write_bytes(b"X"+b[1:])
        self.cli("build_site")
        self.assertNotEqual(before,(self.root/"site/index.html").read_text())

    def test_strict_horizontal_canvas_rejects_square_without_changing_legacy_pad(self):
        output = dict(width=384, height=256)
        self.story["output"] = output
        page = self.story["pages"][0]
        square = png("black", (256, 256))
        with Image.open(io.BytesIO(progress.canvas(self.story, page, square))) as result:
            self.assertEqual(result.getpixel((0, 128)), (255, 255, 255))
            self.assertEqual(result.getpixel((192, 128)), (0, 0, 0))
        self.assertNotIn("fit", common.output_settings(self.story))

        self.story["output"]["fit"] = "strict"
        self.story["generation"] = {"width": 256, "height": 256}
        with self.assertRaisesRegex(ValueError, "same aspect ratio"):
            common.generation_settings(self.story)
        self.story["generation"] = {"width": 1248, "height": 832}
        with self.assertRaisesRegex(ValueError, "does not match"):
            progress.ingest(self.story, 0, square)
        self.assertFalse((self.images/"000.jpg").exists())
        v = progress.ingest(self.story, 0, png("black", (1248, 832)))
        with Image.open(self.images/"000.jpg") as result:
            self.assertEqual(result.size, (384, 256))
            self.assertEqual(result.getpixel((0, 128)), (0, 0, 0))
            self.assertEqual(result.getpixel((383, 128)), (0, 0, 0))
        self.assertIn("满幅横向构图", v["context"]["prompt"])

    def test_strict_qwen_references_use_the_generation_canvas(self):
        self.story["generation"] = {"width": 1248, "height": 832}
        self.story["output"] = {"width": 1536, "height": 1024, "fit": "strict"}
        names = ["Alice"]
        for name in ("Bob", "Carol"):
            names.append(name)
            self.story["cast"].append({"name": name, "anchor": name})
        for person in self.story["cast"]:
            filename = person["name"] + ".png"
            person["reference"] = filename
            path = self.images/"cast"/filename
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(png(size=(256, 256)))
        for preset in ("qwen-q4", "qwen-q6"):
            for count in range(4):
                self.story["pages"][1]["who"] = names[:count]
                self.save_story()
                graph = json.loads(self.cli(
                    "comfyui", "--slug", self.slug, "--page", "1", "--preset", preset, "--dry-run"
                ).stdout)
                node_id, _ = graph["6"]["inputs"]["latent_image"]
                self.assertEqual(graph[node_id]["class_type"], "EmptyLatentImage")
                self.assertEqual(graph[node_id]["inputs"], {"width": 1248, "height": 832, "batch_size": 1})
                encoder = graph["4"]["inputs"]
                self.assertNotIn("vae", encoder)
                for index, name in enumerate(names[:count], 1):
                    image_node, _ = encoder[f"images.image_{index}"]
                    self.assertEqual(pathlib.Path(graph[image_node]["inputs"]["image"]).name, name+".png")

    def test_comfy_qwen_dry_run_presets(self):
        for preset in ("qwen-q4","qwen-q6"):
            result=self.cli("comfyui","--slug",self.slug,"--page","0","--preset",preset,"--dry-run")
            graph=json.loads(result.stdout)
            self.assertEqual(graph["5"]["inputs"]["width"],320)
            self.assertEqual(graph["8"]["class_type"],"SaveImage")
            self.assertEqual(graph["4"]["inputs"]["prompt"],make_prompts.render_page(self.story,self.story["pages"][0]))
        self.story["cast"][0]["reference"]="alice.png"
        f=self.images/"cast/alice.png"; f.parent.mkdir(); f.write_bytes(png())
        self.save_story()
        graph=json.loads(self.cli("comfyui","--slug",self.slug,"--page","1","--preset","qwen-q4","--dry-run").stdout)
        self.assertEqual(pathlib.Path(graph["5"]["inputs"]["image"]).resolve(),f.resolve())
        self.assertIn("<image1> = Alice",graph["4"]["inputs"]["prompt"])
        for i, name in enumerate(("Bob","Carol"),2):
            ref=f"{name.lower()}.png"
            self.story["cast"].append({"name":name,"anchor":name,"reference":ref})
            self.story["pages"][1]["who"].append(name)
            (f.parent/ref).write_bytes(png("gray"))
            self.save_story()
            graph=json.loads(self.cli("comfyui","--slug",self.slug,"--page","1","--preset","qwen-q6","--dry-run").stdout)
            for slot in range(1,i+1):
                target=graph["4"]["inputs"][f"images.image_{slot}"][0]
                self.assertEqual(graph[target]["class_type"],"LoadImage")
            self.assertIn(f"<image{i}> = {name}",graph["4"]["inputs"]["prompt"])

    def test_comfy_timeout_resume_no_duplicate_queue(self):
        class Fake:
            submitted=0
            uploaded=0
            def submit(self, graph, prompt_id):
                self.submitted += 1
                return "mock-id"
            def upload(self, path):
                self.uploaded += 1
                return "reference.png"
            def wait(self, prompt_id, timeout):
                if not self.ready:
                    raise TimeoutError("mock timeout")
                return {"outputs":{"8":{"images":[{"filename":"generated.png","subfolder":"","type":"output"}]}}}
            def download(self, image):
                return png("blue")
        self.story["cast"][0]["reference"]="alice.png"
        f=self.images/"cast/alice.png"; f.parent.mkdir(); f.write_bytes(png())
        self.save_story()
        fake=Fake();fake.ready=False
        args=SimpleNamespace(seed=123,output_node="8",dry_run=False,resume=False,server="http://127.0.0.1:8188",timeout=1)
        template=common.read_json(self.root/"workflows/qwen-q4-1ref.api.json")
        with self.assertRaises(TimeoutError):
            comfyui.run_page(args,self.story,self.story["pages"][1],fake,template,"hash")
        self.assertEqual(progress.state(self.story,self.story["pages"][1])[0],"generating")
        args.resume=True;fake.ready=True
        comfyui.run_page(args,self.story,self.story["pages"][1],fake,template,"hash")
        self.assertEqual(fake.submitted,1)
        self.assertEqual(fake.uploaded,1)
        self.assertEqual(progress.state(self.story,self.story["pages"][1])[0],"pending")
        self.assertEqual(progress.manifest(self.story)["pages"]["1"]["versions"][0]["metadata"]["prompt_id"],"mock-id")

    def test_init_project(self):
        destination=self.root.parent/"new-book"
        self.cli("init_project",str(destination))
        self.assertTrue((destination/"serve.sh").is_file())
        self.assertTrue((destination/"workflows/qwen-q4-2ref.api.json").is_file())
        self.cli("init_project",str(destination),success=False)

    def test_comfy_submit_lost_response_keeps_id(self):
        class Fake:
            sent_id=None
            def submit(self, graph, prompt_id):
                self.sent_id=prompt_id
                raise RuntimeError("mock request lost after submission")
        fake=Fake()
        args=SimpleNamespace(seed=1,output_node="8",dry_run=False,resume=False,server="http://127.0.0.1:8188",timeout=1)
        graph=common.read_json(self.root/"workflows/qwen-q4-0ref.api.json")
        with self.assertRaises(RuntimeError):
            comfyui.run_page(args,self.story,self.story["pages"][0],fake,graph,"hash")
        job=progress.manifest(self.story)["pages"]["0"]["job"]
        self.assertEqual(job["prompt_id"],fake.sent_id)
        with self.assertRaises(ValueError):
            comfyui.run_page(args,self.story,self.story["pages"][0],fake,graph,"hash")

    def test_comfy_read_only_probe_model_choices(self):
        client=comfyui.Client("http://127.0.0.1:8188")
        graph={"1":{"class_type":"UnetLoaderGGUF","inputs":{"unet_name":"model.gguf"}}}
        with patch.object(client,"call",return_value={"UnetLoaderGGUF":{"input":{"required":{"unet_name":[["model.gguf"]]}}}}) as call:
            client.probe(graph)
            call.assert_called_once_with("/object_info/UnetLoaderGGUF")
        with patch.object(client,"call",return_value={"UnetLoaderGGUF":{"input":{"required":{"unet_name":[[]]}}}}):
            with self.assertRaises(ValueError):
                client.probe(graph)

    def test_comfy_probe_checks_sampler_parameters_without_upload(self):
        client = comfyui.Client("http://127.0.0.1:8188")
        graph = {
            "1": {"class_type": "KSampler", "inputs": {"sampler_name": "euler", "seed": 10}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "/local/owner.png"}},
        }
        sampler = {"sampler_name": [["euler"]], "seed": ["INT", {"min": 0, "max": 20}]}
        loader = {"image": [["example.png"], {"image_upload": True}]}
        with patch.object(client, "call", side_effect=[
            {"KSampler": {"input": {"required": sampler}}},
            {"LoadImage": {"input": {"required": loader}}},
            {"KSampler": {"input": {"required": sampler}}},
            {"KSampler": {"input": {"required": sampler}}},
        ]) as call:
            client.probe(graph)
            graph["1"]["inputs"]["seed"] = 21
            with self.assertRaisesRegex(ValueError, r"KSampler\.seed.*outside"):
                client.probe(graph)
            graph["1"]["inputs"]["sampler_name"] = "unknown"
            with self.assertRaisesRegex(ValueError, r"KSampler\.sampler_name.*unavailable"):
                client.probe(graph)
            self.assertTrue(all(args[0][0].startswith("/object_info/") for args in call.call_args_list))

if __name__ == "__main__":
    unittest.main()
