from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import subprocess
from urllib.parse import urlparse
from uuid import uuid4

import numpy as np
import soundfile as sf
from sqlmodel import Session, select
from yt_dlp import YoutubeDL

from app.config import settings
from app.models import Ad, Detection, Stream
from app.services.media import (
    build_constellation_hashes,
    build_constellation_hashes_from_file,
    ensure_storage_dirs,
    ffmpeg_available,
)
from app.time_utils import ensure_local_datetime, now_local

MIN_CONSISTENT_HASHES = 120


@dataclass
class MatchResult:
    ad_id: int
    ad_title: str
    confidence: float
    matched_at: datetime
    offset_seconds: float
    evidence_path: str | None = None
    created_detection: bool = False


@dataclass
class PreparedAdFingerprint:
    ad: Ad
    hashes: dict[str, list[int]]
    duration_seconds: float


class ConstellationFingerprintMatcher:
    """
    Matcher inspirado en audio fingerprinting tipo Shazam.

    En lugar de resumir todo el audio en un unico vector, compara relaciones
    estables entre picos espectrales distribuidos a lo largo del tiempo.
    """

    def best_match_for_ad(
        self,
        window_hashes: dict[str, list[int]],
        prepared_ad: PreparedAdFingerprint,
    ) -> tuple[float, float]:
        ad_hashes = prepared_ad.hashes
        if not ad_hashes or not window_hashes:
            return 0.0, 0.0

        offset_histogram: dict[int, int] = {}
        compared_hashes = 0

        # Un match valido necesita muchos hashes iguales apuntando al mismo offset temporal.
        for hash_key, ad_times in ad_hashes.items():
            window_times = window_hashes.get(hash_key)
            if not window_times:
                continue

            compared_hashes += 1
            limited_ad_times = ad_times[:8]
            limited_window_times = window_times[:8]
            for ad_time in limited_ad_times:
                for window_time in limited_window_times:
                    offset = window_time - ad_time
                    offset_histogram[offset] = offset_histogram.get(offset, 0) + 1

        if not offset_histogram or compared_hashes == 0:
            return 0.0, 0.0

        best_offset_frames, best_count = max(offset_histogram.items(), key=lambda item: item[1])
        if best_count < MIN_CONSISTENT_HASHES:
            return 0.0, 0.0

        # El score expresa que porcentaje de la huella del spot encontro un offset consistente.
        score = best_count / max(len(ad_hashes), 1)
        offset_seconds = max(best_offset_frames, 0) * (512 / settings.sample_rate)
        return min(score, 1.0), offset_seconds

    def prepare_ad(self, ad: Ad) -> PreparedAdFingerprint | None:
        if not ad.normalized_audio_path:
            return None

        normalized_audio_path = Path(ad.normalized_audio_path)
        if not normalized_audio_path.exists():
            return None

        hashes, duration_seconds = build_constellation_hashes_from_file(normalized_audio_path)
        if not hashes:
            return None

        return PreparedAdFingerprint(
            ad=ad,
            hashes=hashes,
            duration_seconds=duration_seconds,
        )


class StreamMonitor:
    def __init__(self, session: Session):
        self.session = session
        self.matcher = ConstellationFingerprintMatcher()

    def run(
        self,
        stream: Stream,
        *,
        window_seconds: int,
        window_step_seconds: float,
        iterations: int,
        similarity_threshold: float,
        cooldown_seconds: int,
        keep_evidence: bool,
        progress_callback=None,
        should_cancel=None,
    ) -> list[dict]:
        if not ffmpeg_available():
            raise RuntimeError("FFmpeg no esta disponible para monitorear streams.")

        ensure_storage_dirs()
        ads = list(
            self.session.exec(
                select(Ad).where(Ad.processing_status == "ready").where(Ad.normalized_audio_path.is_not(None))
            ).all()
        )
        if not ads:
            raise RuntimeError("No hay spots listos para comparar.")

        prepared_ads = [prepared for ad in ads if (prepared := self.matcher.prepare_ad(ad)) is not None]
        if not prepared_ads:
            raise RuntimeError("No se pudieron preparar huellas de spots listos para comparar.")

        resolved_source_url = self._resolve_source_url(stream.source_url)
        process = self._open_stream_process(resolved_source_url)
        results: list[dict] = []
        bytes_per_second = settings.sample_rate * 2
        window_bytes = int(window_seconds * bytes_per_second)
        step_bytes = int(window_step_seconds * bytes_per_second)

        try:
            # Primero llenamos el buffer inicial para tener una ventana completa.
            initial_chunk = self._read_exact_audio(process, window_bytes)
            rolling_samples = self._pcm_bytes_to_samples(initial_chunk)
            first_result = self._scan_window(
                stream=stream,
                window_samples=rolling_samples,
                iteration=1,
                prepared_ads=prepared_ads,
                similarity_threshold=similarity_threshold,
                cooldown_seconds=cooldown_seconds,
                keep_evidence=keep_evidence,
            )
            results.append(first_result)
            if progress_callback:
                progress_callback(first_result)

            for iteration in range(2, iterations + 1):
                if should_cancel and should_cancel():
                    break

                new_chunk = self._read_exact_audio(process, step_bytes)
                new_samples = self._pcm_bytes_to_samples(new_chunk)
                rolling_samples = np.concatenate([rolling_samples, new_samples])
                max_window_samples = int(window_seconds * settings.sample_rate)
                if len(rolling_samples) > max_window_samples:
                    rolling_samples = rolling_samples[-max_window_samples:]

                iteration_result = self._scan_window(
                    stream=stream,
                    window_samples=rolling_samples,
                    iteration=iteration,
                    prepared_ads=prepared_ads,
                    similarity_threshold=similarity_threshold,
                    cooldown_seconds=cooldown_seconds,
                    keep_evidence=keep_evidence,
                )
                results.append(iteration_result)
                if progress_callback:
                    progress_callback(iteration_result)
        finally:
            self._close_stream_process(process)

        return results

    def _open_stream_process(self, resolved_source_url: str) -> subprocess.Popen:
        command = [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            resolved_source_url,
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(settings.sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        ]
        return subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def _resolve_source_url(self, source_url: str) -> str:
        parsed = urlparse(source_url)
        hostname = (parsed.hostname or "").lower()
        if hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
            return source_url

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "format": "bestaudio/best",
        }

        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(source_url, download=False)
        except Exception as exc:
            raise RuntimeError(f"No se pudo resolver el enlace de YouTube: {exc}") from exc

        if info.get("url"):
            return info["url"]

        requested_formats = info.get("requested_formats") or []
        for item in requested_formats:
            if item.get("url"):
                return item["url"]

        formats = info.get("formats") or []
        preferred_audio = None
        fallback = None
        for item in formats:
            if item.get("acodec") and item.get("acodec") != "none" and item.get("url"):
                fallback = item["url"]
                if item.get("vcodec") in (None, "none"):
                    preferred_audio = item["url"]
                    break

        if preferred_audio:
            return preferred_audio
        if fallback:
            return fallback

        raise RuntimeError("yt-dlp no devolvio una URL multimedia utilizable para ese video de YouTube.")

    def _read_exact_audio(self, process: subprocess.Popen, total_bytes: int) -> bytes:
        if process.stdout is None:
            raise RuntimeError("No se pudo abrir la salida de audio del stream.")

        chunks: list[bytes] = []
        bytes_read = 0
        while bytes_read < total_bytes:
            chunk = process.stdout.read(total_bytes - bytes_read)
            if not chunk:
                stderr_output = b""
                if process.stderr is not None:
                    stderr_output = process.stderr.read() or b""
                error_text = stderr_output.decode("utf-8", errors="ignore").strip()
                raise RuntimeError(error_text or "El stream se corto antes de completar la ventana de audio.")
            chunks.append(chunk)
            bytes_read += len(chunk)
        return b"".join(chunks)

    def _pcm_bytes_to_samples(self, raw_audio: bytes) -> np.ndarray:
        samples = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32)
        return samples / 32768.0

    def _close_stream_process(self, process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    def _scan_window(
        self,
        *,
        stream: Stream,
        window_samples: np.ndarray,
        iteration: int,
        prepared_ads: list[PreparedAdFingerprint],
        similarity_threshold: float,
        cooldown_seconds: int,
        keep_evidence: bool,
    ) -> dict:
        captured_at = now_local()
        matches: list[MatchResult] = []

        # La ventana del stream tambien se convierte en huella antes de compararla.
        window_hashes = build_constellation_hashes(window_samples, settings.sample_rate)

        for prepared_ad in prepared_ads:
            ad = prepared_ad.ad

            # Primero exigimos que la ventana tenga suficientes hashes compatibles.
            score, offset_seconds = self.matcher.best_match_for_ad(window_hashes, prepared_ad)
            if score < similarity_threshold:
                continue

            # Guardamos evidencia para poder auditar despues por que hubo una coincidencia.
            evidence_path = self._store_evidence(window_samples, stream.id, ad.id) if keep_evidence else None
            created_detection = self._persist_detection_if_needed(
                stream_id=stream.id,
                ad_id=ad.id,
                confidence=score,
                offset_seconds=offset_seconds,
                evidence_path=evidence_path,
                cooldown_seconds=cooldown_seconds,
            )
            matches.append(
                MatchResult(
                    ad_id=ad.id,
                    ad_title=ad.title,
                    confidence=score,
                    matched_at=captured_at,
                    offset_seconds=offset_seconds,
                    evidence_path=evidence_path,
                    created_detection=created_detection,
                )
            )

        self.session.commit()
        return {
            "iteration": iteration,
            "source_url": stream.source_url,
            "window_seconds": int(round(len(window_samples) / settings.sample_rate)),
            "captured_at": captured_at.isoformat(),
            "matches": [
                {
                    "ad_id": match.ad_id,
                    "ad_title": match.ad_title,
                    "confidence": round(match.confidence, 4),
                    "offset_seconds": round(match.offset_seconds, 2),
                    "evidence_path": match.evidence_path,
                    "created_detection": match.created_detection,
                }
                for match in matches
            ],
        }

    def _persist_detection_if_needed(
        self,
        *,
        stream_id: int,
        ad_id: int,
        confidence: float,
        offset_seconds: float,
        evidence_path: str | None,
        cooldown_seconds: int,
    ) -> bool:
        statement = (
            select(Detection)
            .where(Detection.stream_id == stream_id)
            .where(Detection.ad_id == ad_id)
            .order_by(Detection.detected_at.desc())
        )
        last_detection = self.session.exec(statement).first()
        if last_detection:
            last_detected_at = ensure_local_datetime(last_detection.detected_at)
            elapsed = now_local() - last_detected_at
            if elapsed.total_seconds() < cooldown_seconds:
                return False

        detection = Detection(
            stream_id=stream_id,
            ad_id=ad_id,
            confidence=confidence,
            offset_seconds=offset_seconds,
            evidence_path=evidence_path,
        )
        self.session.add(detection)
        return True

    def _store_evidence(self, window_samples: np.ndarray, stream_id: int, ad_id: int) -> str:
        ensure_storage_dirs()
        filename = f"stream{stream_id}_ad{ad_id}_{uuid4().hex}.wav"
        evidence_path = settings.evidence_dir / filename
        sf.write(evidence_path, window_samples, settings.sample_rate)
        return str(evidence_path)
