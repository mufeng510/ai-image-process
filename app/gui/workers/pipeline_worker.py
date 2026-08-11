"""QThread worker that runs core pipeline without blocking UI."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from app.config.schema import AppConfig
from app.core.models import CancelToken, JobResult, ProgressEvent, ProgressKind
from app.core.pipeline import run_job


class PipelineWorker(QObject):
    progress = Signal(object)  # ProgressEvent
    finished = Signal(object)  # JobResult
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancel = CancelToken()
        self._config: AppConfig | None = None
        self._inputs: list[Path] = []
        self._output: Path | None = None
        self._seed: int | None = None

    def configure(
        self,
        config: AppConfig,
        inputs: list[Path],
        output: Path,
        seed: int | None = None,
    ) -> None:
        self._config = config
        self._inputs = list(inputs)
        self._output = output
        self._seed = seed
        self._cancel = CancelToken()

    @Slot()
    def run(self) -> None:
        try:
            if self._config is None or self._output is None:
                raise RuntimeError("worker not configured")

            def _cb(ev: ProgressEvent) -> None:
                self.progress.emit(ev)

            result = run_job(
                self._config,
                self._inputs,
                output_dir=self._output,
                progress_cb=_cb,
                cancel_token=self._cancel,
                seed=self._seed,
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def request_cancel(self) -> None:
        self._cancel.cancel()
        self.progress.emit(
            ProgressEvent(
                kind=ProgressKind.LOG,
                job_id="",
                message="正在取消…（将在当前文件完成后停止）",
            )
        )


class PipelineController(QObject):
    """Owns QThread + worker lifecycle."""

    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None

    @property
    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, config: AppConfig, inputs: list[Path], output: Path, seed: int | None = None) -> None:
        if self.is_busy:
            raise RuntimeError("job already running")
        thread = QThread(self)
        worker = PipelineWorker()
        worker.configure(config, inputs, output, seed=seed)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress.emit)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        self._worker = worker
        self.busy_changed.emit(True)
        thread.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()

    def _on_finished(self, result: JobResult) -> None:
        self.finished.emit(result)

    def _on_failed(self, message: str) -> None:
        self.failed.emit(message)

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.busy_changed.emit(False)
