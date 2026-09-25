"""VideoGenerator + AIVideoProvider abstractions (vendor-neutral)."""
from __future__ import annotations

import shutil
import time
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class VideoGeneratorContext:
    still_image: Path
    work_dir: Path
    duration_seconds: float = 3.0
    fps: int = 30
    seed: int = 0


class VideoGenerator(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, ctx: VideoGeneratorContext) -> Path:
        """Generate a video file from the still image; return local path."""
        raise NotImplementedError


class AIVideoProvider(ABC):
    """Vendor-neutral Image-to-Video provider.

    Concrete adapters implement submit/poll/download against a real vendor
    endpoint configured by the user. No vendor API is hardcoded here.
    """

    provider_name: str = "base"

    def __init__(self, *, endpoint: str, model: str, api_key: str,
                 timeout_seconds: int = 300, retry_count: int = 2,
                 prompt: str = "", duration_seconds: float = 3.0) -> None:
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.retry_count = retry_count
        self.prompt = prompt
        self.duration_seconds = duration_seconds

    @abstractmethod
    def submit(self, image_path: Path, work_dir: Path) -> str:
        raise NotImplementedError

    @abstractmethod
    def poll(self, job_id: str) -> tuple[str, str | None]:
        """Return (status, download_url|None); status in pending/running/succeeded/failed."""
        raise NotImplementedError

    def wait(self, job_id: str, cancel=None) -> str:
        deadline = time.time() + max(10, self.timeout_seconds)
        attempt = 0
        while time.time() < deadline:
            if cancel is not None and cancel():
                raise RuntimeError("AI video generation cancelled")
            status, url = self.poll(job_id)
            if status == "succeeded" and url:
                return url
            if status == "failed":
                raise RuntimeError("AI video provider reported failure")
            time.sleep(min(5.0, 1.0 + attempt * 0.5))
            attempt += 1
        raise TimeoutError("AI video generation timed out")

    @abstractmethod
    def download(self, url: str, dest: Path) -> Path:
        raise NotImplementedError

    def generate(self, image_path: Path, work_dir: Path, cancel=None) -> Path:
        last: Exception | None = None
        for _ in range(max(1, self.retry_count + 1)):
            try:
                job_id = self.submit(image_path, work_dir)
                url = self.wait(job_id, cancel=cancel)
                dest = work_dir / "ai_video_src.bin"
                return self.download(url, dest)
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise RuntimeError(f"AI video generation failed: {last}") from last

    def redacted(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self.model,
            "endpoint": self.endpoint,
            "api_key": "***",
            "duration_seconds": self.duration_seconds,
        }


class GenericHttpAIVideoProvider(AIVideoProvider):
    """Config-driven generic adapter: POST image+prompt, poll status URL.

    Expected (documented, user-supplied) contract — the app never invents a
    vendor response shape; if the endpoint does not follow it, preflight and
    error messages say so plainly:
      POST {endpoint} (multipart: image, model, prompt, duration)
        -> {"job_id": "..."} or {"status_url": "..."}
      GET {status_url or endpoint/jobs/<id>}
        -> {"status": "succeeded", "video_url": "..."}
    """

    provider_name = "generic-http"

    def _endpoint_origin(self) -> str:
        from urllib.parse import urlparse

        return urlparse(self.endpoint).netloc.lower()

    def _safe_request(self, url: str, *, timeout: int) -> urllib.request.Request:
        """Build a GET request with scheme/host safety.

        Server-supplied URLs (status/video) are untrusted: only http(s) is
        allowed, and the API key is forwarded solely to the configured
        endpoint's own host — never to third-party hosts, and never via
        file:// or other schemes.
        """
        from urllib.parse import urlparse

        parts = urlparse(url)
        if parts.scheme not in ("http", "https"):
            raise RuntimeError(f"AI provider returned unsafe URL scheme: {parts.scheme or url!r}")
        headers: dict[str, str] = {}
        if parts.netloc.lower() == self._endpoint_origin():
            headers["Authorization"] = f"Bearer {self.api_key}"
        return urllib.request.Request(url, headers=headers)

    def submit(self, image_path: Path, work_dir: Path) -> str:
        import json
        import uuid
        from urllib.parse import urlparse

        if urlparse(self.endpoint).scheme not in ("http", "https"):
            raise RuntimeError(f"AI provider endpoint must be http(s): {self.endpoint!r}")

        boundary = f"----aip{uuid.uuid4().hex}"
        fields = {
            "model": self.model,
            "prompt": self.prompt,
            "duration": str(self.duration_seconds),
        }
        body = b""
        for k, v in fields.items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        data = image_path.read_bytes()
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"AI provider submit failed ({self.endpoint}): {exc}") from exc
        job_id = payload.get("job_id") or payload.get("id")
        status_url = payload.get("status_url") or payload.get("statusUrl")
        if status_url:
            (work_dir / "ai_status_url.txt").write_text(str(status_url), encoding="utf-8")
            return str(status_url)
        if job_id:
            return str(job_id)
        raise RuntimeError(f"AI provider returned unexpected submit payload: {sorted(payload.keys())}")

    def _status_url(self, job_id: str, work_dir: Path | None = None) -> str:
        if job_id.startswith("http"):
            return job_id
        base = self.endpoint.rstrip("/")
        return f"{base}/jobs/{job_id}"

    def poll(self, job_id: str) -> tuple[str, str | None]:
        import json

        url = self._status_url(job_id)
        req = self._safe_request(url, timeout=30)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"AI provider poll failed: {exc}") from exc
        status = str(payload.get("status", "pending")).lower()
        video_url = payload.get("video_url") or payload.get("videoUrl") or payload.get("url")
        mapping = {"succeeded": "succeeded", "success": "succeeded", "completed": "succeeded",
                   "failed": "failed", "error": "failed"}
        return mapping.get(status, "pending"), (str(video_url) if video_url else None)

    def download(self, url: str, dest: Path) -> Path:
        req = self._safe_request(url, timeout=120)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
                shutil.copyfileobj(resp, fh)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"AI video download failed: {exc}") from exc
        return dest


class MockAIVideoProvider(AIVideoProvider):
    """Test-only provider: copies a fixture file as the 'downloaded' video."""

    provider_name = "mock"

    def __init__(self, fixture: Path, **kwargs) -> None:
        super().__init__(endpoint=kwargs.get("endpoint", "mock://"),
                         model=kwargs.get("model", "mock"),
                         api_key=kwargs.get("api_key", ""),
                         timeout_seconds=kwargs.get("timeout_seconds", 30),
                         retry_count=kwargs.get("retry_count", 0),
                         prompt=kwargs.get("prompt", ""),
                         duration_seconds=kwargs.get("duration_seconds", 3.0))
        self.fixture = Path(fixture)
        self.poll_count = 0

    def submit(self, image_path: Path, work_dir: Path) -> str:
        return "mock-job-1"

    def poll(self, job_id: str) -> tuple[str, str | None]:
        self.poll_count += 1
        return "succeeded", f"file://{self.fixture}"

    def download(self, url: str, dest: Path) -> Path:
        src = url.removeprefix("file://")
        shutil.copy2(src, dest)
        return dest
