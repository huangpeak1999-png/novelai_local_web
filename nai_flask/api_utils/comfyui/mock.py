"""In-process protocol simulator. No listening port; never a GPU implementation."""
import io
import uuid

from PIL import Image, ImageDraw, ImageFont


class MockComfyClient:
    is_mock = True

    def __init__(self, scenario="success"):
        self.jobs = {}
        self.scenario = scenario

    def health(self):
        return {"online": True, "test_data": True}

    def submit(self, graph, client_id):
        prompt_id = uuid.uuid4().hex
        self.jobs[prompt_id] = {"polls": 0, "graph": graph}
        return {"prompt_id": prompt_id, "number": len(self.jobs), "node_errors": {}}

    def history(self, prompt_id):
        job = self.jobs[prompt_id]
        job["polls"] += 1
        if self.scenario == "timeout" or job["polls"] < 3:
            return {}
        if self.scenario == "failure":
            return {prompt_id: {"status": {"status_str": "error", "completed": False}, "outputs": {}}}
        return {prompt_id: {"status": {"status_str": "success", "completed": True},
                           "outputs": {"mock_output": {"images": [{"filename": "MOCK_TEST_DATA.png", "subfolder": "", "type": "output"}]}}}}

    def queue(self):
        return {"queue_pending": [[0, key] for key, job in self.jobs.items() if job["polls"] == 1],
                "queue_running": [[0, key] for key, job in self.jobs.items() if job["polls"] == 2]}

    def view(self, descriptor):
        image = Image.new("RGB", (512, 512), "#25354a")
        ImageDraw.Draw(image).multiline_text((40, 175), "MOCK / TEST DATA\nNOT GPU GENERATED\nComfyComic M1",
                                             fill="white", font=ImageFont.load_default(size=26), spacing=16)
        output = io.BytesIO()
        image.save(output, "PNG")
        return output.getvalue()
